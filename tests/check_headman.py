"""Class scope, named attendance/menu polls, replay protection and safe delivery failures."""
import asyncio,hashlib,hmac,io,json,logging,os,sqlite3,subprocess,sys,tempfile,time,urllib.parse,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='gym16-headman-');DIR=Path(TEMP.name)
os.environ.update(DATABASE_URL='sqlite+aiosqlite:///'+str(DIR/'check.db'),BOT_TOKEN='123456789:TEST_TOKEN_FOR_LOCAL_CHECKS_ONLY',ADMIN_IDS='2',ADMIN_USERNAME='oldadmin',UPLOAD_DIR=str(DIR/'uploads'),BACKUP_DIR=str(DIR/'backups'))
import httpx
from sqlalchemy import select,func
from database import init_db,async_session,engine
from models import User,Lesson,ClassChat,ClassPoll,ClassLinkToken,ClassRoster,Attendance,MealMenu,MealChoice,AuditLog,ClassPollAnswerInbox
from aiogram.types import PollAnswer,User as TelegramUser,Update
from aiogram.filters.command import CommandObject
import main,headman,headman_bot,bot as personal_bot
from features import build_backup
logging.getLogger('httpx').setLevel(logging.WARNING)
TZ=ZoneInfo('Asia/Yekaterinburg');NOW=datetime(2026,10,26,7,0,tzinfo=TZ);TODAY=NOW.date();TOMORROW=TODAY+timedelta(days=1)
class Clock(datetime):
 @classmethod
 def now(cls,tz=None):return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
headman.datetime=Clock;headman_bot.datetime=Clock

def signed(uid,username=None):
 data={'auth_date':str(int(time.time())),'user':json.dumps({'id':uid,'first_name':'Тест','username':username or 'test'+str(uid)})}
 secret=hmac.new(b'WebAppData',os.environ['BOT_TOKEN'].encode(),hashlib.sha256).digest();data['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
 return {'X-Telegram-Init-Data':urllib.parse.urlencode(data)}
async def run():
 await init_db()
 async with async_session() as db:
  for uid,cls,role in [(1,'11А','student'),(2,'11А','student'),(3,'11А','editor'),(4,'11А','student'),(5,'11Б','student'),(6,'11Б','headman'),(7,'11А','student'),(8,'11А','student'),(9,'11А','student')]:
   db.add(User(id=uid,first_name='Ученик',last_name=str(uid),username='oldadmin' if uid==9 else 'test'+str(uid),class_name=cls,profile_name='Соц-гум' if cls=='11А' else 'Физмат',role=role,headman_class_name=cls if role=='headman' else None,is_member=True,is_banned=uid==8))
  db.add_all([Lesson(class_name=cls,day_of_week=0,lesson_number=1,subject='Физика',teacher_name='Учитель',cabinet='123',start_time='08:15',end_time='08:55') for cls in ['11А','11Б']])
  db.add_all([ClassChat(class_name='11А',chat_id=-1001,chat_title='11А чат'),ClassChat(class_name='11Б',chat_id=-1002,chat_title='11Б чат',attendance_enabled=False)])
  await db.commit()
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as client:
  async def call(method,path,data=None,uid=4,status=200):
   r=await client.request(method,path,json=data,headers=signed(uid));assert r.status_code==status,(path,r.status_code,r.text[:500]);return r.json()
  for uid in [1,3,9]:await call('GET','/api/headman/overview',uid=uid,status=403)
  r=await client.get('/api/headman/overview');assert r.status_code==401
  await call('PUT','/api/admin/users/4/role',{'role':'headman','class_name':'11А'},uid=1,status=403)
  admin_view=await call('GET','/api/headman/overview?class_name=11Б',uid=2);assert admin_view['class_name']=='11Б' and len(admin_view['classes'])==6
  grant=await call('PUT','/api/admin/users/4/role',{'role':'headman','class_name':'11А'},uid=2);assert grant['headman_class_name']=='11А'
  await call('PUT','/api/user/4/profile',{'class_name':'11Б','profile_name':'Физмат','first_name':'Тест','last_name':'Староста','subgroup':1,'headman_class_name':'11Б'})
  me=await call('GET','/api/user/4');assert me['class_name']=='11Б' and me['headman_class_name']=='11А'
  overview=await call('GET','/api/headman/overview');assert overview['classes']==['11А']
  await call('GET','/api/headman/attendance?class_name=11Б&date='+str(TODAY),status=403)
  await call('PUT','/api/headman/attendance',{'class_name':'11Б','date':str(TODAY),'user_id':5,'status':'yes'},status=403)
  await call('PUT','/api/headman/attendance',{'class_name':'11А','date':str(TODAY),'user_id':5,'status':'yes'},status=404)
  await call('PUT','/api/admin/users/1/role',{'role':'editor'},status=403)
  # Existing editors cannot acquire headman permissions via their profile.
  await call('GET','/api/headman/meals?class_name=11А&date='+str(TOMORROW),uid=3,status=403)
  token=await call('POST','/api/headman/link-token',{'class_name':'11А'})
  async with async_session() as db:
   assert await db.get(ClassLinkToken,hashlib.sha256(token['code'].encode()).hexdigest())
  telegram=SimpleNamespace(id=123456789,get_chat_member=AsyncMock(return_value=SimpleNamespace(status='administrator')))
  message=SimpleNamespace(chat=SimpleNamespace(id=-1003,type='supergroup',title='Новый чат 11А'),from_user=TelegramUser(id=4,is_bot=False,first_name='Староста',username='test4'),bot=telegram,answer=AsyncMock())
  await headman_bot.link_class_chat(message,CommandObject(prefix='/',command='class_link',args=token['code']))
  assert (await call('GET','/api/headman/overview'))['chat']['chat_id']==-1003
  await headman_bot.link_class_chat(message,CommandObject(prefix='/',command='class_link',args=token['code']))
  assert 'недействителен' in message.answer.call_args.args[0]
  # Separate date changes and stale weekly writes cannot overwrite another person's changes.
  date=await call('GET','/api/headman/schedule/date?date='+str(TODAY))
  date['rows'][0]['cabinet']='456'
  await call('PUT','/api/headman/schedule/date',date)
  await call('PUT','/api/headman/schedule/date',date,status=409)
  other=await call('GET','/api/headman/schedule/date?class_name=11Б&date='+str(TODAY),uid=6);assert other['rows'][0]['cabinet']=='123'
  week=await call('GET','/api/headman/schedule');week['rows'][0]['cabinet']='789'
  preview=await call('POST','/api/headman/schedule/preview',week);assert preview['base_revision']==week['base_revision']
  await call('POST','/api/headman/schedule/publish',week)
  await call('POST','/api/headman/schedule/publish',week,status=409)
  # Morning worker catches the current due time once and respects the class binding.
  await headman_bot.enqueue_class_attendance(NOW);await headman_bot.enqueue_class_attendance(NOW)
  attendance=await call('GET','/api/headman/attendance?date='+str(TODAY));attendance_id=attendance['poll']['id']
  await call('POST','/api/headman/attendance/publish',{'date':str(TODAY)})
  async with async_session() as db:assert await db.scalar(select(func.count()).select_from(ClassPoll).where(ClassPoll.kind=='attendance'))==1
  options={'main':['Котлета с пюре','Рыба с рисом'],'drink':['Чай','Компот'],'pastry':['Булочка','Пирожок']}
  data=await call('PUT','/api/headman/meals',{'date':str(TOMORROW),'options':options,'base_revision':''});revision=data['menu']['revision']
  await call('PUT','/api/headman/meals',{'date':str(TOMORROW),'options':options,'base_revision':''},status=409)
  bad={**options,'main':['Чай','Чай']};await call('PUT','/api/headman/meals',{'date':str(TOMORROW),'options':bad,'base_revision':revision},status=422)
  publish={'date':str(TOMORROW),'base_revision':revision}
  await asyncio.gather(call('POST','/api/headman/meals/publish',publish),call('POST','/api/headman/meals/publish',publish))
  await call('PUT','/api/headman/meals',{'date':str(TOMORROW),'options':{**options,'main':['Иное блюдо','Ещё одно']},'base_revision':revision},status=409)
  sent=[]
  async def transport(request):
   body=json.loads(request.content)
   if request.url.path.endswith('/getChatMember'):return httpx.Response(200,json={'ok':True,'result':{'status':'administrator'}})
   if request.url.path.endswith('/sendPoll'):
    assert body['is_anonymous'] is False and body['allows_multiple_answers'] is False
    sent.append(body);return httpx.Response(200,json={'ok':True,'result':{'message_id':len(sent),'poll':{'id':'poll-'+str(len(sent))}}})
   if request.url.path.endswith('/stopPoll'):return httpx.Response(200,json={'ok':True,'result':{}})
   raise AssertionError('Unexpected method')
  async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as network:
   await asyncio.gather(headman_bot.deliver_class_polls(network,NOW),headman_bot.deliver_class_polls(network,NOW))
   assert len(sent)==4
   await headman_bot.deliver_class_polls(network,NOW);assert len(sent)==4
  menu=await call('GET','/api/headman/meals?date='+str(TOMORROW));assert menu['menu']['status']=='published' and len(menu['polls'])==3
  async with async_session() as db:
   polls=(await db.scalars(select(ClassPoll))).all();by_kind={poll.kind:poll for poll in polls}
  memberbot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')))
  async def vote(kind,uid,option,sequence):
   event=PollAnswer(poll_id=by_kind[kind].telegram_poll_id,user=TelegramUser(id=uid,is_bot=False,first_name='Участник',last_name=str(uid)),option_ids=[] if option is None else [option],option_persistent_ids=[] if option is None else [str(option)])
   await headman_bot.record_poll_answer(event,memberbot,Update(update_id=sequence,poll_answer=event))
  await vote('attendance',501,0,100);await vote('attendance',501,1,101)
  attendance=await call('GET','/api/headman/attendance?date='+str(TODAY));assert next(row for row in attendance['rows'] if row['user_id']==501)['status']=='no'
  await vote('attendance',501,None,102);await vote('attendance',501,0,101)
  attendance=await call('GET','/api/headman/attendance?date='+str(TODAY));assert next(row for row in attendance['rows'] if row['user_id']==501)['status'] is None
  await vote('main',501,1,103);await vote('drink',501,0,104);await vote('pastry',501,2,105)
  meal=await call('GET','/api/headman/meals?date='+str(TOMORROW));assert next(row for row in meal['rows'] if row['user_id']==501)['choices']=={'main':1,'drink':0,'pastry':2}
  memberbot.get_chat_member=AsyncMock(return_value=SimpleNamespace(status='left'));await vote('main',999,0,106)
  async with async_session() as db:assert await db.get(ClassRoster,('11А',999)) is None
  memberbot.get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member'));await vote('main',8,0,107)
  async with async_session() as db:assert await db.get(MealChoice,(meal['menu']['id'],8,'main')) is None
  # Fast/temporarily unavailable membership lookups are replayed from a durable inbox.
  memberbot.get_chat_member=AsyncMock(side_effect=RuntimeError('temporary lookup failure'))
  await vote('drink',502,1,108)
  async with async_session() as db:assert await db.get(ClassPollAnswerInbox,108)
  async def replay_transport(request):
   return httpx.Response(200,json={'ok':True,'result':{'status':'member'}})
  async with httpx.AsyncClient(transport=httpx.MockTransport(replay_transport)) as network:
   await headman_bot.process_poll_answer_inbox(network,NOW)
  async with async_session() as db:
   assert await db.get(ClassPollAnswerInbox,108) is None
   assert (await db.get(MealChoice,(meal['menu']['id'],502,'drink'))).option_index==1
  # Answers arriving before sendPoll commits its Telegram ID are retained, not dropped.
  async with async_session() as db:
   pending=ClassPoll(id='a'*32,delivery_key='race-test',class_name='11А',poll_date=TOMORROW,kind='main',menu_id=meal['menu']['id'],chat_id=-1003,options_json=json.dumps(['A','B','Не буду']),status='sending');db.add(pending);await db.commit()
  memberbot.get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member'))
  event=PollAnswer(poll_id='race-native-poll',user=TelegramUser(id=503,is_bot=False,first_name='Быстрый'),option_ids=[0],option_persistent_ids=['0'])
  await headman_bot.record_poll_answer(event,memberbot,Update(update_id=109,poll_answer=event))
  async with async_session() as db:
   assert await db.get(ClassPollAnswerInbox,109)
   pending=await db.get(ClassPoll,'a'*32);pending.status='sent';pending.telegram_poll_id='race-native-poll';pending.message_id=50;await db.commit()
  async with httpx.AsyncClient(transport=httpx.MockTransport(replay_transport)) as network:await headman_bot.process_poll_answer_inbox(network,NOW)
  async with async_session() as db:
   assert await db.get(ClassPollAnswerInbox,109) is None
   assert (await db.get(MealChoice,(meal['menu']['id'],503,'main'))).option_index==0
  # Group members can register without first starting a private chat with the bot.
  join_message=SimpleNamespace(chat=message.chat,from_user=TelegramUser(id=504,is_bot=False,first_name='Ученик'),bot=memberbot,answer=AsyncMock())
  await headman_bot.join_class_roster(join_message)
  async with async_session() as db:assert await db.get(ClassRoster,('11А',504))
  await call('PUT','/api/headman/attendance',{'date':str(TODAY),'user_id':1,'status':'yes'})
  await call('PUT','/api/headman/meals/choice',{'date':str(TOMORROW),'user_id':501,'category':'main','option_index':0})
  await call('PUT','/api/headman/meals/choice',{'date':str(TOMORROW),'user_id':5,'category':'main','option_index':0},status=404)
  await call('POST','/api/headman/polls/'+by_kind['main'].id+'/retry',{},status=409)
  # Definitively failed deliveries may be retried; ambiguous sends must never duplicate a poll.
  async with async_session() as db:
   poll=await db.get(ClassPoll,attendance_id);poll.status='failed';poll.telegram_poll_id=None;poll.message_id=None;await db.commit()
  await call('POST','/api/headman/polls/'+attendance_id+'/retry',{})
  async def timeout_transport(request):
   if request.url.path.endswith('/getChatMember'):return httpx.Response(200,json={'ok':True,'result':{'status':'administrator'}})
   raise httpx.ReadTimeout('simulated transport timeout')
  async with httpx.AsyncClient(transport=httpx.MockTransport(timeout_transport)) as network:await headman_bot.deliver_class_polls(network,NOW)
  async with async_session() as db:assert (await db.get(ClassPoll,attendance_id)).status=='uncertain'
  await call('POST','/api/headman/polls/'+attendance_id+'/retry',{},status=409)
  backup=zipfile.ZipFile(io.BytesIO(await build_backup()));tables=json.loads(backup.read('data.json'))['tables'];assert tables['class_chats'] and tables['meal_choices'] and tables['attendance']
  archive_path=DIR/'headman-backup.zip';archive_path.write_bytes(await build_backup())
  restore_env={**os.environ,'DATABASE_URL':'sqlite+aiosqlite:///'+str(DIR/'restored.db')}
  restored=subprocess.run([sys.executable,str(ROOT/'backup_restore.py'),str(archive_path),'--apply'],env=restore_env,capture_output=True,text=True)
  assert restored.returncode==0,restored.stderr[-500:]
  with sqlite3.connect(DIR/'restored.db') as restored_db:
   assert restored_db.execute('SELECT count(*) FROM meal_choices').fetchone()[0]>=3
   assert restored_db.execute('SELECT headman_class_name FROM users WHERE id=4').fetchone()[0]=='11А'
   assert restored_db.execute('SELECT chat_id FROM class_chats WHERE class_name=?',('11А',)).fetchone()[0]==-1003
  # Group chatter and old admin buttons cannot invoke private bot flows in a class group.
  forbidden_handler=AsyncMock()
  await personal_bot.ban_check_middleware(forbidden_handler,SimpleNamespace(chat=SimpleNamespace(type='supergroup')),{})
  callback=SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(type='supergroup')),answer=AsyncMock())
  await personal_bot.ban_check_callback_middleware(forbidden_handler,callback,{})
  forbidden_handler.assert_not_awaited();callback.answer.assert_awaited_once()
  async with async_session() as db:
   logs=(await db.scalars(select(AuditLog).where(AuditLog.section=='headman'))).all()
   assert any(log.actor_id==4 for log in logs) and any(log.actor_id==501 for log in logs)
   assert all(token['code'] not in log.details for log in logs)
  # Removing role immediately revokes app access and previously issued binding credentials.
  token=await call('POST','/api/headman/link-token',{})
  await call('PUT','/api/admin/users/4/role',{'role':'student'},uid=2)
  await call('GET','/api/headman/overview',status=403)
  await headman_bot.link_class_chat(message,CommandObject(prefix='/',command='class_link',args=token['code']))
  assert 'недействителен' in message.answer.call_args.args[0]
  await call('PUT','/api/admin/users/4/role',{'role':'headman','class_name':'11А'},uid=2)
  await headman_bot.link_class_chat(message,CommandObject(prefix='/',command='class_link',args=token['code']))
  assert 'недействителен' in message.answer.call_args.args[0]
 # Group scheduling starts even when the personal-notification worker is occupied.
 import features
 group_started=asyncio.Event();stopped=[]
 async def blocked_maintenance():
  try:await asyncio.Event().wait()
  finally:stopped.append('personal')
 async def independent_groups():
  group_started.set()
  try:await asyncio.Event().wait()
  finally:stopped.append('groups')
 with patch.object(features,'maintenance_loop',blocked_maintenance),patch.object(headman_bot,'class_group_loop',independent_groups):
  async with main.lifespan(main.app):await asyncio.wait_for(group_started.wait(),2)
 assert set(stopped)=={'personal','groups'}
 await engine.dispose()
 print('PASS: headman frozen class scope, role revocation, token ownership, dated/weekly conflicts, menus/individual tables, native named polls, concurrent send deduplication, ordered retractions, membership/ban checks, safe retry and uncertain-send protection, backup inclusion')
asyncio.run(run())
