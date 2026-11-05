"""School tools: scoped inbox, private reports, dated diffs and stable daily practice."""
import asyncio, hashlib, hmac, json, os, sys, tempfile, time, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='gym16-tools-');DIR=Path(TEMP.name)
os.environ.update(DATABASE_URL=os.getenv('GYM16_TEST_DATABASE_URL') or 'sqlite+aiosqlite:///'+str(DIR/'test.db'),BOT_TOKEN='123456789:TEST_ONLY',ADMIN_IDS='2',ADMIN_USERNAME='',UPLOAD_DIR=str(DIR/'uploads'),BACKUP_DIR=str(DIR/'backups'))
import httpx
from sqlalchemy import select, text
from config import settings
from database import async_session, engine, init_db
from models import ContentReport, Lesson, Notification, PracticeProgress, PracticeSession, User
from inbox import queue_inbox
from learning import QUESTIONS, TZ
import main, learning
async def noop(**kwargs):pass
main.notify_admins_about_post=noop

def signed(uid):
    data={'auth_date':str(int(time.time())),'user':json.dumps({'id':uid,'first_name':'Test'})}
    secret=hmac.new(b'WebAppData',settings.BOT_TOKEN.encode(),hashlib.sha256).digest()
    data['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
    return {'X-Telegram-Init-Data':urllib.parse.urlencode(data)}

async def run():
    await init_db();await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as c:
        async def call(method,url,data=None,uid=1,status=200):
            r=await c.request(method,url,json=data,headers=signed(uid))
            assert r.status_code==status,(method,url,r.status_code,r.text[:800])
            if '/api/' in url and (url.startswith('/api/me/') or '/reports' in url):assert r.headers['cache-control']=='no-store'
            return r.json()
        for uid in (1,2,3,4):await call('POST','/api/user/sync',{'id':uid,'first_name':'Test','last_name':'Student','class_name':'11А','profile_name':'Соц-гум'},uid)
        for url in ('/api/me/notifications','/api/admin/reports','/api/me/practice/progress'):
            assert (await c.get(url)).status_code in (401,403)
        # A transaction keeps the event and mutation atomic; repeated events are idempotent.
        async with async_session() as db:
            await queue_inbox(db,1,'news','Private <script>','test', 'news:1')
            await queue_inbox(db,1,'news','Duplicate','test', 'news:1')
            await queue_inbox(db,3,'news','Other account','other')
            await db.commit()
        first=await call('GET','/api/me/notifications');assert first['unread']==1 and len(first['items'])==1
        ident=first['items'][0]['id']
        await call('PUT',f'/api/me/notifications/{ident}/read',uid=3,status=404)
        assert (await call('GET','/api/me/notifications',uid=3))['items'][0]['text']=='Other account'
        async with async_session() as db:
            await queue_inbox(db,1,'news','Arrived meanwhile','later');await db.commit()
        await call('PUT','/api/me/notifications/read',{'through_id':ident})
        assert (await call('GET','/api/me/notifications'))['unread']==1
        await call('PUT',f'/api/me/notifications/{ident}/read');await call('PUT',f'/api/me/notifications/{ident}/read')
        # Approved publications, moderation feedback, comments and reports never leak author identities.
        post=(await call('POST','/api/news',{'title':'Anonymous post','content':'Test content','is_anonymous':True,'author_id':1},status=201))['id']
        pending={'target_type':'news','target_id':post,'reason':'abuse','details':'Test'}
        await call('POST','/api/reports',pending,uid=3,status=404)
        await call('POST',f'/api/admin/news/{post}/moderate',{'action':'approve','admin_id':2},uid=2)
        await call('POST',f'/api/admin/news/{post}/moderate',{'action':'approve','admin_id':2},uid=2)
        notices=(await call('GET','/api/me/notifications',uid=3))['items']
        assert len([row for row in notices if row['kind']=='news'])==2 # one fixture, one publication
        assert len(await call('GET',f'/api/news?post_id={post}',uid=3))==1
        comment=(await call('POST',f'/api/news/{post}/comments',{'user_id':3,'author_name':'Test','text':'Comment'},uid=3,status=201))['id']
        assert any(row['kind']=='comment' for row in (await call('GET','/api/me/notifications'))['items'])
        report=(await call('POST','/api/reports',pending,uid=3,status=201))['id']
        await call('POST','/api/reports',pending,uid=3,status=409)
        await call('POST','/api/reports',dict(pending,reporter_id=1),uid=4,status=422)
        await call('POST','/api/reports',dict(pending,reason='other',details=' '),uid=4,status=422)
        await call('POST','/api/reports',{'target_type':'comment','target_id':comment,'reason':'spam'},uid=4,status=201)
        assert len(await call('GET','/api/me/reports',uid=3))==1
        assert not await call('GET','/api/me/reports',uid=1)
        for url in ('/api/admin/reports',f'/api/admin/reports/{report}'):
            await call('GET',url,uid=3,status=403)
        await call('PUT','/api/admin/users/4/role',{'role':'editor'},uid=2)
        await call('GET','/api/admin/reports',uid=4,status=403)
        admin=await call('GET',f'/api/admin/reports/{report}',uid=2)
        assert admin['context']['author_name']=='Анонимно' and admin['target_available']
        assert 'reporter_id' not in admin
        await call('POST',f'/api/admin/reports/{report}/resolve',{'status':'handled','resolution':'Проверено'},uid=3,status=403)
        await call('POST',f'/api/admin/reports/{report}/resolve',{'status':'handled','resolution':'Проверено'},uid=2)
        await call('POST',f'/api/admin/reports/{report}/resolve',{'status':'dismissed','resolution':'Повтор'},uid=2,status=409)
        assert any(row['kind']=='report_result' for row in (await call('GET','/api/me/notifications',uid=3))['items'])
        assert (await call('GET',f'/api/news?post_id={post}'))[0]['id']==post,'A report must not automatically remove content'
        await call('DELETE',f'/api/news/{post}?user_id=2',uid=2)
        assert (await call('GET',f'/api/admin/reports/{report}',uid=2))['context']['content']=='Test content'
        # Per-audience schedule differences include normalized times and additions/cancellations.
        day='2026-11-02'
        async with async_session() as db:
            db.add_all([Lesson(class_name='11А',day_of_week=0,lesson_number=1,subject='Math',teacher_name='T',cabinet='101',profile_name=p) for p in ('Соц-гум','Филологический')])
            db.add(Lesson(class_name='11А',day_of_week=0,lesson_number=2,subject='Russian',teacher_name='T',cabinet='102'))
            await db.commit()
        url='/api/admin/schedule/date?class_name=11А&date='+day
        original=await call('GET',url,uid=2);rows=[dict(row) for row in original['rows']]
        rows[0].update(cabinet='202',start_time='09:00',end_time='09:40')
        rows=[r for r in rows if r['lesson_number']!=2]
        rows.append(dict(original['rows'][0],lesson_number=3,subject='Added',profile_name=None))
        await call('PUT','/api/admin/schedule/date',{'class_name':'11А','date':day,'rows':rows,'note':'Changes','base_revision':original['base_revision']},uid=2)
        changed_profile=original['rows'][0]['profile_name']
        changes=(await call('GET',f'/api/schedule/lessons?class_name=11А&date={day}&only_my_profile=true&profile_name={changed_profile}'))['changes']
        assert {r['kind'] for r in changes}=={'changed','cancelled','added'}
        assert {'cabinet','start_time','end_time'}<=set(next(r['fields'] for r in changes if r['kind']=='changed'))
        other='Филологический' if changed_profile=='Соц-гум' else 'Соц-гум'
        changes=(await call('GET',f'/api/schedule/lessons?class_name=11А&date={day}&only_my_profile=true&profile_name={other}'))['changes']
        assert not any(r['kind']=='changed' for r in changes)
        assert any(row['kind']=='schedule' for row in (await call('GET','/api/me/notifications'))['items']),'Inbox works without Telegram opt-in'
        # Free topic choice, private sessions and deliberate mistake review.
        path='/api/me/practice/next?subject_code=math&task_number=1'
        item=await call('GET',path);q=item['question'];assert 'answer' not in q and 'explanation' not in q
        await call('POST','/api/me/practice/answer',{'session_id':item['session_id'],'answer':'x'},uid=3,status=404)
        wrong=await call('POST','/api/me/practice/answer',{'session_id':item['session_id'],'answer':'x'});assert not wrong['correct']
        retry=await call('GET',path+'&mode=mistakes');assert retry['question']['id']==q['id']
        answer=QUESTIONS[q['id']]['answer']
        right=await call('POST','/api/me/practice/answer',{'session_id':retry['session_id'],'answer':answer});assert right['correct']
        assert (await call('POST','/api/me/practice/answer',{'session_id':retry['session_id'],'answer':answer}))==right
        assert (await call('GET',path))['question']['id']!=q['id']
        assert (await call('GET',path+'&mode=mistakes'))['question'] is None
        assert (await c.get('/api/me/practice/daily',headers=signed(1))).status_code==404
        async with async_session() as db:
            user=await db.get(User,3);user.is_banned=True;await db.commit()
        for url in ('/api/me/notifications','/api/me/reports','/api/me/practice/progress'):await call('GET',url,uid=3,status=403)
    await engine.dispose()
    print('PASS: scoped/read inbox, durable private reports, admin-only resolution, schedule audience/time diffs, free topic practice and private mistake review')
asyncio.run(run())
