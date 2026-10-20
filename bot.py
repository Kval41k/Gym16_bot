from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from aiogram import Bot, Dispatcher, F, Router, html
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonDefault,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from sqlalchemy import func, select, update

from config import settings
from database import async_session, init_db
from models import BellSchedule, NewsPost, User

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# FSM States for news suggestion via Telegram Bot
class SuggestNews(StatesGroup):
    title = State()
    content = State()
    photo = State()

router = Router(name="main_router")

# -------------------------------------------------------------
# Keyboards & Helpers
# -------------------------------------------------------------
def get_main_inline_keyboard() -> InlineKeyboardMarkup:
    """
    Main iOS-styled action card keyboard.
    If BASE_URL is HTTPS, renders native Telegram Web App button.
    If BASE_URL is HTTP (local dev), renders browser link to avoid TelegramBadRequest.
    """
    web_app_url = f"{settings.BASE_URL}/?v=12.0"
    is_https = web_app_url.startswith("https://")

    if is_https:
        app_button = InlineKeyboardButton(
            text="📱 Открыть Гимназия 16",
            web_app=WebAppInfo(url=web_app_url)
        )
    else:
        app_button = InlineKeyboardButton(
            text="🌐 Открыть в браузере (HTTP)",
            url=web_app_url
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [app_button],
            [
                InlineKeyboardButton(
                    text="📢 Предложить новость",
                    callback_data="suggest_news_start"
                ),
                InlineKeyboardButton(
                    text="🔔 Расписание звонков",
                    callback_data="view_bells"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Мой профиль",
                    callback_data="view_my_profile"
                )
            ]
        ]
    )

def get_admin_inline_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """
    Moderation buttons for incoming news proposals.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Опубликовать",
                    callback_data=f"approve_news_{post_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject_news_{post_id}"
                )
            ]
        ]
    )

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def get_skip_photo_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏩ Пропустить (без фото)")],
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# -------------------------------------------------------------
# Handlers: Start, Help, Profile
# -------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    """
    /start command handler: syncs user with DB, sets WebApp menu button (if HTTPS),
    and displays the main greeting.
    """
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "Гимназист"
    last_name = message.from_user.last_name
    username = message.from_user.username
    is_admin = user_id in settings.admin_ids

    # Upsert user in database
    async with async_session() as session:
        db_user = await session.get(User, user_id)
        if not db_user:
            db_user = User(
                id=user_id,
                first_name=first_name,
                last_name=last_name,
                username=username,
                is_admin=is_admin
            )
            session.add(db_user)
        else:
            db_user.first_name = first_name
            db_user.last_name = last_name
            db_user.username = username
            if is_admin:
                db_user.is_admin = True
        await session.commit()

    # Configure native Telegram Web App menu button if HTTPS
    if settings.BASE_URL.startswith("https://"):
        try:
            await bot.set_chat_menu_button(
                chat_id=user_id,
                menu_button=MenuButtonWebApp(
                    text="Гимназия 16",
                    web_app=WebAppInfo(url=f"{settings.BASE_URL}/?v=12.0")
                )
            )
        except Exception as e:
            logger.warning(f"Could not set chat menu button: {e}")

    is_https = settings.BASE_URL.startswith("https://")
    https_notice = ""
    if not is_https:
        https_notice = (
            "\n\n💡 <i>Примечание: для открытия Mini App прямо внутри Telegram укажите HTTPS-адрес (туннель) в BASE_URL файла .env. Сейчас кнопка открывает сайт в браузере.</i>"
        )

    greeting_text = (
        f"👋 <b>Привет, {html.quote(first_name)}!</b>\n\n"
        f"Добро пожаловать в официальное приложение <b>Гимназии №16</b> (11-е классы).\n\n"
        f"✨ <b>Что доступно в приложении:</b>\n"
        f"• 📅 <b>Умное расписание</b> с учетом профилей (Соц-гум, Филологический) и звонков\n"
        f"• ⏱ <b>Live-таймер</b> уроков и перемен в реальном времени\n"
        f"• 📰 <b>Лента школьных новостей</b> с реакциями и комментариями\n"
        f"• ✍️ <b>Предложка постов</b> с прикреплением фото\n\n"
        f"Нажми кнопку ниже, чтобы запустить приложение:{https_notice}"
    )

    await message.answer(
        text=greeting_text,
        reply_markup=get_main_inline_keyboard()
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📖 <b>Команды бота Гимназии №16:</b>\n\n"
        "/start — Главное меню и запуск Web App\n"
        "/profile — Информация о твоем профиле и классе\n"
        "/bells — Расписание звонков гимназии\n"
        "/suggest — Предложить новость в ленту\n"
        "/help — Справка по командам\n"
    )
    if message.from_user.id in settings.admin_ids:
        help_text += (
            "\n👑 <b>Команды администратора:</b>\n"
            "/admin — Панель администратора и статистика\n"
            "/pending — Список новостей на модерации\n"
            "/delete_post &lt;id&gt; — Удалить новость по ID\n"
            "/delete_comment &lt;id&gt; — Удалить комментарий по ID\n"
        )
    await message.answer(help_text)

@router.callback_query(F.data == "view_bells")
@router.message(Command("bells"))
async def show_bells(event: Union[Message, CallbackQuery]):
    text = (
        "🔔 <b>Расписание звонков МАОУ гимназии №16:</b>\n\n"
        "📌 <b>ПОНЕДЕЛЬНИК (с «Разговорами о важном»):</b>\n"
        "• <b>08:00 — 08:30</b> — 🇷🇺 Разговоры о важном\n"
        "• <b>1 урок:</b> 08:35 — 09:15\n"
        "• <b>2 урок:</b> 09:30 — 10:10\n"
        "• <b>3 урок:</b> 10:25 — 11:05\n"
        "• <b>4 урок:</b> 11:25 — 12:05\n"
        "• <b>5 урок:</b> 12:25 — 13:05\n"
        "• <b>6 урок:</b> 13:10 — 13:50\n"
        "• <b>7 урок:</b> 14:00 — 14:40\n\n"
        "📌 <b>ВТОРНИК — ПЯТНИЦА:</b>\n"
        "• <b>1 урок:</b> 08:15 — 08:55\n"
        "• <b>2 урок:</b> 09:10 — 09:50\n"
        "• <b>3 урок:</b> 10:10 — 10:50\n"
        "• <b>4 урок:</b> 11:10 — 11:50\n"
        "• <b>5 урок:</b> 12:10 — 12:50\n"
        "• <b>6 урок:</b> 13:00 — 13:40\n"
        "• <b>7 урок:</b> 13:50 — 14:30\n"
        "• <b>8 урок:</b> 14:40 — 15:20\n\n"
        "📌 <b>СУББОТА (консультации):</b>\n"
        "• Консультации и спецкурсы с 10:00"
    )

    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text)
    else:
        await event.answer(text)

@router.callback_query(F.data == "view_my_profile")
@router.message(Command("profile"))
async def show_profile(event: Union[Message, CallbackQuery]):
    user_id = event.from_user.id
    async with async_session() as session:
        user = await session.get(User, user_id)

    if not user or not user.class_name or not user.profile_name:
        text = (
            "👤 <b>Твой профиль еще не заполнен!</b>\n\n"
            "Открой Web App по кнопке ниже и выбери свой класс (11А) и профиль обучения (Соц-гум или Филологический)."
        )
    else:
        text = (
            f"👤 <b>Профиль ученика:</b>\n\n"
            f"• <b>Имя:</b> {html.quote(user.first_name)} {html.quote(user.last_name or '')}\n"
            f"• <b>Класс:</b> {user.class_name}\n"
            f"• <b>Профиль:</b> {user.profile_name}\n"
            f"• <b>Статус:</b> {'Администратор 👑' if user.is_admin else 'Ученик 🎓'}\n\n"
            f"Изменить класс и профиль можно в любой момент на вкладке «Профиль» в приложении."
        )

    web_app_url = f"{settings.BASE_URL}/?v=12.0"
    if web_app_url.startswith("https://"):
        app_button = InlineKeyboardButton(
            text="📱 Открыть приложение",
            web_app=WebAppInfo(url=web_app_url)
        )
    else:
        app_button = InlineKeyboardButton(
            text="🌐 Открыть в браузере",
            url=web_app_url
        )

    markup = InlineKeyboardMarkup(inline_keyboard=[[app_button]])

    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text, reply_markup=markup)
    else:
        await event.answer(text, reply_markup=markup)

# -------------------------------------------------------------
# FSM: News Suggestion through Bot
# -------------------------------------------------------------
@router.callback_query(F.data == "suggest_news_start")
@router.message(Command("suggest"))
async def start_suggest_news(event: Union[Message, CallbackQuery], state: FSMContext):
    await state.clear()
    await state.set_state(SuggestNews.title)

    text = (
        "📢 <b>Предложить новость в ленту Гимназии №16</b>\n\n"
        "Шаг 1 из 3: Введи <b>заголовок новости</b> (кратко и понятно):"
    )

    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text, reply_markup=get_cancel_keyboard())
    else:
        await event.answer(text, reply_markup=get_cancel_keyboard())

@router.message(StateFilter(SuggestNews.title), F.text == "❌ Отмена")
@router.message(StateFilter(SuggestNews.content), F.text == "❌ Отмена")
@router.message(StateFilter(SuggestNews.photo), F.text == "❌ Отмена")
async def cancel_suggestion(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Предложение новости отменено.",
        reply_markup=ReplyKeyboardRemove()
    )

@router.message(StateFilter(SuggestNews.title))
async def process_suggest_title(message: Message, state: FSMContext):
    if not message.text or len(message.text.strip()) < 3:
        await message.answer("Заголовок должен содержать как минимум 3 символа. Попробуй еще раз:")
        return

    await state.update_data(title=message.text.strip())
    await state.set_state(SuggestNews.content)
    await message.answer(
        "Шаг 2 из 3: Введи <b>текст новости</b> (подробное описание события или объявления):",
        reply_markup=get_cancel_keyboard()
    )

@router.message(StateFilter(SuggestNews.content))
async def process_suggest_content(message: Message, state: FSMContext):
    if not message.text or len(message.text.strip()) < 5:
        await message.answer("Текст новости должен содержать как минимум 5 символов. Попробуй еще раз:")
        return

    await state.update_data(content=message.text.strip())
    await state.set_state(SuggestNews.photo)
    await message.answer(
        "Шаг 3 из 3: Прикрепи <b>фотографию</b> к новости (или нажми «⏩ Пропустить»):",
        reply_markup=get_skip_photo_keyboard()
    )

@router.message(StateFilter(SuggestNews.photo), F.text == "⏩ Пропустить (без фото)")
async def process_skip_photo(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    await finalize_news_post(
        user=message.from_user,
        title=data["title"],
        content=data["content"],
        image_url=None,
        photo_file_id=None,
        bot=bot,
        message=message
    )

@router.message(StateFilter(SuggestNews.photo), F.photo)
async def process_suggest_photo(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()

    # Get highest resolution photo
    photo = message.photo[-1]
    photo_file_id = photo.file_id

    # Download to uploads directory
    ext = "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    dest_path = settings.UPLOAD_DIR / filename

    try:
        file_info = await bot.get_file(photo_file_id)
        await bot.download_file(file_info.file_path, destination=dest_path)
        image_url = f"/uploads/{filename}"
    except Exception as e:
        logger.error(f"Failed to download photo: {e}")
        image_url = None

    await finalize_news_post(
        user=message.from_user,
        title=data["title"],
        content=data["content"],
        image_url=image_url,
        photo_file_id=photo_file_id,
        bot=bot,
        message=message
    )

async def finalize_news_post(user, title: str, content: str, image_url: Optional[str], photo_file_id: Optional[str], bot: Bot, message: Message):
    author_name = f"{user.first_name} {user.last_name or ''}".strip()

    # Save to SQLite DB
    async with async_session() as session:
        db_user = await session.get(User, user.id)
        author_class = db_user.class_name if db_user else None
        new_post = NewsPost(
            title=title,
            content=content,
            image_url=image_url,
            author_id=user.id,
            author_name=author_name,
            author_class=author_class,
            is_anonymous=False,
            status="pending"
        )
        session.add(new_post)
        await session.commit()
        await session.refresh(new_post)
        post_id = new_post.id

    await message.answer(
        "✅ <b>Спасибо! Твоя новость отправлена на модерацию.</b>\n"
        "После проверки администратором она появится в ленте приложения.",
        reply_markup=ReplyKeyboardRemove()
    )

    # Notify admins with moderation card
    class_str = f" ({author_class})" if author_class else ""
    admin_card_text = (
        f"📢 <b>Новое предложение в ленту новостей (#{post_id})</b>\n\n"
        f"📝 <b>Заголовок:</b> {html.quote(title)}\n"
        f"👤 <b>Автор:</b> {html.quote(author_name)}{class_str} (@{user.username or 'без_юзернейма'})\n\n"
        f"📄 <b>Текст:</b>\n{html.quote(content)}\n"
    )

    app_url = f"{settings.BASE_URL}/?v=12.0"
    admin_kb = None
    if app_url.startswith("https://"):
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📱 Открыть модерацию в приложении", web_app=WebAppInfo(url=app_url))
        ]])

    admin_notice_text = admin_card_text + "\n\nℹ️ <i>Публикация и отклонение производятся в мини-приложении во вкладке «Новости» → «📬 Модерация».</i>"

    for admin_id in settings.admin_ids:
        try:
            if photo_file_id:
                await bot.send_photo(
                    chat_id=admin_id,
                    photo=photo_file_id,
                    caption=admin_notice_text,
                    reply_markup=admin_kb
                )
            else:
                await bot.send_message(
                    chat_id=admin_id,
                    text=admin_notice_text,
                    reply_markup=admin_kb
                )
        except Exception as e:
            logger.error(f"Failed to send moderation notice to admin {admin_id}: {e}")

# -------------------------------------------------------------
# Admin Moderation Callbacks
# -------------------------------------------------------------
@router.callback_query(F.data.startswith("approve_news_"))
async def cb_approve_news(callback: CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    if admin_id not in settings.admin_ids:
        await callback.answer("⛔ У вас нет прав администратора.", show_alert=True)
        return

    post_id = int(callback.data.split("_")[-1])

    async with async_session() as session:
        post = await session.get(NewsPost, post_id)
        if not post:
            await callback.answer("Новость не найдена.", show_alert=True)
            return

        post.status = "approved"
        post.published_at = datetime.now(timezone.utc)
        await session.commit()
        author_id = post.author_id
        post_title = post.title

    admin_name = callback.from_user.first_name
    timestamp_str = datetime.now().strftime("%d.%m.%Y в %H:%M")

    # Update admin message
    approved_notice = (
        f"\n\n──────────────\n"
        f"✅ <b>ОПУБЛИКОВАНО</b> администратором {html.quote(admin_name)} ({timestamp_str})"
    )

    try:
        if callback.message.caption:
            await callback.message.edit_caption(
                caption=callback.message.caption + approved_notice,
                reply_markup=None
            )
        else:
            await callback.message.edit_text(
                text=callback.message.text + approved_notice,
                reply_markup=None
            )
    except Exception as e:
        logger.warning(f"Could not edit message: {e}")

    await callback.answer("Новость успешно опубликована!")

    # Notify author
    if author_id:
        try:
            await bot.send_message(
                chat_id=author_id,
                text=f"🎉 <b>Отличные новости!</b>\n\nТвоя публикация «<b>{html.quote(post_title)}</b>» одобрена и появилась в ленте новостей гимназии."
            )
        except Exception:
            pass

@router.callback_query(F.data.startswith("reject_news_"))
async def cb_reject_news(callback: CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    if admin_id not in settings.admin_ids:
        await callback.answer("⛔ У вас нет прав администратора.", show_alert=True)
        return

    post_id = int(callback.data.split("_")[-1])

    async with async_session() as session:
        post = await session.get(NewsPost, post_id)
        if not post:
            await callback.answer("Новость не найдена.", show_alert=True)
            return

        post.status = "rejected"
        await session.commit()
        author_id = post.author_id
        post_title = post.title

    admin_name = callback.from_user.first_name
    timestamp_str = datetime.now().strftime("%d.%m.%Y в %H:%M")

    rejected_notice = (
        f"\n\n──────────────\n"
        f"❌ <b>ОТКЛОНЕНО</b> администратором {html.quote(admin_name)} ({timestamp_str})"
    )

    try:
        if callback.message.caption:
            await callback.message.edit_caption(
                caption=callback.message.caption + rejected_notice,
                reply_markup=None
            )
        else:
            await callback.message.edit_text(
                text=callback.message.text + rejected_notice,
                reply_markup=None
            )
    except Exception as e:
        logger.warning(f"Could not edit message: {e}")

    await callback.answer("Новость отклонена.")

    # Notify author
    if author_id:
        try:
            await bot.send_message(
                chat_id=author_id,
                text=f"ℹ️ Ваша предложенная новость «<b>{html.quote(post_title)}</b>» была отклонена модератором."
            )
        except Exception:
            pass

# -------------------------------------------------------------
# Admin Management Commands
# -------------------------------------------------------------
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in settings.admin_ids:
        await message.answer("⛔ Доступ запрещен. Вы не являетесь администратором.")
        return

    async with async_session() as session:
        users_count = (await session.execute(select(func.count(User.id)))).scalar_one()
        pending_count = (await session.execute(
            select(func.count(NewsPost.id)).where(NewsPost.status == "pending")
        )).scalar_one()
        approved_count = (await session.execute(
            select(func.count(NewsPost.id)).where(NewsPost.status == "approved")
        )).scalar_one()

    admin_panel_text = (
        "👑 <b>Панель администратора Гимназии №16</b>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"• Всего пользователей в БД: <b>{users_count}</b>\n"
        f"• Новостей на модерации: <b>{pending_count}</b>\n"
        f"• Опубликованных новостей: <b>{approved_count}</b>\n\n"
        f"Используйте команду /pending, чтобы просмотреть и промодерировать ожидающие новости."
    )

    markup = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=f"📬 Модерация ({pending_count})", callback_data="open_pending_list")
        ]]
    )

    await message.answer(admin_panel_text, reply_markup=markup)

@router.callback_query(F.data == "open_pending_list")
@router.message(Command("pending"))
async def show_pending_news(event: Union[Message, CallbackQuery], bot: Bot):
    admin_id = event.from_user.id
    if admin_id not in settings.admin_ids:
        if isinstance(event, CallbackQuery):
            await event.answer("⛔ Доступ запрещен.", show_alert=True)
        else:
            await event.answer("⛔ Доступ запрещен.")
        return

    async with async_session() as session:
        res = await session.execute(
            select(NewsPost).where(NewsPost.status == "pending").order_by(NewsPost.created_at.asc())
        )
        pending_posts = res.scalars().all()

    if isinstance(event, CallbackQuery):
        await event.answer()

    if not pending_posts:
        text = "🎉 Очередь предложки пуста! Все новости промодерированы."
        if isinstance(event, CallbackQuery):
            await event.message.answer(text)
        else:
            await event.answer(text)
        return

    # Send each pending post with moderation controls
    for p in pending_posts:
        card_text = (
            f"📬 <b>Новость #{p.id} на модерации</b>\n\n"
            f"📝 <b>Заголовок:</b> {html.quote(p.title)}\n"
            f"👤 <b>Автор:</b> {html.quote(p.author_name)}\n"
            f"📅 <b>Дата:</b> {p.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"📄 <b>Текст:</b>\n{html.quote(p.content)}"
        )
        markup = get_admin_inline_keyboard(p.id)

        target_chat = event.message.chat.id if isinstance(event, CallbackQuery) else event.chat.id

        if p.image_url and (settings.UPLOAD_DIR / Path(p.image_url).name).exists():
            from aiogram.types import FSInputFile
            local_image = FSInputFile(settings.UPLOAD_DIR / Path(p.image_url).name)
            await bot.send_photo(chat_id=target_chat, photo=local_image, caption=card_text, reply_markup=markup)
        else:
            await bot.send_message(chat_id=target_chat, text=card_text, reply_markup=markup)

@router.message(Command("delete_post"))
async def cmd_delete_post(message: Message):
    if message.from_user.id not in settings.admin_ids:
        await message.answer("⛔ Доступ запрещен.")
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("ℹ️ Использование: <code>/delete_post &lt;id новости&gt;</code>")
        return

    post_id = int(args[1])
    async with async_session() as session:
        post = await session.get(NewsPost, post_id)
        if not post:
            await message.answer(f"❌ Новость #{post_id} не найдена.")
            return

        if post.image_url:
            p = settings.UPLOAD_DIR / Path(post.image_url).name
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

        await session.delete(post)
        await session.commit()

    await message.answer(f"🗑 <b>Новость #{post_id} успешно удалена.</b>")

@router.message(Command("delete_comment"))
async def cmd_delete_comment(message: Message):
    if message.from_user.id not in settings.admin_ids:
        await message.answer("⛔ Доступ запрещен.")
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("ℹ️ Использование: <code>/delete_comment &lt;id комментария&gt;</code>")
        return

    comment_id = int(args[1])
    async with async_session() as session:
        comment = await session.get(Comment, comment_id)
        if not comment:
            await message.answer(f"❌ Комментарий #{comment_id} не найден.")
            return

        await session.delete(comment)
        await session.commit()

    await message.answer(f"🗑 <b>Комментарий #{comment_id} успешно удален.</b>")

# -------------------------------------------------------------

@router.message(Command("users"))
async def cmd_list_users(message: Message):
    if message.from_user.id not in settings.admin_ids and message.from_user.id != 1097947498:
        await message.answer("⛔ Доступ запрещен. Вы не являетесь администратором.")
        return

    async with async_session() as session:
        res = await session.execute(select(User).order_by(User.created_at.desc()))
        users = res.scalars().all()

    if not users:
        await message.answer("ℹ️ В базе данных пока нет зарегистрированных пользователей.")
        return

    total = len(users)
    onboarded = sum(1 for u in users if u.class_name and u.profile_name)

    header = (
        f"👥 <b>Пользователи бота ({total})</b>\n"
        f"<i>Заполнили профиль: {onboarded} из {total}</i>\n\n"
    )
    lines = []
    for i, u in enumerate(users[:40], 1):
        uname = f"@{u.username}" if u.username else "(нет username)"
        cls_prof = f"{u.class_name or '—'} • {u.profile_name or 'профиль не выбран'}"
        admin_mark = " 👑" if u.is_admin else ""
        lines.append(
            f"{i}. <b>{html.quote(u.first_name)} {html.quote(u.last_name or '')}</b>{admin_mark}\n"
            f"   ID: <code>{u.id}</code> | {uname}\n"
            f"   Класс: {cls_prof}"
        )

    if total > 40:
        lines.append(f"\n...и еще {total - 40} пользователей.")

    separator = "\n\n"
    await message.answer(header + separator.join(lines))

# Main Polling Function
# -------------------------------------------------------------
async def main():
    logger.info("Initializing database...")
    await init_db()

    proxy = os.getenv("TELEGRAM_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if proxy:
        logger.info(f"Using Telegram proxy: {proxy}")
        session = AiohttpSession(proxy=proxy, timeout=60.0)
    else:
        session = AiohttpSession(timeout=60.0)

    bot = Bot(
        token=settings.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("Starting Gymnasium 16 aiogram 3 Bot...")
    try:
        await asyncio.wait_for(bot.delete_webhook(drop_pending_updates=True), timeout=10.0)
    except Exception as e:
        logger.warning(f"delete_webhook skipped: {e}. Starting polling directly...")

    while True:
        try:
            await dp.start_polling(bot, handle_signals=False)
            break
        except (TelegramNetworkError, asyncio.TimeoutError) as e:
            logger.warning(f"Telegram network glitch: {e}. Reconnecting in 3 seconds...")
            await asyncio.sleep(3)
        except (KeyboardInterrupt, SystemExit):
            break
        finally:
            try:
                await bot.session.close()
            except Exception:
                pass

if __name__ == "__main__":
    asyncio.run(main())
