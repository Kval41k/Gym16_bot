"""Student tools, timetable publishing, audit history, reminders and backups."""
import asyncio
import csv
import hashlib
import io
import json
import logging
import os
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from audit import audit_actor
from config import CLASS_PROFILES_MAP, settings
from database import Base, async_session, engine, get_db
from models import (AuditLog, BellSchedule, EgeMaterial, Lesson, MaterialProgress,
                    NewsPost, NewsReview, Notification, User, UserPreferences)

TZ = ZoneInfo("Asia/Yekaterinburg")
logger = logging.getLogger(__name__)
LESSON_FIELDS = ("day_of_week", "lesson_number", "subject", "teacher_name", "cabinet", "profile_name", "subgroup", "note", "start_time", "end_time")


class PreferencesRequest(BaseModel):
    lesson_reminders: bool = False
    reminder_minutes: Literal[5, 10, 15] = 10
    schedule_changes: bool = False


class ProgressRequest(BaseModel):
    bookmarked: Optional[bool] = None
    studied: Optional[bool] = None


class LessonRow(BaseModel):
    day_of_week: int = Field(ge=0, le=5)
    lesson_number: int = Field(ge=0, le=12)
    subject: str = Field(min_length=1, max_length=150)
    teacher_name: str = Field(default="", max_length=150)
    cabinet: str = Field(default="", max_length=50)
    profile_name: Optional[str] = Field(None, max_length=100)
    subgroup: Optional[int] = Field(None, ge=1, le=2)
    note: Optional[str] = Field(None, max_length=255)
    start_time: Optional[str] = Field(None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    end_time: Optional[str] = Field(None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")

    @model_validator(mode="after")
    def valid_times(self):
        if bool(self.start_time) != bool(self.end_time):
            raise ValueError("Укажите и начало, и конец занятия")
        if self.start_time and self.end_time <= self.start_time:
            raise ValueError("Конец занятия должен быть позже начала")
        return self

    @field_validator("subject", "teacher_name", "cabinet", "profile_name", "note", mode="before")
    @classmethod
    def clean_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ScheduleRequest(BaseModel):
    class_name: str
    rows: list[LessonRow] = Field(default_factory=list, max_length=600)
    csv_text: Optional[str] = Field(None, max_length=300000)
    base_revision: Optional[str] = None


def lesson_dict(lesson):
    return {key: getattr(lesson, key) for key in LESSON_FIELDS}


def revision(lessons):
    rows = sorted((lesson_dict(item) for item in lessons), key=lambda item: json.dumps(item, sort_keys=True))
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def parse_schedule(payload):
    if payload.class_name not in CLASS_PROFILES_MAP:
        raise HTTPException(422, "Выберите существующий класс.")
    rows = payload.rows
    if payload.csv_text is not None:
        aliases = {"день": "day_of_week", "урок": "lesson_number", "предмет": "subject", "учитель": "teacher_name",
                   "кабинет": "cabinet", "профиль": "profile_name", "группа": "subgroup", "примечание": "note",
                   "начало": "start_time", "конец": "end_time"}
        text = payload.csv_text.lstrip("\ufeff").strip()
        delimiter = ";" if ";" in text.partition("\n")[0] else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        days = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5}
        rows = []
        index = 1
        try:
            headers = {aliases.get(key.strip().lower(), key.strip().lower()) for key in (reader.fieldnames or [])}
            if not {"day_of_week", "lesson_number", "subject"}.issubset(headers):
                raise ValueError("Нужны столбцы день, урок и предмет")
            for index, raw in enumerate(reader, 2):
                if len(rows) >= 600:
                    raise ValueError("Не больше 600 строк на класс")
                if None in raw:
                    raise ValueError("Лишние разделители: заключите текст с ; или , в двойные кавычки")
                item = {aliases.get(key.strip().lower(), key.strip().lower()): value.strip()
                        for key, value in raw.items() if key and value is not None}
                if not any(item.values()):
                    continue
                item["day_of_week"] = days.get(item.get("day_of_week", "").lower(), item.get("day_of_week"))
                for key in ("profile_name", "subgroup", "note", "start_time", "end_time"):
                    item[key] = item.get(key) or None
                rows.append(LessonRow.model_validate(item))
        except (ValueError, TypeError, csv.Error) as exc:
            raise HTTPException(422, f"Строка {index}: проверьте день (0–5 или Пн–Сб), номер урока и заполнение полей. {str(exc)[:180]}")
        if not rows:
            raise HTTPException(422, "Таблица пуста. Нужны заголовки и хотя бы один урок.")
    seen = set()
    for row in rows:
        if row.profile_name and row.profile_name not in CLASS_PROFILES_MAP[payload.class_name]:
            raise HTTPException(422, f"Профиль {row.profile_name} не относится к {payload.class_name}.")
        key = (row.day_of_week, row.lesson_number, row.profile_name, row.subgroup)
        if key in seen:
            raise HTTPException(422, f"Повтор урока: день {row.day_of_week}, урок {row.lesson_number}, профиль {row.profile_name or 'все'}.")
        seen.add(key)
    return rows


def install_features(app, require_user, require_admin, cache_clear):
    router = APIRouter()

    async def student(x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"), db=Depends(get_db)):
        identity = require_user(x_telegram_init_data)
        user = await db.get(User, int(identity["id"]))
        if not user:
            raise HTTPException(409, "Сначала заполните профиль.")
        if user.is_banned:
            raise HTTPException(403, "Ваш аккаунт заблокирован.")
        return user

    async def admin(x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"), db=Depends(get_db)):
        return await require_admin(x_telegram_init_data=x_telegram_init_data, db=db)

    @router.get("/api/me/preferences")
    async def preferences(user=Depends(student), db=Depends(get_db)):
        pref = await db.get(UserPreferences, user.id)
        return {key: getattr(pref, key) if pref else default for key, default in
                (("lesson_reminders", False), ("reminder_minutes", 10), ("schedule_changes", False))}

    @router.put("/api/me/preferences")
    async def save_preferences(payload: PreferencesRequest, user=Depends(student), db=Depends(get_db)):
        pref = await db.get(UserPreferences, user.id)
        if not pref:
            pref = UserPreferences(user_id=user.id)
            db.add(pref)
        for key, value in payload.model_dump().items():
            setattr(pref, key, value)
        await db.commit()
        return payload.model_dump()

    @router.get("/api/me/materials")
    async def material_progress(user=Depends(student), db=Depends(get_db)):
        rows = (await db.scalars(select(MaterialProgress).where(MaterialProgress.user_id == user.id))).all()
        return {str(row.material_id): {"bookmarked": row.bookmarked, "studied": row.studied} for row in rows}

    @router.put("/api/me/materials/{material_id}")
    async def save_progress(material_id: int, payload: ProgressRequest, user=Depends(student), db=Depends(get_db)):
        if not await db.get(EgeMaterial, material_id):
            raise HTTPException(404, "Материал не найден.")
        progress = await db.get(MaterialProgress, (user.id, material_id))
        if not progress:
            progress = MaterialProgress(user_id=user.id, material_id=material_id, bookmarked=False, studied=False)
            db.add(progress)
        for key, value in payload.model_dump(exclude_none=True).items():
            setattr(progress, key, value)
        await db.commit()
        return {"bookmarked": progress.bookmarked, "studied": progress.studied}

    @router.get("/api/me/news")
    async def my_news(user=Depends(student), db=Depends(get_db)):
        rows = (await db.execute(select(NewsPost, NewsReview.reason).outerjoin(NewsReview, NewsReview.post_id == NewsPost.id)
                .where(NewsPost.author_id == user.id).order_by(NewsPost.id.desc()).limit(100))).all()
        return [{"id": post.id, "title": post.title, "status": post.status, "reason": reason,
                 "created_at": post.created_at.isoformat() if post.created_at else None} for post, reason in rows]

    @router.get("/api/admin/logs")
    async def logs(section: Optional[str] = None, action: Optional[str] = None, q: str = Query("", max_length=100),
                   before_id: Optional[int] = None, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
                   limit: int = Query(40, ge=1, le=100), actor=Depends(admin), db=Depends(get_db)):
        query = select(AuditLog)
        if section:
            query = query.where(AuditLog.section == section)
        if action:
            query = query.where(AuditLog.action == action)
        if before_id:
            query = query.where(AuditLog.id < before_id)
        if date_from:
            query = query.where(AuditLog.created_at >= date_from.replace(tzinfo=date_from.tzinfo or TZ).astimezone(timezone.utc))
        if date_to:
            query = query.where(AuditLog.created_at <= date_to.replace(tzinfo=date_to.tzinfo or TZ).astimezone(timezone.utc))
        if q.strip():
            pattern = "%" + q.strip().replace("%", "\\%").replace("_", "\\_") + "%"
            query = query.where(or_(AuditLog.actor_name.ilike(pattern, escape="\\"), AuditLog.actor_username.ilike(pattern, escape="\\"),
                                   AuditLog.entity_id == q.strip(), AuditLog.actor_id == int(q) if q.isdigit() and len(q) < 19 else False))
        rows = (await db.scalars(query.order_by(AuditLog.id.desc()).limit(limit + 1))).all()
        return {"items": [{"id": row.id, "actor_id": row.actor_id, "actor_name": row.actor_name,
                 "actor_username": row.actor_username, "source": row.source, "section": row.section,
                 "action": row.action, "entity": row.entity, "entity_id": row.entity_id,
                 "details": json.loads(row.details), "created_at": row.created_at.isoformat()}
                 for row in rows[:limit]], "next_cursor": rows[limit - 1].id if len(rows) > limit else None}

    @router.get("/api/admin/schedule")
    async def admin_schedule(class_name: str, actor=Depends(admin), db=Depends(get_db)):
        if class_name not in CLASS_PROFILES_MAP:
            raise HTTPException(422, "Неизвестный класс.")
        lessons = (await db.scalars(select(Lesson).where(Lesson.class_name == class_name).order_by(Lesson.day_of_week, Lesson.lesson_number, Lesson.id))).all()
        loaded = set((await db.scalars(select(Lesson.class_name).distinct())).all())
        return {"rows": [lesson_dict(row) for row in lessons], "base_revision": revision(lessons),
                "classes": [{"name": name, "loaded": name in loaded} for name in CLASS_PROFILES_MAP]}

    @router.post("/api/admin/schedule/preview")
    async def preview_schedule(payload: ScheduleRequest, actor=Depends(admin), db=Depends(get_db)):
        rows = parse_schedule(payload)
        existing = (await db.scalars(select(Lesson).where(Lesson.class_name == payload.class_name))).all()
        return {"rows": [row.model_dump() for row in rows], "base_revision": revision(existing),
                "old_count": len(existing), "new_count": len(rows),
                "empty_days": [day for day in range(6) if not any(row.day_of_week == day for row in rows)]}

    @router.post("/api/admin/schedule/publish")
    async def publish_schedule(payload: ScheduleRequest, actor=Depends(admin), db=Depends(get_db)):
        rows = parse_schedule(payload)
        # A write transaction serializes concurrent publishers on PostgreSQL.
        if engine.dialect.name == "postgresql":
            from sqlalchemy import text
            await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int(hashlib.sha256(payload.class_name.encode()).hexdigest()[:8], 16)})
        elif engine.dialect.name == "sqlite":
            from sqlalchemy import text
            await db.execute(text("BEGIN IMMEDIATE"))
        existing = (await db.scalars(select(Lesson).where(Lesson.class_name == payload.class_name).with_for_update())).all()
        if not payload.base_revision or revision(existing) != payload.base_revision:
            raise HTTPException(409, "Расписание изменилось. Загрузите его заново и повторите предпросмотр.")
        key = lambda row: (row.day_of_week, row.lesson_number, row.profile_name, row.subgroup)
        by_key = {key(row): row for row in existing}
        changed = False
        changes = []
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
        for row in rows:
            old = by_key.pop(key(row), None)
            values = row.model_dump()
            if old:
                previous = lesson_dict(old)
                for field, value in values.items():
                    if getattr(old, field) != value:
                        setattr(old, field, value)
                        changed = True
                if previous != values:
                    changes.append(f"{day_names[row.day_of_week]}, {row.lesson_number} урок: {row.subject}, каб. {row.cabinet or '—'}" + (f". {row.note}" if row.note else ""))
            else:
                db.add(Lesson(class_name=payload.class_name, **values))
                changed = True
                changes.append(f"Добавлен: {day_names[row.day_of_week]}, {row.lesson_number} урок — {row.subject}, каб. {row.cabinet or '—'}")
        for row in by_key.values():
            changes.append(f"Отменён: {day_names[row.day_of_week]}, {row.lesson_number} урок — {row.subject}")
            await db.delete(row)
            changed = True
        if changed:
            users = (await db.scalars(select(User).join(UserPreferences).where(
                User.class_name == payload.class_name, User.is_banned.is_(False), UserPreferences.schedule_changes.is_(True)))).all()
            batch = uuid.uuid4().hex
            for user in users:
                db.add(Notification(user_id=user.id, dedup_key=f"schedule:{batch}:{user.id}",
                        text=f"📅 Расписание {payload.class_name} обновлено.\n" + "\n".join(changes[:5]) + "\nПолное расписание — в приложении."))
        await db.commit()
        cache_clear("sched:")
        return {"ok": True, "changed": changed, "count": len(rows)}

    @router.get("/api/admin/storage")
    async def storage(actor=Depends(admin)):
        disk = os.getenv("RENDER_DISK_PATH")
        persistent_db = engine.dialect.name != "sqlite" or bool(disk and str(engine.url.database).startswith(disk + "/"))
        backup_dir = settings.BACKUP_DIR
        files = sorted(backup_dir.glob("gym16-*.zip"), reverse=True) if backup_dir.exists() else []
        return {"persistent_database": persistent_db, "persistent_uploads": bool(disk and str(settings.UPLOAD_DIR).startswith(disk + "/")),
                "render": bool(os.getenv("RENDER")), "backup_count": len(files),
                "last_backup": files[0].name if files else None, "automatic_backups": "ежедневно, последние 7 архивов",
                "reminders_require_awake_service": True}

    @router.get("/api/admin/backup")
    async def download_backup(actor=Depends(admin)):
        content = await build_backup()
        return Response(content, media_type="application/zip", headers={"Content-Disposition":
            f'attachment; filename="gym16-{datetime.now(TZ).strftime("%Y%m%d-%H%M%S")}.zip"', "Cache-Control": "no-store"})

    app.include_router(router)


async def build_backup():
    """Portable table export and local media; credentials and environment are excluded."""
    data = {"format": "gym16-backup-v1", "created_at": datetime.now(timezone.utc).isoformat(), "tables": {}}
    async with engine.connect() as conn:
        # One consistent DB snapshot across all tables, including concurrent mutations.
        if engine.dialect.name == "postgresql":
            conn = await conn.execution_options(isolation_level="REPEATABLE READ")
        async with conn.begin():
            if engine.dialect.name == "sqlite":
                from sqlalchemy import text
                await conn.execute(text("BEGIN"))
            for table in Base.metadata.sorted_tables:
                rows = (await conn.execute(select(table))).mappings().all()
                data["tables"][table.name] = [dict(row) for row in rows]
    def pack():
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("data.json", json.dumps(data, ensure_ascii=False, default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item)))
            archive.writestr("README.txt", "Gym16 portable backup. data.json contains database tables in dependency order. uploads/ contains local media. Restore with: python backup_restore.py ARCHIVE --apply (maintenance mode, empty database). Keep this file private: it contains user data and audit history.")
            for path in settings.UPLOAD_DIR.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    archive.write(path, "uploads/" + str(path.relative_to(settings.UPLOAD_DIR)))
        return output.getvalue()
    return await asyncio.to_thread(pack)


async def create_daily_backup():
    directory = settings.BACKUP_DIR
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"gym16-{datetime.now(TZ).strftime('%Y%m%d')}.zip"
    if target.exists():
        return
    content = await build_backup()
    temporary = target.with_suffix(".tmp")
    await asyncio.to_thread(temporary.write_bytes, content)
    temporary.replace(target)
    for old in sorted(directory.glob("gym16-*.zip"), reverse=True)[7:]:
        old.unlink()


async def enqueue_reminders(now=None):
    now = now or datetime.now(TZ)
    if now.weekday() > 5:
        return
    async with async_session() as db:
        users = (await db.execute(select(User, UserPreferences).join(UserPreferences).where(
            UserPreferences.lesson_reminders.is_(True), User.is_banned.is_(False)))).all()
        lessons = (await db.scalars(select(Lesson).where(Lesson.day_of_week == now.weekday()))).all()
        from timetable import day_bells, lesson_times
        times = await day_bells(db, now.weekday())
        for user, pref in users:
            grouped = {}
            for lesson in lessons:
                if lesson.class_name != user.class_name or (lesson.profile_name and lesson.profile_name != user.profile_name):
                    continue
                if lesson.subgroup and user.subgroup and lesson.subgroup != user.subgroup:
                    continue
                start, end = lesson_times(lesson, times)
                grouped.setdefault((lesson.lesson_number, start, end), []).append(lesson)
            for (number, start, end), items in grouped.items():
                if not start:
                    continue
                hour, minute = map(int, start.split(":"))
                lesson_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                due = lesson_time - timedelta(minutes=pref.reminder_minutes)
                # Never send stale reminders after a free service wakes up.
                if not due <= now < due + timedelta(seconds=65):
                    continue
                key = f"lesson:{now.date()}:{user.id}:{number}:{start}"
                if await db.scalar(select(Notification.id).where(Notification.dedup_key == key)):
                    continue
                text = f"🔔 В {start}, через {pref.reminder_minutes} мин.: " + "; ".join(f"{item.subject}, каб. {item.cabinet}" for item in items)
                db.add(Notification(user_id=user.id, dedup_key=key, text=text))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()


async def deliver_notifications():
    if not settings.BOT_TOKEN:
        return
    async with async_session() as db:
        pending = (await db.scalars(select(Notification).where(Notification.status == "pending").order_by(Notification.id).limit(50))).all()
        async with httpx.AsyncClient(timeout=15) as client:
            for item in pending:
                # Atomic reservation survives restarts and prevents two workers from sending twice.
                claimed = await db.execute(update(Notification).where(Notification.id == item.id, Notification.status == "pending").values(status="sending"))
                await db.commit()
                if not claimed.rowcount:
                    continue
                user = await db.get(User, item.user_id)
                pref = await db.get(UserPreferences, item.user_id)
                enabled = pref and (pref.lesson_reminders if item.dedup_key.startswith("lesson:") else pref.schedule_changes)
                if not user or user.is_banned or not enabled:
                    item.status = "cancelled"
                    await db.commit()
                    continue
                try:
                    response = await client.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage", json={"chat_id": item.user_id, "text": item.text})
                    item.status = "sent" if response.is_success and response.json().get("ok") else "failed"
                    if item.status == "failed":
                        item.error = f"Telegram HTTP {response.status_code}"
                except Exception:
                    item.status = "uncertain"
                    item.error = "Неизвестен результат отправки; автоматический повтор отключён, чтобы избежать дубля."
                await db.commit()
                await asyncio.sleep(0.05)


async def maintenance_loop():
    while True:
        try:
            await create_daily_backup()
            await enqueue_reminders()
            await deliver_notifications()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never log HTTP client exceptions containing the bot-token URL.
            logger.error("Background reminders/backup cycle failed", exc_info=False)
        await asyncio.sleep(30)
