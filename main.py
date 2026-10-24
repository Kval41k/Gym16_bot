import html
import asyncio
import mimetypes
import logging
import hashlib
import hmac
import json
import os
import urllib.parse
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import (
    BackgroundTasks, Depends, FastAPI, File, HTTPException, 
    Header, Query, Request, UploadFile, status
)
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
import time
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import DEFAULT_CLASSES, CLASS_PROFILES_MAP, ALL_PROFILES, settings
from database import async_session, get_db, init_db
from timetable import day_bells
from models import BellSchedule, Comment, EgeMaterial, EgeSubject, Lesson, NewsPost, Profile, Reaction, SchoolClass, User
from schemas import (
    BellItem, CommentCreateRequest, CommentResponse, DayScheduleResponse,
    EgeMaterialCreateRequest, EgeMaterialResponse, EgeSubjectResponse,
    LessonItem, LessonSlot, LiveStatusResponse, ModerationActionRequest,
    NewsCreateRequest, NewsEditRequest, NewsResponse, ReactionCount, ReactionToggleRequest,
    StructureResponse, UserAdminItem, UserBanRequest, UserProfileUpdate, UserResponse, UserSyncRequest
)

# Tyumen Timezone: UTC+5 (Asia/Yekaterinburg)
try:
    TYUMEN_TZ = ZoneInfo("Asia/Yekaterinburg")
except Exception:
    TYUMEN_TZ = timezone(timedelta(hours=5))

# Active Reaction Palette (including negative reactions)
logger = logging.getLogger("Gym16API")
EMOJI_PALETTE = ["❤️", "🔥", "👍", "👎", "🤡", "😢"]

# -------------------------------------------------------------

# -------------------------------------------------------------
# High-Performance In-Memory Cache (Sub-millisecond responses)
# -------------------------------------------------------------
_CACHE: Dict[str, Any] = {}
_RATE_LIMITS: Dict[str, List[float]] = {}

def enforce_rate_limit(key: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    recent = [stamp for stamp in _RATE_LIMITS.get(key, []) if now - stamp < window_seconds]
    if len(recent) >= limit:
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте позже.")
    recent.append(now)
    _RATE_LIMITS[key] = recent
    if len(_RATE_LIMITS) > 10000:
        for old_key, stamps in list(_RATE_LIMITS.items()):
            if not stamps or now - stamps[-1] >= window_seconds:
                _RATE_LIMITS.pop(old_key, None)

def cache_get(key: str, ttl: float) -> Optional[Any]:
    entry = _CACHE.get(key)
    if entry and (time.time() - entry['time'] < ttl):
        return entry['data']
    return None

def cache_set(key: str, data: Any):
    _CACHE[key] = {'time': time.time(), 'data': data}

def cache_clear_prefix(prefix: str):
    global _CACHE
    if not prefix:
        _CACHE.clear()
    else:
        _CACHE = {k: v for k, v in _CACHE.items() if not k.startswith(prefix)}

# Lifespan Management
# -------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure directories exist
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    settings.STATIC_DIR.mkdir(parents=True, exist_ok=True)
    
    # Initialize DB schema and base seeds
    await init_db()
    from features import maintenance_loop
    worker = asyncio.create_task(maintenance_loop())
    try:
        yield
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass

# -------------------------------------------------------------
# FastAPI Application
# -------------------------------------------------------------
app = FastAPI(
    title="Gymnasium 16 Telegram Mini App API",
    description="Backend API for Gymnasium 16 TMA (11th Grade Parallel)",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

@app.middleware("http")
async def audit_identity(request: Request, call_next):
    from audit import audit_actor
    actor = None
    signed_data = request.headers.get("X-Telegram-Init-Data")
    if signed_data:
        try:
            actor = dict(require_telegram_user(signed_data), source="app")
        except HTTPException:
            pass
    token = audit_actor.set(actor)
    try:
        return await call_next(request)
    finally:
        audit_actor.reset(token)

# Enable CORS for Telegram Web App webview
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)

# Ensure directories exist before mounting
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Mount local uploads for direct static image access
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# Mount static frontend directory (for TMA HTML/JS)
if settings.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=settings.STATIC_DIR, html=True), name="static")

# -------------------------------------------------------------
# Telegram WebApp InitData Validator
# -------------------------------------------------------------
def verify_telegram_init_data(init_data_str: str) -> Optional[Dict[str, Any]]:
    """
    Validates initData from Telegram WebApp using HMAC-SHA256 according to Telegram specs.
    Returns parsed user dict or None if invalid.
    """
    if not init_data_str:
        return None

    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data_str))
        hash_received = parsed_data.pop("hash", None)
        if not hash_received:
            return None

        # Build data check string sorted alphabetically
        data_check_arr = [f"{k}={v}" for k, v in sorted(parsed_data.items())]
        data_check_str = "\n".join(data_check_arr)

        # Telegram HMAC algorithm
        secret_key = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_str.encode("utf-8"), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(computed_hash, hash_received):
            return None

        user_raw = parsed_data.get("user")
        user = json.loads(user_raw) if user_raw else parsed_data
        # Telegram keeps auth_date alongside `user` in initData, not inside it.
        user["auth_date"] = parsed_data.get("auth_date")
        return user
    except Exception:
        return None


def require_telegram_user(init_data_str: Optional[str]) -> Dict[str, Any]:
    """Validate a fresh Telegram WebApp identity or reject the request."""
    user = verify_telegram_init_data(init_data_str or "")
    if not user or not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="Требуется подтверждённая авторизация Telegram.")

    try:
        auth_date = int(user.get("auth_date", 0))
        user_id = int(user.get("id", 0))
    except (TypeError, ValueError):
        auth_date = 0
        user_id = 0

    now = int(time.time())
    if not user_id or not auth_date or auth_date > now + 300 or now - auth_date > 86400:
        raise HTTPException(status_code=401, detail="Срок авторизации Telegram истёк. Перезапустите приложение.")
    return user


def require_matching_telegram_user(init_data_str: Optional[str], expected_user_id: Optional[int] = None) -> Dict[str, Any]:
    user = require_telegram_user(init_data_str)
    if expected_user_id is not None and int(user["id"]) != int(expected_user_id):
        raise HTTPException(status_code=403, detail="Нельзя выполнять действия от имени другого пользователя.")
    return user

# -------------------------------------------------------------

# -------------------------------------------------------------
# Admin Verification & Cryptographic Authorization
# -------------------------------------------------------------
def generate_admin_auth_token(admin_id: int, timestamp: int) -> str:
    """Generates an HMAC-SHA256 signature for admin URLs using BOT_TOKEN."""
    msg = f"{admin_id}:{timestamp}".encode("utf-8")
    key = hashlib.sha256(settings.BOT_TOKEN.encode("utf-8")).digest()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()

def verify_admin_auth_token(admin_id: int, timestamp: int, signature: str) -> bool:
    """Verifies HMAC signature and a 15-minute expiration window."""
    if not signature or not timestamp:
        return False
    now = int(time.time())
    if abs(now - timestamp) > 900:
        return False
    expected = generate_admin_auth_token(admin_id, timestamp)
    return hmac.compare_digest(expected, signature)

async def check_admin_permission_or_raise(
    admin_id: Optional[int] = None,
    ts: Optional[int] = None,
    sign: Optional[str] = None,
    x_telegram_init_data: Optional[str] = None,
    db: Optional[AsyncSession] = None
) -> int:
    """
    Cryptographically verifies administrative identity:
    1. If X-Telegram-Init-Data header is passed, verifies Telegram HMAC-SHA256 signature against BOT_TOKEN.
       Checks if authenticated user is in settings.admin_ids.
    2. If signed link (admin_id + ts + sign) is provided, verifies HMAC signature and timestamp validity.
       Checks if admin_id is in settings.admin_ids.
    3. A client-supplied admin ID alone is never accepted as proof of identity.
    4. Otherwise, raises HTTP 403 Forbidden.
    """
    # 1. Telegram WebApp HMAC verification
    if x_telegram_init_data:
        parsed_user = require_telegram_user(x_telegram_init_data)
        if parsed_user:
            caller_id = int(parsed_user["id"])
            caller_username = parsed_user.get("username")
            if caller_id and (caller_id in settings.admin_ids or (caller_username and caller_username.lower().lstrip("@") in settings.admin_usernames)):
                if admin_id is not None and int(admin_id) != caller_id:
                    raise HTTPException(status_code=403, detail="ID администратора не совпадает с авторизованным Telegram-пользователем.")
                return caller_id

    # 2. Signed admin URL token verification
    if admin_id and ts is not None and sign is not None and verify_admin_auth_token(admin_id, ts, sign):
        is_configured_admin = admin_id in settings.admin_ids
        if not is_configured_admin and db:
            user = await db.get(User, admin_id)
            is_configured_admin = bool(
                user
                and user.username
                and user.username.lower().lstrip("@") in settings.admin_usernames
            )
        if is_configured_admin:
            from audit import audit_actor
            admin_user = await db.get(User, admin_id) if db else None
            audit_actor.set({"id": admin_id, "first_name": admin_user.first_name if admin_user else "Администратор",
                             "last_name": admin_user.last_name if admin_user else None,
                             "username": admin_user.username if admin_user else None, "source": "app"})
            return admin_id

    # A client-supplied admin ID or a database role alone is not proof of identity.
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="⛔ Доступ запрещен. Требуется подтвержденная авторизация администратора."
    )

async def check_is_admin(admin_id: int, db: AsyncSession) -> bool:
    """Checks configured admin identity; persisted role flags are not authority."""
    if admin_id in settings.admin_ids:
        return True
    user = await db.get(User, admin_id)
    if user and user.username and user.username.lower().lstrip("@") in settings.admin_usernames:
        return True
    return False

# Admin Notification Service (Background Tasks)
# -------------------------------------------------------------
async def notify_admins_about_post(
    post_id: int, 
    title: str, 
    content: str,
    author_name: str, 
    author_class: Optional[str], 
    is_anonymous: bool, 
    image_url: Optional[str],
    author_username: Optional[str] = None,
    author_id: Optional[int] = None
):
    """
    Sends notification to Telegram administrators when a new news post is suggested.
    Always reveals author identity, class, and Telegram username to admins for moderation safety.
    Guarantees photo is attached and delivered via multipart sendPhoto to admins.
    """
    if not settings.BOT_TOKEN or (not settings.admin_ids and not settings.admin_usernames) or "ABCdefGHI" in settings.BOT_TOKEN:
        return

    bot_url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}"
    
    clean_username = f"@{author_username.lstrip('@')}" if author_username else "без @username"
    author_info = f"{html.escape(author_name)} ({html.escape(author_class) if author_class else 'класс не указан'})"
    username_line = f"💬 <b>Телеграм:</b> <b>{html.escape(clean_username)}</b>"
    if author_id:
        username_line += f" [ID: <code>{author_id}</code>]"
    if is_anonymous:
        username_line += " • <i>(🎭 В ленте будет анонимно)</i>"

    title_safe = html.escape(title[:100])
    content_safe = html.escape(content[:450])
    if len(content) > 450:
        content_safe += "..."

    caption_text = (
        f"📢 <b>Новое предложение в школьную ленту (#{post_id})</b>\n\n"
        f"📝 <b>Заголовок:</b> {title_safe}\n"
        f"👤 <b>Автор:</b> {author_info}\n"
        f"{username_line}\n"
        f"📄 <b>Текст:</b>\n{content_safe}\n\n"
        f"ℹ️ <i>Публикация и отклонение производятся в мини-приложении во вкладке «Новости» → «📬 Модерация».</i>"
    )

    reply_markup = None
    if settings.BASE_URL and settings.BASE_URL.startswith("https://"):
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "📱 Открыть модерацию в приложении", "web_app": {"url": f"{settings.BASE_URL}/?v=19.0"}}
                ]
            ]
        }

    local_image_path: Optional[Path] = None
    if image_url:
        img_name = Path(image_url).name
        candidates = [
            settings.UPLOAD_DIR / img_name,
            Path("uploads") / img_name,
            Path(__file__).resolve().parent / "uploads" / img_name,
        ]
        for c in candidates:
            if c.exists():
                local_image_path = c
                break

    admin_recipients = set(settings.admin_ids)
    if settings.admin_usernames:
        normalized_admin_usernames = [username.lower().lstrip("@") for username in settings.admin_usernames]
        async with async_session() as session:
            result = await session.execute(
                select(User.id).where(func.lower(User.username).in_(normalized_admin_usernames))
            )
            admin_recipients.update(result.scalars().all())

    async with httpx.AsyncClient(timeout=20.0) as client:
        for admin_id in admin_recipients:
            sent_photo = False
            # 1. Try sending local file via multipart/form-data
            if local_image_path and local_image_path.exists():
                try:
                    with open(local_image_path, "rb") as f:
                        file_bytes = f.read()
                    mime_type, _ = mimetypes.guess_type(local_image_path.name)
                    if not mime_type:
                        mime_type = "image/jpeg"
                    resp = await client.post(
                        f"{bot_url}/sendPhoto",
                        data={
                            "chat_id": str(admin_id),
                            "caption": caption_text,
                            "parse_mode": "HTML",
                            "reply_markup": json.dumps(reply_markup)
                        },
                        files={"photo": (local_image_path.name, file_bytes, mime_type)}
                    )
                    if resp.status_code == 200:
                        sent_photo = True
                    else:
                        logger.warning(f"sendPhoto local file failed ({resp.status_code}): {resp.text}")
                except Exception as e:
                    logger.warning(f"Error sending local photo to admin {admin_id}: {e}")

            # 2. Try sending by URL if not sent yet
            if not sent_photo and image_url:
                target_url = image_url
                if not target_url.startswith("http"):
                    if settings.BASE_URL:
                        target_url = f"{settings.BASE_URL.rstrip('/')}/{image_url.lstrip('/')}"
                if target_url.startswith("http"):
                    try:
                        resp = await client.post(
                            f"{bot_url}/sendPhoto",
                            data={
                                "chat_id": str(admin_id),
                                "photo": target_url,
                                "caption": caption_text,
                                "parse_mode": "HTML",
                                "reply_markup": json.dumps(reply_markup)
                            }
                        )
                        if resp.status_code == 200:
                            sent_photo = True
                        else:
                            logger.warning(f"sendPhoto URL failed ({resp.status_code}): {resp.text}")
                    except Exception as e:
                        logger.warning(f"Error sending photo URL to admin {admin_id}: {e}")

            # 3. Fallback to sendMessage if photo could not be sent
            if not sent_photo:
                try:
                    await client.post(
                        f"{bot_url}/sendMessage",
                        json={
                            "chat_id": str(admin_id),
                            "text": caption_text,
                            "parse_mode": "HTML",
                            "reply_markup": reply_markup
                        }
                    )
                except Exception as e:
                    logger.error(f"Failed to send moderation notice to admin {admin_id}: {e}")

# -------------------------------------------------------------
# Base & Meta Endpoints
# -------------------------------------------------------------
@app.get("/")
async def root():
    index_file = settings.STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(
            index_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {
        "app": "Gymnasium 16 Telegram Mini App",
        "status": "online",
        "docs": "/docs" if settings.DEBUG else "disabled"
    }

@app.get("/api/health")
async def health_check():
    return {
        "status": "ok", 
        "timestamp_tyumen": datetime.now(TYUMEN_TZ).isoformat()
    }

@app.get("/api/meta/structure", response_model=StructureResponse)
async def get_structure(db: AsyncSession = Depends(get_db)):
    """
    Returns available classes (11А..11Ж) and mapping of classes to their profiles.
    """
    cached = cache_get("meta_structure", 600.0)
    if cached:
        return cached

    classes_res = await db.execute(select(SchoolClass.name).order_by(SchoolClass.name))
    classes = [r[0] for r in classes_res.all()]
    if not classes:
        classes = DEFAULT_CLASSES

    resp = StructureResponse(
        classes=classes,
        class_profiles=CLASS_PROFILES_MAP,
        all_profiles=ALL_PROFILES
    )
    cache_set("meta_structure", resp)
    return resp

# -------------------------------------------------------------
# User Profile & Onboarding Endpoints
# -------------------------------------------------------------
@app.post("/api/user/sync", response_model=UserResponse)
async def sync_user(
    payload: UserSyncRequest,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """
    Syncs or creates a student account upon opening the TMA.
    Preserves and updates class_name and profile_name so bot and webapp remain synchronized.
    """
    telegram_user = require_matching_telegram_user(x_telegram_init_data, payload.id)
    user = await db.get(User, payload.id)
    telegram_username = telegram_user.get("username")

    if payload.class_name and payload.class_name not in CLASS_PROFILES_MAP:
        raise HTTPException(status_code=422, detail="Выберите существующий класс.")
    if payload.profile_name and payload.class_name and payload.profile_name not in CLASS_PROFILES_MAP[payload.class_name]:
        raise HTTPException(status_code=422, detail="Профиль не соответствует выбранному классу.")

    is_admin = (
        payload.id in settings.admin_ids 
        or (telegram_username and telegram_username.lower().lstrip("@") in settings.admin_usernames)
    )

    if not user:
        user = User(
            id=payload.id,
            first_name=payload.first_name,
            last_name=payload.last_name or "",
            username=telegram_username,
            photo_url=payload.photo_url,
            class_name=payload.class_name or ("11А" if is_admin else None),
            profile_name=payload.profile_name or ("Соц-гум" if is_admin else None),
            is_admin=is_admin
        )
        db.add(user)
    else:
        if payload.first_name:
            user.first_name = payload.first_name
        if payload.last_name is not None:
            user.last_name = payload.last_name
        user.username = telegram_username
        if payload.photo_url:
            user.photo_url = payload.photo_url
        if payload.class_name:
            user.class_name = payload.class_name
        if payload.profile_name:
            user.profile_name = payload.profile_name
        user.is_admin = is_admin
        if is_admin:
            if not user.class_name:
                user.class_name = "11А"
            if not user.profile_name:
                user.profile_name = "Соц-гум"

    await db.commit()
    await db.refresh(user)

    is_onboarded = bool(user.class_name and user.profile_name and user.first_name)
    return UserResponse(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        photo_url=user.photo_url,
        class_name=user.class_name,
        profile_name=user.profile_name,
        subgroup=user.subgroup,
        is_admin=is_admin,
        is_banned=user.is_banned,
        is_onboarded=is_onboarded
    )

@app.get("/api/user/{user_id}", response_model=UserResponse)
async def get_user_profile(
    user_id: int,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    require_matching_telegram_user(x_telegram_init_data, user_id)
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    is_onboarded = bool(user.class_name and user.profile_name and user.first_name and user.last_name)
    configured_admin = user.id in settings.admin_ids or bool(
        user.username and user.username.lower().lstrip("@") in settings.admin_usernames
    )
    return UserResponse(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        photo_url=user.photo_url,
        class_name=user.class_name,
        profile_name=user.profile_name,
        subgroup=user.subgroup,
        is_admin=configured_admin,
        is_banned=user.is_banned,
        is_onboarded=is_onboarded
    )

@app.put("/api/user/{user_id}/profile", response_model=UserResponse)
async def update_user_profile(
    user_id: int,
    payload: UserProfileUpdate,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """
    Saves student onboarding selection.
    Both first_name and last_name are MANDATORY (one cannot be left empty).
    """
    require_matching_telegram_user(x_telegram_init_data, user_id)
    first_name = payload.first_name.strip() if payload.first_name else ""
    last_name = payload.last_name.strip() if payload.last_name else ""

    if not first_name or not last_name:
        raise HTTPException(
            status_code=400,
            detail="И имя, и фамилия обязательны к заполнению. Нельзя указать только одно поле."
        )

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_banned:
        raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован администратором.")

    class_name = payload.class_name.strip()
    profile_name = payload.profile_name.strip()
    if class_name not in CLASS_PROFILES_MAP or profile_name not in CLASS_PROFILES_MAP[class_name]:
        raise HTTPException(status_code=422, detail="Выберите существующий класс и профиль.")
    if payload.subgroup not in (None, 1, 2):
        raise HTTPException(status_code=422, detail="Номер подгруппы должен быть 1 или 2.")

    user.class_name = class_name
    user.profile_name = profile_name
    user.first_name = first_name
    user.last_name = last_name
    user.subgroup = payload.subgroup

    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        photo_url=user.photo_url,
        class_name=user.class_name,
        profile_name=user.profile_name,
        subgroup=user.subgroup,
        is_admin=(user.id in settings.admin_ids or bool(user.username and user.username.lower().lstrip("@") in settings.admin_usernames)),
        is_banned=user.is_banned,
        is_onboarded=True
    )

# -------------------------------------------------------------
# Bell Schedule & Live Status Endpoints (Tyumen Time UTC+5)
# -------------------------------------------------------------
@app.get("/api/schedule/bells", response_model=List[BellItem])
async def get_bells(db: AsyncSession = Depends(get_db)):
    cached = cache_get("schedule_bells", 600.0)
    if cached:
        return cached
    res = await db.execute(
        select(BellSchedule).order_by(BellSchedule.lesson_number)
    )
    raw_bells = res.scalars().all()
    bells = [
        BellItem(
            lesson_number=b.lesson_number,
            start_time=b.start_time,
            end_time=b.end_time
        )
        for b in raw_bells
    ]
    cache_set("schedule_bells", bells)
    return bells

def format_minutes_human(minutes: int) -> str:
    """
    Formats minute duration into natural Russian string.
    Under 60 mins: e.g. '45 мин'.
    >= 60 mins: e.g. '1 час и 15 минут', '2 часа', '1 час и 1 минута'.
    """
    if minutes < 60:
        return f"{minutes} мин"

    h = minutes // 60
    m = minutes % 60

    h_mod100 = h % 100
    h_mod10 = h % 10
    if 11 <= h_mod100 <= 14:
        h_unit = "часов"
    elif h_mod10 == 1:
        h_unit = "час"
    elif 2 <= h_mod10 <= 4:
        h_unit = "часа"
    else:
        h_unit = "часов"

    if m == 0:
        return f"{h} {h_unit}"

    m_mod100 = m % 100
    m_mod10 = m % 10
    if 11 <= m_mod100 <= 14:
        m_unit = "минут"
    elif m_mod10 == 1:
        m_unit = "минута"
    elif 2 <= m_mod10 <= 4:
        m_unit = "минуты"
    else:
        m_unit = "минут"

    return f"{h} {h_unit} и {m} {m_unit}"

@app.get("/api/schedule/live", response_model=LiveStatusResponse)
async def get_live_status(
    class_name: Optional[str] = Query(None),
    profile_name: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Real-time progress calculation synchronized with Tyumen timezone (Asia/Yekaterinburg, UTC+5).
    Differentiates Monday schedule (08:00 «Разговоры о важном») vs Tuesday-Friday standard bells.
    Enriches status with active/next lesson subject & cabinet if class_name is provided.
    """
    now = datetime.now(TYUMEN_TZ)
    day_of_week = now.weekday() # 0=Mon..6=Sun
    now_minutes = now.hour * 60 + now.minute
    time_str = now.strftime("%H:%M")

    def parse_minutes(t_str: str) -> int:
        h, m = map(int, t_str.split(":"))
        return h * 60 + m

    if class_name:
        class_has_schedule = await db.scalar(
            select(Lesson.id).where(Lesson.class_name == class_name).limit(1)
        )
        if class_has_schedule is None:
            return LiveStatusResponse(
                current_time=time_str,
                state="no_schedule",
                message=f"Расписание для {class_name} ещё не загружено"
            )

    async def get_lesson_for_num(num: int) -> Optional[Lesson]:
        if not class_name or day_of_week > 5:
            return None
        q = select(Lesson).where(
            Lesson.class_name == class_name,
            Lesson.day_of_week == day_of_week,
            Lesson.lesson_number == num
        )
        res = await db.execute(q)
        lessons = res.scalars().all()
        if not lessons:
            return None
        if profile_name:
            for l in lessons:
                if l.profile_name and l.profile_name.strip().lower() == profile_name.strip().lower():
                    return l
        return lessons[0]

    # Sunday check
    if day_of_week == 6:
        return LiveStatusResponse(
            current_time=time_str,
            state="weekend",
            message="Сегодня воскресенье — уроков нет"
        )

    # Saturday check
    if day_of_week == 5:
        sat_start = parse_minutes("10:00")
        sat_end = parse_minutes("14:00")
        if now_minutes < sat_start:
            diff = sat_start - now_minutes
            return LiveStatusResponse(
                current_time=time_str,
                state="before_school",
                minutes_left=diff,
                message=f"Консультации начнутся в 10:00 (через {format_minutes_human(diff)})"
            )
        elif sat_start <= now_minutes < sat_end:
            diff = sat_end - now_minutes
            return LiveStatusResponse(
                current_time=time_str,
                state="lesson",
                minutes_left=diff,
                message=f"Идут консультации (до окончания {format_minutes_human(diff)})"
            )
        else:
            return LiveStatusResponse(
                current_time=time_str,
                state="after_school",
                message="Консультации завершены 🎉"
            )

    # Monday bell schedule (with Разговоры о важном)
    if day_of_week == 0:
        day_bells = [
            {"num": 0, "title": "Разговоры о важном", "start": "08:00", "end": "08:30"},
            {"num": 1, "title": "1 урок", "start": "08:35", "end": "09:15"},
            {"num": 2, "title": "2 урок", "start": "09:30", "end": "10:10"},
            {"num": 3, "title": "3 урок", "start": "10:25", "end": "11:05"},
            {"num": 4, "title": "4 урок", "start": "11:25", "end": "12:05"},
            {"num": 5, "title": "5 урок", "start": "12:25", "end": "13:05"},
            {"num": 6, "title": "6 урок", "start": "13:10", "end": "13:50"},
            {"num": 7, "title": "7 урок", "start": "14:00", "end": "14:40"},
        ]
    else:
        bell_res = await db.execute(select(BellSchedule).order_by(BellSchedule.lesson_number))
        day_bells = [
            {"num": bell.lesson_number, "title": f"{bell.lesson_number} урок", "start": bell.start_time, "end": bell.end_time}
            for bell in bell_res.scalars().all()
        ]
        if not day_bells:
            return LiveStatusResponse(
                current_time=time_str,
                state="no_schedule",
                message="Расписание звонков ещё не настроено"
            )

    first_start = parse_minutes(day_bells[0]["start"])
    if now_minutes < first_start:
        diff = first_start - now_minutes
        target_name = day_bells[0]["title"]
        next_les = await get_lesson_for_num(day_bells[0]["num"])
        les_info = f" • {next_les.subject} (каб. {next_les.cabinet})" if next_les else ""
        return LiveStatusResponse(
            current_time=time_str,
            state="before_school",
            minutes_left=diff,
            message=f"До начала ({target_name}{les_info}): {format_minutes_human(diff)}",
            next_lesson_number=day_bells[0]["num"],
            next_lesson_time=day_bells[0]["start"]
        )

    last_end = parse_minutes(day_bells[-1]["end"])
    if now_minutes >= last_end:
        return LiveStatusResponse(
            current_time=time_str,
            state="after_school",
            message="Учебный день завершен 🎉"
        )

    for i, bell in enumerate(day_bells):
        b_start = parse_minutes(bell["start"])
        b_end = parse_minutes(bell["end"])

        if b_start <= now_minutes < b_end:
            diff = b_end - now_minutes
            lesson_label = bell["title"]
            active_les = await get_lesson_for_num(bell["num"])
            les_info = f" • {active_les.subject} (каб. {active_les.cabinet})" if active_les else ""
            return LiveStatusResponse(
                current_time=time_str,
                state="lesson",
                current_lesson_number=bell["num"],
                minutes_left=diff,
                message=f"{lesson_label}{les_info}: до конца {format_minutes_human(diff)}"
            )

        if i < len(day_bells) - 1:
            next_b = day_bells[i + 1]
            next_start = parse_minutes(next_b["start"])
            if b_end <= now_minutes < next_start:
                diff = next_start - now_minutes
                next_label = next_b["title"]
                next_les = await get_lesson_for_num(next_b["num"])
                les_info = f" • След: {next_les.subject} (каб. {next_les.cabinet})" if next_les else ""
                return LiveStatusResponse(
                    current_time=time_str,
                    state="break",
                    current_lesson_number=bell["num"],
                    minutes_left=diff,
                    message=f"Перемена{les_info}: до {next_label} {format_minutes_human(diff)}",
                    next_lesson_number=next_b["num"],
                    next_lesson_time=next_b["start"]
                )

    return LiveStatusResponse(
        current_time=time_str,
        state="after_school",
        message="Уроки закончились"
    )

# -------------------------------------------------------------
# Schedule Endpoints
# -------------------------------------------------------------
DAY_NAMES = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

@app.get("/api/schedule/lessons", response_model=DayScheduleResponse)
async def get_lessons(
    class_name: str = Query(..., description="11А, 11Б, 11В, 11Г, 11Д, 11Ж"),
    day_of_week: int = Query(0, ge=0, le=5, description="0=Пн..5=Сб"),
    only_my_profile: bool = Query(False, description="Filter for student's profile"),
    profile_name: Optional[str] = Query(None),
    subgroup: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetches day schedule for a given class.
    If only_my_profile=True, filters to common lessons + matching profile.
    If only_my_profile=False, returns all class lessons grouped into slots with split indicators.
    """
    cache_key = f"sched:{class_name}:{day_of_week}:{only_my_profile}:{profile_name}:{subgroup}"
    cached = cache_get(cache_key, 180.0)
    if cached:
        return cached

    times = await day_bells(db, day_of_week)
    bells_map = {number: BellItem(lesson_number=number, start_time=value[0], end_time=value[1]) for number, value in times.items()}

    query = select(Lesson).where(
        Lesson.class_name == class_name,
        Lesson.day_of_week == day_of_week
    ).order_by(Lesson.lesson_number, Lesson.profile_name)

    res = await db.execute(query)
    raw_lessons = res.scalars().all()
    class_schedule_id = await db.scalar(
        select(Lesson.id).where(Lesson.class_name == class_name).limit(1)
    )
    schedule_loaded = class_schedule_id is not None

    # Apply profile filter if requested
    filtered_lessons: List[Lesson] = []
    for l in raw_lessons:
        if only_my_profile and profile_name:
            profile_matches = (l.profile_name is None) or (l.profile_name.strip().lower() == profile_name.strip().lower())
            subgroup_matches = l.subgroup is None or subgroup is None or l.subgroup == subgroup
            if profile_matches and subgroup_matches:
                filtered_lessons.append(l)
        elif subgroup is not None:
            if l.subgroup is None or l.subgroup == subgroup:
                filtered_lessons.append(l)
        else:
            filtered_lessons.append(l)

    # Group into LessonSlots by lesson_number
    slots_map: Dict[int, List[LessonItem]] = {}
    for l in filtered_lessons:
        b = bells_map.get(l.lesson_number)
        item = LessonItem(
            id=l.id,
            day_of_week=l.day_of_week,
            lesson_number=l.lesson_number,
            class_name=l.class_name,
            subject=l.subject,
            teacher_name=l.teacher_name,
            cabinet=l.cabinet,
            profile_name=l.profile_name,
            subgroup=l.subgroup,
            note=l.note,
            start_time=b.start_time if b else "",
            end_time=b.end_time if b else ""
        )
        slots_map.setdefault(l.lesson_number, []).append(item)

    slots: List[LessonSlot] = []
    for num in sorted(slots_map.keys()):
        items = slots_map[num]
        b = bells_map.get(num)
        start_t = b.start_time if b else ""
        end_t = b.end_time if b else ""
        is_split = len(items) > 1

        slots.append(LessonSlot(
            lesson_number=num,
            start_time=start_t,
            end_time=end_t,
            is_split=is_split,
            lessons=items
        ))

    resp = DayScheduleResponse(
        day_of_week=day_of_week,
        day_name=DAY_NAMES[day_of_week],
        class_name=class_name,
        schedule_loaded=schedule_loaded,
        slots=slots
    )
    cache_set(cache_key, resp)
    return resp

# -------------------------------------------------------------
# News Feed & Social Endpoints
# -------------------------------------------------------------
@app.get("/api/news", response_model=List[NewsResponse])
async def get_news(
    user_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    parsed_user_id: Optional[int] = None
    if user_id:
        cleaned_uid = str(user_id).strip()
        if not cleaned_uid.isdigit():
            raise HTTPException(status_code=400, detail="Некорректный Telegram ID.")
        parsed_user_id = int(cleaned_uid)
        require_matching_telegram_user(x_telegram_init_data, parsed_user_id)
    """
    Returns approved news feed posts with reaction tallies and comments count.
    If post is anonymous, author_name is masked as 'Анонимно' and author_class is omitted.
    Otherwise, shows author_name and author_class.
    Timestamps formatted in Tyumen timezone (UTC+5).
    """
    query = (
        select(NewsPost)
        .where(NewsPost.status == "approved")
        .options(selectinload(NewsPost.author))
        .order_by(NewsPost.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    res = await db.execute(query)
    posts = res.scalars().all()
    post_ids = [post.id for post in posts]
    if not post_ids:
        return []

    reaction_counts: Dict[int, Dict[str, int]] = {}
    reaction_rows = await db.execute(
        select(Reaction.post_id, Reaction.emoji, func.count(Reaction.id))
        .where(Reaction.post_id.in_(post_ids))
        .group_by(Reaction.post_id, Reaction.emoji)
    )
    for post_id, emoji, count in reaction_rows.all():
        reaction_counts.setdefault(post_id, {})[emoji] = count

    reacted_by_user = set()
    if parsed_user_id:
        user_reaction_rows = await db.execute(
            select(Reaction.post_id, Reaction.emoji)
            .where(Reaction.post_id.in_(post_ids), Reaction.user_id == parsed_user_id)
        )
        reacted_by_user = set(user_reaction_rows.all())

    comment_count_rows = await db.execute(
        select(Comment.post_id, func.count(Comment.id))
        .where(Comment.post_id.in_(post_ids))
        .group_by(Comment.post_id)
    )
    comment_counts = dict(comment_count_rows.all())

    response: List[NewsResponse] = []

    for p in posts:
        # Calculate reactions across the 6 emojis palette
        reaction_counts_dict: Dict[str, int] = {e: 0 for e in EMOJI_PALETTE}
        user_reacted_dict: Dict[str, bool] = {e: False for e in EMOJI_PALETTE}

        for emoji, count in reaction_counts.get(p.id, {}).items():
            reaction_counts_dict[emoji] = count
        for emoji in EMOJI_PALETTE:
            user_reacted_dict[emoji] = (p.id, emoji) in reacted_by_user

        reactions_list = [
            ReactionCount(
                emoji=e,
                count=reaction_counts_dict[e],
                user_reacted=user_reacted_dict[e]
            )
            for e in EMOJI_PALETTE
        ]

        # Handle anonymity
        if p.is_anonymous:
            display_author = "Анонимно"
            display_class = None
        else:
            display_author = p.author_name
            display_class = p.author_class

        # Convert created_at to Tyumen time
        if p.created_at:
            post_dt = p.created_at
            if post_dt.tzinfo is None:
                post_dt = post_dt.replace(tzinfo=timezone.utc).astimezone(TYUMEN_TZ)
            else:
                post_dt = post_dt.astimezone(TYUMEN_TZ)
            formatted_date = post_dt.strftime("%d.%m.%Y %H:%M")
        else:
            formatted_date = ""

        author_photo = None
        if not p.is_anonymous and p.author and p.author.photo_url:
            author_photo = p.author.photo_url

        response.append(NewsResponse(
            id=p.id,
            title=p.title,
            content=p.content,
            image_url=p.image_url,
            author_name=display_author,
            author_class=display_class,
            author_photo_url=author_photo,
            is_anonymous=p.is_anonymous,
            status=p.status,
            created_at=formatted_date,
            reactions=reactions_list,
            comments_count=comment_counts.get(p.id, 0)
        ))

    return response

@app.post("/api/news", response_model=NewsResponse, status_code=status.HTTP_201_CREATED)
async def suggest_news(
    payload: NewsCreateRequest, 
    background_tasks: BackgroundTasks,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """
    Students propose a news post.
    Guarantees user exists in DB to prevent foreign key errors and accurately captures author and class.
    """
    telegram_user = require_telegram_user(x_telegram_init_data)
    author_id = int(telegram_user["id"])
    enforce_rate_limit(f"news:{author_id}", 5, 3600)
    if payload.author_id is not None and payload.author_id != author_id:
        raise HTTPException(status_code=403, detail="Нельзя отправлять новость от имени другого пользователя.")
    user = await db.get(User, author_id)
    if not user:
        raise HTTPException(status_code=409, detail="Сначала заполните профиль Telegram.")

    if user.is_banned:
        raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован администратором.")

    author_class = user.class_name
    author_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Гимназист"

    new_post = NewsPost(
        title=payload.title.strip(),
        content=payload.content.strip(),
        image_url=payload.image_url,
        author_id=user.id,
        author_name=author_name,
        author_class=author_class,
        is_anonymous=payload.is_anonymous,
        status="pending"
    )
    db.add(new_post)
    await db.commit()
    await db.refresh(new_post)

    # Trigger admin notification in background
    background_tasks.add_task(
        notify_admins_about_post,
        post_id=new_post.id,
        title=new_post.title,
        content=new_post.content,
        author_name=new_post.author_name,
        author_class=new_post.author_class,
        is_anonymous=new_post.is_anonymous,
        image_url=new_post.image_url,
        author_username=user.username or payload.author_username,
        author_id=user.id
    )

    reactions_list = [ReactionCount(emoji=e, count=0, user_reacted=False) for e in EMOJI_PALETTE]

    user_photo = None
    if not new_post.is_anonymous and user and user.photo_url:
        user_photo = user.photo_url

    return NewsResponse(
        id=new_post.id,
        title=new_post.title,
        content=new_post.content,
        image_url=new_post.image_url,
        author_name="Анонимно" if new_post.is_anonymous else new_post.author_name,
        author_class=None if new_post.is_anonymous else new_post.author_class,
        author_photo_url=user_photo,
        is_anonymous=new_post.is_anonymous,
        status=new_post.status,
        created_at=datetime.now(TYUMEN_TZ).strftime("%d.%m.%Y %H:%M"),
        reactions=reactions_list,
        comments_count=0
    )

@app.post("/api/news/{post_id}/react", response_model=List[ReactionCount])
async def toggle_reaction(
    post_id: int, 
    payload: ReactionToggleRequest, 
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """
    Toggles reaction on a news post.
    - If user taps the SAME emoji they already reacted with -> removes it (un-react).
    - If user taps a DIFFERENT emoji -> replaces previous reaction with the new one.
    """
    require_matching_telegram_user(x_telegram_init_data, payload.user_id)
    enforce_rate_limit(f"reaction:{payload.user_id}", 60, 60)
    post = await db.get(NewsPost, post_id)
    if not post or post.status != "approved":
        raise HTTPException(status_code=404, detail="News post not found or not approved")

    user = await db.get(User, payload.user_id)
    if user and user.is_banned:
        raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован администратором.")

    # Check if this exact reaction already exists
    res = await db.execute(
        select(Reaction).where(
            Reaction.post_id == post_id,
            Reaction.user_id == payload.user_id,
            Reaction.emoji == payload.emoji
        )
    )
    existing_same = res.scalars().first()

    if existing_same:
        # User clicked same emoji -> Remove it (toggle off)
        await db.delete(existing_same)
    else:
        # User clicked different emoji or new reaction -> Remove any previous reaction on this post
        previous_reactions = (await db.scalars(
            select(Reaction).where(
                Reaction.post_id == post_id,
                Reaction.user_id == payload.user_id
            )
        )).all()
        for reaction in previous_reactions:
            await db.delete(reaction)
        # Add new reaction
        new_reaction = Reaction(
            post_id=post_id,
            user_id=payload.user_id,
            emoji=payload.emoji
        )
        db.add(new_reaction)

    await db.commit()

    # Tally updated counts for this post
    all_reactions_res = await db.execute(
        select(Reaction).where(Reaction.post_id == post_id)
    )
    all_reactions = all_reactions_res.scalars().all()

    counts_map = {e: 0 for e in EMOJI_PALETTE}
    user_map = {e: False for e in EMOJI_PALETTE}

    for r in all_reactions:
        if r.emoji in counts_map:
            counts_map[r.emoji] += 1
        if r.user_id == payload.user_id and r.emoji in user_map:
            user_map[r.emoji] = True

    return [
        ReactionCount(emoji=e, count=counts_map[e], user_reacted=user_map[e])
        for e in EMOJI_PALETTE
    ]

@app.get("/api/news/{post_id}/comments", response_model=List[CommentResponse])
async def get_comments(
    post_id: int,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves all comments for a news post (Bottom Sheet).
    Timestamps formatted in Tyumen timezone.
    """
    post = await db.get(NewsPost, post_id)
    if not post or post.status != "approved":
        raise HTTPException(status_code=404, detail="News post not found")

    res = await db.execute(
        select(Comment)
        .where(Comment.post_id == post_id)
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .offset(offset)
        .limit(limit)
    )
    comments = res.scalars().all()

    result: List[CommentResponse] = []
    for c in comments:
        if c.created_at:
            dt = c.created_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc).astimezone(TYUMEN_TZ)
            else:
                dt = dt.astimezone(TYUMEN_TZ)
            c_date = dt.strftime("%d.%m %H:%M")
        else:
            c_date = ""

        result.append(CommentResponse(
            id=c.id,
            post_id=c.post_id,
            user_id=c.user_id,
            author_name=c.author_name,
            author_class=c.author_class,
            text=c.text,
            created_at=c_date
        ))

    result.reverse()
    return result

@app.post("/api/news/{post_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def add_comment(
    post_id: int, 
    payload: CommentCreateRequest, 
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """
    Adds a new comment to a news post.
    """
    require_matching_telegram_user(x_telegram_init_data, payload.user_id)
    enforce_rate_limit(f"comment:{payload.user_id}", 30, 60)
    post = await db.get(NewsPost, post_id)
    if not post or post.status != "approved":
        raise HTTPException(status_code=404, detail="News post not found")

    user = await db.get(User, payload.user_id)
    if user and user.is_banned:
        raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован администратором.")

    if not user:
        raise HTTPException(status_code=409, detail="Сначала заполните профиль Telegram.")

    new_comment = Comment(
        post_id=post_id,
        user_id=payload.user_id,
        author_name=f"{user.first_name or ''} {user.last_name or ''}".strip() or "Гимназист",
        author_class=user.class_name,
        text=payload.text
    )
    db.add(new_comment)
    await db.commit()
    await db.refresh(new_comment)

    return CommentResponse(
        id=new_comment.id,
        post_id=new_comment.post_id,
        user_id=new_comment.user_id,
        author_name=new_comment.author_name,
        author_class=new_comment.author_class,
        text=new_comment.text,
        created_at=datetime.now(TYUMEN_TZ).strftime("%d.%m %H:%M")
    )

# -------------------------------------------------------------
# -------------------------------------------------------------
# Admin Moderation Endpoints
# -------------------------------------------------------------
@app.get("/api/admin/news/pending", response_model=List[NewsResponse])
async def get_pending_news(
    admin_id: Optional[int] = Query(None),
    ts: Optional[int] = Query(None),
    sign: Optional[str] = Query(None),
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    await check_admin_permission_or_raise(
        admin_id=admin_id, ts=ts, sign=sign,
        x_telegram_init_data=x_telegram_init_data, db=db
    )

    res = await db.execute(
        select(NewsPost)
        .where(NewsPost.status == "pending")
        .order_by(NewsPost.created_at.desc())
    )
    posts = res.scalars().all()

    author_ids = {p.author_id for p in posts if p.author_id}
    users_by_id = {}
    if author_ids:
        u_res = await db.execute(select(User).where(User.id.in_(author_ids)))
        users_by_id = {u.id: u for u in u_res.scalars().all()}

    return [
        NewsResponse(
            id=p.id,
            title=p.title,
            content=p.content,
            image_url=p.image_url,
            author_name=p.author_name,
            author_class=p.author_class,
            author_username=users_by_id.get(p.author_id).username if users_by_id.get(p.author_id) else None,
            is_anonymous=p.is_anonymous,
            status=p.status,
            created_at=p.created_at.strftime("%d.%m.%Y %H:%M") if p.created_at else "",
            reactions=[ReactionCount(emoji=e, count=0, user_reacted=False) for e in EMOJI_PALETTE],
            comments_count=0
        )
        for p in posts
    ]

@app.post("/api/admin/news/{post_id}/moderate")
async def moderate_news(
    post_id: int, 
    payload: ModerationActionRequest, 
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """
    Approves or rejects a suggested news item.
    """
    await check_admin_permission_or_raise(
        admin_id=payload.admin_id, ts=payload.ts, sign=payload.sign,
        x_telegram_init_data=x_telegram_init_data, db=db
    )

    post = await db.get(NewsPost, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="News post not found")

    if payload.action == "approve":
        post.status = "approved"
        post.published_at = datetime.now(timezone.utc)
    else:
        post.status = "rejected"

    from models import NewsReview
    review = await db.get(NewsReview, post_id)
    if not review:
        review = NewsReview(post_id=post_id)
        db.add(review)
    review.reason = payload.reason.strip() if payload.action == "reject" and payload.reason else None

    await db.commit()
    return {"status": "success", "post_id": post_id, "action": payload.action}

@app.delete("/api/admin/news/{post_id}")
@app.delete("/api/news/{post_id}")
async def delete_news_post(
    post_id: int, 
    admin_id: Optional[int] = Query(None), 
    user_id: Optional[int] = Query(None),
    ts: Optional[int] = Query(None),
    sign: Optional[str] = Query(None),
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """
    Deletes a news post and removes its attached media file.
    Only authorized administrators can delete posts.
    """
    uid = admin_id or user_id
    await check_admin_permission_or_raise(
        admin_id=uid, ts=ts, sign=sign,
        x_telegram_init_data=x_telegram_init_data, db=db
    )

    post = await db.get(NewsPost, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="News post not found")

    if post.image_url:
        img_path = settings.UPLOAD_DIR / Path(post.image_url).name
        if img_path.exists():
            try:
                img_path.unlink()
            except Exception:
                pass

    await db.delete(post)
    await db.commit()
    return {"status": "success", "post_id": post_id, "action": "deleted"}

@app.put("/api/admin/news/{post_id}", response_model=NewsResponse)
@app.put("/api/news/{post_id}", response_model=NewsResponse)
async def edit_news_post(
    post_id: int, 
    payload: NewsEditRequest, 
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """
    Allows administrator to edit post title, content, and image directly in the feed.
    """
    admin_uid = payload.admin_id or payload.user_id
    await check_admin_permission_or_raise(
        admin_id=admin_uid,
        x_telegram_init_data=x_telegram_init_data, db=db
    )

    post = await db.get(NewsPost, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="News post not found")

    post.title = payload.title.strip()
    post.content = payload.content.strip()
    if payload.image_url is not None:
        new_img = payload.image_url.strip()
        post.image_url = new_img if new_img else None

    await db.commit()

    # Reload post with full relationships
    query = (
        select(NewsPost)
        .where(NewsPost.id == post_id)
        .options(selectinload(NewsPost.reactions), selectinload(NewsPost.comments), selectinload(NewsPost.author))
    )
    res = await db.execute(query)
    updated_post = res.scalar_one_or_none() or post

    reaction_counts_dict: Dict[str, int] = {e: 0 for e in EMOJI_PALETTE}
    user_reacted_dict: Dict[str, bool] = {e: False for e in EMOJI_PALETTE}
    for r in getattr(updated_post, "reactions", []):
        reaction_counts_dict[r.emoji] = reaction_counts_dict.get(r.emoji, 0) + 1
        if admin_uid and r.user_id == admin_uid:
            user_reacted_dict[r.emoji] = True

    reactions_list = [
        ReactionCount(
            emoji=e,
            count=reaction_counts_dict[e],
            user_reacted=user_reacted_dict[e]
        )
        for e in EMOJI_PALETTE
    ]

    if updated_post.created_at:
        post_dt = updated_post.created_at
        if post_dt.tzinfo is None:
            post_dt = post_dt.replace(tzinfo=timezone.utc).astimezone(TYUMEN_TZ)
        else:
            post_dt = post_dt.astimezone(TYUMEN_TZ)
        formatted_date = post_dt.strftime("%d.%m.%Y %H:%M")
    else:
        formatted_date = ""

    author_photo = None
    if not updated_post.is_anonymous and updated_post.author and updated_post.author.photo_url:
        author_photo = updated_post.author.photo_url

    return NewsResponse(
        id=updated_post.id,
        title=updated_post.title,
        content=updated_post.content,
        image_url=updated_post.image_url,
        author_name="Анонимно" if updated_post.is_anonymous else updated_post.author_name,
        author_class=None if updated_post.is_anonymous else updated_post.author_class,
        author_photo_url=author_photo,
        is_anonymous=updated_post.is_anonymous,
        status=updated_post.status,
        created_at=formatted_date,
        reactions=reactions_list,
        comments_count=len(getattr(updated_post, "comments", []))
    )

@app.delete("/api/admin/comments/{comment_id}")
@app.delete("/api/news/comments/{comment_id}")
async def delete_comment(
    comment_id: int, 
    user_id: int = Query(...), 
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """
    Deletes a comment. Allowed for admins, or the author of the comment.
    """
    require_matching_telegram_user(x_telegram_init_data, user_id)
    comment = await db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    user = await db.get(User, user_id)
    if user and user.is_banned:
        raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован администратором.")
    is_admin = await check_is_admin(user_id, db)

    if not is_admin and comment.user_id != user_id:
        raise HTTPException(status_code=403, detail="Permission denied to delete this comment")

    await db.delete(comment)
    await db.commit()
    return {"status": "success", "comment_id": comment_id, "action": "deleted"}

# -------------------------------------------------------------
# Media Storage & Proxy Endpoints
# -------------------------------------------------------------
ALLOWED_IMAGE_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif", 
    "image/heic", "image/heif", "image/bmp", "image/jpg", 
    "image/pjpeg", "image/x-png"
}
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "heic", "heif", "bmp"}

@app.post("/api/upload")
async def upload_image(
    file: UploadFile = File(...),
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """
    Saves an uploaded image locally to /uploads without paid cloud services.
    Supports all mobile image formats (including iPhone HEIC / JPEG / PNG).
    Validates file extension, disallows SVG/scripts, and checks image magic bytes.
    """
    telegram_user = require_telegram_user(x_telegram_init_data)
    enforce_rate_limit(f"upload:{telegram_user['id']}", 10, 3600)
    user = await db.get(User, int(telegram_user["id"]))
    if not user:
        raise HTTPException(status_code=409, detail="Сначала заполните профиль Telegram.")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован администратором.")

    ext = file.filename.split(".")[-1].lower() if file.filename and "." in file.filename else "jpg"
    if ext not in ALLOWED_EXTENSIONS:
        ext = "jpg"

    # Reject dangerous SVG or executable formats
    if file.content_type and "svg" in file.content_type.lower():
        raise HTTPException(status_code=400, detail="Формат SVG запрещен в целях безопасности.")

    # Read in bounded chunks so oversized files do not allocate unbounded memory.
    content = bytearray()
    while chunk := await file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Размер файла превышает лимит 10 МБ.")
    content = bytes(content)
    if len(content) < 16:
        raise HTTPException(status_code=400, detail="Некорректный файл изображения.")

    # Validate image magic bytes to prevent polyglot / script uploads
    is_valid_image = (
        content[:2] == b"\xff\xd8" or                            # JPEG
        content[:8] == b"\x89PNG\r\n\x1a\n" or                    # PNG
        content[:4] in (b"GIF8",) or                             # GIF
        (content[:4] == b"RIFF" and b"WEBP" in content[:16]) or  # WebP
        b"ftyp" in content[:24] or                               # HEIC / HEIF
        content[:2] == b"BM"                                     # BMP
    )
    if not is_valid_image:
        raise HTTPException(status_code=400, detail="Файл поврежден или не является допустимым изображением.")

    filename = f"{uuid.uuid4().hex}.{ext}"
    file_path = settings.UPLOAD_DIR / filename

    with open(file_path, "wb") as f:
        f.write(content)

    return {
        "url": f"/uploads/{filename}",
        "filename": filename
    }

@app.get("/api/media/{file_id}")
async def proxy_telegram_media(file_id: str):
    """
    Proxy endpoint: Streams media directly from Telegram Bot API via file_id.
    Provides free, permanent media hosting directly via Telegram CDN.
    """
    if not settings.BOT_TOKEN or "ABCdefGHI" in settings.BOT_TOKEN:
        raise HTTPException(status_code=500, detail="Telegram Bot Token is not configured")

    bot_url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Step 1: getFilePath from Telegram
        info_resp = await client.get(f"{bot_url}/getFile", params={"file_id": file_id})
        if info_resp.status_code != 200:
            raise HTTPException(status_code=404, detail="Media not found on Telegram servers")

        file_path = info_resp.json().get("result", {}).get("file_path")
        if not file_path:
            raise HTTPException(status_code=404, detail="Telegram file path not found")

        # Step 2: Stream content
        download_url = f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{file_path}"
        media_resp = await client.get(download_url)
        if media_resp.status_code != 200:
            raise HTTPException(status_code=media_resp.status_code, detail="Failed to fetch media from Telegram")

        content_type = media_resp.headers.get("content-type", "image/jpeg")
        return StreamingResponse(
            iter([media_resp.content]),
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"}
        )


# -------------------------------------------------------------
# EGE (ЕГЭ) Preparation Endpoints
# -------------------------------------------------------------
@app.get("/api/ege/subjects", response_model=List[EgeSubjectResponse])
async def get_ege_subjects(db: AsyncSession = Depends(get_db)):
    """Returns available EGE subjects (Русский язык, Математика, etc.)"""
    res = await db.execute(select(EgeSubject).order_by(EgeSubject.id))
    subjects = res.scalars().all()
    return subjects

@app.get("/api/ege/materials", response_model=List[EgeMaterialResponse])
async def get_ege_materials(
    subject_code: str = Query("russian"),
    task_number: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Returns cheat-sheets and theory materials filtered by subject and task number."""
    query = select(EgeMaterial).where(EgeMaterial.subject_code == subject_code)
    if task_number is not None and task_number > 0:
        query = query.where(EgeMaterial.task_number == task_number)
    query = query.order_by(EgeMaterial.task_number.asc(), EgeMaterial.created_at.desc())
    res = await db.execute(query)
    materials = res.scalars().all()

    response = []
    for m in materials:
        created_str = m.created_at.strftime("%d.%m.%Y") if m.created_at else ""
        response.append(EgeMaterialResponse(
            id=m.id,
            subject_code=m.subject_code,
            task_number=m.task_number,
            title=m.title,
            theory=m.theory,
            image_url=m.image_url,
            link_url=m.link_url,
            created_at=created_str
        ))
    return response

@app.post("/api/ege/materials", response_model=EgeMaterialResponse, status_code=status.HTTP_201_CREATED)
async def create_ege_material(
    payload: EgeMaterialCreateRequest,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """Allows administrator to publish new reference theory/cheat-sheet for EGE tasks."""
    await check_admin_permission_or_raise(
        admin_id=payload.admin_id, x_telegram_init_data=x_telegram_init_data, db=db
    )

    new_mat = EgeMaterial(
        subject_code=payload.subject_code,
        task_number=payload.task_number,
        title=payload.title.strip(),
        theory=payload.theory.strip(),
        image_url=payload.image_url,
        link_url=payload.link_url
    )
    cache_clear_prefix("ege_")
    db.add(new_mat)
    await db.commit()
    await db.refresh(new_mat)

    return EgeMaterialResponse(
        id=new_mat.id,
        subject_code=new_mat.subject_code,
        task_number=new_mat.task_number,
        title=new_mat.title,
        theory=new_mat.theory,
        image_url=new_mat.image_url,
        link_url=new_mat.link_url,
        created_at=datetime.now(TYUMEN_TZ).strftime("%d.%m.%Y")
    )

@app.put("/api/ege/materials/{material_id}", response_model=EgeMaterialResponse)
async def update_ege_material(
    material_id: int,
    payload: EgeMaterialCreateRequest,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """Allows administrator to update an existing EGE material."""
    await check_admin_permission_or_raise(
        admin_id=payload.admin_id, x_telegram_init_data=x_telegram_init_data, db=db
    )

    mat = await db.get(EgeMaterial, material_id)
    if not mat:
        raise HTTPException(status_code=404, detail="Material not found")

    mat.subject_code = payload.subject_code
    mat.task_number = payload.task_number
    mat.title = payload.title.strip()
    mat.theory = payload.theory.strip()
    mat.image_url = payload.image_url
    mat.link_url = payload.link_url

    await db.commit()
    await db.refresh(mat)

    return EgeMaterialResponse(
        id=mat.id,
        subject_code=mat.subject_code,
        task_number=mat.task_number,
        title=mat.title,
        theory=mat.theory,
        image_url=mat.image_url,
        link_url=mat.link_url,
        created_at=mat.created_at.strftime("%d.%m.%Y") if mat.created_at else ""
    )

@app.delete("/api/ege/materials/{material_id}")
async def delete_ege_material(
    material_id: int,
    admin_id: int = Query(...),
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """Allows administrator to delete an EGE material."""
    await check_admin_permission_or_raise(
        admin_id=admin_id, x_telegram_init_data=x_telegram_init_data, db=db
    )

    mat = await db.get(EgeMaterial, material_id)
    if not mat:
        raise HTTPException(status_code=404, detail="Material not found")

    if mat.image_url:
        p = settings.UPLOAD_DIR / Path(mat.image_url).name
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    cache_clear_prefix("ege_")
    await db.delete(mat)
    await db.commit()
    return {"status": "success", "material_id": material_id, "action": "deleted"}

# -------------------------------------------------------------
# -------------------------------------------------------------
# Admin User List & Management Endpoints
# -------------------------------------------------------------
@app.get("/api/admin/users", response_model=List[UserAdminItem])
async def get_all_users_for_admin(
    admin_id: Optional[int] = Query(None),
    ts: Optional[int] = Query(None),
    sign: Optional[str] = Query(None),
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """Returns list of registered users for administrator review."""
    await check_admin_permission_or_raise(
        admin_id=admin_id, ts=ts, sign=sign,
        x_telegram_init_data=x_telegram_init_data, db=db
    )

    res = await db.execute(select(User).order_by(User.created_at.desc()))
    users = res.scalars().all()

    result = []
    for u in users:
        is_onboarded = bool(u.class_name and u.profile_name and u.first_name and u.last_name)
        c_str = u.created_at.strftime("%d.%m.%Y %H:%M") if u.created_at else ""
        result.append(UserAdminItem(
            id=u.id,
            first_name=u.first_name,
            last_name=u.last_name,
            username=u.username,
            class_name=u.class_name,
            profile_name=u.profile_name,
            is_admin=(u.id in settings.admin_ids or bool(u.username and u.username.lower().lstrip("@") in settings.admin_usernames)),
            is_banned=u.is_banned,
            is_onboarded=is_onboarded,
            created_at=c_str
        ))
    return result

@app.post("/api/admin/users/{user_id}/ban")
async def toggle_user_ban(
    user_id: int,
    payload: UserBanRequest,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """Allows administrator to ban or unban a user."""
    await check_admin_permission_or_raise(
        admin_id=payload.admin_id, ts=payload.ts, sign=payload.sign,
        x_telegram_init_data=x_telegram_init_data, db=db
    )

    target_user = await db.get(User, user_id)
    target_username = (target_user.username or "").lower().lstrip("@") if target_user else ""
    if user_id in settings.admin_ids or target_username in settings.admin_usernames:
        raise HTTPException(status_code=400, detail="Нельзя заблокировать администратора")

    user = target_user
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    user.is_banned = payload.is_banned
    await db.commit()
    await db.refresh(user)

    action_text = "заблокирован" if user.is_banned else "разблокирован"
    return {
        "status": "success",
        "user_id": user.id,
        "is_banned": user.is_banned,
        "message": f"Пользователь {user.first_name} {user.last_name or ''} (@{user.username or 'нет'}) успешно {action_text}."
    }

@app.get("/api/admin/users/export")
async def export_users_csv(
    admin_id: Optional[int] = Query(None),
    ts: Optional[int] = Query(None),
    sign: Optional[str] = Query(None),
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db)
):
    """Exports all registered users into a CSV spreadsheet file."""
    await check_admin_permission_or_raise(
        admin_id=admin_id, ts=ts, sign=sign,
        x_telegram_init_data=x_telegram_init_data, db=db
    )

    res = await db.execute(select(User).order_by(User.created_at.desc()))
    users = res.scalars().all()

    import csv
    import io

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM for Microsoft Excel compatibility
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "Telegram ID",
        "Имя",
        "Фамилия",
        "Username",
        "Класс",
        "Профиль",
        "Статус",
        "Роль",
        "Дата регистрации"
    ])

    for u in users:
        status_str = "Заблокирован 🚫" if u.is_banned else "Активен 🟢"
        role_str = "Администратор 👑" if u.is_admin else "Ученик 🎓"
        uname_str = f"@{u.username}" if u.username else "—"
        c_str = u.created_at.strftime("%d.%m.%Y %H:%M") if u.created_at else "—"
        writer.writerow([
            str(u.id),
            u.first_name or "",
            u.last_name or "",
            uname_str,
            u.class_name or "—",
            u.profile_name or "—",
            status_str,
            role_str,
            c_str
        ])

    csv_bytes = output.getvalue().encode("utf-8")
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=gym16_users.csv"}
    )

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_dashboard_page(
    admin_id: Optional[int] = Query(None),
    ts: Optional[int] = Query(None),
    sign: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Dedicated web dashboard page where administrator can view all users and toggle bans.
    """
    try:
        authenticated_admin_id = await check_admin_permission_or_raise(
            admin_id=admin_id, ts=ts, sign=sign, db=db
        )
    except HTTPException:
        return HTMLResponse(
            "<h3>⛔ Доступ запрещен. Требуется подтвержденная авторизация администратора.</h3>",
            status_code=403
        )

    res = await db.execute(select(User).order_by(User.created_at.desc()))
    users = res.scalars().all()

    total_count = len(users)
    banned_count = sum(1 for u in users if u.is_banned)
    active_count = total_count - banned_count

    rows_html = ""
    for u in users:
        is_adm = u.is_admin or u.id in settings.admin_ids
        status_badge = (
            '<span class="badge badge-banned">🚫 Заблокирован</span>'
            if u.is_banned else
            '<span class="badge badge-active">🟢 Активен</span>'
        )
        role_badge = '<span class="badge badge-admin">Админ 👑</span>' if is_adm else '<span class="badge badge-user">Ученик</span>'
        uname = f'<a href="https://t.me/{u.username}" target="_blank" class="tg-link">@{u.username}</a>' if u.username else '<span class="text-muted">нет</span>'
        c_date = u.created_at.strftime("%d.%m.%Y %H:%M") if u.created_at else "—"
        
        if is_adm:
            btn_action = '<span class="text-muted text-sm">Администратор</span>'
        elif u.is_banned:
            btn_action = f'<button onclick="toggleBan({u.id}, false)" class="btn btn-unban">✅ Разбанить</button>'
        else:
            btn_action = f'<button onclick="toggleBan({u.id}, true)" class="btn btn-ban">🚫 Забанить</button>'

        rows_html += f"""
        <tr data-user-id="{u.id}" class="user-row {'row-banned' if u.is_banned else ''}">
            <td><code>{u.id}</code></td>
            <td><b>{html.escape(u.first_name)} {html.escape(u.last_name or '')}</b></td>
            <td>{uname}</td>
            <td><span class="badge badge-class">{html.escape(u.class_name or '—')}</span></td>
            <td>{html.escape(u.profile_name or '—')}</td>
            <td>{role_badge}</td>
            <td id="status-{u.id}">{status_badge}</td>
            <td class="text-muted text-sm">{c_date}</td>
            <td id="action-{u.id}">{btn_action}</td>
        </tr>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Управление пользователями — Гимназия №16</title>
    <style>
        :root {{
            --bg: #F2F2F7;
            --card: #FFFFFF;
            --text: #1C1C1E;
            --muted: #8E8E93;
            --blue: #007AFF;
            --green: #34C759;
            --red: #FF3B30;
            --border: #E5E5EA;
        }}
        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg: #000000;
                --card: #1C1C1E;
                --text: #FFFFFF;
                --muted: #8E8E93;
                --blue: #0A84FF;
                --green: #30D158;
                --red: #FF453A;
                --border: #2C2C2E;
            }}
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 20px;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
            margin-bottom: 20px;
        }}
        h1 {{
            margin: 0;
            font-size: 24px;
            font-weight: 700;
        }}
        .stats {{
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        .stat-card {{
            flex: 1;
            min-width: 140px;
            background: var(--card);
            border-radius: 16px;
            padding: 14px 18px;
            border: 1px solid var(--border);
        }}
        .stat-num {{
            font-size: 22px;
            font-weight: 700;
        }}
        .stat-label {{
            font-size: 12px;
            color: var(--muted);
            margin-top: 2px;
        }}
        .controls {{
            display: flex;
            gap: 12px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }}
        .search-box {{
            flex: 1;
            min-width: 240px;
            padding: 10px 14px;
            border-radius: 12px;
            border: 1px solid var(--border);
            background: var(--card);
            color: var(--text);
            font-size: 14px;
            outline: none;
        }}
        .btn {{
            padding: 10px 16px;
            border-radius: 12px;
            border: none;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.15s;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .btn:hover {{ opacity: 0.85; }}
        .btn-primary {{ background: var(--blue); color: #fff; }}
        .btn-ban {{ background: rgba(255, 59, 48, 0.15); color: var(--red); border: 1px solid rgba(255, 59, 48, 0.3); }}
        .btn-unban {{ background: rgba(52, 199, 89, 0.15); color: var(--green); border: 1px solid rgba(52, 199, 89, 0.3); }}
        .table-wrap {{
            background: var(--card);
            border-radius: 20px;
            border: 1px solid var(--border);
            overflow-x: auto;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 13px;
        }}
        th, td {{
            padding: 12px 14px;
            border-bottom: 1px solid var(--border);
        }}
        th {{
            color: var(--muted);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 11px;
            letter-spacing: 0.5px;
        }}
        tr:last-child td {{ border-bottom: none; }}
        tr.row-banned td {{
            background: rgba(255, 59, 48, 0.04);
        }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 8px;
            font-size: 11px;
            font-weight: 600;
        }}
        .badge-active {{ background: rgba(52, 199, 89, 0.15); color: var(--green); }}
        .badge-banned {{ background: rgba(255, 59, 48, 0.15); color: var(--red); }}
        .badge-admin {{ background: rgba(0, 122, 255, 0.15); color: var(--blue); }}
        .badge-user {{ background: rgba(142, 142, 147, 0.15); color: var(--muted); }}
        .badge-class {{ background: rgba(0, 122, 255, 0.1); color: var(--blue); }}
        .tg-link {{ color: var(--blue); text-decoration: none; font-weight: 600; }}
        .text-muted {{ color: var(--muted); }}
        .text-sm {{ font-size: 11px; }}
        code {{ font-family: monospace; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>👥 Пользователи бота и приложения</h1>
                <p class="text-muted" style="margin: 4px 0 0 0; font-size: 13px;">МАОУ Гимназия №16 • Панель администратора</p>
            </div>
            <div style="display: flex; gap: 8px;">
                <a href="/api/admin/users/export?admin_id={authenticated_admin_id}&ts={ts or 0}&sign={sign or ''}" class="btn btn-primary">
                    📥 Скачать CSV
                </a>
            </div>
        </div>

        <div class="stats">
            <div class="stat-card">
                <div class="stat-num">{total_count}</div>
                <div class="stat-label">Всего зарегистрировано</div>
            </div>
            <div class="stat-card">
                <div class="stat-num" style="color: var(--green);">{active_count}</div>
                <div class="stat-label">Активных учеников</div>
            </div>
            <div class="stat-card">
                <div class="stat-num" style="color: var(--red);">{banned_count}</div>
                <div class="stat-label">Заблокировано</div>
            </div>
        </div>

        <div class="controls">
            <input type="text" id="searchInput" class="search-box" placeholder="🔍 Поиск по имени, фамилии, классу или @username..." oninput="filterUsers()">
        </div>

        <div class="table-wrap">
            <table id="usersTable">
                <thead>
                    <tr>
                        <th>TG ID</th>
                        <th>Имя и Фамилия</th>
                        <th>Username</th>
                        <th>Класс</th>
                        <th>Профиль</th>
                        <th>Роль</th>
                        <th>Статус</th>
                        <th>Регистрация</th>
                        <th>Действие</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        const adminId = {authenticated_admin_id};
        const authTs = {ts or 0};
        const authSign = "{sign or ''}";

        function filterUsers() {{
            const query = document.getElementById("searchInput").value.toLowerCase();
            const rows = document.querySelectorAll("#usersTable tbody tr");
            rows.forEach(r => {{
                const text = r.innerText.toLowerCase();
                r.style.display = text.includes(query) ? "" : "none";
            }});
        }}

        async function toggleBan(userId, setBanned) {{
            const action = setBanned ? "заблокировать" : "разблокировать";
            if (!confirm(`Вы действительно хотите ${{action}} этого пользователя?`)) return;

            try {{
                const res = await fetch(`/api/admin/users/${{userId}}/ban`, {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{ admin_id: adminId, ts: authTs, sign: authSign, is_banned: setBanned }})
                }});
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || "Ошибка запроса");

                const statusEl = document.getElementById(`status-${{userId}}`);
                const actionEl = document.getElementById(`action-${{userId}}`);
                const row = document.querySelector(`tr[data-user-id="${{userId}}"]`);

                if (setBanned) {{
                    statusEl.innerHTML = '<span class="badge badge-banned">🚫 Заблокирован</span>';
                    actionEl.innerHTML = `<button onclick="toggleBan(${{userId}}, false)" class="btn btn-unban">✅ Разбанить</button>`;
                    row?.classList.add("row-banned");
                }} else {{
                    statusEl.innerHTML = '<span class="badge badge-active">🟢 Активен</span>';
                    actionEl.innerHTML = `<button onclick="toggleBan(${{userId}}, true)" class="btn btn-ban">🚫 Забанить</button>`;
                    row?.classList.remove("row-banned");
                }}
            }} catch (err) {{
                alert("Ошибка: " + err.message);
            }}
        }}
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)


# Register tools after the authentication and cache helpers have been defined.
from features import install_features
install_features(app, require_telegram_user, check_admin_permission_or_raise, cache_clear_prefix)
