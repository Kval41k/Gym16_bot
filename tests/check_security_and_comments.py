"""Isolated negative checks: identity, comment conflicts, private media, limits and logs."""
import asyncio, hashlib, hmac, io, json, logging, os, sqlite3, sys, tempfile, time, urllib.parse
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='gym16-security-')
DIR = Path(TEMP.name)
os.environ.update(DATABASE_URL=os.getenv('GYM16_TEST_DATABASE_URL') or 'sqlite+aiosqlite:///' + str(DIR/'test.db'), BOT_TOKEN='123456789:TEST_TOKEN_FOR_LOCAL_CHECKS_ONLY', ADMIN_IDS='2', ADMIN_USERNAME='', UPLOAD_DIR=str(DIR/'uploads'), BACKUP_DIR=str(DIR/'backups'))
# Existing installations do not yet have the new theme/updated_at columns.
if not os.getenv('GYM16_TEST_DATABASE_URL'):
    with sqlite3.connect(DIR/'test.db') as conn:
        conn.execute('CREATE TABLE user_preferences (user_id BIGINT PRIMARY KEY, lesson_reminders BOOLEAN, reminder_minutes INTEGER, schedule_changes BOOLEAN)')
        conn.execute('CREATE TABLE comments (id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL, user_id BIGINT NOT NULL, author_name VARCHAR(100) NOT NULL, author_class VARCHAR(20), text TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
import httpx
from PIL import Image
from sqlalchemy import select, func
from database import init_db, async_session, engine
from models import User, NewsPost, AuditLog
from config import settings
from security import clean_image, csv_cell
import main
async def no_notification(**kwargs): pass
main.notify_admins_about_post = no_notification
logging.getLogger('httpx').setLevel(logging.WARNING)

def signed(uid=1, age=0):
    fields={'auth_date':str(int(time.time())-age),'user':json.dumps({'id':uid,'first_name':'Тест','username':'user'+str(uid)})}
    secret=hmac.new(b'WebAppData',settings.BOT_TOKEN.encode(),hashlib.sha256).digest()
    fields['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(fields.items())).encode(),hashlib.sha256).hexdigest()
    return {'X-Telegram-Init-Data':urllib.parse.urlencode(fields)}

async def run():
    await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as c:
        async def call(method,path,data=None,uid=1,status=200,**kwargs):
            response=await c.request(method,path,json=data,headers=signed(uid),**kwargs)
            assert response.status_code==status,(method,path,response.status_code,response.text[:500])
            return response
        for uid in (1,2,3):
            await call('POST','/api/user/sync',{'id':uid,'first_name':'Тест','class_name':'11А','profile_name':'Соц-гум','photo_url':'https://evil.invalid/fake.jpg'},uid)
        profile=(await call('GET','/api/user/1')).json()
        assert profile['photo_url'] is None, 'Unsigned photo must not override signed Telegram identity'
        for path in ('/api/news','/api/news/1/comments','/api/ege/subjects','/api/ege/materials?subject_code=russian&task_number=1','/api/me/preferences','/api/admin/logs','/uploads/'+'a'*32+'.jpg','/api/media/unreferenced_file'):
            assert (await c.get(path)).status_code in (401,403),path
        for headers in (signed(age=86401),signed(age=-301),{'X-Telegram-Init-Data':signed()['X-Telegram-Init-Data']+'&auth_date=1'}, {'X-Telegram-Init-Data':signed()['X-Telegram-Init-Data'].replace('user1','user2')}):
            assert (await c.get('/api/me/preferences',headers=headers)).status_code==401
        await call('POST','/api/user/sync',{'id':3,'first_name':'Подмена'},status=403)
        await call('GET','/api/admin/users?admin_id=2',status=403)
        prefs=(await call('GET','/api/me/preferences')).json();assert prefs['theme']=='auto'
        await call('PUT','/api/me/preferences',{'lesson_reminders':True,'reminder_minutes':15,'schedule_changes':True})
        prefs=(await call('PUT','/api/me/preferences',{'theme':'dark'})).json()
        assert prefs=={'lesson_reminders':True,'reminder_minutes':15,'schedule_changes':True,'theme':'dark'}
        await call('PUT','/api/me/preferences',{'theme':'evil'},status=422)
        assert (await call('GET','/api/me/preferences',uid=3)).json()['theme']=='auto'
        post=(await call('POST','/api/news',{'author_id':1,'title':'Новость','content':'Проверка комментариев'},status=201)).json()
        pid=post['id']
        await call('POST',f'/api/admin/news/{pid}/moderate',{'admin_id':2,'action':'approve'},uid=2)
        comment=(await call('POST',f'/api/news/{pid}/comments',{'user_id':1,'author_name':'Тест','text':'Первая версия'},status=201)).json()
        url=f'/api/news/comments/{comment["id"]}'
        edit={'text':'<img src=x onerror=alert(1)> Исправлено','revision':comment['revision']}
        await call('PUT',url,edit,uid=3,status=403)
        await call('PUT',url,edit,uid=2,status=403)
        edited=(await call('PUT',url,edit)).json()
        assert edited['is_edited'] and edited['updated_at'] and edited['revision']!=comment['revision']
        assert edited['text']==edit['text']
        await call('PUT',url,edit,status=409)
        edit['revision']=edited['revision']
        assert (await call('PUT',url,edit)).json()['revision']==edited['revision']
        for text in ('   ','x'*1001):await call('PUT',url,dict(edit,text=text),status=422)
        assert (await call('GET',url)).json()==edited
        logs=(await call('GET','/api/admin/logs?section=comments',uid=2)).json()['items']
        changes=[r for r in logs if r['action']=='update']
        assert len(changes)==1 and changes[0]['details']['text']['before']=='Первая версия'
        image=io.BytesIO();Image.new('RGB',(20,20),'blue').save(image,format='PNG')
        upload=await c.post('/api/upload',headers=signed(),files={'file':('picture.png',image.getvalue()+b'<script>LEAK</script>','image/png')})
        assert upload.status_code==200,upload.text
        path=upload.json()['url']
        assert not (DIR/'uploads'/upload.json()['filename']).read_bytes().endswith(b'<script>LEAK</script>')
        assert (await call('GET',path)).headers['content-type'].startswith('image/')
        await call('GET',path,uid=3,status=404)
        await call('GET',path,uid=2)
        await call('POST','/api/news',{'author_id':3,'title':'Чужое фото','content':'Нельзя присвоить чужой файл','image_url':path},uid=3,status=404)
        photo=(await call('POST','/api/news',{'author_id':1,'title':'С фото','content':'Приватное изображение','image_url':path},status=201)).json()
        await call('GET',path,uid=3,status=404)
        await call('POST',f'/api/admin/news/{photo["id"]}/moderate',{'admin_id':2,'action':'approve'},uid=2)
        response=await call('GET',path,uid=3)
        assert response.headers['cache-control']=='no-store' and response.headers['x-content-type-options']=='nosniff'
        await call('GET','/api/media/unreferenced_file',status=404)
        for body,mime in ((b'\x89PNG\r\n\x1a\n' + b'x'*100,'image/png'),(b'<svg onload="alert(1)"/>','image/svg+xml')):
            bad=await c.post('/api/upload',headers=signed(),files={'file':('bad.png',body,mime)})
            assert bad.status_code==400,bad.text
        oversized=await c.put('/api/me/preferences',headers={**signed(),'Content-Type':'application/json'},content=b' '*524289)
        assert oversized.status_code==413,oversized.text
        async def chunks():
            yield b' '*300000
            yield b' '*300000
        oversized=await c.put('/api/me/preferences',headers={**signed(),'Content-Type':'application/json'},content=chunks())
        assert oversized.status_code==413,oversized.text
        assert 'frame-ancestors' in (await call('GET','/api/news')).headers['content-security-policy']
        async with async_session() as db:
            user=await db.get(User,1);user.is_banned=True;await db.commit()
        await call('PUT',url,edit,status=403)
        await call('GET',path,status=403)
        await call('GET','/api/news',status=403)
    assert csv_cell(' =1+1').startswith("'") and csv_cell('Обычный текст')=='Обычный текст'
    stream=io.StringIO();handler=logging.StreamHandler(stream);logger=logging.getLogger('security-check');logger.addHandler(handler);logger.setLevel(logging.INFO)
    logger.info('Request %s', 'https://api.telegram.org/bot'+settings.BOT_TOKEN+'/getMe?token=private')
    try:raise RuntimeError(settings.BOT_TOKEN)
    except RuntimeError:logger.exception('Failure')
    logger.removeHandler(handler)
    assert settings.BOT_TOKEN not in stream.getvalue() and 'token=private' not in stream.getvalue()
    await engine.dispose()
    print('PASS: signed identity, expiry/tampering, admin isolation, comment editing/conflicts/audit, partial theme preferences, private images, sanitized upload, request limits including chunked data, banned users, security headers, CSV and secret redaction')
try:asyncio.run(run())
finally:TEMP.cleanup()
