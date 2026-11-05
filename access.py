"""School access is separate from Telegram identity and editorial permissions."""
from fastapi import HTTPException
from config import settings, CLASS_PROFILES_MAP
from models import AccessPolicy


def configured_admin(user):
    return user.id in settings.admin_ids or bool(user.username and user.username.lower().lstrip('@') in settings.admin_usernames)


async def access_allowed(db, user):
    if user.is_banned or user.registration_reset:
        return False
    policy = await db.get(AccessPolicy, 1)
    return not (policy and policy.invites_required) or user.is_member or configured_admin(user)


async def require_school_access(db, user):
    if not registration_complete(user):
        raise HTTPException(409, 'Для входа заполните имя, фамилию, класс и профиль.')
    if not await access_allowed(db, user):
        raise HTTPException(403, 'Для входа нужен код приглашения. Откройте приложение и введите код от администратора.')


def registration_complete(user):
    return bool(user and not user.registration_reset and (user.first_name or '').strip() and (user.last_name or '').strip()
                and user.profile_name in CLASS_PROFILES_MAP.get(user.class_name, []))
