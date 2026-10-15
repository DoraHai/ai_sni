"""Customer identity for SEO confirmation and human conversation."""

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.models.module_workspace import GeoProject
from app.models.role import Role
from app.models.seo import SeoSiteAdvisorAssignment
from app.models.user import User
from app.security.auth import AuthContext


def is_customer_account(ctx, user, assignments, tenant_id: int, *, role=None,
                        geo_assignment=False) -> bool:
    """A tenant-bound viewer with no internal editing, administration or advisor history."""
    permissions = (role.permissions or {}) if role else {}
    return bool(
        ctx.user_id is not None
        and not ctx.is_superadmin
        and user is not None
        and user.id == ctx.user_id
        and user.is_active
        and user.tenant_id == tenant_id
        and ctx.tenant_id == tenant_id
        and role is not None and role.is_system and role.name == "品牌方客户"
        and ctx.can_view("seo.content")
        and permissions.get("seo.content") in {"view", "edit"}
        and not any(level == "edit" and (key.startswith("settings.") or
                    key.endswith(".content")) for key, level in permissions.items())
        and not any(level == "edit" and (key.startswith("settings.") or
                    key.endswith(".content")) for key, level in ctx.permissions.items())
        and not assignments and not geo_assignment
    )


async def customer_account_for_tenant(session, ctx, tenant_id: int,
                                      *, user_id: int | None = None, lock: bool = False) -> bool:
    actor_id = ctx.user_id if user_id is None else user_id
    if actor_id is None or (user_id is None and (
        ctx.tenant_id != tenant_id or ctx.is_superadmin
        or any(level == "edit" and (key.startswith("settings.") or key.endswith(".content"))
               for key, level in ctx.permissions.items())
    )):
        return False
    user_query = select(User).where(User.id == actor_id)
    user = await session.scalar(user_query.with_for_update(read=True) if lock else user_query)
    if user is None or user.tenant_id != tenant_id:
        return False
    role = await session.get(Role, user.role_id, **({"with_for_update": {"read": True}} if lock else {}))
    if role is None or not role.is_system or role.name != "品牌方客户":
        return False
    assignment_query = select(SeoSiteAdvisorAssignment.id).where(
        SeoSiteAdvisorAssignment.advisor_user_id == actor_id)
    assignments = list(await session.scalars(
        assignment_query.with_for_update(read=True) if lock else assignment_query))
    try:
        async with session.begin_nested():
            geo_query = select(GeoProject.id).where(
                GeoProject.project_settings["geo_service_plan"]["advisor_user_id"].as_string() == str(actor_id)
            ).limit(1)
            geo_assignment = await session.scalar(
                geo_query.with_for_update(read=True) if lock else geo_query)
    except DBAPIError:
        return False  # Missing or incompatible GEO schema must fail closed.
    if user_id is not None:
        permissions = (role.permissions or {}) if role else {}
        ctx = AuthContext(actor_id, user.username, role.name if role else "", tenant_id, permissions)
    return is_customer_account(ctx, user, assignments, tenant_id, role=role,
                               geo_assignment=bool(geo_assignment))
