"""Date-specific timetables, invitations, editorial roles and private news drafts."""
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from access import access_allowed, configured_admin, require_school_access
from config import CLASS_PROFILES_MAP
from database import engine, get_db
from features import LessonRow, ScheduleRequest, parse_schedule, lesson_dict
from models import AccessPolicy, ClassLinkToken, DatedSchedule, NewsDraft, NewsPost, Notification, SchoolInvite, User, UserPreferences
from timetable import effective_lessons, lesson_timeline

TZ = ZoneInfo('Asia/Yekaterinburg')


async def write_lock(db):
    if engine.dialect.name == 'sqlite':
        await db.execute(text('BEGIN IMMEDIATE'))
    else:
        await db.execute(text('SELECT pg_advisory_xact_lock(160025)'))


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def row_revision(rows, note='', overridden=False):
    return hashlib.sha256(json.dumps([rows,note,overridden],sort_keys=True,ensure_ascii=False).encode()).hexdigest()


async def date_payload(db, cls, day):
    override=await db.scalar(select(DatedSchedule).where(DatedSchedule.class_name==cls,DatedSchedule.lesson_date==day))
    rows=[lesson_dict(row) for row in await effective_lessons(db,day.weekday(),cls,day)]
    note=override.note if override else ''
    return {'class_name':cls,'date':day.isoformat(),'rows':rows,'note':note,'is_override':override is not None,
            'base_revision':row_revision(rows,note,override is not None)}


class DateRequest(BaseModel):
    class_name: str
    date: date
    rows: list[LessonRow] = Field(max_length=100)
    note: str = Field('',max_length=255)
    base_revision: str = Field(pattern=r'^[a-f0-9]{64}$')


class InviteRequest(BaseModel):
    label: str = Field(min_length=1,max_length=80)
    max_uses: int = Field(1,ge=1,le=1000)
    days: int = Field(7,ge=1,le=90)


class RedeemRequest(BaseModel):
    code: str = Field(min_length=10,max_length=80)


class PolicyRequest(BaseModel):
    invites_required: bool


class RoleRequest(BaseModel):
    role: Literal['student','editor','headman']
    class_name: Optional[str] = None


class DraftRequest(BaseModel):
    title: str = Field('',max_length=255)
    content: str = Field('',max_length=20000)
    is_anonymous: bool = False
    revision: str = Field('',max_length=32)


class PinRequest(BaseModel):
    pinned: bool


async def change_date_schedule(payload,db,cache_clear,reset=False,locked=False):
    if not locked:await write_lock(db)
    if payload.class_name not in CLASS_PROFILES_MAP:raise HTTPException(422,'Выберите существующий класс')
    if payload.date.weekday()==6 and payload.rows:raise HTTPException(422,'Воскресенье — выходной. Выберите учебный день.')
    rows=parse_schedule(ScheduleRequest(class_name=payload.class_name,rows=payload.rows))
    if any(row.day_of_week!=payload.date.weekday() for row in rows):raise HTTPException(422,'День урока должен совпадать с выбранной датой')
    old=await date_payload(db,payload.class_name,payload.date)
    if not hmac.compare_digest(old['base_revision'],payload.base_revision):raise HTTPException(409,'Расписание изменилось. Загрузите дату заново.')
    record=await db.scalar(select(DatedSchedule).where(DatedSchedule.class_name==payload.class_name,DatedSchedule.lesson_date==payload.date))
    if reset:
        if record:await db.delete(record)
    else:
        if not record:
            record=DatedSchedule(class_name=payload.class_name,lesson_date=payload.date);db.add(record)
        record.rows_json=json.dumps([row.model_dump() for row in rows],ensure_ascii=False)
        record.note=payload.note.strip()
    users=(await db.scalars(select(User).where(User.class_name==payload.class_name))).all()
    notices=(await db.scalars(select(Notification).where(Notification.status=='pending',Notification.dedup_key.like(f'lesson:{payload.date}:%')))).all()
    ids={user.id for user in users}
    for notice in notices:
        if notice.user_id in ids:notice.status='cancelled'
    change_id=uuid.uuid4().hex
    for user in users:
        pref=await db.get(UserPreferences,user.id)
        if pref and pref.schedule_changes and await access_allowed(db,user):
            db.add(Notification(user_id=user.id,dedup_key=f'date:{change_id}:{user.id}',text=f'📅 Расписание {payload.class_name} на {payload.date:%d.%m.%Y} обновлено. '+('Восстановлено обычное расписание.' if reset else payload.note.strip() or 'Проверьте замены в приложении.')))
    await db.commit();cache_clear('sched:')
    return await date_payload(db,payload.class_name,payload.date)


def install_community(app, require_identity, require_admin, require_editor, cache_clear, rate_limit):
    router=APIRouter()
    async def admin(x_telegram_init_data: Optional[str]=Header(None),db=Depends(get_db)):
        return await require_admin(x_telegram_init_data=x_telegram_init_data,db=db)
    async def editor(x_telegram_init_data: Optional[str]=Header(None),db=Depends(get_db)):
        return await require_editor(x_telegram_init_data=x_telegram_init_data,db=db)
    async def student(x_telegram_init_data: Optional[str]=Header(None),db=Depends(get_db)):
        identity=require_identity(x_telegram_init_data)
        user=await db.get(User,int(identity['id']))
        if not user or user.is_banned:raise HTTPException(403,'Доступ ограничен')
        await require_school_access(db,user)
        return user

    @router.get('/api/admin/schedule/date')
    async def get_date(class_name: str,date: date,actor=Depends(admin),db=Depends(get_db)):
        if class_name not in CLASS_PROFILES_MAP:raise HTTPException(422,'Выберите существующий класс')
        return await date_payload(db,class_name,date)

    @router.put('/api/admin/schedule/date')
    async def put_date(payload:DateRequest,actor=Depends(admin),db=Depends(get_db)):
        return await change_date_schedule(payload,db,cache_clear)

    @router.post('/api/admin/schedule/date/reset')
    async def reset_date(payload:DateRequest,actor=Depends(admin),db=Depends(get_db)):
        return await change_date_schedule(payload,db,cache_clear,True)

    @router.get('/api/me/next-lesson')
    async def next_lesson(user=Depends(student),db=Depends(get_db)):
        now=datetime.now(TZ)
        if not user.class_name:return {"now":now.isoformat(),"current":None,"next":None,"class_name":None}
        current=None;upcoming=None
        for offset in range(8):
            day=now.date()+timedelta(days=offset)
            if day.weekday()==6:continue
            timeline=await lesson_timeline(db,day.weekday(),user.class_name,user.profile_name,user.subgroup,day)
            for item in timeline:
                start=datetime.combine(day,datetime.strptime(item['start'],'%H:%M').time(),TZ)
                end=datetime.combine(day,datetime.strptime(item['end'],'%H:%M').time(),TZ)
                data={'date':day.isoformat(),'start_time':item['start'],'end_time':item['end'],
                      'minutes_until':max(0,int((start-now).total_seconds()//60)),
                      'minutes_left':max(0,int((end-now).total_seconds()//60)),
                      'lessons':[{'subject':row.subject,'cabinet':row.cabinet,'teacher_name':row.teacher_name} for row in item['lessons']]}
                if start<=now<end:current=data
                if start>now and upcoming is None:upcoming=data
            if upcoming:break
        return {'now':now.isoformat(),'current':current,'next':upcoming,'class_name':user.class_name}

    @router.get('/api/admin/access')
    async def get_access(actor=Depends(admin),db=Depends(get_db)):
        policy=await db.get(AccessPolicy,1)
        invites=(await db.scalars(select(SchoolInvite).order_by(SchoolInvite.id.desc()).limit(100))).all()
        return {'invites_required':bool(policy and policy.invites_required),'invites':[
            {'id':row.id,'label':row.label,'max_uses':row.max_uses,'uses':row.uses,'expires_at':utc(row.expires_at).isoformat(),'revoked':row.revoked} for row in invites]}

    @router.put('/api/admin/access')
    async def put_access(payload:PolicyRequest,actor=Depends(admin),db=Depends(get_db)):
        await write_lock(db)
        policy=await db.get(AccessPolicy,1)
        if not policy:policy=AccessPolicy(id=1);db.add(policy)
        if payload.invites_required and not policy.invites_required:
            for user in (await db.scalars(select(User))).all():
                user.is_member=True
        policy.invites_required=payload.invites_required
        await db.commit()
        return {'invites_required':policy.invites_required}

    @router.post('/api/admin/invites',status_code=201)
    async def create_invite(payload:InviteRequest,actor=Depends(admin),db=Depends(get_db)):
        if not payload.label.strip():raise HTTPException(422,'Укажите название приглашения')
        code=secrets.token_urlsafe(18)
        record=SchoolInvite(code_hash=hashlib.sha256(code.encode()).hexdigest(),label=payload.label.strip(),max_uses=payload.max_uses,
                            expires_at=datetime.now(timezone.utc)+timedelta(days=payload.days),created_by=actor)
        db.add(record);await db.commit()
        return {'id':record.id,'code':code,'expires_at':utc(record.expires_at).isoformat()}

    @router.post('/api/admin/invites/{invite_id}/revoke')
    async def revoke_invite(invite_id:int,actor=Depends(admin),db=Depends(get_db)):
        await write_lock(db)
        record=await db.get(SchoolInvite,invite_id)
        if not record:raise HTTPException(404,'Приглашение не найдено')
        record.revoked=True;await db.commit()
        return {'revoked':True}

    @router.post('/api/access/redeem')
    async def redeem(payload:RedeemRequest,x_telegram_init_data:Optional[str]=Header(None),db=Depends(get_db)):
        identity=require_identity(x_telegram_init_data)
        rate_limit(f'invite:{identity["id"]}',10,600)
        await write_lock(db)
        user=await db.get(User,int(identity['id']))
        if not user or user.is_banned:raise HTTPException(403,'Доступ ограничен')
        if user.is_member:return {'access_allowed':True}
        record=await db.scalar(select(SchoolInvite).where(SchoolInvite.code_hash==hashlib.sha256(payload.code.strip().encode()).hexdigest()))
        if not record or record.revoked or record.uses>=record.max_uses or utc(record.expires_at)<=datetime.now(timezone.utc):
            raise HTTPException(400,'Код недействителен, истёк или уже использован')
        record.uses+=1;user.is_member=True
        await db.commit()
        return {'access_allowed':True}

    @router.put('/api/admin/users/{user_id}/role')
    async def role(user_id:int,payload:RoleRequest,actor=Depends(admin),db=Depends(get_db)):
        await write_lock(db)
        user=await db.get(User,user_id)
        if not user:raise HTTPException(404,'Пользователь не найден')
        if configured_admin(user):raise HTTPException(422,'Администраторы назначаются в настройках хостинга')
        scope=user.class_name
        if payload.role=='headman' and payload.class_name and payload.class_name != scope:
            raise HTTPException(422,'Класс старосты определяется классом, выбранным при регистрации ученика')
        if payload.role=='headman' and scope not in CLASS_PROFILES_MAP:raise HTTPException(422,'Укажите класс старосты')
        if user.role != payload.role or user.headman_class_name != (scope if payload.role=='headman' else None):
            for token in (await db.scalars(select(ClassLinkToken).where(ClassLinkToken.created_by==user.id, ClassLinkToken.used_at.is_(None)))).all():
                token.used_at=datetime.now(timezone.utc)
        user.role=payload.role
        user.headman_class_name=scope if payload.role=='headman' else None
        if payload.role in ('editor','headman'):user.is_member=True
        await db.commit()
        return {'id':user.id,'role':user.role,'headman_class_name':user.headman_class_name}

    @router.put('/api/news/{post_id}/pin')
    async def pin(post_id:int,payload:PinRequest,actor=Depends(editor),db=Depends(get_db)):
        await write_lock(db)
        post=await db.get(NewsPost,post_id)
        if not post or post.status!='approved':raise HTTPException(404,'Опубликованная новость не найдена')
        if payload.pinned and not post.is_pinned:
            pinned=(await db.scalars(select(NewsPost.id).where(NewsPost.is_pinned.is_(True),NewsPost.status=='approved'))).all()
            if len(pinned)>=3:raise HTTPException(422,'Можно закрепить до трёх объявлений. Снимите одно закрепление.')
        post.is_pinned=payload.pinned;await db.commit()
        return {'id':post.id,'is_pinned':post.is_pinned}

    @router.get('/api/me/news-draft')
    async def draft(user=Depends(student),db=Depends(get_db)):
        row=await db.get(NewsDraft,user.id)
        return {'title':row.title if row else '', 'content':row.content if row else '',
                'is_anonymous':row.is_anonymous if row else False,'revision':row.revision if row else ''}

    @router.put('/api/me/news-draft')
    async def save_draft(payload:DraftRequest,x_telegram_init_data:Optional[str]=Header(None),db=Depends(get_db)):
        identity=require_identity(x_telegram_init_data)
        await write_lock(db)
        user=await db.get(User,int(identity['id']))
        if not user or user.is_banned:raise HTTPException(403,'Доступ ограничен')
        await require_school_access(db,user)
        row=await db.get(NewsDraft,user.id)
        current=row.revision if row else ''
        if not hmac.compare_digest(current,payload.revision):raise HTTPException(409,'Черновик изменён на другом устройстве. Скопируйте текст и откройте редактор заново.')
        if not row:row=NewsDraft(user_id=user.id);db.add(row)
        row.title=payload.title;row.content=payload.content;row.is_anonymous=payload.is_anonymous;row.revision=uuid.uuid4().hex
        await db.commit()
        return {'revision':row.revision}

    app.include_router(router)
