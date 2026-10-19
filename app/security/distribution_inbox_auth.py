"""Personnel-only inbox admission, separate from tenant/business permissions."""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException

from app.database import get_session
from app.distribution_inbox_protocol import ProtocolError
from app.models.role import Role
from app.models.user import User
from app.security.advisor_seo_scope import is_advisor_role
from app.security.auth import require_auth


def is_inbox_admin(user, role):
    return bool(user and user.is_active and role and role.is_system and role.name == '管理员')


async def require_inbox_identity(ctx=Depends(require_auth), session=Depends(get_session)):
    def forbidden():
        error = ProtocolError('INBOX_FORBIDDEN', 403)
        raise HTTPException(error.status, error.detail)
    if ctx.user_id is None or ctx.is_superadmin:
        forbidden()
    user = await session.get(User, ctx.user_id, populate_existing=True)
    if user is None or not user.is_active:
        forbidden()
    locked = user.locked_until
    if locked is not None:
        if locked.tzinfo is None:
            locked = locked.replace(tzinfo=timezone.utc)
        if locked > datetime.now(timezone.utc):
            forbidden()
    role = await session.get(Role, user.role_id, populate_existing=True)
    if is_inbox_admin(user, role) and ctx.scope_kind is None:
        return ctx
    # require_auth already verified aud=advisor-session for this scope, with
    # signature, expiry, active account and current advisor role from the DB.
    if is_advisor_role(role) and ctx.is_advisor and ctx.scope_kind == 'advisor_identity':
        return ctx
    forbidden()
