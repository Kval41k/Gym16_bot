"""Private reports with retained context and explicit administrative resolution."""
import json
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from access import require_school_access
from database import engine, get_db
from models import Comment, ContentReport, NewsPost, User

REASONS = {'spam': 'Спам', 'abuse': 'Оскорбления или травля', 'unsafe': 'Опасный контент',
           'privacy': 'Личные данные', 'other': 'Другое'}




class ReportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_type: Literal['news', 'comment']
    target_id: int = Field(gt=0)
    reason: Literal['spam', 'abuse', 'unsafe', 'privacy', 'other']
    details: str = Field('', max_length=1000)


class ResolutionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['handled', 'dismissed']
    resolution: str = Field(min_length=1, max_length=1000)


async def report_lock(db):
    if engine.dialect.name == 'sqlite':
        await db.execute(text('BEGIN IMMEDIATE'))
    else:
        await db.execute(text('SELECT pg_advisory_xact_lock(160027)'))


def report_data(row, context=False):
    result = {key: getattr(row, key) for key in ('id', 'target_type', 'target_id', 'post_id', 'reason', 'details',
                                               'status', 'resolution', 'created_at', 'resolved_at')}
    if context:
        result['context'] = json.loads(row.context_json)
    return result


def install_reports(app, require_identity, require_admin, rate_limit, queue_inbox=None):
    router = APIRouter()

    async def student(x_telegram_init_data: Optional[str] = Header(None), db=Depends(get_db)):
        identity = require_identity(x_telegram_init_data)
        user = await db.get(User, int(identity['id']))
        if not user or user.is_banned:
            raise HTTPException(403, 'Доступ ограничен')
        await require_school_access(db, user)
        return user

    async def admin(x_telegram_init_data: Optional[str] = Header(None), actor=Depends(student), db=Depends(get_db)):
        await require_admin(x_telegram_init_data=x_telegram_init_data, db=db)
        return actor

    @router.post('/api/reports', status_code=201)
    async def create_report(payload: ReportRequest, actor=Depends(student), db=Depends(get_db)):
        rate_limit(f'reports:{actor.id}', 20, 600)
        details = payload.details.strip()
        if payload.reason == 'other' and not details:
            raise HTTPException(422, 'Укажите причину жалобы')
        await report_lock(db)
        duplicate = await db.scalar(select(ContentReport.id).where(ContentReport.reporter_id == actor.id,
                                   ContentReport.target_type == payload.target_type, ContentReport.target_id == payload.target_id))
        if duplicate:
            raise HTTPException(409, 'Вы уже отправили жалобу на эту запись')
        count = await db.scalar(select(func.count(ContentReport.id)).where(ContentReport.reporter_id == actor.id,
                               ContentReport.created_at >= datetime.now(timezone.utc) - timedelta(hours=1)))
        if count >= 10:
            raise HTTPException(429, 'Слишком много жалоб. Попробуйте позже.')
        comment = await db.get(Comment, payload.target_id) if payload.target_type == 'comment' else None
        post_id = comment.post_id if comment else payload.target_id if payload.target_type == 'news' else None
        post = await db.get(NewsPost, post_id) if post_id else None
        if not post or post.status != 'approved':
            raise HTTPException(404, 'Запись недоступна')
        context = {'title': post.title, 'content': post.content,
                   'author_name': 'Анонимно' if post.is_anonymous else post.author_name}
        if comment:
            context['comment'] = {'text': comment.text, 'author_name': comment.author_name}
        row = ContentReport(reporter_id=actor.id, target_type=payload.target_type, target_id=payload.target_id,
                            post_id=post.id, reason=payload.reason, details=details,
                            context_json=json.dumps(context, ensure_ascii=False), status='pending')
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(409, 'Вы уже отправили жалобу на эту запись')
        return {'id': row.id, 'status': row.status}

    @router.get('/api/me/reports')
    async def own_reports(actor=Depends(student), db=Depends(get_db), offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
        rows = (await db.scalars(select(ContentReport).where(ContentReport.reporter_id == actor.id)
                                .order_by(ContentReport.id.desc()).offset(offset).limit(limit))).all()
        return [report_data(row) for row in rows]

    @router.get('/api/admin/reports')
    async def list_reports(status: Literal['pending', 'handled', 'dismissed'] = 'pending', actor=Depends(admin),
                           db=Depends(get_db), offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
        rows = (await db.scalars(select(ContentReport).where(ContentReport.status == status)
                                .order_by(ContentReport.id.asc()).offset(offset).limit(limit))).all()
        return [report_data(row, context=True) for row in rows]

    @router.get('/api/admin/reports/{report_id}')
    async def get_report(report_id: int, actor=Depends(admin), db=Depends(get_db)):
        row = await db.get(ContentReport, report_id)
        if not row:
            raise HTTPException(404, 'Жалоба не найдена')
        result = report_data(row, context=True)
        post = await db.get(NewsPost, row.post_id)
        comment = await db.get(Comment, row.target_id) if row.target_type == 'comment' else None
        result['target_available'] = bool(post and post.status == 'approved' and (row.target_type == 'news' or comment))
        return result

    @router.post('/api/admin/reports/{report_id}/resolve')
    async def resolve_report(report_id: int, payload: ResolutionRequest, actor=Depends(admin), db=Depends(get_db)):
        note = payload.resolution.strip()
        if not note:
            raise HTTPException(422, 'Укажите результат рассмотрения')
        rate_limit(f'report-resolution:{actor.id}', 60, 60)
        await report_lock(db)
        row = await db.get(ContentReport, report_id)
        if not row:
            raise HTTPException(404, 'Жалоба не найдена')
        if row.status != 'pending':
            raise HTTPException(409, 'Жалоба уже рассмотрена')
        row.status, row.resolution = payload.status, note
        row.resolved_by, row.resolved_at = actor.id, datetime.now(timezone.utc)
        if queue_inbox and row.reporter_id:
            label = 'рассмотрена' if row.status == 'handled' else 'отклонена'
            await queue_inbox(db, row.reporter_id, 'report_result', f'Жалоба №{row.id} {label}. {note}',
                              f'report:{row.id}:resolved', link=None)
        await db.commit()
        return report_data(row)

    app.include_router(router)
