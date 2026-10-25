"""Check the reviewed Google Calendar snapshot against old-schema data and live timing."""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='gym16-calendar-')
DIRECTORY = Path(TEMP.name)
os.environ.update(DATABASE_URL='sqlite+aiosqlite:///' + str(DIRECTORY/'check.db'), UPLOAD_DIR=str(DIRECTORY/'uploads'),
                  BACKUP_DIR=str(DIRECTORY/'backups'), BOT_TOKEN='123456789:TEST_ONLY', ADMIN_IDS='2', ADMIN_USERNAME='')
# Reproduce an installed database from before per-lesson time columns existed.
with sqlite3.connect(DIRECTORY/'check.db') as conn:
    conn.execute('CREATE TABLE lessons (id INTEGER PRIMARY KEY, day_of_week INTEGER NOT NULL, lesson_number INTEGER NOT NULL, class_name VARCHAR(20) NOT NULL, subject VARCHAR(150) NOT NULL, teacher_name VARCHAR(150) NOT NULL, cabinet VARCHAR(50) NOT NULL, profile_name VARCHAR(100), subgroup INTEGER, note VARCHAR(255))')

import httpx
from sqlalchemy import select, delete
from database import init_db, async_session, engine
from models import Lesson, User, UserPreferences, Notification, AuditLog, AppliedDataUpdate
from seed_data import LESSONS_11A, LESSONS_11V, LESSONS_11G, LESSONS_11ZH
from data_updates import apply_calendar_schedule, SNAPSHOT
from features import enqueue_reminders, parse_schedule, ScheduleRequest
import main
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)

TZ = ZoneInfo('Asia/Yekaterinburg')

def signature(lesson):
    return (lesson.id, lesson.class_name, lesson.day_of_week, lesson.lesson_number, lesson.subject,
            lesson.teacher_name, lesson.cabinet, lesson.subgroup, lesson.note, lesson.start_time, lesson.end_time)

def public_signature(data):
    return [(slot['lesson_number'], lesson['subject'], lesson['teacher_name'], lesson['cabinet'], lesson['start_time'], lesson['end_time'])
            for slot in data['slots'] for lesson in slot['lessons']]

async def run():
    await init_db()
    async with async_session() as db:
        original = LESSONS_11A + LESSONS_11V + LESSONS_11G + LESSONS_11ZH + [{**row,'class_name':'11Д'} for row in LESSONS_11V]
        for row in original: db.add(Lesson(**row))
        db.add(User(id=1,first_name='Тест',last_name='Ученик',class_name='11А',profile_name='Соц-гум'))
        await db.commit()
        db.add(UserPreferences(user_id=1,lesson_reminders=True,reminder_minutes=10,schedule_changes=True))
        await db.commit()
        before_other = sorted(signature(row) for row in (await db.scalars(select(Lesson).where(Lesson.class_name!='11А'))).all())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as client:
        async def schedule(day, profile='Соц-гум', cls='11А'):
            r=await client.get('/api/schedule/lessons',params={'class_name':cls,'day_of_week':day,'only_my_profile':'true','profile_name':profile})
            assert r.status_code==200,r.text
            return r.json()
        philology_before=[public_signature(await schedule(day,'Филологический')) for day in range(6)]
        assert await apply_calendar_schedule() is True
        main.cache_clear_prefix('sched:')
        snapshot=json.loads(SNAPSHOT.read_text())['rows']
        assert len(snapshot)==36
        for day in range(6):
            actual=await schedule(day)
            expected=[row for row in snapshot if row['day_of_week']==day]
            flattened=[lesson for slot in actual['slots'] for lesson in slot['lessons']]
            assert len(flattened)==len(expected),(day,len(flattened),len(expected))
            for lesson,row in zip(flattened,expected):
                for key,value in row.items(): assert lesson[key]==value,(day,key,lesson[key],value)
        assert philology_before[:5]==[public_signature(await schedule(day,'Филологический')) for day in range(5)],'Other profile must retain its classes and times'
        async with async_session() as db:
            after_other=sorted(signature(row) for row in (await db.scalars(select(Lesson).where(Lesson.class_name!='11А'))).all())
            assert before_other==after_other,'Other classes must be unchanged'
            assert len((await db.scalars(select(Notification))).all())==1
            assert await db.scalar(select(AuditLog.id).where(AuditLog.source=='calendar'))
        saturday = await schedule(5, 'Филологический')
        consultation = saturday['slots'][0]['lessons'][0]
        assert consultation['profile_name'] is None and consultation['teacher_name'] == 'Ермакова М.В.' and consultation['cabinet'] == '3/306'
        assert not any(item['subject'] in ('IT Lab', 'Консультация по информатике') for item in snapshot)
        assert (await schedule(0,cls='11Б'))['schedule_loaded'] is False
        from types import SimpleNamespace
        from bot import show_bells
        messages=[]
        async def answer(message): messages.append(message)
        await show_bells(SimpleNamespace(from_user=SimpleNamespace(id=1),answer=answer))
        assert len(messages)==1 and len(messages[0]) < 4096
        assert '13:25 — 14:05' in messages[0] and '14:10 — 14:50' in messages[0] and '10:00 — 12:00' in messages[0]
        # The same clock drives card times, live status and reminders.
        async def live(at):
            class Clock(datetime):
                @classmethod
                def now(cls,tz=None): return at
            with patch('main.datetime',Clock):
                r=await client.get('/api/schedule/live',params={'class_name':'11А','profile_name':'Соц-гум'})
                assert r.status_code==200,r.text
                return r.json()
        cases=[(8,0,'lesson',0,None),(8,30,'break',None,'08:35'),(13,10,'break',None,'13:25'),
               (13,25,'lesson',6,None),(14,6,'break',None,'14:10'),(14,10,'lesson',7,None),
               (14,50,'after_school',None,None),(15,1,'after_school',None,None),(16,0,'after_school',None,None)]
        for hour,minute,state,number,next_time in cases:
            result=await live(datetime(2026,10,26,hour,minute,tzinfo=TZ))
            assert result['state']==state,(hour,minute,result)
            if number is not None: assert result['current_lesson_number']==number,result
            if next_time: assert result['next_lesson_time']==next_time,result
        assert (await live(datetime(2026,10,31,10,30,tzinfo=TZ)))['state']=='lesson'
        assert (await live(datetime(2026,10,31,12,0,tzinfo=TZ)))['state']=='after_school'
        # There must be no reminder at the old, incorrect Monday time.
        await enqueue_reminders(datetime(2026,10,26,13,0,tzinfo=TZ))
        async with async_session() as db:
            assert not (await db.scalars(select(Notification).where(Notification.dedup_key.like('lesson:%')))).all()
        await enqueue_reminders(datetime(2026,10,26,14,0,tzinfo=TZ))
        await enqueue_reminders(datetime(2026,10,26,14,0,tzinfo=TZ))
        async with async_session() as db:
            reminders=(await db.scalars(select(Notification).where(Notification.dedup_key.like('lesson:%')))).all()
            assert len(reminders)==1 and 'Информатика и ИКТ' in reminders[0].text and '14:10' in reminders[0].text
        valid='день;урок;предмет;начало;конец\nПн;7;Информатика;14:10;14:50'
        rows=parse_schedule(ScheduleRequest(class_name='11А',csv_text=valid))
        assert rows[0].start_time=='14:10'
        try:
            parse_schedule(ScheduleRequest(class_name='11А',csv_text=valid.replace('14:50','14:00')))
            assert False,'Reversed times must be rejected'
        except main.HTTPException as error: assert error.status_code==422
        # Applied marker prevents the snapshot from overwriting subsequent admin edits.
        async with async_session() as db:
            row=await db.scalar(select(Lesson).where(Lesson.class_name=='11А',Lesson.profile_name=='Соц-гум'))
            row.subject='Ручное изменение';await db.commit();changed_id=row.id
        assert await apply_calendar_schedule() is False
        async with async_session() as db:
            assert (await db.get(Lesson,changed_id)).subject=='Ручное изменение'
        assert list((DIRECTORY/'backups').glob('schedule-before-*.json'))
        # Installed v1 receives only the requested correction, preserving admin changes.
        metadata=json.loads(SNAPSHOT.read_text())
        async with async_session() as db:
            await db.delete(await db.get(AppliedDataUpdate,metadata['revision']))
            await db.execute(delete(Notification).where(Notification.dedup_key.like('schedule:'+metadata['revision']+':%')))
            db.add(AppliedDataUpdate(revision=metadata['previous_revision']))
            db.add(Lesson(day_of_week=0,lesson_number=8,class_name='11А',subject='IT Lab',teacher_name='',cabinet='',profile_name='Соц-гум'))
            db.add(Lesson(day_of_week=1,lesson_number=8,class_name='11А',subject='Консультация по информатике',teacher_name='',cabinet='',profile_name='Соц-гум'))
            sat=await db.scalar(select(Lesson).where(Lesson.class_name=='11А',Lesson.day_of_week==5))
            sat.profile_name='Соц-гум';sat.teacher_name='';sat.cabinet=''
            await db.commit()
        assert await apply_calendar_schedule() is True
        async with async_session() as db:
            assert (await db.get(Lesson,changed_id)).subject=='Ручное изменение'
            lessons=(await db.scalars(select(Lesson).where(Lesson.class_name=='11А'))).all()
            assert not any(row.profile_name=='Соц-гум' and row.subject in metadata['removed_subjects'] for row in lessons)
            sat=[row for row in lessons if row.subject=='Консультация по профильной математике']
            assert len(sat)==1 and sat[0].profile_name is None and sat[0].teacher_name=='Ермакова М.В.' and sat[0].cabinet=='3/306'
        assert await apply_calendar_schedule() is False

    await engine.dispose()
    print('PASS: legacy migration, 36 lessons, shared Saturday maths, exact times, live countdown, reminders, CSV times, other classes/profiles preserved, idempotence')

try:
    asyncio.run(run())
finally:
    TEMP.cleanup()
