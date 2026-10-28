"""Copy tracked local images to private S3 with read-back verification; retain originals."""
import argparse,asyncio,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from config import settings
from database import async_session,engine
from models import MediaUpload
from storage import s3_client,validate_storage_configuration
async def run(apply):
    if apply:
        validate_storage_configuration()
        if not all((settings.S3_BUCKET, settings.S3_ACCESS_KEY_ID, settings.S3_SECRET_ACCESS_KEY)):
            raise RuntimeError('Configure the destination private bucket credentials before copying')
    client=s3_client() if apply else None
    count=0
    async with async_session() as db:
        for row in (await db.scalars(select(MediaUpload))).all():
            path=settings.UPLOAD_DIR/row.filename
            if not path.is_file() or path.is_symlink():raise ValueError('Missing tracked local image; migration stopped')
            if apply:
                data=await asyncio.to_thread(path.read_bytes)
                await asyncio.to_thread(client.put_object,Bucket=settings.S3_BUCKET,Key='media/'+row.filename,Body=data,ContentType='image/png' if path.suffix=='.png' else 'image/jpeg',CacheControl='no-store')
                result=await asyncio.to_thread(client.get_object,Bucket=settings.S3_BUCKET,Key='media/'+row.filename)
                stream=result['Body']
                try:copy=await asyncio.to_thread(stream.read,len(data)+1)
                finally:stream.close()
                if hashlib.sha256(copy).digest()!=hashlib.sha256(data).digest():raise ValueError('Media verification failed')
                row.size_bytes=len(data)
            count+=1
        if apply:await db.commit()
    await engine.dispose()
    print(('Verified copied' if apply else 'Ready to copy'),count,'images; local originals retained')
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args();asyncio.run(run(args.apply))
