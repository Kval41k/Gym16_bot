"""Resource bounds, actual CSV exports, private image reuse and bounded SQL work."""
import asyncio, csv, hashlib, hmac, io, json, os, sys, tempfile, time, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='gym16-efficiency-');D=Path(TEMP.name)
os.environ.update(DATABASE_URL=os.getenv('GYM16_TEST_DATABASE_URL') or 'sqlite+aiosqlite:///'+str(D/'test.db'),BOT_TOKEN='123456789:TEST_ONLY',ADMIN_IDS='2',ADMIN_USERNAME='',UPLOAD_DIR=str(D/'uploads'),BACKUP_DIR=str(D/'backups'))
import httpx
from sqlalchemy import event, select
from config import settings
from database import init_db,async_session,engine
from models import AccessPolicy,Comment,MediaUpload,NewsPost,Notification,PracticeSession,User
from inbox import publication_notices
from security import BodyLimitMiddleware, safe_csv_writer
from learning import TZ
import main,bot
async def noop(**kwargs):pass
main.notify_admins_about_post=noop

def signed(uid):
    d={'auth_date':str(int(time.time())),'user':json.dumps({'id':uid,'first_name':'Test'})}
    secret=hmac.new(b'WebAppData',settings.BOT_TOKEN.encode(),hashlib.sha256).digest()
    d['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(d.items())).encode(),hashlib.sha256).hexdigest()
    return {'X-Telegram-Init-Data':urllib.parse.urlencode(d)}

async def run():
    # A short-window operation cannot erase a still-active hourly quota.
    main._RATE_LIMITS.clear();main._RATE_EXPIRY.clear()
    with patch('main._RATE_LIMIT_KEYS',2),patch('main.time.monotonic',return_value=0):
        main.enforce_rate_limit('hour',1,3600);main.enforce_rate_limit('short',1,60)
    with patch('main._RATE_LIMIT_KEYS',2),patch('main.time.monotonic',return_value=61):
        main.enforce_rate_limit('new',1,60)
        try:main.enforce_rate_limit('hour',1,3600)
        except main.HTTPException as e:assert e.status_code==429
        else:raise AssertionError('Hourly limit was evicted by a minute limit')
        try:main.enforce_rate_limit('overflow',1,60)
        except main.HTTPException as e:assert e.status_code==429
        else:raise AssertionError('Active quota could be evicted')
        assert len(main._RATE_LIMITS)==2
    main._RATE_LIMITS.clear();main._RATE_EXPIRY.clear();main._CACHE.clear()
    with patch('main.time.monotonic',return_value=1):
        for i in range(main._CACHE_LIMIT+100):main.cache_set(str(i),i)
        assert len(main._CACHE)==main._CACHE_LIMIT and main.cache_get('0',180) is None
    with patch('main.time.monotonic',return_value=182):assert main.cache_get('355',180) is None
    main._CACHE.clear()
    output=io.StringIO();safe_csv_writer(output,delimiter=';').writerow([' =1+1','+cmd','@SUM(A1)','normal'])
    assert next(csv.reader(io.StringIO(output.getvalue()),delimiter=';'))==["' =1+1","'+cmd","'@SUM(A1)",'normal']
    release=asyncio.Event();messages=[]
    async def upload_app(scope,receive,send):
        await release.wait()
        await main.JSONResponse({'ok':True})(scope,receive,send)
    async def receive():return {'type':'http.request','body':b'','more_body':False}
    async def send(message):messages.append(message)
    guard=BodyLimitMiddleware(upload_app)
    scope={'type':'http','method':'POST','path':'/api/upload','headers':[]}
    tasks=[asyncio.create_task(guard(scope,receive,send)) for _ in range(4)]
    await asyncio.sleep(0)
    await guard(scope,receive,send)
    assert messages[0]['status']==429 and guard.active_uploads==4
    release.set();await asyncio.gather(*tasks);assert guard.active_uploads==0
    release.clear();task=asyncio.create_task(guard(scope,receive,send));await asyncio.sleep(0);task.cancel()
    await asyncio.gather(task,return_exceptions=True);assert guard.active_uploads==0
    await init_db()
    async with async_session() as db:
        db.add_all([User(id=i,first_name='=1+1' if i==3 else 'Test',last_name='Student',class_name='11А',profile_name='Соц-гум',is_member=True) for i in (1,2,3)])
        db.add_all([User(id=i,first_name='Test',is_member=i%2==0,is_banned=i==100) for i in range(100,300)])
        await db.flush()
        post=NewsPost(author_id=1,author_name='Test',title='Title',content='Body',status='approved');db.add(post);await db.flush();pid=post.id
        db.add_all([Comment(post_id=pid,user_id=3,author_name='Test',text='Comment') for _ in range(100)])
        db.add(AccessPolicy(id=1,invites_required=True));await db.commit()
    queries=[]
    def observe(conn,cursor,statement,parameters,context,many):queries.append(statement)
    event.listen(engine.sync_engine,'before_cursor_execute',observe)
    try:
        async with async_session() as db:
            queries.clear();await publication_notices(db,SimpleNamespace(id=pid,author_id=1,title='Title'));await db.commit()
            assert len(queries)<=6,('Broadcast query count',len(queries))
            recipients=set(await db.scalars(select(Notification.user_id)))
            assert 2 in recipients and 100 not in recipients and 101 not in recipients and 102 in recipients and 1 not in recipients
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as client:
            queries.clear();r=await client.get('/api/news',headers=signed(1));assert r.status_code==200
            assert r.json()[0]['comments_count']==100
            assert not any('FROM comments' in q and 'comments.id AS' in q for q in queries),'Feed fetched entire comment objects'
            assert not any('FROM reactions' in q and 'reactions.id AS' in q for q in queries),'Feed fetched entire reaction objects'
            await client.put('/api/admin/users/1/role',json={'role':'editor'},headers=signed(2))
            name='a'*32+'.jpg'
            async with async_session() as db:
                db.add(MediaUpload(filename=name,user_id=3,size_bytes=10));await db.commit()
            payload={'admin_id':1,'subject_code':'russian','task_number':1,'title':'Material','theory':'Theory','image_url':'/uploads/'+name}
            r=await client.post('/api/ege/materials',json=payload,headers=signed(1));assert r.status_code==404,'Editor attached another account\'s unpublished upload'
            for invalid in ('/uploads/../file','/uploads/file.jpg?x=1','/uploads/a.svg'):
                r=await client.post('/api/news',json={'author_id':3,'title':'Title','content':'Content','image_url':invalid},headers=signed(3));assert r.status_code==422
            # SQL aggregates still place attempts correctly at Tyumen midnight.
            now=datetime.now(timezone.utc)
            async with async_session() as db:
                db.add_all([PracticeSession(id=f'{i:032x}',user_id=1,question_id='fixture',answer='x',correct=i%2==0,answered_at=now,created_at=now) for i in range(500,800)]);await db.commit()
            midnight=now.astimezone(TZ).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
            async with async_session() as db:
                db.add_all([PracticeSession(id=f'{i:032x}',user_id=1,question_id='fixture',answer='x',correct=correct,answered_at=stamp,created_at=now)
                    for i,stamp,correct in ((800,midnight-timedelta(microseconds=1),False),(801,midnight,True),(802,midnight+timedelta(days=1),True))]);await db.commit()
            queries.clear();r=await client.get('/api/me/practice/daily',headers=signed(1));assert r.status_code==200
            assert r.json()['week'][-1]['answered']==301 and r.json()['week'][-1]['correct']==151
            assert r.json()['week'][-2]['answered']==1
            assert not any('FROM practice_sessions' in q and 'answered_at >=' in q and 'count(' not in q.lower() for q in queries)
    finally:event.remove(engine.sync_engine,'before_cursor_execute',observe)
    # Exercise the bot export itself, not only the escaping helper.
    documents=[]
    async def answer_document(document,**kwargs):documents.append(document)
    async def answer(*args,**kwargs):pass
    message=SimpleNamespace(from_user=SimpleNamespace(id=2,username=None),answer_document=answer_document,answer=answer)
    callback=SimpleNamespace(from_user=message.from_user,message=message,answer=answer)
    await bot.cb_admin_export_users(callback);await bot.cmd_list_users(message)
    assert len(documents)==2
    for document in documents:
        rows=list(csv.reader(io.StringIO(document.data.decode('utf-8-sig')),delimiter=';'))
        assert next(r for r in rows[1:] if r[0]=='3')[1]=="'=1+1"
    await engine.dispose()
    print('PASS: bounded memory/quotas, real CSV exports, private upload ownership, batch notices, feed loading and SQL practice aggregates')
asyncio.run(run())
