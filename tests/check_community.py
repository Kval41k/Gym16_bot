"""School access, editorial rights, dated schedules, drafts and pinned/searchable news."""
import asyncio, subprocess, hashlib, hmac, json, logging, os, sys, tempfile, time, urllib.parse
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='gym16-community-');DIR=Path(TEMP.name)
os.environ.update(DATABASE_URL='sqlite+aiosqlite:///'+str(DIR/'test.db'),BOT_TOKEN='123456789:TEST_TOKEN_FOR_LOCAL_CHECKS_ONLY',ADMIN_IDS='2',ADMIN_USERNAME='',UPLOAD_DIR=str(DIR/'uploads'),BACKUP_DIR=str(DIR/'backups'))
import httpx
from sqlalchemy import select
from config import settings
from database import init_db,async_session,engine
from models import User,Lesson,SchoolInvite,Notification,UserPreferences,AuditLog
import main,community
from features import enqueue_reminders
async def noop(**kwargs):pass
main.notify_admins_about_post=noop
logging.getLogger('httpx').setLevel(logging.WARNING)
TZ=ZoneInfo('Asia/Yekaterinburg')
def signed(uid):
    data={'auth_date':str(int(time.time())),'user':json.dumps({'id':uid,'first_name':'Тест','username':'test'+str(uid)})}
    secret=hmac.new(b'WebAppData',settings.BOT_TOKEN.encode(),hashlib.sha256).digest();data['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
    return {'X-Telegram-Init-Data':urllib.parse.urlencode(data)}
async def run():
    await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as c:
        async def call(method,path,data=None,uid=2,status=200):
            r=await c.request(method,path,json=data,headers=signed(uid));assert r.status_code==status,(method,path,r.status_code,r.text[:700]);return r.json()
        async def sync(uid):return await call('POST','/api/user/sync',{'id':uid,'first_name':'Тест','class_name':'11А','profile_name':'Соц-гум'},uid)
        for uid in [1,2,3]:assert (await sync(uid))['access_allowed']
        # Editorial rights do not imply administrative authority or allow self-promotion.
        await call('PUT','/api/admin/users/1/role',{'role':'editor'},uid=1,status=403)
        await call('PUT','/api/admin/users/1/role',{'role':'admin'},status=422)
        await call('PUT','/api/admin/users/1/role',{'role':'editor'})
        assert (await sync(1))['role']=='editor'
        for path in ['/api/admin/users','/api/admin/logs','/api/admin/access','/api/admin/backup','/api/admin/schedule?class_name=11А']:
            await call('GET',path,uid=1,status=403)
        post=(await call('POST','/api/news',{'title':'Редкое слово жираф','content':'Тест поиска по содержимому','author_id':3},uid=3,status=201))['id']
        await call('GET','/api/admin/news/pending',uid=1)
        await call('POST',f'/api/admin/news/{post}/moderate',{'action':'approve','admin_id':1},uid=1)
        await call('PUT',f'/api/news/{post}/pin',{'pinned':True},uid=3,status=403)
        await call('PUT',f'/api/news/{post}/pin',{'pinned':True},uid=1)
        assert (await call('GET','/api/news?q=жираф',uid=3))[0]['is_pinned']
        assert len(await call('GET','/api/news?q=ЖИРАФ',uid=3))==1
        assert not await call('GET','/api/news?q=НЕСУЩЕСТВУЮЩЕЕ',uid=3)
        assert not await call('GET','/api/news?q=%25',uid=3),'SQL wildcard must be literal'
        # Drafts are private and stale writes cannot replace another device's work.
        draft=await call('GET','/api/me/news-draft',uid=3)
        saved=await call('PUT','/api/me/news-draft',{'title':'Мой черновик','content':'Текст','revision':draft['revision']},uid=3)
        assert (await call('GET','/api/me/news-draft',uid=3))['content']=='Текст'
        assert (await call('GET','/api/me/news-draft',uid=1))['content']==''
        await call('PUT','/api/me/news-draft',{'title':'Потерять','revision':''},uid=3,status=409)
        # Dated schedule replacements affect only one actual day, both profiles and reminders.
        async with async_session() as db:
            db.add(Lesson(class_name='11А',day_of_week=0,lesson_number=1,subject='Математика',teacher_name='Учитель',cabinet='101',start_time='09:00',end_time='09:40'))
            db.add(UserPreferences(user_id=3,lesson_reminders=True,reminder_minutes=10,schedule_changes=True));await db.commit()
        url='/api/admin/schedule/date?class_name=11А&date=2026-10-26'
        original=await call('GET',url)
        rows=[dict(original['rows'][0],subject='Замена',cabinet='202',start_time='10:00',end_time='10:40')]
        payload={'class_name':'11А','date':'2026-10-26','rows':rows,'note':'Изменён кабинет','base_revision':original['base_revision']}
        await call('PUT','/api/admin/schedule/date',payload,uid=1,status=403)
        dated=await call('PUT','/api/admin/schedule/date',payload)
        await call('PUT','/api/admin/schedule/date',payload,status=409)
        for profile in ['Соц-гум','Филологический']:
            result=await call('GET','/api/schedule/lessons?class_name=11А&date=2026-10-26&only_my_profile=true&profile_name='+profile)
            assert result['is_override'] and result['slots'][0]['lessons'][0]['cabinet']=='202'
        assert (await call('GET','/api/schedule/lessons?class_name=11А&date=2026-11-02'))['slots'][0]['lessons'][0]['cabinet']=='101'
        assert not (await call('GET','/api/schedule/lessons?class_name=11А&date=2026-11-01'))['slots']
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return datetime(2026,10,26,9,50,tzinfo=TZ)
        with patch('community.datetime',Clock):
            next_lesson=await call('GET','/api/me/next-lesson',uid=3)
            assert next_lesson['next']['lessons'][0]['cabinet']=='202' and next_lesson['next']['minutes_until']==10
        await enqueue_reminders(datetime(2026,10,26,9,50,tzinfo=TZ))
        async with async_session() as db:
            reminders=(await db.scalars(select(Notification).where(Notification.dedup_key.like('lesson:%')))).all()
            assert len(reminders)==1 and 'Замена' in reminders[0].text
        cancel=dict(payload,rows=[],base_revision=dated['base_revision'],note='Отмена')
        cancelled=await call('PUT','/api/admin/schedule/date',cancel)
        assert not (await call('GET','/api/schedule/lessons?class_name=11А&date=2026-10-26'))['slots']
        with patch('main.datetime',Clock):assert (await call('GET','/api/schedule/live?class_name=11А'))['state']=='after_school'
        async with async_session() as db:
            reminders=(await db.scalars(select(Notification).where(Notification.dedup_key.like('lesson:%')))).all();assert reminders[0].status=='cancelled'
        await enqueue_reminders(datetime(2026,10,26,9,50,tzinfo=TZ))
        revived=await call('PUT','/api/admin/schedule/date',dict(payload,base_revision=cancelled['base_revision']))
        await enqueue_reminders(datetime(2026,10,26,9,50,tzinfo=TZ))
        await enqueue_reminders(datetime(2026,10,26,9,50,tzinfo=TZ))
        async with async_session() as db:
            reminders=(await db.scalars(select(Notification).where(Notification.dedup_key.like('lesson:%')))).all()
            assert len(reminders)==1 and reminders[0].status=='pending'
        await call('POST','/api/admin/schedule/date/reset',dict(cancel,base_revision=revived['base_revision']))
        assert (await call('GET',url))['rows']==original['rows']
        # Existing students are retained when enabling invitations; new ones must redeem.
        await call('PUT','/api/admin/access',{'invites_required':True})
        assert (await sync(3))['access_allowed']
        assert not (await sync(4))['access_allowed']
        await call('GET','/api/news',uid=4,status=403)
        await call('POST','/api/news',{'title':'Без приглашения','content':'Нельзя писать','author_id':4},uid=4,status=403)
        await call('PUT','/api/me/preferences',{'theme':'dark'},uid=4,status=403)
        invite=await call('POST','/api/admin/invites',{'label':'11А','max_uses':1,'days':1},status=201)
        await call('POST','/api/access/redeem',{'code':'incorrect-code'},uid=4,status=400)
        await call('POST','/api/access/redeem',{'code':invite['code']},uid=4)
        await call('POST','/api/access/redeem',{'code':invite['code']},uid=4)
        assert (await sync(4))['access_allowed']
        await sync(5)
        await call('POST','/api/access/redeem',{'code':invite['code']},uid=5,status=400)
        listed=await call('GET','/api/admin/access');assert 'code_hash' not in str(listed) and invite['code'] not in str(listed)
        invite2=await call('POST','/api/admin/invites',{'label':'Отзыв','max_uses':2,'days':1},status=201)
        await call('POST',f'/api/admin/invites/{invite2["id"]}/revoke',{})
        await call('POST','/api/access/redeem',{'code':invite2['code']},uid=5,status=400)
        # Contending activations serialize: a one-use code grants exactly one new member.
        for uid in (6,7):await sync(uid)
        single=await call('POST','/api/admin/invites',{'label':'Гонка','max_uses':1,'days':1},status=201)
        results=await asyncio.gather(*(c.post('/api/access/redeem',headers=signed(uid),json={'code':single['code']}) for uid in (6,7)))
        assert sorted(r.status_code for r in results)==[200,400]
        await call('PUT','/api/admin/users/1/role',{'role':'student'})
        await call('GET','/api/admin/news/pending',uid=1,status=403)
        # Include new Date, invite and draft tables in a real backup round trip.
        empty=await call('GET','/api/admin/schedule/date?class_name=11Б&date=2026-10-26')
        special=dict(payload,class_name='11Б',rows=[dict(rows[0],profile_name=None)],base_revision=empty['base_revision'])
        await call('PUT','/api/admin/schedule/date',special)
        with patch('main.datetime',Clock):assert (await call('GET','/api/schedule/live?class_name=11Б'))['state']=='before_school'
        from features import build_backup
        archive=DIR/'roundtrip.zip';archive.write_bytes(await build_backup())
        restore_env=dict(os.environ,DATABASE_URL='sqlite+aiosqlite:///'+str(DIR/'restored.db'),UPLOAD_DIR=str(DIR/'restored-uploads'))
        result=await asyncio.to_thread(subprocess.run,[sys.executable,str(ROOT/'backup_restore.py'),str(archive),'--apply'],env=restore_env,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        async with async_session() as db:
            row=await db.get(SchoolInvite,invite['id']);assert row.uses==1 and row.code_hash!=invite['code']
            user=await db.get(User,4);assert user.role=='student'
            logs=(await db.scalars(select(AuditLog))).all();assert any(r.entity=='dated_schedules' for r in logs)
            assert all(invite['code'] not in r.details and 'code_hash' not in r.details for r in logs)
    await engine.dispose()
    print('PASS: editorial/admin separation, searchable/pinned news, private revisioned drafts, dated replacement/reset/cancellation, next lesson, reminder cancellation, membership gate, invitation limits/revocation and secret-free audit')
try:asyncio.run(run())
finally:TEMP.cleanup()
