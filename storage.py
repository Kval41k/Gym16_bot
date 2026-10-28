"""Bounded private media storage, quotas and readiness. S3 buckets must stay private."""
import asyncio
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from fastapi import HTTPException
from sqlalchemy import select, func, text
from config import settings
from database import engine, async_session
from models import MediaUpload, NewsPost, EgeMaterial

MB = 1024 * 1024


def s3_client():
    import boto3
    from botocore.config import Config
    return boto3.client('s3', endpoint_url=settings.S3_ENDPOINT_URL or None,
        region_name=settings.S3_REGION, aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        config=Config(signature_version='s3v4', connect_timeout=5, read_timeout=20,
                      retries={'max_attempts': 2, 'mode': 'standard'}))


def validate_storage_configuration():
    if settings.S3_MEDIA_ENABLED or settings.BACKUP_REMOTE_ENABLED:
        if not all((settings.S3_BUCKET, settings.S3_ACCESS_KEY_ID, settings.S3_SECRET_ACCESS_KEY)):
            raise RuntimeError('Private S3 storage credentials are incomplete')
        if settings.S3_ENDPOINT_URL and not settings.S3_ENDPOINT_URL.startswith('https://'):
            raise RuntimeError('S3 endpoint must use HTTPS')
    if settings.BACKUP_REMOTE_ENABLED:
        from cryptography.fernet import Fernet
        Fernet(settings.BACKUP_ENCRYPTION_KEY.encode())
    if settings.REQUIRE_PERSISTENT_STORAGE:
        disk = os.getenv('RENDER_DISK_PATH')
        def on_disk(path):
            return bool(disk and path.resolve().is_relative_to(__import__('pathlib').Path(disk).resolve()))
        database_ok = engine.dialect.name != 'sqlite' or on_disk(__import__('pathlib').Path(engine.url.database))
        if not database_ok or not (settings.S3_MEDIA_ENABLED or on_disk(settings.UPLOAD_DIR)) or not settings.BACKUP_REMOTE_ENABLED:
            raise RuntimeError('Persistent database, media and external encrypted backup are required')


def upload_size(row):
    path = settings.UPLOAD_DIR / row.filename
    return max(row.size_bytes or 0, path.stat().st_size if path.is_file() and not path.is_symlink() else 0)


async def reserve_upload(db, user_id, content, ext):
    # Same DB lock on every writer serializes both quotas and subsequent metadata commit.
    from community import write_lock
    await write_lock(db)
    rows = (await db.scalars(select(MediaUpload))).all()
    own = sum(upload_size(row) for row in rows if row.user_id == user_id)
    local = sum(path.stat().st_size for path in settings.UPLOAD_DIR.iterdir() if path.is_file() and not path.is_symlink())
    total = max(local, sum(upload_size(row) for row in rows))
    if own + len(content) > settings.UPLOAD_USER_QUOTA_MB * MB:
        raise HTTPException(413, 'Достигнут лимит ваших фотографий. Обратитесь к администратору.')
    if total + len(content) > settings.UPLOAD_TOTAL_QUOTA_MB * MB:
        raise HTTPException(507, 'Хранилище заполнено. Администратору нужно освободить место.')
    if shutil.disk_usage(settings.UPLOAD_DIR).free - len(content) < settings.UPLOAD_MIN_FREE_MB * MB:
        raise HTTPException(507, 'Недостаточно свободного места для безопасного сохранения.')
    name = f'{uuid.uuid4().hex}.{ext}'
    path = settings.UPLOAD_DIR / name
    if settings.S3_MEDIA_ENABLED:
        try:
            await asyncio.to_thread(s3_client().put_object, Bucket=settings.S3_BUCKET,
                Key='media/'+name, Body=content, ContentType='image/png' if ext == 'png' else 'image/jpeg', CacheControl='no-store')
        except Exception:
            raise HTTPException(503, 'Хранилище временно недоступно. Фото не сохранено.') from None
    else:
        await asyncio.to_thread(path.write_bytes, content)
    return name, path


async def read_remote_image(name):
    try:
        result = await asyncio.to_thread(s3_client().get_object, Bucket=settings.S3_BUCKET, Key='media/'+name)
        stream = result['Body']
        try:
            body = await asyncio.to_thread(stream.read, 10*MB+1)
        finally:
            stream.close()
        if len(body)>10*MB: raise ValueError('Oversized stored media')
        return body
    except Exception:
        raise HTTPException(503, 'Не удалось загрузить изображение из хранилища') from None


async def delete_upload(name):
    if settings.S3_MEDIA_ENABLED:
        await asyncio.to_thread(s3_client().delete_object, Bucket=settings.S3_BUCKET, Key='media/'+name)
    (settings.UPLOAD_DIR/name).unlink(missing_ok=True)


async def cleanup_uploads():
    from community import write_lock
    cutoff = datetime.now(timezone.utc)-timedelta(days=settings.UPLOAD_ORPHAN_DAYS)
    async with async_session() as db:
        await write_lock(db)
        references = set()
        for model in (NewsPost,EgeMaterial):
            for url in (await db.scalars(select(model.image_url).where(model.image_url.is_not(None)))).all():
                parsed=urlsplit(url)
                if not parsed.netloc or parsed.netloc==urlsplit(settings.BASE_URL).netloc:
                    references.add(parsed.path)
        rows=(await db.scalars(select(MediaUpload).where(MediaUpload.created_at<cutoff))).all()
        for row in rows:
            if '/uploads/'+row.filename not in references:
                await delete_upload(row.filename)
                await db.delete(row)
        # Files left behind by a crash between write and commit also count against quotas.
        tracked=set((await db.scalars(select(MediaUpload.filename))).all())
        for path in settings.UPLOAD_DIR.iterdir():
            if path.is_file() and not path.is_symlink() and path.name not in tracked and path.name!='.gitkeep' and path.stat().st_mtime<cutoff.timestamp():
                path.unlink()
        await db.commit()


async def readiness_status():
    checks={'database':False,'disk':False}
    try:
        async def probe_db():
            async with engine.connect() as conn:
                await conn.execute(text('SELECT 1'))
        await asyncio.wait_for(probe_db(),5)
        checks['database']=True
    except Exception: pass
    try:
        checks['disk']=shutil.disk_usage(settings.UPLOAD_DIR).free>=settings.UPLOAD_MIN_FREE_MB*MB and os.access(settings.UPLOAD_DIR,os.W_OK)
    except OSError: pass
    if settings.S3_MEDIA_ENABLED:
        try:
            await asyncio.wait_for(asyncio.to_thread(s3_client().head_bucket, Bucket=settings.S3_BUCKET), 8)
            checks['media_store']=True
        except Exception:
            checks['media_store']=False
    checks['ready']=all(checks.values())
    # Backup freshness is observable but must not trigger a restart loop on a new installation.
    candidates=list(settings.BACKUP_DIR.glob('gym16-*.zip')) if settings.BACKUP_DIR.exists() else []
    checks['backup_recent']=bool(candidates and max(p.stat().st_mtime for p in candidates)>datetime.now().timestamp()-36*3600)
    if settings.BACKUP_REMOTE_ENABLED:
        markers=list(settings.BACKUP_DIR.glob('*.remote-ok'))
        checks['external_backup_recent']=bool(markers and max(p.stat().st_mtime for p in markers)>datetime.now().timestamp()-36*3600)
    return checks
