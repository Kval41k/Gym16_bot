"""Record committed model changes, with identity supplied by verified requests or Telegram."""
import json
from contextvars import ContextVar
from datetime import date, datetime

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from models import AuditLog

audit_actor = ContextVar("audit_actor", default=None)
SECTIONS = {
    "users": "profile", "user_preferences": "profile", "lessons": "schedule",
    "bell_schedules": "schedule", "news_posts": "news", "news_reviews": "news",
    "comments": "comments", "reactions": "reactions", "ege_materials": "ege",
    "material_progress": "ege",
}


def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


@event.listens_for(Session, "after_flush")
def record_changes(session, flush_context):
    actor = audit_actor.get()
    if not actor:
        return
    for action, objects in (("create", session.new), ("update", session.dirty), ("delete", session.deleted)):
        for obj in list(objects):
            entity = getattr(obj, "__tablename__", "")
            if entity not in SECTIONS:
                continue
            state = inspect(obj)
            details = {}
            for column in state.mapper.column_attrs:
                key = column.key
                if key in ("created_at", "updated_at"):
                    continue
                value = json_value(getattr(obj, key, None))
                if action == "update":
                    history = state.attrs[key].history
                    if not history.has_changes():
                        continue
                    details[key] = {"before": json_value(history.deleted[0]) if history.deleted else None, "after": value}
                else:
                    details[key] = value
            if not details:
                continue
            primary_key = ":".join(str(getattr(obj, col.key)) for col in state.mapper.primary_key)
            session.add(AuditLog(
                actor_id=int(actor["id"]),
                actor_name=" ".join(filter(None, (actor.get("first_name"), actor.get("last_name")))) or str(actor["id"]),
                actor_username=actor.get("username"), source=actor.get("source", "app"),
                section=SECTIONS[entity], action=action, entity=entity, entity_id=primary_key,
                details=json.dumps(details, ensure_ascii=False, default=str),
            ))
