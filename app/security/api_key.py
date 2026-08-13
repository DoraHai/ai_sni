"""最简 API Key 鉴权：校验 env 里的 ADMIN_API_KEY。

调用方通过 X-API-Key 请求头携带。
query 参数 key 仅当 ADMIN_API_KEY_QUERY_ENABLED=true（本地冒烟）；生产必须关闭。
"""
import secrets

from fastapi import HTTPException, Query, Security
from fastapi.security import APIKeyHeader

from app.config import get_settings

_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    header_key: str | None = Security(_header_scheme),
    key: str | None = Query(
        None, description="API Key（仅 ADMIN_API_KEY_QUERY_ENABLED 时可用）"
    ),
) -> None:
    settings = get_settings()
    provided = header_key
    if key:
        if settings.admin_api_key_query_enabled:
            provided = provided or key
        elif not header_key:
            raise HTTPException(
                401,
                "已禁用 query 传 API Key，请通过 X-API-Key 请求头提供。",
            )
    if not provided:
        raise HTTPException(
            401, "请求缺少 API Key，请通过 X-API-Key 请求头提供。"
        )
    if not secrets.compare_digest(provided, settings.admin_api_key):
        raise HTTPException(403, "API Key 不正确，请核对后重试。")
