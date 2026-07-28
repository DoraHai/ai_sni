"""最简 API Key 鉴权：校验 env 里的 ADMIN_API_KEY。

调用方通过 X-API-Key 请求头携带；原型页直连场景可用 key 查询参数等价替代。
P0/P1 内部使用够用，P2 引入多用户后替换为正式登录态。
"""
import secrets

from fastapi import HTTPException, Query, Security
from fastapi.security import APIKeyHeader

from app.config import get_settings

_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    header_key: str | None = Security(_header_scheme),
    key: str | None = Query(
        None, description="API Key，与 X-API-Key 请求头等价，供原型页直连使用"
    ),
) -> None:
    provided = header_key or key
    if not provided:
        raise HTTPException(
            401, "请求缺少 API Key，请通过 X-API-Key 请求头或 key 查询参数提供。"
        )
    if not secrets.compare_digest(provided, get_settings().admin_api_key):
        raise HTTPException(403, "API Key 不正确，请核对后重试。")
