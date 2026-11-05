"""Registration, real subgroup availability and private Telegram avatar regressions."""
import asyncio, hashlib, hmac, io, json, os, sys, tempfile, time, urllib.parse
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='gym16-beta-'); folder = Path(TEMP.name)
os.environ.update(DATABASE_URL='sqlite+aiosqlite:///'+str(folder/'test.db'), BOT_TOKEN='123456789:TEST_TOKEN_FOR_LOCAL_CHECKS_ONLY', ADMIN_IDS='2', ADMIN_USERNAME='', UPLOAD_DIR=str(folder/'uploads'), BACKUP_DIR=str(folder/'backups'))
import httpx
from PIL import Image
from database import init_db, async_session, engine
from models import Lesson
import main

def signed(uid=1):
    fields = {'auth_date':str(int(time.time())), 'user':json.dumps({'id':uid, 'first_name':'Тест'})}
    secret = hmac.new(b'WebAppData', os.environ['BOT_TOKEN'].encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(secret, '\n'.join(f'{k}={v}' for k,v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    return {'X-Telegram-Init-Data':urllib.parse.urlencode(fields)}

async def run():
    await init_db()
    async with async_session() as db:
        db.add(Lesson(class_name='11Д',day_of_week=0,lesson_number=1,subject='Английский язык',teacher_name='Учитель',cabinet='1',subgroup=1)); await db.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as client:
        result = await client.post('/api/user/sync',headers=signed(),json={'id':1,'first_name':'Тест','class_name':'11А','profile_name':'Соц-гум'})
        assert not result.json()['is_onboarded']
        for path in ['/api/news','/api/me/preferences','/api/me/notifications','/api/ege/subjects','/api/me/avatar']:
            assert (await client.get(path,headers=signed())).status_code == 409, path
        assert (await client.get('/api/me/avatar')).status_code == 401
        profile = {'first_name':'Тест','last_name':'Ученик','class_name':'11А','profile_name':'Соц-гум','subgroup':1}
        result = await client.put('/api/user/1/profile',headers=signed(),json=profile)
        assert result.status_code == 200 and result.json()['is_onboarded'] and result.json()['subgroup'] is None
        assert (await client.get('/api/news',headers=signed())).status_code == 200
        assert (await client.get('/api/meta/structure')).json()['subgroup_classes'] == ['11Д']
        profile.update(class_name='11Д',profile_name='Инфотех')
        assert (await client.put('/api/user/1/profile',headers=signed(),json=profile)).json()['subgroup'] == 1
        profile['last_name'] = ' '
        assert (await client.put('/api/user/1/profile',headers=signed(),json=profile)).status_code in (400,422)
        image = io.BytesIO(); Image.new('RGB',(20,20)).save(image,format='JPEG')
        calls = []
        def upstream(request):
            calls.append(request)
            if request.url.path.endswith('/getUserProfilePhotos'):
                assert request.url.params['user_id'] == '1'
                return httpx.Response(200,json={'result':{'photos':[[{'file_id':'fake_photo_id'}]]}})
            if request.url.path.endswith('/getFile'):
                return httpx.Response(200,json={'result':{'file_path':'photos/file_1.jpg'}})
            return httpx.Response(200,content=image.getvalue())
        native = httpx.AsyncClient
        with patch('main.httpx.AsyncClient',side_effect=lambda **kwargs:native(transport=httpx.MockTransport(upstream),**kwargs)):
            result = await client.get('/api/me/avatar?user_id=2',headers=signed())
        assert result.status_code == 200 and result.headers['content-type'] == 'image/jpeg'
        assert result.headers['cache-control'] == 'no-store' and len(calls) == 3
        assert os.environ['BOT_TOKEN'].encode() not in result.content
    from bot import get_main_inline_keyboard
    buttons = [button for row in get_main_inline_keyboard().inline_keyboard for button in row]
    assert len(buttons) == 3 and buttons[1].callback_data == 'view_bells' and buttons[2].url == 'https://t.me/kvalx'
    await engine.dispose()
    print('PASS: mandatory registration, class subgroups, own private avatar and minimal bot menu')

if __name__ == '__main__':
    try: asyncio.run(run())
    finally: TEMP.cleanup()
