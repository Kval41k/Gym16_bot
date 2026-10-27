"""Class-scoped headman tools. Telegram identity and administrator-granted scope are separate."""
import hashlib
import hmac
import json
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from access import access_allowed, configured_admin, require_school_access
from community import DateRequest, change_date_schedule, date_payload, utc, write_lock
from config import CLASS_PROFILES_MAP, settings
from database import engine, get_db
from features import ScheduleRequest, lesson_dict, parse_schedule, revision
from models import (Attendance, ClassChat, ClassLinkToken, ClassPoll, ClassRoster, Lesson,
                    MealChoice, MealMenu, Notification, User, UserPreferences)
from timetable import effective_lessons

TZ = ZoneInfo('Asia/Yekaterinburg')
CATEGORIES = ('main', 'drink', 'pastry')
ATTENDANCE_OPTIONS = ['Буду', 'Опоздаю', 'Болею', 'Не буду (неуважительная причина)']
ATTENDANCE_STATUSES = ('yes', 'late', 'sick', 'unexcused')


def attendance_status_for_option(options, index):
    """Decode the frozen poll labels, never reinterpret an old two-choice index."""
    known = {'буду': 'yes', 'буду на уроках': 'yes', 'опоздаю': 'late', 'болею': 'sick',
             'не буду': 'no', 'не буду (неуважительная причина)': 'unexcused'}
    if not 0 <= index < len(options):
        return None
    label = ' '.join(str(options[index]).strip().casefold().split())
    return known.get(label)


def upgrade_unsent_poll_options(poll):
    """Only a never-sent pending poll may adopt the new audience-facing format."""
    if poll.status != 'pending' or poll.telegram_poll_id or poll.message_id:
        return False
    options = json.loads(poll.options_json)
    if poll.kind == 'attendance':
        wanted = ATTENDANCE_OPTIONS
    elif poll.kind in CATEGORIES and len(options) == 3 and str(options[2]).strip().casefold() == 'не буду':
        wanted = options[:2]
    else:
        return False
    if wanted == options:
        return False
    poll.options_json = json.dumps(wanted, ensure_ascii=False)
    return True


def scoped_class(user, requested=None):
    """A changed self-service profile must never broaden delegated permissions."""
    if getattr(user, '_headman_verified_admin', False):
        name = requested or user.class_name or next(iter(CLASS_PROFILES_MAP))
    elif user.role == 'headman' and user.headman_class_name:
        name = user.headman_class_name
        if requested and requested != name:
            raise HTTPException(403, 'Староста может работать только со своим назначенным классом')
    else:
        raise HTTPException(403, 'Этот раздел доступен назначенному старосте и администратору')
    if name not in CLASS_PROFILES_MAP:
        raise HTTPException(422, 'Выберите существующий класс')
    return name


async def lock_headman(db, user, requested=None):
    """Recheck a delegated role under the same lock used to revoke it."""
    await write_lock(db)
    await db.refresh(user)
    if user.is_banned:
        raise HTTPException(403, 'Доступ ограничен')
    await require_school_access(db, user)
    return scoped_class(user, requested)


async def ensure_roster(db, class_name, user_id, first_name, last_name=None, username=None):
    row = await db.get(ClassRoster, (class_name, user_id))
    if not row:
        row = ClassRoster(class_name=class_name, user_id=user_id, first_name=first_name[:100] or str(user_id),
                          last_name=(last_name or '')[:100] or None, username=(username or '')[:100] or None)
        db.add(row)
    else:
        row.first_name = first_name[:100] or str(user_id)
        row.last_name = (last_name or '')[:100] or None
        row.username = (username or '')[:100] or None
        row.active = True
    return row


async def class_roster(db, class_name):
    """Include app students and separately enrolled Telegram poll participants."""
    rows = {row.user_id: row for row in (await db.scalars(select(ClassRoster).where(
        ClassRoster.class_name == class_name, ClassRoster.active.is_(True)))).all()}
    users = (await db.scalars(select(User).where(User.class_name == class_name, User.is_banned.is_(False)))).all()
    for user in users:
        # Reading a table does not write roster records or alter Telegram membership.
        rows[user.id] = user
    return [{'user_id': getattr(row, 'user_id', None) or row.id, 'first_name': row.first_name,
             'last_name': row.last_name, 'username': row.username}
            for row in sorted(rows.values(), key=lambda row: ((row.last_name or '').casefold(), row.first_name.casefold(), getattr(row, 'user_id', None) or row.id))]


async def require_roster_person(db, class_name, user_id):
    if not 0 < user_id < 2**63:
        raise HTTPException(422, 'Некорректный Telegram ID')
    roster = await db.get(ClassRoster, (class_name, user_id))
    user = await db.get(User, user_id)
    if user and user.is_banned:
        raise HTTPException(403, 'Аккаунт ученика заблокирован')
    if not ((roster and roster.active) or (user and user.class_name == class_name)):
        raise HTTPException(404, 'Ученик не найден в этом классе')
    if not roster and user:
        # Preserve named historical manual entries even if the student later changes class.
        return await ensure_roster(db, class_name, user.id, user.first_name, user.last_name, user.username)
    return roster or user


async def chat_settings(db, class_name, create=False):
    row = await db.get(ClassChat, class_name)
    if not row and create:
        row = ClassChat(class_name=class_name, chat_title='', attendance_time='07:00', attendance_enabled=True,
                        attendance_weekdays='0,1,2,3,4,5')
        db.add(row)
    return row


def chat_payload(row):
    return {'chat_id': row.chat_id if row else None, 'chat_title': row.chat_title if row else '',
            'attendance_time': row.attendance_time if row else '07:00',
            'attendance_enabled': row.attendance_enabled if row else True,
            'weekdays': [int(value) for value in row.attendance_weekdays.split(',') if value] if row else list(range(6))}


def poll_payload(row):
    if not row:
        return None
    options = json.loads(row.options_json)
    legacy = (row.kind == 'attendance' and len(options) == 2) or (row.kind in CATEGORIES and len(options) == 3)
    return {'id': row.id, 'kind': row.kind, 'status': row.status, 'last_error': row.last_error,
            'options': options, 'legacy_format': legacy,
            'telegram_poll_id': row.telegram_poll_id, 'message_id': row.message_id}


async def queue_attendance(db, class_name, poll_date):
    """Caller holds write_lock. One durable outbox item per class and date."""
    chat = await chat_settings(db, class_name)
    if not chat or not chat.chat_id:
        raise HTTPException(422, 'Сначала привяжите чат класса')
    key = f'attendance:{class_name}:{poll_date.isoformat()}'
    old = await db.scalar(select(ClassPoll).where(ClassPoll.delivery_key == key))
    if old:
        upgrade_unsent_poll_options(old)
        return old
    row = ClassPoll(id=secrets.token_hex(16), delivery_key=key, class_name=class_name, poll_date=poll_date,
                    kind='attendance', chat_id=chat.chat_id, options_json=json.dumps(ATTENDANCE_OPTIONS, ensure_ascii=False), status='pending')
    db.add(row)
    return row


async def attendance_payload(db, class_name, day):
    roster = await class_roster(db, class_name)
    records = {row.user_id: row.status for row in (await db.scalars(select(Attendance).where(
        Attendance.class_name == class_name, Attendance.attendance_date == day))).all()}
    rows = [{**row, 'status': records.get(row['user_id']), 'legacy_absence': records.get(row['user_id']) == 'no'} for row in roster]
    poll = await db.scalar(select(ClassPoll).where(ClassPoll.delivery_key == f'attendance:{class_name}:{day.isoformat()}'))
    return {'class_name': class_name, 'date': day.isoformat(), 'rows': rows,
            'totals': {**{status: sum(row['status'] == status for row in rows) for status in ATTENDANCE_STATUSES},
                       'legacy_no': sum(row['legacy_absence'] for row in rows),
                       'no': sum(row['legacy_absence'] for row in rows),
                       'unanswered': sum(row['status'] is None for row in rows)}, 'poll': poll_payload(poll)}


async def meal_record(db, class_name, day):
    return await db.scalar(select(MealMenu).where(MealMenu.class_name == class_name, MealMenu.meal_date == day))


async def meals_payload(db, class_name, day):
    menu = await meal_record(db, class_name, day)
    choices = (await db.scalars(select(MealChoice).where(MealChoice.menu_id == menu.id))).all() if menu else []
    by_user = {(choice.user_id, choice.category): choice.option_index for choice in choices}
    rows = [{**row, 'choices': {category: by_user.get((row['user_id'], category)) for category in CATEGORIES},
             'legacy_declined': {category: by_user.get((row['user_id'], category)) == 2 for category in CATEGORIES}}
            for row in await class_roster(db, class_name)]
    polls = (await db.scalars(select(ClassPoll).where(ClassPoll.menu_id == menu.id).order_by(ClassPoll.kind))).all() if menu else []
    return {'class_name': class_name, 'date': day.isoformat(), 'rows': rows,
            'menu': {'id': menu.id, 'date': menu.meal_date.isoformat(), 'options': json.loads(menu.options_json),
                     'revision': menu.revision, 'status': menu.status} if menu else None,
            'polls': [poll_payload(row) for row in polls],
            'totals': {category: [sum(row['choices'][category] == option for row in rows) for option in range(2)] for category in CATEGORIES},
            'legacy_declined': {category: sum(row['legacy_declined'][category] for row in rows) for category in CATEGORIES}}


class ScopeRequest(BaseModel):
    class_name: Optional[str] = None


class SettingsRequest(ScopeRequest):
    attendance_time: str = Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    attendance_enabled: bool
    weekdays: list[int] = Field(min_length=1, max_length=6)

    @field_validator('weekdays')
    @classmethod
    def valid_weekdays(cls, values):
        if any(value not in range(6) for value in values) or len(values) != len(set(values)):
            raise ValueError('Учебные дни: 0–5, без повторов')
        return sorted(values)


class DayRequest(ScopeRequest):
    date: date


class AttendanceRequest(DayRequest):
    user_id: int
    status: Optional[Literal['yes', 'late', 'sick', 'unexcused', 'no']]


class MenuOptions(BaseModel):
    main: list[str] = Field(min_length=2, max_length=2)
    drink: list[str] = Field(min_length=2, max_length=2)
    pastry: list[str] = Field(min_length=2, max_length=2)

    @field_validator('main', 'drink', 'pastry')
    @classmethod
    def valid_names(cls, values):
        values = [value.strip() for value in values]
        if any(not value or len(value) > 100 for value in values):
            raise ValueError('Название блюда: от 1 до 100 символов')
        if len({value.casefold() for value in values}) != 2:
            raise ValueError('Укажите два разных варианта')
        return values


class MenuRequest(DayRequest):
    options: MenuOptions
    base_revision: str = Field('', max_length=32, pattern=r'^(?:[a-f0-9]{32})?$')


class PublishMenuRequest(DayRequest):
    base_revision: str = Field(min_length=32, max_length=32, pattern=r'^[a-f0-9]{32}$')


class ChoiceRequest(DayRequest):
    user_id: int
    category: Literal['main', 'drink', 'pastry']
    option_index: Optional[Literal[0, 1]]


def install_headman(app, require_identity, cache_clear, rate_limit):
    router = APIRouter()

    async def actor(x_telegram_init_data: Optional[str] = Header(None), db=Depends(get_db)):
        identity = require_identity(x_telegram_init_data)
        user = await db.get(User, int(identity['id']))
        if not user or user.is_banned:
            raise HTTPException(403, 'Доступ ограничен')
        await require_school_access(db, user)
        username = str(identity.get('username') or '').lower().lstrip('@')
        user._headman_verified_admin = user.id in settings.admin_ids or username in settings.admin_usernames
        scoped_class(user)
        rate_limit(f'headman:{user.id}', 180, 60)
        return user

    @router.get('/api/headman/overview')
    async def overview(class_name: Optional[str] = None, actor=Depends(actor), db=Depends(get_db)):
        cls = scoped_class(actor, class_name)
        return {'class_name': cls, 'classes': list(CLASS_PROFILES_MAP) if actor._headman_verified_admin else [cls],
                'today': datetime.now(TZ).date().isoformat(), 'chat': chat_payload(await chat_settings(db, cls))}

    @router.put('/api/headman/settings')
    async def save_settings(payload: SettingsRequest, actor=Depends(actor), db=Depends(get_db)):
        cls = scoped_class(actor, payload.class_name)
        cls = await lock_headman(db, actor, payload.class_name)
        chat = await chat_settings(db, cls, True)
        chat.attendance_time = payload.attendance_time
        chat.attendance_enabled = payload.attendance_enabled
        chat.attendance_weekdays = ','.join(map(str, payload.weekdays))
        await db.commit()
        return chat_payload(chat)

    @router.post('/api/headman/link-token')
    async def link_token(payload: ScopeRequest, actor=Depends(actor), db=Depends(get_db)):
        cls = scoped_class(actor, payload.class_name)
        rate_limit(f'headman-link:{actor.id}', 10, 600)
        cls = await lock_headman(db, actor, payload.class_name)
        now = datetime.now(timezone.utc)
        # Only the newest token for the issuing person/class stays usable.
        tokens = (await db.scalars(select(ClassLinkToken).where(ClassLinkToken.created_by == actor.id,
            ClassLinkToken.class_name == cls, ClassLinkToken.used_at.is_(None)))).all()
        for row in tokens:
            row.used_at = now
        code = secrets.token_urlsafe(18)
        row = ClassLinkToken(code_hash=hashlib.sha256(code.encode()).hexdigest(), created_by=actor.id,
                             class_name=cls, expires_at=now + timedelta(minutes=15))
        db.add(row)
        await db.commit()
        return {'class_name': cls, 'code': code, 'command': '/class_link ' + code, 'expires_at': row.expires_at.isoformat()}

    @router.post('/api/headman/disconnect')
    async def disconnect(payload: ScopeRequest, actor=Depends(actor), db=Depends(get_db)):
        cls = scoped_class(actor, payload.class_name)
        cls = await lock_headman(db, actor, payload.class_name)
        chat = await chat_settings(db, cls)
        if chat:
            chat.chat_id = None; chat.chat_title = ''; chat.linked_by = None
        now = datetime.now(timezone.utc)
        for row in (await db.scalars(select(ClassLinkToken).where(ClassLinkToken.class_name == cls, ClassLinkToken.used_at.is_(None)))).all():
            row.used_at = now
        for row in (await db.scalars(select(ClassPoll).where(ClassPoll.class_name == cls, ClassPoll.status == 'pending'))).all():
            row.status = 'failed'; row.last_error = 'Чат класса отвязан'
        await db.commit()
        return {'ok': True}

    @router.get('/api/headman/attendance')
    async def attendance(date: date, class_name: Optional[str] = None, actor=Depends(actor), db=Depends(get_db)):
        return await attendance_payload(db, scoped_class(actor, class_name), date)

    @router.post('/api/headman/polls/{poll_id}/retry')
    async def retry_poll(poll_id: str, payload: ScopeRequest, actor=Depends(actor), db=Depends(get_db)):
        cls = scoped_class(actor, payload.class_name)
        cls = await lock_headman(db, actor, payload.class_name)
        poll = await db.get(ClassPoll, poll_id)
        if not poll or poll.class_name != cls:
            raise HTTPException(404, 'Опрос не найден в этом классе')
        if poll.status != 'failed' or poll.telegram_poll_id or poll.message_id:
            raise HTTPException(409, 'Повтор возможен только для заведомо неотправленного опроса')
        today = datetime.now(TZ).date()
        if (poll.kind == 'attendance' and poll.poll_date != today) or (poll.kind != 'attendance' and poll.poll_date != today + timedelta(days=1)):
            raise HTTPException(409, 'Дата опроса уже неактуальна')
        chat = await chat_settings(db, cls)
        if not chat or not chat.chat_id:
            raise HTTPException(422, 'Сначала привяжите чат класса')
        poll.chat_id = chat.chat_id; poll.status = 'pending'; poll.last_error = None; poll.claimed_at = None
        upgrade_unsent_poll_options(poll)
        await db.commit()
        return poll_payload(poll)

    @router.put('/api/headman/attendance')
    async def set_attendance(payload: AttendanceRequest, actor=Depends(actor), db=Depends(get_db)):
        cls = scoped_class(actor, payload.class_name)
        cls = await lock_headman(db, actor, payload.class_name)
        await require_roster_person(db, cls, payload.user_id)
        record = await db.get(Attendance, (cls, payload.user_id, payload.date))
        if payload.status is None:
            if record: await db.delete(record)
        elif record:
            record.status = payload.status; record.updated_by = actor.id
        else:
            db.add(Attendance(class_name=cls, user_id=payload.user_id, attendance_date=payload.date,
                              status=payload.status, updated_by=actor.id))
        await db.commit()
        return await attendance_payload(db, cls, payload.date)

    @router.post('/api/headman/attendance/publish')
    async def publish_attendance(payload: DayRequest, actor=Depends(actor), db=Depends(get_db)):
        cls = scoped_class(actor, payload.class_name)
        if payload.date != datetime.now(TZ).date():
            raise HTTPException(422, 'Опрос посещаемости отправляется только на сегодня')
        cls = await lock_headman(db, actor, payload.class_name)
        if not await effective_lessons(db, payload.date.weekday(), cls, payload.date):
            raise HTTPException(422, 'На этот день нет занятий')
        row = await queue_attendance(db, cls, payload.date)
        await db.commit()
        return poll_payload(row)

    @router.get('/api/headman/meals')
    async def meals(date: date, class_name: Optional[str] = None, actor=Depends(actor), db=Depends(get_db)):
        return await meals_payload(db, scoped_class(actor, class_name), date)

    @router.put('/api/headman/meals')
    async def save_menu(payload: MenuRequest, actor=Depends(actor), db=Depends(get_db)):
        cls = scoped_class(actor, payload.class_name)
        cls = await lock_headman(db, actor, payload.class_name)
        row = await meal_record(db, cls, payload.date)
        if row and not hmac.compare_digest(row.revision, payload.base_revision):
            raise HTTPException(409, 'Меню изменилось. Загрузите его заново')
        if not row and payload.base_revision:
            raise HTTPException(409, 'Меню больше не существует. Загрузите дату заново')
        options = payload.options.model_dump()
        if row and row.status != 'draft':
            if json.loads(row.options_json) == options:
                return await meals_payload(db, cls, payload.date)
            raise HTTPException(409, 'Опубликованное меню нельзя менять: ответы уже привязаны к вариантам')
        encoded = json.dumps(options, ensure_ascii=False)
        if row:
            if row.options_json != encoded:
                row.options_json = encoded; row.revision = secrets.token_hex(16)
        else:
            row = MealMenu(class_name=cls, meal_date=payload.date, options_json=encoded,
                           revision=secrets.token_hex(16), status='draft', created_by=actor.id)
            db.add(row)
        await db.commit()
        return await meals_payload(db, cls, payload.date)

    @router.post('/api/headman/meals/publish')
    async def publish_menu(payload: PublishMenuRequest, actor=Depends(actor), db=Depends(get_db)):
        cls = scoped_class(actor, payload.class_name)
        if payload.date != datetime.now(TZ).date() + timedelta(days=1):
            raise HTTPException(422, 'Меню отправляется на следующий календарный день')
        cls = await lock_headman(db, actor, payload.class_name)
        chat = await chat_settings(db, cls)
        if not chat or not chat.chat_id:
            raise HTTPException(422, 'Сначала привяжите чат класса')
        menu = await meal_record(db, cls, payload.date)
        if not menu: raise HTTPException(404, 'Сначала сохраните меню')
        if not hmac.compare_digest(menu.revision, payload.base_revision):
            raise HTTPException(409, 'Меню изменилось. Загрузите его заново')
        if menu.status == 'draft':
            options = json.loads(menu.options_json)
            for category in CATEGORIES:
                db.add(ClassPoll(id=secrets.token_hex(16), delivery_key=f'meal:{menu.id}:{menu.revision}:{category}',
                    class_name=cls, poll_date=menu.meal_date, kind=category, menu_id=menu.id, chat_id=chat.chat_id,
                    options_json=json.dumps(options[category], ensure_ascii=False), status='pending'))
            menu.status = 'queued'
            await db.commit()
        return await meals_payload(db, cls, payload.date)

    @router.put('/api/headman/meals/choice')
    async def set_choice(payload: ChoiceRequest, actor=Depends(actor), db=Depends(get_db)):
        cls = scoped_class(actor, payload.class_name)
        cls = await lock_headman(db, actor, payload.class_name)
        await require_roster_person(db, cls, payload.user_id)
        menu = await meal_record(db, cls, payload.date)
        if not menu: raise HTTPException(404, 'Меню не найдено')
        if menu.status == 'draft': raise HTTPException(409, 'Сначала отправьте меню в чат, чтобы зафиксировать варианты')
        record = await db.get(MealChoice, (menu.id, payload.user_id, payload.category))
        if payload.option_index is None:
            if record: await db.delete(record)
        elif record:
            record.option_index = payload.option_index; record.updated_by = actor.id
        else:
            db.add(MealChoice(menu_id=menu.id, user_id=payload.user_id, category=payload.category,
                              option_index=payload.option_index, updated_by=actor.id))
        await db.commit()
        return await meals_payload(db, cls, payload.date)

    @router.get('/api/headman/schedule/date')
    async def get_date(date: date, class_name: Optional[str] = None, actor=Depends(actor), db=Depends(get_db)):
        return await date_payload(db, scoped_class(actor, class_name), date)

    @router.put('/api/headman/schedule/date')
    async def put_date(payload: DateRequest, actor=Depends(actor), db=Depends(get_db)):
        scoped_class(actor, payload.class_name)
        await lock_headman(db, actor, payload.class_name)
        return await change_date_schedule(payload, db, cache_clear, locked=True)

    @router.post('/api/headman/schedule/date/reset')
    async def reset_date(payload: DateRequest, actor=Depends(actor), db=Depends(get_db)):
        scoped_class(actor, payload.class_name)
        await lock_headman(db, actor, payload.class_name)
        return await change_date_schedule(payload, db, cache_clear, True, locked=True)

    @router.get('/api/headman/schedule')
    async def get_schedule(class_name: Optional[str] = None, actor=Depends(actor), db=Depends(get_db)):
        cls = scoped_class(actor, class_name)
        rows = (await db.scalars(select(Lesson).where(Lesson.class_name == cls).order_by(Lesson.day_of_week, Lesson.lesson_number, Lesson.id))).all()
        return {'class_name': cls, 'rows': [lesson_dict(row) for row in rows], 'base_revision': revision(rows)}

    @router.post('/api/headman/schedule/preview')
    async def preview_schedule(payload: ScheduleRequest, actor=Depends(actor), db=Depends(get_db)):
        cls = scoped_class(actor, payload.class_name)
        rows = parse_schedule(payload)
        old = (await db.scalars(select(Lesson).where(Lesson.class_name == cls))).all()
        if payload.base_revision and revision(old) != payload.base_revision:
            raise HTTPException(409, 'Расписание изменилось. Загрузите его заново')
        return {'rows': [row.model_dump() for row in rows], 'base_revision': revision(old),
                'old_count': len(old), 'new_count': len(rows),
                'empty_days': [day for day in range(6) if not any(row.day_of_week == day for row in rows)]}

    @router.post('/api/headman/schedule/publish')
    async def publish_schedule(payload: ScheduleRequest, actor=Depends(actor), db=Depends(get_db)):
        cls = scoped_class(actor, payload.class_name)
        rows = parse_schedule(payload)
        cls = await lock_headman(db, actor, payload.class_name)
        if engine.dialect.name == 'postgresql':
            from sqlalchemy import text
            # Coordinate with the existing administrator's per-class publisher as well.
            await db.execute(text('SELECT pg_advisory_xact_lock(:key)'),
                             {'key': int(hashlib.sha256(cls.encode()).hexdigest()[:8], 16)})
        old = (await db.scalars(select(Lesson).where(Lesson.class_name == cls).with_for_update())).all()
        if not payload.base_revision or revision(old) != payload.base_revision:
            raise HTTPException(409, 'Расписание изменилось. Загрузите его заново')
        key = lambda row: (row.day_of_week, row.lesson_number, row.profile_name, row.subgroup)
        previous = {key(row): row for row in old}
        changed = False
        for row in rows:
            before = previous.pop(key(row), None)
            values = row.model_dump()
            if before:
                for field, value in values.items():
                    if getattr(before, field) != value:
                        setattr(before, field, value); changed = True
            else:
                db.add(Lesson(class_name=cls, **values)); changed = True
        for row in previous.values():
            await db.delete(row); changed = True
        if changed:
            ids = select(User.id).where(User.class_name == cls)
            for notice in (await db.scalars(select(Notification).where(Notification.status == 'pending',
                    Notification.dedup_key.like('lesson:%'), Notification.user_id.in_(ids)))).all():
                notice.status = 'cancelled'
            batch = secrets.token_hex(16)
            for user in (await db.scalars(select(User).where(User.class_name == cls))).all():
                pref = await db.get(UserPreferences, user.id)
                if pref and pref.schedule_changes and await access_allowed(db, user):
                    db.add(Notification(user_id=user.id, dedup_key=f'schedule:{batch}:{user.id}',
                        text=f'📅 Староста обновил расписание {cls}. Проверьте расписание в приложении.'))
        await db.commit()
        cache_clear('sched:')
        return {'ok': True, 'changed': changed, 'count': len(rows)}

    app.include_router(router)
