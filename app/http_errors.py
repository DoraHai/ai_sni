"""Map infrastructure failures to readable HTTP errors."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

DB_DOWN_DETAIL = (
    "数据库连不上。请先打开 Docker Desktop，再执行 docker compose up -d postgres，然后刷新页面。"
)


def is_db_unavailable(exc: BaseException) -> bool:
    chunks: list[str] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        chunks.append(type(cur).__name__)
        chunks.append(str(cur))
        cur = cur.__cause__ or cur.__context__
    blob = " ".join(chunks).lower()
    needles = (
        "connectionrefusederror",
        "connection refused",
        "winerror 1225",
        "could not connect",
        "connect call failed",
        "error connecting to server",
        "connectiondoesnotexisterror",
        "the database system is starting up",
        "server closed the connection unexpectedly",
    )
    return any(n in blob for n in needles)


def register_infra_handlers(app: FastAPI) -> None:
    from app.api_controls import ControlDenied
    from app.api_metering import MeteringUnavailable

    @app.exception_handler(ControlDenied)
    async def _policy_denied(request: Request, exc: ControlDenied):
        return JSONResponse(status_code=429, content={'detail': str(exc)}, headers={'Cache-Control': 'no-store'})

    @app.exception_handler(MeteringUnavailable)
    async def _metering_down(request: Request, exc: MeteringUnavailable):
        return JSONResponse(status_code=503, content={'detail': str(exc)}, headers={'Cache-Control': 'no-store'})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        if is_db_unavailable(exc):
            return JSONResponse(status_code=503, content={"detail": DB_DOWN_DETAIL})
        raise exc
