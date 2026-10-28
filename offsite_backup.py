"""Authenticated encryption and read-back verification before remote rotation."""
import asyncio
import hashlib
import io
import json
import zipfile
from cryptography.fernet import Fernet
from config import settings
from storage import s3_client


def validate_archive(content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if archive.testzip() is not None:
            raise ValueError('Corrupt backup')
        data=json.loads(archive.read('data.json'))
        if data.get('format')!='gym16-backup-v1':raise ValueError('Invalid backup format')


def encrypt_backup(content):
    validate_archive(content)
    return Fernet(settings.BACKUP_ENCRYPTION_KEY.encode()).encrypt(content)


def decrypt_backup(content):
    plain=Fernet(settings.BACKUP_ENCRYPTION_KEY.encode()).decrypt(content)
    validate_archive(plain)
    return plain


async def publish_backup(path):
    if not settings.BACKUP_REMOTE_ENABLED:return
    content=await asyncio.to_thread(path.read_bytes)
    marker=path.with_suffix('.remote-ok')
    digest=hashlib.sha256(content).hexdigest()
    if marker.exists() and marker.read_text()==digest:return
    encrypted=await asyncio.to_thread(encrypt_backup,content)
    client=s3_client();key='backups/'+path.name+'.fernet'
    await asyncio.to_thread(client.put_object,Bucket=settings.S3_BUCKET,Key=key,Body=encrypted,ContentType='application/octet-stream')
    result=await asyncio.to_thread(client.get_object,Bucket=settings.S3_BUCKET,Key=key)
    stream=result['Body']
    try:downloaded=await asyncio.to_thread(stream.read,len(encrypted)+1)
    finally:stream.close()
    if downloaded!=encrypted or await asyncio.to_thread(decrypt_backup,downloaded)!=content:
        raise ValueError('External backup verification failed')
    await asyncio.to_thread(marker.write_text,digest)
    # Only our dedicated prefix and format are eligible for rotation.
    keys=[]
    pages=client.get_paginator('list_objects_v2')
    def list_keys():
        import re
        for page in pages.paginate(Bucket=settings.S3_BUCKET,Prefix='backups/gym16-'):
            for item in page.get('Contents',[]):
                if re.fullmatch(r'backups/gym16-\d{8}\.zip\.fernet',item['Key']):keys.append(item['Key'])
    await asyncio.to_thread(list_keys)
    for old in sorted(keys,reverse=True)[settings.BACKUP_REMOTE_KEEP:]:
        await asyncio.to_thread(client.delete_object,Bucket=settings.S3_BUCKET,Key=old)
