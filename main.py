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
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import DEFAULT_CLASSES, CLASS_PROFILES_MAP, ALL_PROFILES, settings
from database import get_db, init_db
from models import BellSchedule, Comment, Lesson, NewsPost, Profile, Reaction, SchoolClass, User
from schemas import (
    BellItem, CommentCreateRequest, CommentResponse, DayScheduleResponse,
    LessonItem, LessonSlot, LiveStatusResponse, ModerationActionRequest,
    NewsCreateRequest, NewsResponse, ReactionCount, ReactionToggleRequest,
    StructureResponse, UserProfileUpdate, UserResponse, UserSyncRequest
)

# Tyumen Timezone: UTC+5 (Asia/Yekaterinburg)
try:
    TYUMEN_TZ = ZoneInfo("Asia/Yekaterinburg")
except Exception:
    TYUMEN_TZ = timezone(timedelta(hours=5))

# Active Reaction Palette (including negative reactions)
EMOJI_PALETTE = ["❤️", "🔥", "👍", "👎", "🤡", "😢"]

# -------------------------------------------------------------
# Lifespan Management
# -------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure directories exist
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    settings.STATIC_DIR.mkdir(parents=True, exist_ok=True)
    
    # Initialize DB schema and base seeds
    await init_db()
    yield

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

# Enable CORS for Telegram Web App webview
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        if user_raw:
            return json.loads(user_raw)
        return parsed_data
    except Exception:
        return None

# -------------------------------------------------------------
# Admin Notification Service (Background Tasks)
# -------------------------------------------------------------
async def notify_admins_about_post(
    post_id: int, 
    title: str, 
    author_name: str, 
    author_class: Optional[str], 
    is_anonymous: bool, 
    has_image: bool
):
    """
    Sends notification to Telegram administrators when a new news post is suggested.
    Always reveals author identity and class to admins for moderation safety,
    even if marked anonymous for the public feed.
    """
    if not settings.BOT_TOKEN or not settings.admin_ids or "ABCdefGHI" in settings.BOT_TOKEN:
        return

    bot_url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}"
    author_info = f"{author_name} ({author_class or 'класс не указан'})"
    if is_anonymous:
        author_info += " <b>[🎭 Анонимно в ленте]</b>"

    text = (
        f"📢 <b>Новое предложение в ленту новостей (#{post_id})</b>\n\n"
        f"📝 <b>Заголовок:</b> {title}\n"
        f"👤 <b>Автор:</b> {author_info}\n"
        f"🖼 <b>Медиа:</b> {'Да' if has_image else 'Нет'}\n\n"
        f"Выберите действие для модерации:"
    )

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Опубликовать", "callback_data": f"approve_news_{post_id}"},
                {"text": "❌ Отклонить", "callback_data": f"reject_news_{post_id}"}
            ]
        ]
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        for admin_id in settings.admin_ids:
            try:
                await client.post(
                    f"{bot_url}/sendMessage",
                    json={
                        "chat_id": admin_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "reply_markup": reply_markup
                    }
                )
            except Exception:
                pass

# -------------------------------------------------------------
# Base & Meta Endpoints
# -------------------------------------------------------------
@app.get("/")
async def root():
    index_file = settings.STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
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
    classes_res = await db.execute(select(SchoolClass.name).order_by(SchoolClass.name))
    classes = [r[0] for r in classes_res.all()]
    if not classes:
        classes = DEFAULT_CLASSES

    return StructureResponse(
        classes=classes,
        class_profiles=CLASS_PROFILES_MAP,
        all_profiles=ALL_PROFILES
    )

# -------------------------------------------------------------
# User Profile & Onboarding Endpoints
# -------------------------------------------------------------
@app.post("/api/user/sync", response_model=UserResponse)
async def sync_user(payload: UserSyncRequest, db: AsyncSession = Depends(get_db)):
    """
    Syncs or creates a student account upon opening the TMA.
    Returns whether the student has completed onboarding (selected class & profile).
    """
    user_res = await db.execute(select(User).where(User.id == payload.id))
    user = user_res.scalars().first()

    is_admin = payload.id in settings.admin_ids

    if not user:
        user = User(
            id=payload.id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            username=payload.username,
            photo_url=payload.photo_url,
            is_admin=is_admin
        )
        db.add(user)
    else:
        # Only set default names if user hasn't configured custom profile yet
        if not user.class_name:
            user.first_name = payload.first_name
            user.last_name = payload.last_name
        user.username = payload.username
        if payload.photo_url:
            user.photo_url = payload.photo_url
        if is_admin:
            user.is_admin = True

    await db.commit()
    await db.refresh(user)

    is_onboarded = bool(user.class_name and user.profile_name and user.first_name and user.last_name)
    return UserResponse(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        photo_url=user.photo_url,
        class_name=user.class_name,
        profile_name=user.profile_name,
        subgroup=user.subgroup,
        is_admin=user.is_admin,
        is_onboarded=is_onboarded
    )

@app.get("/api/user/{user_id}", response_model=UserResponse)
async def get_user_profile(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    is_onboarded = bool(user.class_name and user.profile_name and user.first_name and user.last_name)
    return UserResponse(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        photo_url=user.photo_url,
        class_name=user.class_name,
        profile_name=user.profile_name,
        subgroup=user.subgroup,
        is_admin=user.is_admin,
        is_onboarded=is_onboarded
    )

@app.put("/api/user/{user_id}/profile", response_model=UserResponse)
async def update_user_profile(user_id: int, payload: UserProfileUpdate, db: AsyncSession = Depends(get_db)):
    """
    Saves student onboarding selection.
    Both first_name and last_name are MANDATORY (one cannot be left empty).
    """
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

    user.class_name = payload.class_name.strip()
    user.profile_name = payload.profile_name.strip()
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
        is_admin=user.is_admin,
        is_onboarded=True
    )

# -------------------------------------------------------------
# Bell Schedule & Live Status Endpoints (Tyumen Time UTC+5)
# -------------------------------------------------------------
@app.get("/api/schedule/bells", response_model=List[BellItem])
async def get_bells(db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(BellSchedule).order_by(BellSchedule.lesson_number)
    )
    bells = res.scalars().all()
    return bells

@app.get("/api/schedule/live", response_model=LiveStatusResponse)
async def get_live_status(db: AsyncSession = Depends(get_db)):
    """
    Real-time progress calculation synchronized with Tyumen timezone (Asia/Yekaterinburg, UTC+5).
    """
    now = datetime.now(TYUMEN_TZ)
    day_of_week = now.weekday() # 0=Mon..6=Sun
    now_minutes = now.hour * 60 + now.minute
    time_str = now.strftime("%H:%M")

    # Sunday check
    if day_of_week == 6:
        return LiveStatusResponse(
            current_time=time_str,
            state="weekend",
            message="Сегодня воскресенье — уроков нет"
        )

    res = await db.execute(
        select(BellSchedule).order_by(BellSchedule.lesson_number)
    )
    bells = res.scalars().all()
    if not bells:
        return LiveStatusResponse(
            current_time=time_str,
            state="before_school",
            message="Расписание звонков не настроено"
        )

    def parse_minutes(t_str: str) -> int:
        h, m = map(int, t_str.split(":"))
        return h * 60 + m

    # Check if before first lesson
    first_start = parse_minutes(bells[0].start_time)
    if now_minutes < first_start:
        diff = first_start - now_minutes
        return LiveStatusResponse(
            current_time=time_str,
            state="before_school",
            minutes_left=diff,
            message=f"До начала 1 урока: {diff} мин",
            next_lesson_number=1,
            next_lesson_time=bells[0].start_time
        )

    # Check if after last lesson
    last_end = parse_minutes(bells[-1].end_time)
    if now_minutes >= last_end:
        return LiveStatusResponse(
            current_time=time_str,
            state="after_school",
            message="Учебный день завершен 🎉"
        )

    # Check within lessons and breaks
    for i, bell in enumerate(bells):
        b_start = parse_minutes(bell.start_time)
        b_end = parse_minutes(bell.end_time)

        # Inside this lesson
        if b_start <= now_minutes < b_end:
            diff = b_end - now_minutes
            return LiveStatusResponse(
                current_time=time_str,
                state="lesson",
                current_lesson_number=bell.lesson_number,
                minutes_left=diff,
                message=f"Урок {bell.lesson_number}: до конца {diff} мин"
            )

        # Inside break between this lesson and next
        if i < len(bells) - 1:
            next_bell = bells[i + 1]
            next_start = parse_minutes(next_bell.start_time)
            if b_end <= now_minutes < next_start:
                diff = next_start - now_minutes
                return LiveStatusResponse(
                    current_time=time_str,
                    state="break",
                    current_lesson_number=bell.lesson_number,
                    minutes_left=diff,
                    message=f"Перемена: до {next_bell.lesson_number} урока {diff} мин",
                    next_lesson_number=next_bell.lesson_number,
                    next_lesson_time=next_bell.start_time
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
    bells_res = await db.execute(select(BellSchedule).order_by(BellSchedule.lesson_number))
    bells = {b.lesson_number: b for b in bells_res.scalars().all()}

    query = select(Lesson).where(
        Lesson.class_name == class_name,
        Lesson.day_of_week == day_of_week
    ).order_by(Lesson.lesson_number, Lesson.profile_name)

    res = await db.execute(query)
    raw_lessons = res.scalars().all()

    # Apply profile filter if requested
    filtered_lessons: List[Lesson] = []
    for l in raw_lessons:
        if only_my_profile and profile_name:
            profile_matches = (l.profile_name is None) or (l.profile_name.strip().lower() == profile_name.strip().lower())
            if profile_matches:
                filtered_lessons.append(l)
        else:
            filtered_lessons.append(l)

    # Group into LessonSlots by lesson_number
    slots_map: Dict[int, List[LessonItem]] = {}
    for l in filtered_lessons:
        b = bells.get(l.lesson_number)
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
        b = bells.get(num)
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

    return DayScheduleResponse(
        day_of_week=day_of_week,
        day_name=DAY_NAMES[day_of_week],
        class_name=class_name,
        slots=slots
    )

# -------------------------------------------------------------
# News Feed & Social Endpoints
# -------------------------------------------------------------
@app.get("/api/news", response_model=List[NewsResponse])
async def get_news(
    user_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns approved news feed posts with reaction tallies and comments count.
    If post is anonymous, author_name is masked as 'Анонимно' and author_class is omitted.
    Otherwise, shows author_name and author_class.
    Timestamps formatted in Tyumen timezone (UTC+5).
    """
    query = (
        select(NewsPost)
        .where(NewsPost.status == "approved")
        .options(selectinload(NewsPost.reactions), selectinload(NewsPost.comments))
        .order_by(NewsPost.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    res = await db.execute(query)
    posts = res.scalars().all()

    response: List[NewsResponse] = []

    for p in posts:
        # Calculate reactions across the 6 emojis palette
        reaction_counts_dict: Dict[str, int] = {e: 0 for e in EMOJI_PALETTE}
        user_reacted_dict: Dict[str, bool] = {e: False for e in EMOJI_PALETTE}

        for r in p.reactions:
            reaction_counts_dict[r.emoji] = reaction_counts_dict.get(r.emoji, 0) + 1
            if user_id and r.user_id == user_id:
                user_reacted_dict[r.emoji] = True

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

        response.append(NewsResponse(
            id=p.id,
            title=p.title,
            content=p.content,
            image_url=p.image_url,
            author_name=display_author,
            author_class=display_class,
            is_anonymous=p.is_anonymous,
            status=p.status,
            created_at=formatted_date,
            reactions=reactions_list,
            comments_count=len(p.comments)
        ))

    return response

@app.post("/api/news", response_model=NewsResponse, status_code=status.HTTP_201_CREATED)
async def suggest_news(
    payload: NewsCreateRequest, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Students propose a news post.
    Supports anonymous submissions and captures author_class.
    """
    author_class = payload.author_class
    if not author_class:
        user = await db.get(User, payload.author_id)
        if user:
            author_class = user.class_name

    new_post = NewsPost(
        title=payload.title,
        content=payload.content,
        image_url=payload.image_url,
        author_id=payload.author_id,
        author_name=payload.author_name,
        author_class=author_class,
        is_anonymous=payload.is_anonymous,
        status="pending"
    )
    db.add(new_post)
    await db.commit()
    await db.refresh(new_post)

    # Trigger admin notification in background (revealing author to admins for moderation)
    background_tasks.add_task(
        notify_admins_about_post,
        post_id=new_post.id,
        title=new_post.title,
        author_name=new_post.author_name,
        author_class=new_post.author_class,
        is_anonymous=new_post.is_anonymous,
        has_image=bool(new_post.image_url)
    )

    reactions_list = [ReactionCount(emoji=e, count=0, user_reacted=False) for e in EMOJI_PALETTE]

    return NewsResponse(
        id=new_post.id,
        title=new_post.title,
        content=new_post.content,
        image_url=new_post.image_url,
        author_name="Анонимно" if new_post.is_anonymous else new_post.author_name,
        author_class=None if new_post.is_anonymous else new_post.author_class,
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
    db: AsyncSession = Depends(get_db)
):
    """
    Toggles reaction on a news post.
    - If user taps the SAME emoji they already reacted with -> removes it (un-react).
    - If user taps a DIFFERENT emoji -> replaces previous reaction with the new one.
    """
    post = await db.get(NewsPost, post_id)
    if not post or post.status != "approved":
        raise HTTPException(status_code=404, detail="News post not found or not approved")

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
        await db.execute(
            delete(Reaction).where(
                Reaction.post_id == post_id,
                Reaction.user_id == payload.user_id
            )
        )
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
async def get_comments(post_id: int, db: AsyncSession = Depends(get_db)):
    """
    Retrieves all comments for a news post (Bottom Sheet).
    Timestamps formatted in Tyumen timezone.
    """
    res = await db.execute(
        select(Comment)
        .where(Comment.post_id == post_id)
        .order_by(Comment.created_at.asc())
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

    return result

@app.post("/api/news/{post_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def add_comment(
    post_id: int, 
    payload: CommentCreateRequest, 
    db: AsyncSession = Depends(get_db)
):
    """
    Adds a new comment to a news post.
    """
    post = await db.get(NewsPost, post_id)
    if not post or post.status != "approved":
        raise HTTPException(status_code=404, detail="News post not found")

    new_comment = Comment(
        post_id=post_id,
        user_id=payload.user_id,
        author_name=payload.author_name,
        author_class=payload.author_class,
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
# Admin Moderation Endpoints
# -------------------------------------------------------------
@app.get("/api/admin/news/pending", response_model=List[NewsResponse])
async def get_pending_news(
    admin_id: int = Query(...), 
    db: AsyncSession = Depends(get_db)
):
    if admin_id not in settings.admin_ids:
        admin_user = await db.get(User, admin_id)
        if not admin_user or not admin_user.is_admin:
            raise HTTPException(status_code=403, detail="Admin permissions required")

    res = await db.execute(
        select(NewsPost)
        .where(NewsPost.status == "pending")
        .order_by(NewsPost.created_at.desc())
    )
    posts = res.scalars().all()

    return [
        NewsResponse(
            id=p.id,
            title=p.title,
            content=p.content,
            image_url=p.image_url,
            author_name=p.author_name,
            author_class=p.author_class,
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
    db: AsyncSession = Depends(get_db)
):
    """
    Approves or rejects a suggested news item.
    """
    if payload.admin_id not in settings.admin_ids:
        admin_user = await db.get(User, payload.admin_id)
        if not admin_user or not admin_user.is_admin:
            raise HTTPException(status_code=403, detail="Admin permissions required")

    post = await db.get(NewsPost, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="News post not found")

    if payload.action == "approve":
        post.status = "approved"
        post.published_at = datetime.now(timezone.utc)
    else:
        post.status = "rejected"

    await db.commit()
    return {"status": "success", "post_id": post_id, "action": payload.action}

# -------------------------------------------------------------
# Media Storage & Proxy Endpoints
# -------------------------------------------------------------
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    """
    Saves an uploaded image locally to /uploads without paid cloud services.
    Returns the relative URL to access the image.
    """
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400, 
            detail="Unsupported image format. Allowed: JPEG, PNG, WebP, GIF."
        )

    # Generate unique filename
    ext = file.filename.split(".")[-1].lower() if file.filename and "." in file.filename else "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    file_path = settings.UPLOAD_DIR / filename

    content = await file.read()
    # Enforce maximum size 10MB
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image size exceeds 10MB limit")

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
