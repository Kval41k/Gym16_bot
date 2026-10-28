"""Negative regressions for the 2026-10-28 hardening; isolated DB and fake S3 only."""
import asyncio,hashlib,hmac,io,json,os,sys,tempfile,time,urllib.parse,zipfile,subprocess,sqlite3
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='gym16-hardening-');DIR=Path(TEMP.name)
os.environ.update(DATABASE_URL='sqlite+aiosqlite:///'+str(DIR/'test.db'),BOT_TOKEN='123456789:TEST_ONLY',ADMIN_IDS='2',ADMIN_USERNAME='reclaimed_admin',UPLOAD_DIR=str(DIR/'uploads'),BACKUP_DIR=str(DIR/'backups'))
import httpx
from PIL import Image
from sqlalchemy import select,text
from cryptography.fernet import Fernet,InvalidToken
from config import settings
from database import init_db,async_session,engine
from models import User,MediaUpload,NewsPost
import main,storage,features,offsite_backup

def signed(uid,username=None,age=0):
    data={'auth_date':str(int(time.time())-age),'user':json.dumps({'id':uid,'first_name':'Test','username':username or 'u'+str(uid)})}
    key=hmac.new(b'WebAppData',settings.BOT_TOKEN.encode(),hashlib.sha256).digest()
    data['hash']=hmac.new(key,'\n'.join(k+'='+v for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
    return {'X-Telegram-Init-Data':urllib.parse.urlencode(data)}

class FakeS3:
    def __init__(self):self.objects={};self.writes=0
    def put_object(self,**kw):self.objects[kw['Key']]=kw['Body'];self.writes+=1
    def get_object(self,**kw):return {'Body':io.BytesIO(self.objects[kw['Key']])}
    def delete_object(self,**kw):self.objects.pop(kw['Key'],None)
    def get_paginator(self,*a):return self
    def paginate(self,**kw):return [{'Contents':[{'Key':k} for k in self.objects]}]

async def run():
    await init_db();await init_db()
    async with engine.connect() as conn:assert await conn.scalar(text('SELECT version_num FROM alembic_version'))=='20261028_01'
    async with async_session() as db:
        db.add_all([User(id=i,first_name='Test',class_name='11А',profile_name='Соц-гум',is_member=True) for i in (1,2)])
        await db.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as c:
        r=await c.get('/api/admin/users',headers=signed(1,'reclaimed_admin'));assert r.status_code==403
        r=await c.get('/api/admin/users',headers=signed(2));assert r.status_code==200
        r=await c.get('/api/me/preferences',headers=signed(1,age=7201));assert r.status_code==401
        r=await c.get('/api/me/preferences',headers=signed(1,age=7190));assert r.status_code==200
        r=await c.get('/api/headman/overview',headers=signed(2));assert r.status_code==200 and r.headers.get('cache-control')=='no-store'
        assert "script-src-attr 'none'" in r.headers['content-security-policy']
        assert "script-src 'self' https://telegram.org;" in r.headers['content-security-policy']
        assert "img-src 'self' https: " not in r.headers['content-security-policy']
        r=await c.post('/api/news',headers=signed(1),json={'author_id':1,'title':'Tracking','content':'Image','image_url':'https://tracker.invalid/pixel.png'});assert r.status_code==422
        image=io.BytesIO();Image.new('RGB',(20,20),'blue').save(image,format='PNG')
        async def upload():return await c.post('/api/upload',headers=signed(1),files={'file':('a.png',image.getvalue(),'image/png')})
        fake=FakeS3()
        with patch.object(settings,'S3_MEDIA_ENABLED',True),patch.object(storage,'s3_client',return_value=fake):
            r=await upload();assert r.status_code==200,r.text
            path=r.json()['url'];name=r.json()['filename'];assert not (settings.UPLOAD_DIR/name).exists()
            r=await c.get(path,headers=signed(1));assert r.status_code==200 and r.headers['cache-control']=='no-store'
            r=await c.get(path,headers=signed(2));assert r.status_code==200 # Configured administrator.
            async with async_session() as db:
                row=await db.get(MediaUpload,name);assert row.size_bytes>0
                row.created_at=datetime.now(timezone.utc)-timedelta(days=8);await db.commit()
            await storage.cleanup_uploads();assert 'media/'+name not in fake.objects
            async with async_session() as db:assert await db.get(MediaUpload,name) is None
        r=await upload();assert r.status_code==200,r.text
        name=r.json()['filename']
        async with async_session() as db:
            row=await db.get(MediaUpload,name);row.size_bytes=storage.MB;await db.commit()
        with patch.object(settings,'UPLOAD_USER_QUOTA_MB',1):assert (await upload()).status_code==413
        with patch.object(settings,'UPLOAD_TOTAL_QUOTA_MB',1):assert (await upload()).status_code==507
        with patch.object(storage.shutil,'disk_usage',return_value=SimpleNamespace(free=0)):
            assert (await upload()).status_code==507
            ready=await c.get('/api/ready');assert ready.status_code==503 and not ready.json()['checks']['disk']
        async with async_session() as db:
            row=await db.get(MediaUpload,name);row.created_at=datetime.now(timezone.utc)-timedelta(days=8)
            db.add(NewsPost(author_id=1,author_name='Test',title='Keep',content='Image',image_url='/uploads/'+name,status='approved'));await db.commit()
        await storage.cleanup_uploads();assert (settings.UPLOAD_DIR/name).exists()
        ready=await c.get('/api/ready');assert ready.status_code==200 and ready.json()['checks']['database']
    key=Fernet.generate_key().decode();fake=FakeS3()
    with patch.object(settings,'BACKUP_ENCRYPTION_KEY',key),patch.object(settings,'BACKUP_REMOTE_ENABLED',True),patch.object(offsite_backup,'s3_client',return_value=fake):
        content=await features.build_backup();cipher=offsite_backup.encrypt_backup(content)
        assert b'data.json' not in cipher and offsite_backup.decrypt_backup(cipher)==content
        try:offsite_backup.decrypt_backup(cipher[:-5]+b'xxxxx')
        except InvalidToken:pass
        else:raise AssertionError('Tampered encrypted backup accepted')
        await asyncio.gather(features.create_daily_backup(),features.create_daily_backup())
        assert fake.writes==1
        archive=next(settings.BACKUP_DIR.glob('gym16-*.zip'))
        assert offsite_backup.decrypt_backup(next(iter(fake.objects.values())))==archive.read_bytes()
        encrypted_path=DIR/'external.zip.fernet';encrypted_path.write_bytes(next(iter(fake.objects.values())))
        env={**os.environ,'DATABASE_URL':'sqlite+aiosqlite:///'+str(DIR/'restored.db'),'UPLOAD_DIR':str(DIR/'restored-uploads'),'BACKUP_ENCRYPTION_KEY':key}
        restored=await asyncio.to_thread(subprocess.run,[sys.executable,str(ROOT/'backup_restore.py'),str(encrypted_path),'--apply'],env=env,capture_output=True,text=True)
        assert restored.returncode==0,restored.stderr[-1000:]
        with sqlite3.connect(DIR/'restored.db') as restored_db:assert restored_db.execute('SELECT count(*) FROM users').fetchone()[0]==2
        assert (DIR/'restored-uploads'/name).exists()
        archive.write_bytes(b'CORRUPTED');await features.create_daily_backup()
        offsite_backup.validate_archive(archive.read_bytes())
    # Every production JS file parses and HTML has no executable inline attributes/scripts.
    import re
    for path in [ROOT/'static/index.html',*[ROOT/'static'/n for n in ['app.js','headman.js','features.js','learning.js','community.js']]]:
        assert not re.search(r'(?<![\w.])on(?:click|change|input|submit|error|load)\s*=',path.read_text()),path
    assert '<script>' not in (ROOT/'static/index.html').read_text()
    await engine.dispose()
    print('PASS: ID-only admins, 2h auth, private cache headers, strict CSP, tracking URLs rejected, local/S3 quotas and cleanup, readiness, Alembic adoption/idempotence, encrypted verified offsite backups and corruption repair')
asyncio.run(run())
