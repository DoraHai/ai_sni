"""Super-admin-only, read-only AI automation governance endpoint."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import text

from app.ai_governance import read_ai_governance
from app.api.platform_console import require_console_admin
from app.database import async_session_factory
from app.security.auth import AuthContext

router = APIRouter(prefix="/api/v1/platform", tags=["平台 AI 治理"])
_read_slots = asyncio.BoundedSemaphore(2)


@router.get("/ai-governance")
async def ai_governance(
    response: Response,
    _ctx: AuthContext = Depends(require_console_admin),
) -> dict:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Vary"] = "Authorization"
    try:
        async with asyncio.timeout(10):
            async with _read_slots, async_session_factory() as session:
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                await session.execute(text("SET LOCAL statement_timeout = '3000ms'"))
                return await read_ai_governance(session)
    except TimeoutError:
        raise HTTPException(503, "AI 治理状态读取超时，请稍后重试") from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "AI 治理状态暂时无法读取，请稍后重试") from None
