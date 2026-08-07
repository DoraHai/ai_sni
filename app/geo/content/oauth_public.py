"""Public OAuth callback (no JWT/API-Key — state is HMAC-signed)."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import GeoChannelAccount

router = APIRouter(tags=["GEO OAuth public"])


@router.get("/api/v1/geo/oauth/social/callback")
async def oauth_social_callback(
    code: str = Query(...),
    state: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Browser redirect target after user authorizes the app on the platform."""
    from app.geo.content.ai_settings import encrypt_api_key
    from app.geo.content.connectors.oauth2 import (
        OAuth2Error,
        exchange_code_for_tokens,
        parse_oauth_state,
    )
    from app.geo.content.connectors.social import decrypt_credentials_json

    try:
        parsed = parse_oauth_state(state)
    except OAuth2Error as exc:
        raise HTTPException(400, str(exc)) from exc
    tenant_id = parsed["tenant_id"]
    account_id = parsed["account_id"]
    row = await session.get(GeoChannelAccount, account_id)
    if row is None or int(row.tenant_id) != int(tenant_id):
        raise HTTPException(404, "账号不存在")
    if not row.credentials_encrypted:
        raise HTTPException(400, "账号无 OAuth 客户端配置")
    try:
        creds = decrypt_credentials_json(row.credentials_encrypted)
        patch = await exchange_code_for_tokens(creds, code=code)
        merged = {**creds, **patch, "provider": "oauth2"}
        row.credentials_encrypted = encrypt_api_key(
            json.dumps(merged, ensure_ascii=False, sort_keys=True)
        )
        row.status = "active"
        row.last_verified_at = datetime.utcnow()
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"OAuth 回调失败: {exc}") from exc
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "account_id": account_id,
        "oauth_authorized": True,
        "message": "授权成功，可返回发布渠道页推送",
    }
