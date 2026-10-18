"""Recheck advisor authority before delivering a completed read or stream chunk."""
from datetime import datetime, timezone

from fastapi import HTTPException
from starlette.responses import JSONResponse


async def recheck_delivery(user_id, claims, tenant_id, menu_keys=frozenset()):
    from app.database import async_session_factory
    from app.models.user import User
    from app.module_scope import ensure_module_access
    from app.security.advisor_scope import account_locked, deny
    from app.security.auth import _build_context
    if claims["exp"] <= datetime.now(timezone.utc).timestamp():
        deny(401, "ADVISOR_INVALID_TOKEN", "登录已过期")
    async with async_session_factory() as session:
        user = await session.get(User, user_id, populate_existing=True)
        if user is None or not user.is_active or account_locked(user):
            deny(401, "ADVISOR_INVALID_TOKEN", "账号不可用")
        ctx = await _build_context(user, session, claims)
        if ctx.advisor_scope is None:
            deny(401, "ADVISOR_ROLE_CHANGED", "请重新登录")
        ctx.ensure_tenant(tenant_id)
        if menu_keys and not ctx.can_view(*menu_keys):
            deny(403, "ADVISOR_ROLE_CHANGED", "当前角色已无权访问此功能")
        await ensure_module_access(session, ctx, tenant_id, "geo")


class AdvisorDeliveryMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        suppressed = False
        started = False
        successful = False

        async def checked_send(message):
            nonlocal suppressed, started, successful
            if suppressed:
                return
            binding = scope.get("geo_advisor_delivery")
            if binding and (message["type"] == "http.response.start" and message["status"] < 400
                            or message["type"] == "http.response.body" and successful and message.get("body")):
                try:
                    await recheck_delivery(*binding)
                except HTTPException as exc:
                    suppressed = True
                    if not started:
                        await JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                                           headers={"Cache-Control": "private, no-store"})(scope, receive, send)
                    else:
                        await send({"type": "http.response.body", "body": b"", "more_body": False})
                    return
            if message["type"] == "http.response.start":
                started = True
                successful = message["status"] < 400
                if binding:
                    message["headers"] = [(k, v) for k, v in message.get("headers", [])
                                          if k.lower() != b"cache-control"] + [(b"cache-control", b"private, no-store")]
            await send(message)

        await self.app(scope, receive, checked_send)
