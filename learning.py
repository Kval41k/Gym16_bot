"""Reviewed study catalog and server-checked, per-account practice with mistake review."""
import hashlib
import json
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Literal, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from access import require_school_access
from audit import audit_actor
from community import TZ, write_lock, utc
from database import async_session, get_db
from models import AppliedDataUpdate, EgeMaterial, EgeSubject, PracticeProgress, PracticeSession, User

ROOT=Path(__file__).parent
CATALOG=json.loads((ROOT/'data/ege_2027.json').read_text())
BANK=json.loads((ROOT/'data/practice_2027.json').read_text())['questions']
QUESTIONS={q['id']:q for q in BANK}
TOPICS={(row['subject_code'],row['task_number']):row for row in CATALOG['topics']}


async def apply_learning_catalog():
    token=audit_actor.set({'id':0,'first_name':'Учебный каталог ЕГЭ-2027','source':'curriculum'})
    try:
        async with async_session() as db:
            await write_lock(db)
            if await db.get(AppliedDataUpdate,CATALOG['version']):return False
            # Preserve manual materials and progress; move only the old numbered topics once.
            math_map={**{i:i for i in range(1,6)},6:7,7:8,8:9,9:10,10:11,11:12,12:17,13:14,14:15,15:16,16:13,17:18,18:19,19:20}
            russian_map={22:23,23:24,24:25,25:26,26:22}
            existing=(await db.scalars(select(EgeMaterial))).all()
            for material in existing:
                if material.source_key:continue
                if material.subject_code=='math':
                    if material.task_number==20:material.is_archived=True
                    else:material.task_number=math_map.get(material.task_number,material.task_number)
                elif material.subject_code=='russian':material.task_number=russian_map.get(material.task_number,material.task_number)
            for topic in CATALOG['topics']:
                key=f'ege-2027:{topic["subject_code"]}:{topic["task_number"]}'
                if not any(row.source_key==key for row in existing):
                    db.add(EgeMaterial(subject_code=topic['subject_code'],task_number=topic['task_number'],title=topic['title'],theory=topic['theory'],link_url=topic['source_url'],source_key=key))
            subject=await db.scalar(select(EgeSubject).where(EgeSubject.code=='math'))
            if subject:subject.name='Профильная математика';subject.tasks_count=20
            db.add(AppliedDataUpdate(revision=CATALOG['version']))
            await db.commit()
            return True
    finally:audit_actor.reset(token)


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC',value).strip().casefold().replace('ё','е').split())


def check_answer(question,answer):
    value=normalized(answer)
    if question['kind']=='number':
        # Exact arithmetic only; never evaluate a user-supplied expression.
        value=value.replace(',','.').replace(' ','').replace('−','-')
        if len(value)>100 or not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:/[+-]?\d+)?',value):return False
        try:return Fraction(value)==Fraction(question['answer'])
        except (ValueError,ZeroDivisionError):return False
    return value==normalized(question['answer'])


def feedback(question,session):
    answer=question['answer']
    if question['kind']=='choice':answer=next(option['text'] for option in question['options'] if option['id']==answer)
    return {'correct':session.correct,'correct_answer':answer,'explanation':question['explanation'],
            'repeat':not session.correct,'notice':'Проверен учебный шаг. Это не экспертная оценка полного развёрнутого ответа.' if TOPICS[(question['subject_code'],question['task_number'])]['practice_scope']!='Учебные мини-задания по теме' else ''}


DAILY_TARGET=5


def daily_session_id(user_id,day,question_id,review):
    # Persist the assignment and original kind without a separate plan table.
    key=f'daily:{user_id}:{day}:{question_id}'.encode()
    return hashlib.sha256(key).hexdigest()[:31]+str(int(review))


async def daily_plan(db,user,now):
    day=now.astimezone(TZ).date().isoformat()
    ids={daily_session_id(user.id,day,q['id'],review):(q,review) for q in BANK for review in (False,True)}
    records={r.question_id:r for r in (await db.scalars(select(PracticeProgress).where(PracticeProgress.user_id==user.id))).all()}
    sessions=list((await db.scalars(select(PracticeSession).where(PracticeSession.user_id==user.id,PracticeSession.id.in_(ids)))).all())
    if not sessions:
        weak={topic:sum(r.mistakes for r in records.values() if not r.mastered and r.question_id in QUESTIONS and (QUESTIONS[r.question_id]['subject_code'],QUESTIONS[r.question_id]['task_number'])==topic) for topic in TOPICS}
        unseen=[q for q in BANK if q['id'] not in records]
        # Rotate equal-priority topics per pupil and day, prioritising weak topics.
        unseen.sort(key=lambda q:(-weak[(q['subject_code'],q['task_number'])],daily_session_id(user.id,day,q['id'],False)))
        due=[q for q in BANK if q['id'] in records and not records[q['id']].mastered and records[q['id']].mistakes and (not records[q['id']].next_review_at or utc(records[q['id']].next_review_at)<=now)]
        due.sort(key=lambda q:(-records[q['id']].mistakes,q['id']))
        selected=[(q,True) for q in due[:2]]
        selected.extend((q,False) for q in unseen[:DAILY_TARGET-len(selected)])
        selected.extend((q,True) for q in due[2:2+DAILY_TARGET-len(selected)])
        for q,review in selected:
            session=PracticeSession(id=daily_session_id(user.id,day,q['id'],review),user_id=user.id,question_id=q['id'],created_at=now)
            db.add(session);sessions.append(session)
        await db.flush()
    sessions.sort(key=lambda session:(not ids[session.id][1],session.id))
    entries=[]
    for session in sessions:
        q,review=ids[session.id]
        record=records.get(q['id'])
        done=bool(session.answered_at or (record and record.mastered))
        entries.append({'question_id':q['id'],'subject_code':q['subject_code'],'task_number':q['task_number'],
                        'title':TOPICS[(q['subject_code'],q['task_number'])]['title'],'review':review,
                        'done':done,'correct':session.correct if session.answered_at else True if done else None})
    return day,sessions,entries,records


class AnswerRequest(BaseModel):
    session_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    answer:str=Field(min_length=1,max_length=1000)


def install_learning(app,require_identity,require_active,require_editor,rate_limit):
    router=APIRouter()
    async def student(x_telegram_init_data:Optional[str]=Header(None),db=Depends(get_db)):
        return await require_active(require_identity(x_telegram_init_data),db)

    @router.get('/api/ege/catalog')
    async def catalog(user=Depends(student)):
        return {**{key:value for key,value in CATALOG.items() if key!='topics'},'topics':[
            {key:topic[key] for key in ('subject_code','task_number','title','source_url','practice_scope')} for topic in CATALOG['topics']]}

    @router.get('/api/admin/ege/archive')
    async def archive(x_telegram_init_data:Optional[str]=Header(None),db=Depends(get_db)):
        await require_editor(x_telegram_init_data=x_telegram_init_data,db=db)
        rows=(await db.scalars(select(EgeMaterial).where(EgeMaterial.is_archived.is_(True)))).all()
        return [{'id':row.id,'title':row.title,'theory':row.theory,'subject_code':row.subject_code,'task_number':row.task_number} for row in rows]

    @router.get('/api/me/practice/daily')
    async def daily(user=Depends(student),db=Depends(get_db)):
        rate_limit(f'practice-daily:{user.id}',90,60)
        await write_lock(db)
        now=datetime.now(timezone.utc)
        day,sessions,entries,records=await daily_plan(db,user,now)
        week_start=(now.astimezone(TZ).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=6)).astimezone(timezone.utc)
        boundaries=[week_start+timedelta(days=offset) for offset in range(8)]
        aggregates=[]
        for start,end in zip(boundaries,boundaries[1:]):
            in_day=(PracticeSession.answered_at>=start)&(PracticeSession.answered_at<end)
            aggregates.extend((func.count(PracticeSession.id).filter(in_day),
                               func.count(PracticeSession.id).filter(in_day,PracticeSession.correct.is_(True))))
        counts=(await db.execute(select(*aggregates).where(PracticeSession.user_id==user.id,
            PracticeSession.answered_at>=week_start,PracticeSession.answered_at<boundaries[-1]))).one()
        week=[{'date':start.astimezone(TZ).date().isoformat(),'answered':counts[2*i],'correct':counts[2*i+1]}
              for i,start in enumerate(boundaries[:-1])]
        weak=[]
        for topic in TOPICS:
            mistakes=[r for r in records.values() if r.question_id in QUESTIONS and not r.mastered and r.mistakes and (QUESTIONS[r.question_id]['subject_code'],QUESTIONS[r.question_id]['task_number'])==topic]
            if mistakes:weak.append({'subject_code':topic[0],'task_number':topic[1],'title':TOPICS[topic]['title'],'mistakes':sum(r.mistakes for r in mistakes),'remaining':len(mistakes)})
        weak.sort(key=lambda row:(-row['mistakes'],row['subject_code'],row['task_number']))
        await db.commit()
        return {'date':day,'timezone':str(TZ),'target':DAILY_TARGET,'items':entries,'completed':sum(e['done'] for e in entries),
                'correct':sum(e['correct'] is True for e in entries),'weak_topics':weak[:5],'week':week}

    @router.get('/api/me/practice/daily/next')
    async def daily_next(user=Depends(student),db=Depends(get_db)):
        rate_limit(f'practice-next:{user.id}',90,60)
        await write_lock(db)
        now=datetime.now(timezone.utc)
        day,sessions,entries,records=await daily_plan(db,user,now)
        stats={'total':len(entries),'mastered':sum(e['correct'] is True for e in entries),'mistakes':sum(e['correct'] is False for e in entries),'completed':sum(e['done'] for e in entries)}
        pending=next(((session,entry) for session,entry in zip(sessions,entries) if not entry['done']),None)
        if not pending:
            await db.commit()
            return {'question':None,'stats':stats,'message':'План на сегодня выполнен. Новые задания и повторение ошибок появятся завтра.' if entries else 'Все доступные задания решены или ошибки пока не готовы к повторению. Можно выбрать тему вручную.'}
        session,entry=pending
        # Opening a stable daily assignment renews the usual answer window.
        session.created_at=now
        await db.commit()
        q=QUESTIONS[session.question_id]
        return {'question':{key:q[key] for key in ('id','subject_code','task_number','kind','prompt','options')},'session_id':session.id,'stats':stats,
                'scope':TOPICS[(q['subject_code'],q['task_number'])]['practice_scope'],'review':entry['review'],'notice':'Повторение ошибки' if entry['review'] else 'Новое авторское учебное мини-задание, не официальный КИМ.'}

    @router.get('/api/me/practice/next')
    async def next_question(subject_code:Literal['math','russian'],task_number:int=Query(ge=1,le=27),
                            mode:Literal['all','mistakes']='all',user=Depends(student),db=Depends(get_db)):
        if (subject_code,task_number) not in TOPICS:raise HTTPException(422,'Такого задания нет в каталоге')
        rate_limit(f'practice-next:{user.id}',90,60)
        await write_lock(db)
        items=[q for q in BANK if q['subject_code']==subject_code and q['task_number']==task_number]
        progress={row.question_id:row for row in (await db.scalars(select(PracticeProgress).where(PracticeProgress.user_id==user.id,PracticeProgress.question_id.in_([q['id'] for q in items])))).all()}
        now=datetime.now(timezone.utc)
        mastered=sum(bool(progress.get(q['id']) and progress[q['id']].mastered) for q in items)
        remaining=[q for q in items if not progress.get(q['id']) or not progress[q['id']].mastered]
        mistakes=[q for q in remaining if progress.get(q['id']) and progress[q['id']].mistakes]
        unseen=[q for q in remaining if q['id'] not in progress]
        due=[q for q in mistakes if not progress[q['id']].next_review_at or utc(progress[q['id']].next_review_at)<=now]
        candidates=mistakes if mode=='mistakes' else unseen or due
        candidates=sorted(candidates,key=lambda q:(progress[q['id']].attempts if q['id'] in progress else 0, q['id']))
        stats={'total':len(items),'mastered':mastered,'mistakes':len(mistakes),'remaining':len(remaining)}
        if not candidates:
            return {'question':None,'stats':stats,'message':'Все учебные задачи этой темы решены правильно. Они больше не повторяются.' if not remaining else 'Новых задач нет. Можно повторить ошибки сейчас или вернуться к теории.' if mode=='all' else 'Нерешённых ошибок в этой теме нет.'}
        q=candidates[0]
        session=await db.scalar(select(PracticeSession).where(PracticeSession.user_id==user.id,PracticeSession.question_id==q['id'],PracticeSession.answered_at.is_(None),PracticeSession.created_at>=now-timedelta(minutes=30)).order_by(PracticeSession.created_at.desc()))
        if not session:
            session=PracticeSession(id=secrets.token_hex(16),user_id=user.id,question_id=q['id']);db.add(session);await db.commit()
        return {'question':{key:q[key] for key in ('id','subject_code','task_number','kind','prompt','options')},'session_id':session.id,'stats':stats,
                'scope':TOPICS[(subject_code,task_number)]['practice_scope'],'notice':'Авторское учебное мини-задание, не официальный КИМ.'}

    @router.post('/api/me/practice/answer')
    async def answer(payload:AnswerRequest,x_telegram_init_data:Optional[str]=Header(None),db=Depends(get_db)):
        identity=require_identity(x_telegram_init_data)
        rate_limit(f'practice-answer:{identity["id"]}',120,60)
        await write_lock(db)
        user=await require_active(identity,db)
        session=await db.get(PracticeSession,payload.session_id)
        if not session or session.user_id!=user.id:raise HTTPException(404,'Учебная попытка не найдена')
        q=QUESTIONS.get(session.question_id)
        if not q:raise HTTPException(410,'Задание обновлено. Откройте новую попытку.')
        if session.answered_at:return feedback(q,session)
        now=datetime.now(timezone.utc)
        if utc(session.created_at)<now-timedelta(minutes=30):raise HTTPException(409,'Попытка устарела. Откройте следующую задачу.')
        record=await db.get(PracticeProgress,(user.id,q['id']))
        if record and record.mastered:raise HTTPException(409,'Эта задача уже решена правильно. Откройте следующую.')
        if not record:
            record=PracticeProgress(user_id=user.id,question_id=q['id'],attempts=0,mistakes=0,mastered=False);db.add(record)
        record.attempts+=1
        session.answer=payload.answer;session.correct=check_answer(q,payload.answer);session.answered_at=now
        if session.correct:record.mastered=True;record.next_review_at=None
        else:record.mistakes+=1;record.next_review_at=now+timedelta(minutes=1)
        await db.commit()
        return feedback(q,session)

    @router.get('/api/me/practice/progress')
    async def progress(user=Depends(student),db=Depends(get_db)):
        records=(await db.scalars(select(PracticeProgress).where(PracticeProgress.user_id==user.id))).all()
        result={}
        for topic in TOPICS:
            subset=[row for row in records if row.question_id in QUESTIONS and (QUESTIONS[row.question_id]['subject_code'],QUESTIONS[row.question_id]['task_number'])==topic]
            result[f'{topic[0]}:{topic[1]}']={'mastered':sum(row.mastered for row in subset),'mistakes':sum(row.mistakes>0 and not row.mastered for row in subset),'attempts':sum(row.attempts for row in subset),'total':sum((q['subject_code'],q['task_number'])==topic for q in BANK)}
        return result
    app.include_router(router)
