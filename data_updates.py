"""Apply reviewed timetable snapshots once; later admin edits remain authoritative."""
import asyncio
import json
from pathlib import Path
from sqlalchemy import select, text

from audit import audit_actor
from config import settings
from database import async_session, engine
from models import AppliedDataUpdate, Lesson, Notification, User, UserPreferences

SNAPSHOT = Path(__file__).parent / "data" / "11a_socgum_schedule.json"


async def apply_calendar_schedule():
    snapshot = json.loads(SNAPSHOT.read_text())
    revision = snapshot["revision"]
    token = audit_actor.set({"id": 0, "first_name": "Синхронизация Google Календаря", "source": "calendar"})
    try:
        async with async_session() as db:
            if engine.dialect.name == "sqlite":
                await db.execute(text("BEGIN IMMEDIATE"))
            elif engine.dialect.name == "postgresql":
                await db.execute(text("SELECT pg_advisory_xact_lock(110011)"))
            if await db.get(AppliedDataUpdate, revision):
                return False
            current = (await db.scalars(select(Lesson).where(Lesson.class_name == "11А"))).all()
            if current:
                previous = [{column.key: getattr(lesson, column.key) for column in Lesson.__table__.columns} for lesson in current]
                settings.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread((settings.BACKUP_DIR / f"schedule-before-{revision}.json").write_text,
                                        json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
            previous_revision = snapshot.get("previous_revision")
            if previous_revision and await db.get(AppliedDataUpdate, previous_revision):
                # A focused correction must preserve other manual edits made after v1.
                for lesson in current:
                    if lesson.profile_name == "Соц-гум" and lesson.subject in snapshot["removed_subjects"]:
                        await db.delete(lesson)
                target = next(row for row in snapshot["rows"] if row["subject"] == "Консультация по профильной математике")
                existing = [lesson for lesson in current if lesson.subject == target["subject"]]
                consultation = existing[0] if existing else Lesson(**target)
                if not existing:
                    db.add(consultation)
                for extra in existing[1:]:
                    await db.delete(extra)
                for key, value in target.items():
                    setattr(consultation, key, value)
            else:
                # Previously common rows remain available to the other profile.
                for lesson in current:
                    if lesson.profile_name == "Соц-гум":
                        await db.delete(lesson)
                    elif lesson.profile_name is None:
                        lesson.profile_name = "Филологический"
                for row in snapshot["rows"]:
                    db.add(Lesson(**row))
            users = (await db.scalars(select(User).join(UserPreferences).where(
                User.class_name == "11А", User.is_banned.is_(False),
                UserPreferences.schedule_changes.is_(True)))).all()
            for user in users:
                db.add(Notification(user_id=user.id, dedup_key=f"schedule:{revision}:{user.id}",
                    text=snapshot.get("notification", "📅 Расписание 11А обновлено. Проверьте расписание в приложении.")))
            db.add(AppliedDataUpdate(revision=revision))
            await db.commit()
            return True
    finally:
        audit_actor.reset(token)
