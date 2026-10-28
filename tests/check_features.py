import os, sys, asyncio, json, hashlib, hmac, time, urllib.parse, io, zipfile, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="gym16-check-")
CHECK_DIR = Path(TEMP.name)
os.environ.update(DATABASE_URL=os.getenv('GYM16_TEST_DATABASE_URL') or 'sqlite+aiosqlite:///' + str(CHECK_DIR/'check.db'), BOT_TOKEN='123456789:TEST_TOKEN_FOR_LOCAL_CHECKS_ONLY', ADMIN_IDS='2', ADMIN_USERNAME='', UPLOAD_DIR=str(CHECK_DIR/'uploads'), BACKUP_DIR=str(CHECK_DIR/'backups'))
import httpx
from config import settings
from database import init_db, async_session, engine
from models import User, AuditLog, Notification, Lesson
from sqlalchemy import select, func
import main
from audit import audit_actor
from features import enqueue_reminders, build_backup, create_daily_backup, deliver_notifications
import subprocess
from unittest.mock import patch
async def no_notification(**kwargs): pass
main.notify_admins_about_post = no_notification

def signed(uid):
    data={'auth_date':str(int(time.time())), 'user':json.dumps({'id':uid,'first_name':'Админ' if uid==2 else 'Ученик','username':'test'+str(uid)},separators=(',',':'))}
    check='\n'.join(f'{key}={value}' for key,value in sorted(data.items()))
    secret=hmac.new(b'WebAppData',settings.BOT_TOKEN.encode(),hashlib.sha256).digest()
    data['hash']=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    return {'X-Telegram-Init-Data':urllib.parse.urlencode(data)}

async def run():
    await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://local') as c:
        async def call(method,path,data=None,uid=2,expected=200):
            response=await c.request(method,path,json=data,headers=signed(uid))
            assert response.status_code==expected,(path,response.status_code,response.text[:800])
            return response.json()
        for uid in (1,2,3):
            await call('POST','/api/user/sync',{'id':uid,'first_name':'Тестовый','last_name':'Ученик','class_name':'11А','profile_name':'Соц-гум'},uid)
        for path in ('/api/admin/logs','/api/admin/schedule?class_name=11А','/api/admin/storage','/api/admin/backup'):
            assert (await c.get(path,headers=signed(1))).status_code==403,path
            assert (await c.get(path)).status_code in (401,403),path
        prefs=await call('PUT','/api/me/preferences',{'lesson_reminders':True,'reminder_minutes':10,'schedule_changes':True},1)
        assert prefs['lesson_reminders']
        assert (await call('GET','/api/me/preferences',uid=3))['lesson_reminders'] is False
        post=await call('POST','/api/news',{'title':'Тестовая новость','content':'Текст публикации для проверки','author_id':1},1,201)
        pid=post['id']
        await call('POST',f'/api/admin/news/{pid}/moderate',{'admin_id':2,'action':'reject','reason':'Нужны подробности'})
        mine=await call('GET','/api/me/news',uid=1)
        assert mine[0]['reason']=='Нужны подробности'
        assert not await call('GET','/api/me/news',uid=3)
        await call('POST',f'/api/admin/news/{pid}/moderate',{'admin_id':2,'action':'approve'})
        comment=await call('POST',f'/api/news/{pid}/comments',{'user_id':1,'text':'Текст комментария','author_name':'Ученик'},1,201)
        await call('POST',f'/api/news/{pid}/react',{'user_id':1,'emoji':'👍'},1)
        await call('POST',f'/api/news/{pid}/react',{'user_id':1,'emoji':'🔥'},1)
        await call('POST',f'/api/news/{pid}/react',{'user_id':1,'emoji':'🔥'},1)
        await call('DELETE',f'/api/news/comments/{comment["id"]}?user_id=3',uid=3,expected=403)
        await call('DELETE',f'/api/news/comments/{comment["id"]}?user_id=1',uid=1)
        mat=await call('POST','/api/ege/materials',{'admin_id':2,'subject_code':'russian','task_number':4,'title':'Ударения','theory':'Правила ударений'},expected=201)
        progress=await call('PUT',f'/api/me/materials/{mat["id"]}',{'bookmarked':True,'studied':True},1)
        assert progress=={'bookmarked':True,'studied':True}
        assert str(mat['id']) in await call('GET','/api/me/materials',uid=1)
        assert not await call('GET','/api/me/materials',uid=3)
        body={'class_name':'11А','csv_text':'день;урок;предмет;учитель;кабинет;профиль;группа;примечание\nПн;1;История;Иванов;12;Соц-гум;;Замена кабинета'}
        preview=await call('POST','/api/admin/schedule/preview',body)
        payload={'class_name':'11А','rows':preview['rows'],'base_revision':preview['base_revision']}
        await call('POST','/api/admin/schedule/publish',dict(payload,base_revision='wrong'),expected=409)
        result=await call('POST','/api/admin/schedule/publish',payload)
        assert result['changed']
        await call('POST','/api/admin/schedule/publish',payload,expected=409)
        fresh=await call('GET','/api/admin/schedule?class_name=11А')
        assert not (await call('POST','/api/admin/schedule/publish',{'class_name':'11А','rows':fresh['rows'],'base_revision':fresh['base_revision']}))['changed']
        assert (await call('GET','/api/schedule/lessons?class_name=11Б'))['schedule_loaded'] is False
        bad={'class_name':'11А','rows':[dict(preview['rows'][0],profile_name='Химбио')]}
        await call('POST','/api/admin/schedule/preview',bad,expected=422)
        await call('POST','/api/admin/schedule/preview',{'class_name':'11А','rows':preview['rows']*2},expected=422)
        logs=await call('GET','/api/admin/logs?limit=100')
        assert all(log['actor_id'] in (1,2,3) for log in logs['items'])
        assert any(log['entity']=='comments' and log['action']=='delete' and log['details']['text']=='Текст комментария' for log in logs['items'])
        assert any(log['entity']=='reactions' and log['action']=='delete' for log in logs['items'])
        assert any(log['entity']=='material_progress' and log['actor_id']==1 for log in logs['items'])
        assert any(log['entity']=='lessons' for log in logs['items'])
        filtered=await call('GET','/api/admin/logs?section=reactions&action=delete&limit=1')
        assert len(filtered['items'])==1 and filtered['next_cursor']
        older=await call('GET',f'/api/admin/logs?section=reactions&action=delete&before_id={filtered["next_cursor"]}')
        assert all(row['id']<filtered['next_cursor'] for row in older['items'])
        # Rollbacks must not leave fictitious actions in the log.
        async with async_session() as db:
            before=await db.scalar(select(func.count()).select_from(AuditLog))
            token=audit_actor.set({'id':1,'first_name':'Тест'})
            try:
                user=await db.get(User,1); user.first_name='Не сохранять';await db.flush();await db.rollback()
            finally:audit_actor.reset(token)
            assert before==await db.scalar(select(func.count()).select_from(AuditLog))
        archive=await build_backup()
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            data=json.loads(z.read('data.json'))
            assert data['tables']['audit_logs'] and data['tables']['users']
            assert '.env' not in z.namelist()
        backup_file = CHECK_DIR / 'roundtrip.zip'
        backup_file.write_bytes(archive)
        restore_env = dict(os.environ, DATABASE_URL='sqlite+aiosqlite:///' + str(CHECK_DIR/'restored.db'), UPLOAD_DIR=str(CHECK_DIR/'restored-uploads'))
        restore_result = await asyncio.to_thread(subprocess.run, [sys.executable, str(ROOT/'backup_restore.py'), str(backup_file), '--apply'], env=restore_env, capture_output=True, text=True)
        assert restore_result.returncode == 0, restore_result.stderr
        refused = await asyncio.to_thread(subprocess.run, [sys.executable, str(ROOT/'backup_restore.py'), str(backup_file), '--apply'], env=restore_env, capture_output=True, text=True)
        assert refused.returncode != 0 and 'not empty' in refused.stderr
        await create_daily_backup()
        await create_daily_backup()
        assert len(list(Path(os.environ['BACKUP_DIR']).glob('*.zip')))==1
        from datetime import datetime
        from zoneinfo import ZoneInfo
        # Exact time of first Monday lesson minus ten minutes, twice: one reminder.
        await enqueue_reminders(datetime(2026,10,26,8,25,tzinfo=ZoneInfo('Asia/Yekaterinburg')))
        await enqueue_reminders(datetime(2026,10,26,8,25,tzinfo=ZoneInfo('Asia/Yekaterinburg')))
        async with async_session() as db:
            notices=(await db.scalars(select(Notification))).all()
            assert len([n for n in notices if n.dedup_key.startswith('lesson:')])==1
            assert len([n for n in notices if n.dedup_key.startswith('schedule:')])==1
        sent = []
        class FakeTelegram:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def __init__(self, *args, **kwargs): pass
            async def post(self, url, json):
                sent.append(json['chat_id'])
                raise TimeoutError('simulated uncertain delivery')
        with patch('features.httpx.AsyncClient', FakeTelegram):
            await deliver_notifications()
            await deliver_notifications()
        assert len(sent) == 2, 'Uncertain sends must not be retried'
        token = audit_actor.set({'id':2,'first_name':'Админ','source':'bot'})
        try:
            async with async_session() as db:
                user = await db.get(User,3)
                user.is_banned = True
                await db.commit()
        finally: audit_actor.reset(token)
        bot_logs = await call('GET','/api/admin/logs?section=profile')
        assert any(row['source']=='bot' and row['details'].get('is_banned',{}).get('after') is True for row in bot_logs['items'])
        await call('DELETE',f'/api/ege/materials/{mat["id"]}?admin_id=2')
        await call('DELETE',f'/api/admin/news/{pid}?admin_id=2')
        print('PASS: auth, isolation, atomic audit, reactions/comments, statuses, preferences, EGE progress, CSV validation, schedule revisions, reminder/send deduplication, bot audit, backup export/restore and overwrite refusal')
    await engine.dispose()
try:
    asyncio.run(run())
finally:
    TEMP.cleanup()
