"""Diagnostic permissions, independent of GEO's path dispatch."""
from fastapi import Depends, HTTPException, Request
from app.security.auth import AuthContext, require_auth


async def require_diagnostic_auth(
    request: Request, ctx: AuthContext = Depends(require_auth),
) -> AuthContext:
    write_asset = (
        request.url.path.startswith("/api/v1/diagnostic/assets/")
        and request.method not in {"GET", "HEAD", "OPTIONS"}
        and not request.url.path.endswith("/brand/discover")
    )
    allowed = ctx.can_edit("geo.diagnosis") if write_asset else ctx.can_view("geo.diagnosis")
    if not allowed:
        raise HTTPException(403, "当前角色无权访问或修改诊断资料")
    return ctx
