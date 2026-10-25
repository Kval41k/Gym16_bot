"""Scoped class-group links, named poll answers, and a durable poll delivery queue."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from types import SimpleNamespace

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import ChatMemberUpdated, Message, PollAnswer, Update
from sqlalchemy import select, update, case
from sqlalchemy.exc import IntegrityError

from access import configured_admin, require_school_access
from audit import audit_actor
from community import utc, write_lock
from config import settings
from database import async_session
from models import (Attendance, ClassChat, ClassLinkToken, ClassPoll, ClassPollVoteCursor, ClassPollAnswerInbox,
                    MealChoice, MealMenu, User)
from timetable import effective_lessons, day_bells, lesson_times

router = Router(name='class_group_tools')
TZ = ZoneInfo('Asia/Yekaterinburg')
logger = logging.getLogger(__name__)
CATEGORIES = {'main': 'Основное блюдо', 'drink': 'Напиток', 'pastry': 'Выпечка'}


def is_group_member(member):
    return str(member.status) in {'creator', 'administrator', 'member'} or (
        str(member.status) == 'restricted' and bool(getattr(member, 'is_member', False)))


@router.message(Command('class_link'))
async def link_class_chat(message: Message, command: CommandObject):
    if message.chat.type not in {'group', 'supergroup'} or not message.from_user or message.from_user.is_bot:
        await message.answer('Команду привязки нужно отправить в чат класса от своего аккаунта. Код доступен в разделе «Староста» мини-приложения.')
        return
    code = (command.args or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,100}', code):
        await message.answer('Получите новый код в разделе «Староста» и отправьте /class_link КОД в чат класса.')
        return
    # Check Telegram permissions before opening a database write transaction.
    try:
        actor_member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        bot_member = await message.bot.get_chat_member(message.chat.id, message.bot.id)
        if str(actor_member.status) not in {'creator', 'administrator'}:
            await message.answer('Привязать чат может староста или администратор приложения, который также является администратором этого Telegram-чата.')
            return
        if str(bot_member.status) != 'administrator':
            await message.answer('Для проверки участников и именных опросов добавьте бота в администраторы чата. Права удаления сообщений и блокировки участников не нужны.')
            return
    except Exception:
        await message.answer('Не удалось проверить права в чате. Проверьте, что бот добавлен администратором, и повторите команду.')
        return
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    token = audit_actor.set(dict(message.from_user.model_dump(), source='class_bot'))
    try:
        async with async_session() as db:
            await write_lock(db)
            actor = await db.get(User, message.from_user.id)
            invitation = await db.get(ClassLinkToken, code_hash)
            now = datetime.now(timezone.utc)
            if (not actor or actor.is_banned or not invitation or invitation.used_at
                    or utc(invitation.expires_at) <= now or invitation.created_by != actor.id):
                await message.answer('Код недействителен, истёк или выдан другому пользователю. Получите свой новый код в приложении.')
                return
            await require_school_access(db, actor)
            if not configured_admin(message.from_user) and not (
                    actor.role == 'headman' and actor.headman_class_name == invitation.class_name):
                await message.answer('Для этого класса у вас нет действующей роли старосты.')
                return
            occupied = await db.scalar(select(ClassChat).where(ClassChat.chat_id == message.chat.id))
            if occupied and occupied.class_name != invitation.class_name:
                await message.answer('Этот чат уже привязан к другому классу. Сначала отмените прежнюю привязку в приложении.')
                return
            chat = await db.get(ClassChat, invitation.class_name)
            if chat is None:
                chat = ClassChat(class_name=invitation.class_name)
                db.add(chat)
            old_id = chat.chat_id
            if old_id and old_id != message.chat.id:
                pending = (await db.scalars(select(ClassPoll).where(
                    ClassPoll.class_name == invitation.class_name, ClassPoll.status == 'pending'))).all()
                for poll in pending:
                    poll.status = 'failed'
                    poll.last_error = 'Привязка чата изменена. Опрос в прежний чат не отправлен.'
            chat.chat_id = message.chat.id
            chat.chat_title = (message.chat.title or 'Чат класса')[:255]
            chat.linked_by = actor.id
            invitation.used_at = now
            await db.commit()
            class_name = invitation.class_name
        await message.answer(f'✅ Чат привязан к {class_name}. Время утреннего опроса и меню питания настраиваются в разделе «Староста» мини-приложения.')
    except IntegrityError:
        await message.answer('Чат уже привязан. Обновите раздел «Староста» и проверьте текущую привязку.')
    except Exception:
        # Never log link codes, full Telegram exceptions, or token-bearing HTTP URLs.
        logger.warning('Class-chat binding failed; sensitive error details omitted')
        await message.answer('Не удалось привязать чат. Обновите раздел «Староста» и попробуйте получить новый код.')
    finally:
        audit_actor.reset(token)


@router.message(F.migrate_to_chat_id | F.migrate_from_chat_id)
async def migrate_class_chat(message: Message):
    old_id = message.migrate_from_chat_id or message.chat.id
    new_id = message.migrate_to_chat_id or message.chat.id
    if old_id == new_id:
        return
    async with async_session() as db:
        await write_lock(db)
        chat = await db.scalar(select(ClassChat).where(ClassChat.chat_id == old_id))
        if chat:
            chat.chat_id = new_id
            if message.chat.title:
                chat.chat_title = message.chat.title[:255]
            await db.execute(update(ClassPoll).where(ClassPoll.class_name == chat.class_name,
                                                    ClassPoll.chat_id == old_id).values(chat_id=new_id))
            await db.commit()


@router.my_chat_member()
async def class_bot_membership(event: ChatMemberUpdated):
    if event.chat.type not in {'group', 'supergroup'} or str(event.new_chat_member.status) == 'administrator':
        return
    async with async_session() as db:
        await write_lock(db)
        chat = await db.scalar(select(ClassChat).where(ClassChat.chat_id == event.chat.id))
        if chat:
            chat.attendance_enabled = False
            pending = (await db.scalars(select(ClassPoll).where(
                ClassPoll.chat_id == event.chat.id, ClassPoll.status == 'pending'))).all()
            for poll in pending:
                poll.status = 'failed'
                poll.last_error = 'Бот удалён из чата или больше не администратор. Проверьте права и включите опросы заново.'
            await db.commit()


@router.message(Command('class_join'))
async def join_class_roster(message: Message):
    if message.chat.type not in {'group', 'supergroup'} or not message.from_user or message.from_user.is_bot:
        await message.answer('Отправьте /class_join в подключённой группе класса.')
        return
    async with async_session() as db:
        chat = await db.scalar(select(ClassChat).where(ClassChat.chat_id == message.chat.id))
        user = await db.get(User, message.from_user.id)
        if not chat:
            await message.answer('Сначала староста должен подключить этот чат через /class_link.')
            return
        if user and user.is_banned:
            await message.answer('Доступ к школьному боту ограничен.')
            return
        class_name = chat.class_name
    try:
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        if not is_group_member(member):
            return
    except Exception:
        await message.answer('Не удалось проверить участие в группе. Проверьте права бота и повторите команду.')
        return
    from headman import ensure_roster
    token = audit_actor.set(dict(message.from_user.model_dump(), source='class_bot'))
    try:
        async with async_session() as db:
            await write_lock(db)
            chat = await db.get(ClassChat, class_name)
            user = await db.get(User, message.from_user.id)
            if not chat or chat.chat_id != message.chat.id or (user and user.is_banned):
                return
            await ensure_roster(db, class_name, message.from_user.id, message.from_user.first_name,
                                message.from_user.last_name, message.from_user.username)
            await db.commit()
        await message.answer(f'✅ Вы в списке {class_name}. Староста увидит ваши ответы на посещаемость и питание.')
    finally:
        audit_actor.reset(token)


async def apply_poll_answer(event, bot, sequence=None):
    """True means handled/irrelevant; False retains a durable answer for a later retry."""
    if not event.user or event.user.is_bot or len(event.option_ids) > 1:
        return True
    async with async_session() as db:
        poll = await db.scalar(select(ClassPoll).where(ClassPoll.telegram_poll_id == event.poll_id))
        if not poll:
            return False  # sendPoll may still be committing its returned ID.
        if poll.status != 'sent':
            return True
        now = datetime.now(TZ)
        if (poll.kind == 'attendance' and poll.poll_date != now.date()) or (
                poll.kind in CATEGORIES and poll.poll_date <= now.date()):
            return True
        options = json.loads(poll.options_json)
        if event.option_ids and not 0 <= event.option_ids[0] < len(options):
            return True
        chat = await db.get(ClassChat, poll.class_name)
        user = await db.get(User, event.user.id)
        if not chat or chat.chat_id != poll.chat_id or (user and user.is_banned):
            return True
    try:
        member = await bot.get_chat_member(poll.chat_id, event.user.id)
        if not is_group_member(member):
            return True
    except Exception:
        return False  # Temporary membership lookup failures must not lose a valid vote.
    from headman import ensure_roster
    token = audit_actor.set(dict(event.user.model_dump(), source='class_poll'))
    try:
        async with async_session() as db:
            await write_lock(db)
            current = await db.get(ClassPoll, poll.id)
            chat = await db.get(ClassChat, poll.class_name)
            user = await db.get(User, event.user.id)
            if not current or current.status != 'sent' or not chat or chat.chat_id != poll.chat_id or (user and user.is_banned):
                return True
            cursor = await db.get(ClassPollVoteCursor, (poll.id, event.user.id))
            if sequence is not None:
                if cursor and cursor.last_update_id >= sequence:
                    return True
                if cursor:
                    cursor.last_update_id = sequence
                else:
                    db.add(ClassPollVoteCursor(poll_id=poll.id, user_id=event.user.id, last_update_id=sequence))
            await ensure_roster(db, poll.class_name, event.user.id, event.user.first_name,
                                event.user.last_name, event.user.username)
            if poll.kind == 'attendance':
                row = await db.get(Attendance, (poll.class_name, event.user.id, poll.poll_date))
                if not event.option_ids:
                    if row:
                        await db.delete(row)
                elif row:
                    row.status = 'yes' if event.option_ids[0] == 0 else 'no'
                    row.updated_by = event.user.id
                else:
                    db.add(Attendance(class_name=poll.class_name, user_id=event.user.id,
                                      attendance_date=poll.poll_date,
                                      status='yes' if event.option_ids[0] == 0 else 'no', updated_by=event.user.id))
            elif poll.kind in CATEGORIES and poll.menu_id:
                menu = await db.get(MealMenu, poll.menu_id)
                if not menu or menu.class_name != poll.class_name or menu.meal_date != poll.poll_date:
                    return True
                row = await db.get(MealChoice, (poll.menu_id, event.user.id, poll.kind))
                if not event.option_ids:
                    if row:
                        await db.delete(row)
                elif row:
                    row.option_index = event.option_ids[0]
                    row.updated_by = event.user.id
                else:
                    db.add(MealChoice(menu_id=poll.menu_id, user_id=event.user.id, category=poll.kind,
                                      option_index=event.option_ids[0], updated_by=event.user.id))
            else:
                return True
            await db.commit()
            return True
    finally:
        audit_actor.reset(token)


async def delete_inbox_answer(sequence):
    async with async_session() as db:
        await write_lock(db)
        row = await db.get(ClassPollAnswerInbox, sequence)
        if row:
            await db.delete(row)
            await db.commit()


@router.poll_answer()
async def record_poll_answer(event: PollAnswer, bot, event_update: Update | None = None):
    if not event.user or event.user.is_bot:
        return
    sequence = event_update.update_id if event_update else None
    if sequence is not None:
        async with async_session() as db:
            await write_lock(db)
            if not await db.get(ClassPollAnswerInbox, sequence):
                db.add(ClassPollAnswerInbox(update_id=sequence, telegram_poll_id=event.poll_id,
                    user_id=event.user.id, payload_json=event.model_dump_json(), created_at=datetime.now(timezone.utc)))
                await db.commit()
    try:
        handled = await apply_poll_answer(event, bot, sequence)
        if handled and sequence is not None:
            await delete_inbox_answer(sequence)
    except Exception:
        logger.warning('Poll answer retained for a later retry; sensitive details omitted')


class PollMembershipClient:
    def __init__(self, client):
        self.client = client
        self.lookup_failed = False

    async def get_chat_member(self, chat_id, user_id):
        try:
            response = await self.client.post(f'https://api.telegram.org/bot{settings.BOT_TOKEN}/getChatMember',
                                             json={'chat_id': chat_id, 'user_id': user_id})
            data = response.json()
            if not response.is_success or not data.get('ok'):
                raise RuntimeError('Membership lookup unavailable')
            return SimpleNamespace(**data['result'])
        except Exception:
            self.lookup_failed = True
            raise


async def process_poll_answer_inbox(client=None, now=None):
    if not settings.BOT_TOKEN:
        return
    if client is None:
        async with httpx.AsyncClient(timeout=15) as owned:
            return await process_poll_answer_inbox(owned, now)
    now = now or datetime.now(timezone.utc)
    async with async_session() as db:
        expired = (await db.scalars(select(ClassPollAnswerInbox).where(
            ClassPollAnswerInbox.created_at < now.astimezone(timezone.utc) - timedelta(days=1)))).all()
        for row in expired:
            await db.delete(row)
        await db.commit()
        rows = (await db.scalars(select(ClassPollAnswerInbox).order_by(ClassPollAnswerInbox.update_id).limit(100))).all()
    member_client = PollMembershipClient(client)
    for row in rows:
        try:
            event = PollAnswer.model_validate_json(row.payload_json)
            if await apply_poll_answer(event, member_client, row.update_id):
                await delete_inbox_answer(row.update_id)
            if member_client.lookup_failed:
                break  # One network timeout per cycle, rather than blocking every pending answer.
        except Exception:
            logger.warning('Pending poll answer could not be applied; sensitive details omitted')


async def enqueue_class_attendance(now=None):
    now = (now or datetime.now(TZ)).astimezone(TZ)
    if now.weekday() == 6:
        return
    from headman import queue_attendance
    async with async_session() as db:
        await write_lock(db)
        chats = (await db.scalars(select(ClassChat).where(ClassChat.chat_id.is_not(None),
                                                          ClassChat.attendance_enabled.is_(True)))).all()
        for chat in chats:
            weekdays = {int(day) for day in chat.attendance_weekdays.split(',') if day.isdigit()}
            if now.weekday() not in weekdays or not re.fullmatch(r'\d\d:\d\d', chat.attendance_time):
                continue
            hour, minute = map(int, chat.attendance_time.split(':'))
            if hour > 23 or minute > 59:
                continue
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now < due or now >= due + timedelta(hours=2):
                continue
            lessons = await effective_lessons(db, now.weekday(), chat.class_name, now.date())
            if not lessons:
                continue
            bells = await day_bells(db, now.weekday())
            starts = [lesson_times(lesson, bells)[0] for lesson in lessons]
            starts = [start for start in starts if start]
            if starts and now.strftime('%H:%M') >= min(starts):
                continue
            await queue_attendance(db, chat.class_name, now.date())
        await db.commit()


def poll_question(poll):
    if poll.kind == 'attendance':
        return f'{poll.class_name} · {poll.poll_date:%d.%m} · Кто сегодня будет на уроках?'
    return f'{poll.class_name} · питание {poll.poll_date:%d.%m} · {CATEGORIES[poll.kind]}'


def poll_expired(poll, today):
    return poll.poll_date < today if poll.kind == 'attendance' else poll.poll_date <= today


async def deliver_class_polls(client=None, now=None):
    if not settings.BOT_TOKEN:
        return
    now = (now or datetime.now(TZ)).astimezone(TZ)
    if client is None:
        async with httpx.AsyncClient(timeout=15) as owned:
            return await deliver_class_polls(owned, now)
    endpoint = f'https://api.telegram.org/bot{settings.BOT_TOKEN}/'
    # A reservation surviving a process crash cannot safely be sent again.
    async with async_session() as db:
        await write_lock(db)
        stale = (await db.scalars(select(ClassPoll).where(ClassPoll.status == 'sending',
            ClassPoll.claimed_at < now.astimezone(timezone.utc) - timedelta(minutes=3)))).all()
        for poll in stale:
            poll.status = 'uncertain'
            poll.last_error = 'Сервер перезапустился во время отправки. Повтор отключён, чтобы не создать дубль.'
        pending = list((await db.scalars(select(ClassPoll).where(ClassPoll.status == 'pending')
                                        .order_by(ClassPoll.created_at, case((ClassPoll.kind == 'attendance', 0), (ClassPoll.kind == 'main', 1), (ClassPoll.kind == 'drink', 2), else_=3), ClassPoll.id).limit(12))).all())
        await db.commit()
    for candidate in pending:
        async with async_session() as db:
            await write_lock(db)
            poll = await db.get(ClassPoll, candidate.id)
            if not poll or poll.status != 'pending':
                continue
            chat = await db.get(ClassChat, poll.class_name)
            if not chat or chat.chat_id != poll.chat_id or poll_expired(poll, now.date()):
                poll.status = 'failed'
                poll.last_error = 'Опрос устарел или чат класса изменился; отправка отменена.'
                await db.commit()
                continue
            if poll.poll_date > now.date() and poll.kind == 'attendance':
                continue
            claimed = await db.execute(update(ClassPoll).where(ClassPoll.id == poll.id,
                ClassPoll.status == 'pending').values(status='sending', claimed_at=now.astimezone(timezone.utc)))
            await db.commit()
            if not claimed.rowcount:
                continue
        try:
            # Preflight does not create a poll, so failures here are not ambiguous sends.
            permission = await client.post(endpoint + 'getChatMember', json={
                'chat_id': poll.chat_id, 'user_id': int(settings.BOT_TOKEN.split(':', 1)[0])})
            permission_data = permission.json()
            if permission.status_code >= 500 or permission.status_code == 429:
                raise RuntimeError('Temporary permission lookup failure')
            if not permission.is_success or not permission_data.get('ok') or permission_data.get('result', {}).get('status') != 'administrator':
                async with async_session() as db:
                    record = await db.get(ClassPoll, poll.id)
                    record.status = 'failed'
                    record.last_error = 'Нет прав бота в чате. Добавьте бота администратором и проверьте разрешение на опросы.'
                    await db.commit()
                continue
        except Exception:
            async with async_session() as db:
                record = await db.get(ClassPoll, poll.id)
                record.status = 'pending'
                record.last_error = 'Не удалось проверить доступ к чату. Опрос ещё не отправлялся; проверка повторится.'
                await db.commit()
            break  # A network outage must not block the background loop for every queued poll.
        try:
            response = await client.post(endpoint + 'sendPoll', json={
                'chat_id': poll.chat_id, 'question': poll_question(poll),
                'options': [{'text': text} for text in json.loads(poll.options_json)],
                'is_anonymous': False, 'type': 'regular', 'allows_multiple_answers': False})
            payload = response.json()
            if response.is_success and payload.get('ok'):
                result = payload['result']
                telegram_id = result['poll']['id']
                message_id = result['message_id']
                status, error = 'sent', None
            elif response.status_code >= 500:
                status, error = 'uncertain', 'Telegram не подтвердил результат отправки. Повтор отключён во избежание дубля.'
                telegram_id = message_id = None
            else:
                status, error = 'failed', f'Telegram отклонил отправку (HTTP {response.status_code}). Проверьте права бота в чате.'
                telegram_id = message_id = None
        except Exception:
            status, error = 'uncertain', 'Неизвестен результат отправки. Автоматический повтор отключён во избежание дубля.'
            telegram_id = message_id = None
        async with async_session() as db:
            record = await db.get(ClassPoll, poll.id)
            record.status = status
            record.last_error = error
            if status == 'sent':
                record.telegram_poll_id = telegram_id
                record.message_id = message_id
                record.sent_at = datetime.now(timezone.utc)
            await db.commit()
            if record.menu_id:
                menu = await db.get(MealMenu, record.menu_id)
                siblings = (await db.scalars(select(ClassPoll).where(ClassPoll.menu_id == record.menu_id))).all()
                if menu and len(siblings) == 3 and all(sibling.status in {'sent', 'closed'} for sibling in siblings):
                    menu.status = 'published'
                    await db.commit()
        await asyncio.sleep(.05)
    # Close yesterday's attendance and menus whose meal day has started.
    async with async_session() as db:
        sent = (await db.scalars(select(ClassPoll).where(ClassPoll.status == 'sent'))).all()
        for poll in sent:
            if not poll_expired(poll, now.date()) or not poll.message_id:
                continue
            try:
                response = await client.post(endpoint + 'stopPoll', json={'chat_id': poll.chat_id, 'message_id': poll.message_id})
                data = response.json()
                if (response.is_success and data.get('ok')) or response.status_code in {400, 403}:
                    poll.status = 'closed'
                    await db.commit()
            except Exception:
                pass  # Closing an already sent poll is idempotent and may be retried safely.


async def class_group_cycle(now=None, client=None):
    await enqueue_class_attendance(now)
    await deliver_class_polls(client, now)
    await process_poll_answer_inbox(client, now)


async def class_group_loop():
    """Class polls run independently from backup and personal-notification delivery."""
    while True:
        try:
            await class_group_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error('Class poll cycle failed; sensitive details omitted')
        await asyncio.sleep(30)
