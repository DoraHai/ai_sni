"""Shared validation contract for advisor switch JWTs in SEM, SEO and GEO."""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError

from app.models.advisor_account import AdvisorAccountLink
from app.models.role import Role
from app.models.user import User
from app.config import get_settings


def _invalid():
    raise HTTPException(401, "切换登录凭证无效或关联已变化")


def _advisor_role(role):
    if role is None or (role.is_system and role.name == "管理员"):
        return False
    permissions = role.permissions or {}
    return (not any(key.startswith("settings.") and level == "edit"
                    for key, level in permissions.items())
            and ((permissions.get("seo.site") == "edit" and permissions.get("seo.content") == "edit")
                 or (permissions.get("geo.assets") == "edit" and permissions.get("geo.content") == "edit")))


async def validate_switch_claims(session, payload: dict, target: User) -> None:
    """Fail closed for malformed, expired or revoked derived sessions."""
    if "via" not in payload:
        return
    if not get_settings().advisor_legacy_account_switch_enabled:
        _invalid()
    if payload.get("via") != "advisor_switch":
        _invalid()
    try:
        if type(payload["src"]) is not int or type(payload["root_src"]) is not int:
            _invalid()
        source_id = payload["src"]
        root_id = payload["root_src"]
        group_id = str(payload["grp"])
        auth_exp = payload["auth_exp"]
        exp = payload["exp"]
        if (type(auth_exp) is not int or type(exp) is not int
                or source_id <= 0 or root_id <= 0 or not group_id
                or exp > auth_exp or auth_exp <= datetime.now(timezone.utc).timestamp()):
            _invalid()
    except (KeyError, TypeError, ValueError):
        _invalid()
    try:
        users = {target.id: target}
        for user_id in {source_id, root_id} - {target.id}:
            users[user_id] = await session.get(User, user_id)
        links = {user_id: await session.get(AdvisorAccountLink, user_id) for user_id in users}
        roles = {user_id: await session.get(Role, user.role_id) if user else None
                 for user_id, user in users.items()}
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "42P01" or getattr(exc.orig, "pgcode", None) == "42P01":
            _invalid()
        raise
    if (source_id == target.id or users[source_id] is None
            or users[source_id].tenant_id == target.tenant_id):
        _invalid()
    for user_id, user in users.items():
        link = links[user_id]
        if (user is None or not user.is_active or user.tenant_id is None
                or not _advisor_role(roles[user_id]) or link is None
                or link.tenant_id != user.tenant_id or str(link.group_id) != group_id):
            _invalid()
