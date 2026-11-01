"""Private in-app notifications share durable events with the Telegram outbox."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update

from access import access_allowed
from database import get_db
from models import AccessPolicy, Notification, User
from config import settings


async def queue_inbox(db, user_id, kind, message, event_key, link=None):
    """Insert once in the caller's transaction; never send unsolicited Telegram DMs."""
    user = await db.get(User, user_id)
    if not user or not await access_allowed(db, user):
        return
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    await db.execute(insert(Notification).values(
        user_id=user_id, kind=kind, text=message, link=link,
        dedup_key=f'inbox:{event_key}:{user_id}', status='inbox',
    ).on_conflict_do_nothing(index_elements=['dedup_key']))


async def publication_notices(db, post):
    query=select(User.id).where(User.is_banned.is_(False),User.id!=post.author_id)
    policy=await db.get(AccessPolicy,1)
    if policy and policy.invites_required:
        query=query.where(or_(User.is_member.is_(True),User.id.in_(settings.admin_ids)))
    ids=list(await db.scalars(query))
    if db.bind.dialect.name=='postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    for offset in range(0,len(ids),100):
        rows=[{'user_id':uid,'kind':'news','text':f'Новая публикация: {post.title}',
               'link':f'news:{post.id}','dedup_key':f'inbox:published:{post.id}:{uid}','status':'inbox'}
              for uid in ids[offset:offset+100]]
        await db.execute(insert(Notification).values(rows).on_conflict_do_nothing(index_elements=['dedup_key']))


class ReadRequest(BaseModel):
    through_id: int = Field(ge=1)


def install_inbox(app, require_identity, require_active):
    router = APIRouter(prefix='/api/me/notifications')

    async def student(x_telegram_init_data: Optional[str] = Header(None), db=Depends(get_db)):
        return await require_active(require_identity(x_telegram_init_data), db)

    def visible(user):
        # Cancelled reminders refer to lessons that no longer take place.
        return (Notification.user_id == user.id, Notification.status != 'cancelled')

    @router.get('')
    async def listing(before_id: Optional[int] = Query(None, ge=1), limit: int = Query(30, ge=1, le=100),
                      user=Depends(student), db=Depends(get_db)):
        query = select(Notification).where(*visible(user))
        if before_id:
            query = query.where(Notification.id < before_id)
        rows = (await db.scalars(query.order_by(Notification.id.desc()).limit(limit + 1))).all()
        unread = await db.scalar(select(func.count()).select_from(Notification).where(*visible(user), Notification.read_at.is_(None)))
        latest = await db.scalar(select(func.max(Notification.id)).where(*visible(user)))
        return {'items': [{'id': row.id, 'kind': row.kind, 'text': row.text, 'link': row.link,
                           'read': row.read_at is not None, 'created_at': row.created_at.isoformat()}
                          for row in rows[:limit]], 'unread': unread, 'latest_id': latest,
                'next_cursor': rows[limit - 1].id if len(rows) > limit else None}

    @router.put('/read')
    async def read_all(payload: ReadRequest, user=Depends(student), db=Depends(get_db)):
        # Only events already seen in the listing; a concurrent new event stays unread.
        await db.execute(update(Notification).where(*visible(user), Notification.id <= payload.through_id,
                                                   Notification.read_at.is_(None)).values(read_at=datetime.now(timezone.utc)))
        await db.commit()
        return {'ok': True}

    @router.put('/{notification_id}/read')
    async def read_one(notification_id: int, user=Depends(student), db=Depends(get_db)):
        row = await db.scalar(select(Notification).where(*visible(user), Notification.id == notification_id))
        if not row:
            raise HTTPException(404, 'Уведомление не найдено')
        if row.read_at is None:
            row.read_at = datetime.now(timezone.utc)
            await db.commit()
        return {'ok': True}

    app.include_router(router)
