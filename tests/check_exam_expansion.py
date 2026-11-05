"""Exam bank integrity, safe curriculum upgrades and explicit written-answer self-check."""
import asyncio, hashlib, hmac, json, os, sys, tempfile, time, urllib.parse
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='gym16-exam-');D=Path(TEMP.name)
os.environ.update(DATABASE_URL=os.getenv('GYM16_TEST_DATABASE_URL') or 'sqlite+aiosqlite:///'+str(D/'test.db'),BOT_TOKEN='123456789:TEST_ONLY',ADMIN_IDS='2',ADMIN_USERNAME='',UPLOAD_DIR=str(D/'uploads'),BACKUP_DIR=str(D/'backups'))
import httpx
from sqlalchemy import select
from database import init_db,async_session,engine
from models import AppliedDataUpdate,EgeMaterial,MaterialProgress,PracticeProgress,User
import main,learning

def signed(uid=1):
    fields={'auth_date':str(int(time.time())),'user':json.dumps({'id':uid,'first_name':'Тест'})}
    key=hmac.new(b'WebAppData',os.environ['BOT_TOKEN'].encode(),hashlib.sha256).digest()
    fields['hash']=hmac.new(key,'\n'.join(f'{k}={v}' for k,v in sorted(fields.items())).encode(),hashlib.sha256).hexdigest()
    return {'X-Telegram-Init-Data':urllib.parse.urlencode(fields)}

async def run():
    counts=Counter((q['subject_code'],q['task_number']) for q in learning.BANK)
    assert len(counts)==47 and set(counts.values())=={10} and len(learning.QUESTIONS)==470
    figures=[q['figure'] for q in learning.BANK if q.get('figure')]
    assert len(figures)==16
    import xml.etree.ElementTree as ET
    for figure in figures:
        assert figure.startswith('/static/ege-graphs/') and figure.endswith('.svg')
        svg=ET.parse(ROOT/figure.lstrip('/')).getroot()
        assert svg.tag=='{http://www.w3.org/2000/svg}svg'
        assert not any(node.tag.endswith('script') for node in svg.iter())
    for topic in learning.CATALOG['topics']:
        key=(topic['subject_code'],topic['task_number']);rows=[q for q in learning.BANK if (q['subject_code'],q['task_number'])==key]
        assert len(topic['theory'])>=1500,key
        assert len({q['prototype'] for q in rows})==10,('Repeated prototypes',key)
        assert len({q['prompt'] for q in rows})==10,key
        for q in rows:
            assert q['answer'] and q['explanation'] and len(q['prompt'])>20,q['id']
            if q['kind']=='self_check':
                assert 'только одно число' not in q['prompt'].lower(),q['id']
                assert len(q['explanation'])>250,q['id']
            else:
                assert learning.check_answer(q,q['answer']),q['id']
                assert not learning.check_answer(q,'НЕВЕРНЫЙ ОТВЕТ'),q['id']
                if q.get('answer_order')=='any':assert learning.check_answer(q,q['answer'][::-1]),q['id']
    await init_db()
    async with async_session() as db:
        db.add(User(id=1,first_name='Тест',last_name='Ученик',class_name='11А',profile_name='Соц-гум'))
        db.add(AppliedDataUpdate(revision='ege-2027-20261025-v1'))
        manual=EgeMaterial(subject_code='math',task_number=7,title='Ручной материал',theory='Не менять');db.add(manual)
        default=EgeMaterial(subject_code='math',task_number=1,title='Прежняя теория',theory='Старая',source_key='ege-2027:math:1');db.add(default)
        await db.flush();default_id=default.id;manual_id=manual.id
        db.add(MaterialProgress(user_id=1,material_id=default_id,bookmarked=True,studied=True));await db.commit()
    assert await learning.apply_learning_catalog()
    assert not await learning.apply_learning_catalog()
    async with async_session() as db:
        assert (await db.get(EgeMaterial,default_id)).theory==learning.TOPICS['math',1]['theory']
        assert (await db.get(MaterialProgress,(1,default_id))).bookmarked
        assert (await db.get(EgeMaterial,manual_id)).task_number==7, 'Do not renumber manual materials twice'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as c:
        async def call(method,path,payload=None,status=200):
            r=await c.request(method,path,headers=signed(),json=payload);assert r.status_code==status,(path,r.status_code,r.text[:200]);return r.json()
        for sub,n in [('math',14),('russian',27)]:
            path=f'/api/me/practice/next?subject_code={sub}&task_number={n}'
            item=await call('GET',path);q=item['question'];assert q['kind']=='self_check' and 'answer' not in q and 'explanation' not in q
            payload={'session_id':item['session_id'],'answer':'Полное решение на бумаге'}
            await call('POST','/api/me/practice/answer',{**payload,'self_assessment':True},status=409)
            review=await call('POST','/api/me/practice/answer',{**payload,'answer':'а'*15000});assert review['needs_review'] and review['explanation']
            async with async_session() as db:assert await db.get(PracticeProgress,(1,q['id'])) is None
            wrong=await call('POST','/api/me/practice/answer',{**payload,'self_assessment':False});assert not wrong['correct'] and wrong['self_assessed']
            assert (await call('POST','/api/me/practice/answer',{**payload,'self_assessment':True}))==wrong
            retry=await call('GET',path+'&mode=mistakes');assert retry['question']['id']==q['id']
            payload['session_id']=retry['session_id']
            await call('POST','/api/me/practice/answer',payload)
            assert (await call('POST','/api/me/practice/answer',{**payload,'self_assessment':True}))['correct']
            assert (await call('GET',path))['question']['id']!=q['id']
        item=await call('GET','/api/me/practice/next?subject_code=math&task_number=1')
        await call('POST','/api/me/practice/answer',{'session_id':item['session_id'],'answer':'1','self_assessment':True},status=422)
    await engine.dispose()
    print('PASS: 470 distinct prototypes, 47 expanded guides, preserved curriculum IDs, explicit private self-check and mistake replay')

if __name__=='__main__':
    try:asyncio.run(run())
    finally:TEMP.cleanup()
