"""Apply reviewed timetable snapshots once; later admin edits remain authoritative."""
import asyncio
import json
import re
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


async def _apply_photo_snapshot(snapshot, align_clock=False):
    """Apply one reviewed source without resetting unrelated class snapshots."""
    revision=snapshot['revision']
    token=audit_actor.set({'id':0,'first_name':'Обновление расписания по фотографиям','source':'schedule'})
    try:
        async with async_session() as db:
            if engine.dialect.name=='sqlite':await db.execute(text('BEGIN IMMEDIATE'))
            else:await db.execute(text('SELECT pg_advisory_xact_lock(110011)'))
            if await db.get(AppliedDataUpdate,revision):return False
            classes={row['class_name'] for row in snapshot['rows']}
            affected=classes|({'11А'} if align_clock else set())
            current=(await db.scalars(select(Lesson).where(Lesson.class_name.in_(affected)))).all()
            settings.BACKUP_DIR.mkdir(parents=True,exist_ok=True)
            previous=[{column.key:getattr(row,column.key) for column in Lesson.__table__.columns} for row in current]
            await asyncio.to_thread((settings.BACKUP_DIR/f'schedule-before-{revision}.json').write_text,json.dumps(previous,ensure_ascii=False,indent=2),encoding='utf-8')
            # The old philology Monday counted the form period as lesson 1; match the reviewed 0–7 clock.
            philology=[row for row in current if row.class_name=='11А' and row.profile_name=='Филологический']
            legacy_monday=any(row.day_of_week==0 and row.lesson_number==1 and row.subject=='Разговоры о важном' for row in philology) and not any(row.day_of_week==0 and row.lesson_number==0 for row in philology)
            shared_times={(row['day_of_week'],row['lesson_number']):(row['start_time'],row['end_time']) for row in json.loads(SNAPSHOT.read_text())['rows']}
            from timetable import day_bells
            for row in current:
                if row.class_name in classes:await db.delete(row)
            for row in current:
                if row.class_name=='11А' and row.teacher_name.replace(' ','') in {'БурейкевичЮ.Ю.','БураковичЮ.Ю.','БураковаЮ.Ю.','БуракевичЮ.Ю.'}:
                    row.teacher_name='Буракевич Ю.Ю.'
            for row in philology:
                if legacy_monday and row.day_of_week==0:row.lesson_number-=1
                times=shared_times.get((row.day_of_week,row.lesson_number))
                if times is None:times=(await day_bells(db,row.day_of_week)).get(row.lesson_number)
                if times:row.start_time,row.end_time=times
            for row in snapshot['rows']:db.add(Lesson(**row))
            affected_users=select(User.id).where(User.class_name.in_(affected))
            stale=(await db.scalars(select(Notification).where(Notification.status=='pending',Notification.dedup_key.like('lesson:%'),Notification.user_id.in_(affected_users)))).all()
            for notice in stale:notice.status='cancelled'
            db.add(AppliedDataUpdate(revision=revision))
            await db.commit()
            return True
    finally:audit_actor.reset(token)


async def apply_photo_timetables():
    directory=Path(__file__).parent/'data'
    changed=False
    for filename,align_clock in [('photo_timetables_20261025.json',True),('11b_reviewed_20261025.json',False)]:
        snapshot=json.loads((directory/filename).read_text())
        changed=await _apply_photo_snapshot(snapshot,align_clock) or changed
    changed=await apply_11a_shared_clock() or changed
    return changed


async def apply_11a_shared_clock():
    """Remove legacy time-only captions while keeping useful lesson notes."""
    revision='11a-shared-clock-notes-20261025-v1'
    token=audit_actor.set({'id':0,'first_name':'Единое время уроков 11А','source':'schedule'})
    try:
        async with async_session() as db:
            if engine.dialect.name=='sqlite':await db.execute(text('BEGIN IMMEDIATE'))
            else:await db.execute(text('SELECT pg_advisory_xact_lock(110011)'))
            if await db.get(AppliedDataUpdate,revision):return False
            rows=(await db.scalars(select(Lesson).where(Lesson.class_name=='11А'))).all()
            shared={(row['day_of_week'],row['lesson_number']):(row['start_time'],row['end_time']) for row in json.loads(SNAPSHOT.read_text())['rows']}
            from timetable import day_bells
            for row in rows:
                times=shared.get((row.day_of_week,row.lesson_number))
                if times is None:times=(await day_bells(db,row.day_of_week)).get(row.lesson_number)
                if times:row.start_time,row.end_time=times
                if re.fullmatch(r'\s*\d{1,2}:\d{2}\s*[-–—]\s*\d{1,2}:\d{2}\s*',row.note or ''):
                    row.note=''
            db.add(AppliedDataUpdate(revision=revision))
            await db.commit()
            return True
    finally:audit_actor.reset(token)
