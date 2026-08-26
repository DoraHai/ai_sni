"""最简 API Key 鉴权：校验 env 里的 ADMIN_API_KEY。

调用方通过 X-API-Key 请求头携带；仅在显式开启兼容开关时接受 key 查询参数。
P0/P1 内部使用够用，P2 引入多用户后替换为正式登录态。
"""
import secrets

from fastapi import HTTPException, Query, Security
from fastapi.security import APIKeyHeader

from app.config import get_settings

_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def resolve_api_key(header_key: str | None, query_key: str | None) -> str | None:
    """按安全配置选择凭证；请求头始终优先，查询参数默认禁用。"""
    if header_key:
        return header_key
    if get_settings().admin_api_key_query_enabled:
        return query_key
    return None


async def require_api_key(
    header_key: str | None = Security(_header_scheme),
    key: str | None = Query(
        None, description="旧版 API Key 查询参数；仅在服务端显式开启兼容开关时可用"
    ),
) -> None:
    settings = get_settings()
    provided = resolve_api_key(header_key, key)
    if not provided:
        hint = "X-API-Key 请求头"
        if settings.admin_api_key_query_enabled:
            hint += "或 key 查询参数"
        raise HTTPException(401, f"请求缺少 API Key，请通过{hint}提供。")
    if not secrets.compare_digest(provided, settings.admin_api_key):
        raise HTTPException(403, "API Key 不正确，请核对后重试。")
