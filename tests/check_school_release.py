"""Independent regressions for photo transcription, philology clock and EGE-2027 training."""
import asyncio, hashlib, hmac, io, json, logging, os, sys, tempfile, time, urllib.parse, zipfile, subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='gym16-school-');DIR=Path(TEMP.name)
os.environ.update(DATABASE_URL='sqlite+aiosqlite:///'+str(DIR/'check.db'),BOT_TOKEN='123456789:TEST_TOKEN_FOR_LOCAL_CHECKS_ONLY',ADMIN_IDS='2',ADMIN_USERNAME='',UPLOAD_DIR=str(DIR/'uploads'),BACKUP_DIR=str(DIR/'backups'))
import httpx
from sqlalchemy import select,func
from database import init_db,async_session,engine
from models import Lesson,EgeMaterial,MaterialProgress,PracticeProgress,User,AppliedDataUpdate
from seed_data import LESSONS_11A,LESSONS_11V
from data_updates import apply_calendar_schedule,apply_photo_timetables
from learning import apply_learning_catalog,QUESTIONS,TOPICS,check_answer
from features import build_backup
import main
logging.getLogger('httpx').setLevel(logging.WARNING)
def signed(uid):
 d={'auth_date':str(int(time.time())),'user':json.dumps({'id':uid,'first_name':'Тест','username':'test'+str(uid)})}
 secret=hmac.new(b'WebAppData',os.environ['BOT_TOKEN'].encode(),hashlib.sha256).digest();d['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(d.items())).encode(),hashlib.sha256).hexdigest()
 return {'X-Telegram-Init-Data':urllib.parse.urlencode(d)}
async def run():
 await init_db()
 async with async_session() as db:
  db.add_all([Lesson(**row) for row in LESSONS_11A]);db.add_all([Lesson(**dict(row,class_name='11Д')) for row in LESSONS_11V])
  for uid in (1,2,3):db.add(User(id=uid,first_name='Тест',last_name='Ученик',class_name='11А',profile_name='Соц-гум'))
  await db.commit()
  old=EgeMaterial(subject_code='math',task_number=6,title='Старая теория уравнений',theory='Сохранить авторский материал');db.add(old)
  unsupported=EgeMaterial(subject_code='math',task_number=20,title='Комплексные числа',theory='Сохранить в архиве');db.add(unsupported)
  expressive=EgeMaterial(subject_code='russian',task_number=26,title='Средства выразительности',theory='Личный разбор');db.add(expressive)
  await db.commit();old_id=old.id;unsupported_id=unsupported.id;expressive_id=expressive.id
  db.add(MaterialProgress(user_id=1,material_id=old_id,bookmarked=True,studied=True));await db.commit()
 assert await apply_calendar_schedule()
 async with async_session() as db:
  installed=await db.scalar(select(Lesson).where(Lesson.class_name=='11А',Lesson.profile_name=='Соц-гум',Lesson.subject=='Английский язык'))
  installed.teacher_name='Бурейкевич Ю.Ю.';await db.commit()
 assert await apply_photo_timetables()
 assert await apply_learning_catalog()
 assert not await apply_photo_timetables() and not await apply_learning_catalog()
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as c:
  async def call(method,path,data=None,uid=1,status=200):
   r=await c.request(method,path,json=data,headers=signed(uid));assert r.status_code==status,(path,r.status_code,r.text[:700]);return r.json()
  async def day(cls,d,profile=None,group=None):
   params={'class_name':cls,'day_of_week':d}
   if profile:params.update(profile_name=profile,only_my_profile=True)
   if group:params['subgroup']=group
   data=await call('GET','/api/schedule/lessons?'+urllib.parse.urlencode(params))
   return [item for slot in data['slots'] for item in slot['lessons']]
  # Two independent photographs have paired sports/physics and asymmetrical subgroup cells.
  assert [r['lesson_number'] for r in await day('11Г',1)]==[1,2,3,4,5,6]
  assert [r['subject'] for r in await day('11Г',1)]==['Обществознание']*2+['Биология']*2+['Основы безопасности и защиты Родины']*2
  assert [r['lesson_number'] for r in await day('11Г',2,group=1)]==list(range(1,9))
  assert [(r['lesson_number'],r['subject']) for r in await day('11Д',2,group=1)]==[(2,'Английский язык'),(3,'Физика'),(4,'Физика'),(5,'Русский язык'),(6,'Русский язык'),(7,'Информатика и ИКТ')]
  assert [r['lesson_number'] for r in await day('11Д',3,group=2)]==[2,3,4,5,6,7]
  assert [r['subject'] for r in await day('11Ж',4,group=1)][:5]==['Физика','Физика','История','История','Вероятность и статистика']
  assert [r['lesson_number'] for r in await day('11Ж',2,group=2)]==[1,2,3,4,5,6]
  assert [r['lesson_number'] for r in await day('11Ж',2,group=1)]==[1,2,3,4,5,6,7]
  assert [(r['subject'],r['start_time']) for r in await day('11В',4,'Инфотех')][:2]==[('Английский язык','08:15'),('Физика','09:10')]
  assert [r['subject'] for r in await day('11В',4,'Инженерный')][:2]==['Физика','Английский язык']
  assert (await day('11В',3,'Инфотех'))[-1]['subject']=='Зачёт по математике'
  assert [r['subject'] for r in await day('11В',1,'Инфотех')][:6]==['Информатика и ИКТ']*2+['Русский язык']*2+['Геометрия']*2
  for d in range(5):
   soc={r['lesson_number']:(r['start_time'],r['end_time']) for r in await day('11А',d,'Соц-гум')}
   for row in await day('11А',d,'Филологический'):
    if row['lesson_number'] in soc:assert (row['start_time'],row['end_time'])==soc[row['lesson_number']]
  monday=await day('11А',0,'Филологический');assert monday[0]['lesson_number']==0 and monday[-1]['end_time']=='14:50'
  assert (await call('GET','/api/schedule/lessons?class_name=11Б'))['schedule_loaded'] is True
  assert [r['subject'] for r in await day('11Б',4,group=1)][4:6]==['Информатика и ИКТ','Английский язык']
  assert [r['subject'] for r in await day('11Б',4,group=2)][4:6]==['Английский язык','Информатика и ИКТ']
  assert not await day('11Б',5)
  assert (await day('11Д',0,group=1))[1]['teacher_name']=='Буракевич Ю.Ю.'
  assert all(r['teacher_name']=='Буракевич Ю.Ю.' for r in await day('11А',1,'Соц-гум') if r['subject']=='Английский язык')
  # Every task has real theory; old material IDs/bookmarks survive the renumbering.
  catalog=await call('GET','/api/ege/catalog');assert len(catalog['topics'])==47
  assert TOPICS['math',6]['title'].startswith('Случайные') and TOPICS['math',12]['title']=='Функции и графики'
  assert TOPICS['russian',22]['title'].startswith('Изобразительно')
  for sub,expected in [('math',20),('russian',27)]:
   materials=await call('GET','/api/ege/materials?subject_code='+sub)
   assert set(range(1,expected+1))<={r['task_number'] for r in materials}
   assert all(len(t['theory'])>500 for t in __import__('learning').CATALOG['topics'] if t['subject_code']==sub)
  async with async_session() as db:
   assert (await db.get(EgeMaterial,old_id)).task_number==7
   assert (await db.get(EgeMaterial,expressive_id)).task_number==22
   assert (await db.get(EgeMaterial,unsupported_id)).is_archived
   assert (await db.get(MaterialProgress,(1,old_id))).bookmarked
  await call('GET','/api/admin/ege/archive',status=403)
  assert (await call('GET','/api/admin/ege/archive',uid=2))[0]['id']==unsupported_id
  for path in ['/api/ege/catalog','/api/me/practice/next?subject_code=math&task_number=6','/api/me/practice/progress']:
   assert (await c.get(path)).status_code in (401,403)
  await call('GET','/api/me/practice/next?subject_code=math&task_number=27',status=422)
  # All major content types use real API flows, not just the answer helper.
  for sub,n in [('math',6),('math',13),('math',17),('math',20),('russian',4),('russian',12),('russian',27)]:
   path=f'/api/me/practice/next?subject_code={sub}&task_number={n}'
   first=await call('GET',path);q=first['question'];assert 'answer' not in q and 'explanation' not in q
   await call('POST','/api/me/practice/answer',{'session_id':first['session_id'],'answer':'wrong'},uid=3,status=404)
   wrong=await call('POST','/api/me/practice/answer',{'session_id':first['session_id'],'answer':'wrong'});assert wrong['correct'] is False and wrong['explanation']
   replay=await call('POST','/api/me/practice/answer',{'session_id':first['session_id'],'answer':QUESTIONS[q['id']]['answer']});assert replay==wrong
   fresh=await call('GET',path);assert fresh['question']['id']!=q['id']
   retry=await call('GET',path+'&mode=mistakes');assert retry['question']['id']==q['id']
   correct=await call('POST','/api/me/practice/answer',{'session_id':retry['session_id'],'answer':QUESTIONS[q['id']]['answer']});assert correct['correct'] is True
   assert (await call('GET',path))['question']['id']!=q['id']
   assert (await call('GET',path+'&mode=mistakes'))['question'] is None
  # Two simultaneous submissions of one session must produce one recorded attempt.
  single=await call('GET','/api/me/practice/next?subject_code=math&task_number=1',uid=2)
  payload={'session_id':single['session_id'],'answer':'5'}
  together=await asyncio.gather(*(c.post('/api/me/practice/answer',headers=signed(2),json=payload) for _ in range(2)))
  assert all(r.status_code==200 and r.json()['correct'] for r in together)
  assert (await call('GET','/api/me/practice/progress',uid=2))['math:1']['attempts']==1
  # Answer keys are never exposed as static assets.
  assert (await c.get('/data/practice_2027.json')).status_code==404
  stats=await call('GET','/api/me/practice/progress');assert stats['math:6']['mastered']==1 and stats['math:6']['attempts']==2
  assert (await call('GET','/api/me/practice/progress',uid=3))['math:6']['mastered']==0
  assert check_answer({'kind':'number','answer':'1/4'},'0,25') and check_answer({'kind':'number','answer':'0.25'},'1/4')
  assert not check_answer({'kind':'number','answer':'1'},'__import__("os").system("id")')
  # Independently hand-calculated keys for every numeric mathematics topic.
  expected={1:[5,13,17],2:[11,7,-2],3:[20,24,70],4:['1/4','7/20','3/10'],5:['3/10','2/5','63/100'],6:[10,12,30,16,4,"3/10"],7:[10,21,33],8:[3,2,2],9:[4,-2,3],10:[60,60,54],11:[2,2,4],12:[4,5,2],13:[22000,54000,46000,23000,12100,12100],14:[2,3,4],15:[6,8,6],16:[3,7,6],17:[4,9,16,18,8,25],18:[8,11,15],19:[2,3,4],20:[3,4,5]}
  for n,values in expected.items():
   actual=[Fraction(q['answer']) for q in QUESTIONS.values() if q['subject_code']=='math' and q['task_number']==n]
   assert actual==[Fraction(value) for value in values],(n,actual,values)
  # A backup containing progress, sessions, source keys and photo lessons must restore.
  archive=DIR/'complete.zip';archive.write_bytes(await build_backup())
  env=dict(os.environ,DATABASE_URL='sqlite+aiosqlite:///'+str(DIR/'restored.db'),UPLOAD_DIR=str(DIR/'restored-uploads'))
  restored=await asyncio.to_thread(subprocess.run,[sys.executable,str(ROOT/'backup_restore.py'),str(archive),'--apply'],env=env,capture_output=True,text=True)
  assert restored.returncode==0,restored.stderr
  # Later administrator edits are authoritative across restarts.
  async with async_session() as db:
   lesson=await db.scalar(select(Lesson).where(Lesson.class_name=='11Д'));lesson.cabinet='Ручная правка';changed_id=lesson.id;await db.commit()
  assert not await apply_photo_timetables()
  async with async_session() as db:assert (await db.get(Lesson,changed_id)).cabinet=='Ручная правка'
  assert list((DIR/'backups').glob('schedule-before-photo-*.json'))
 await engine.dispose()
 print('PASS: photo transcription, both subgroup asymmetries, corrected 11В tracks, shared 11А clock, 47 populated topics, preserved legacy materials, isolated/idempotent practice, mistakes then mastery, all numeric keys and full backup restoration')
try:asyncio.run(run())
finally:TEMP.cleanup()
