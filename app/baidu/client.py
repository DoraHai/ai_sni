"""百度营销 API 异步客户端。

请求约定（文档 0009/0010/0011）：
  POST {BAIDU_API_BASE_URL}/json/sms/service/{ServiceName}/{methodName}
  Content-Type: application/json;charset=utf-8
  body:
    {
      "header": {"userName": "<广告主推广账户名>", "accessToken": "<token>"},
      "body":   {...}
    }

响应约定：
  {
    "header": {"desc": "...", "status": 0, "failures": [...]},
    "body":   {...}
  }
  header.status == 0 表示成功；非 0 失败，failures[0] 给出具体错误码与文案
"""
import logging
import re
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


# token 相关的错误码（文档 0003 第 5 节）。命中这些码意味着需要重新授权或续期。
TOKEN_ERROR_CODES = {89403, 89405, 89406, 894061, 894062, 894063, 894064, 89407}

# 百度搜索推广接口在请求字段不受支持时返回此错误码。服务层只应在这个
# 明确错误上移除试探字段，不能把权限、资产不存在等错误误判成字段兼容问题。
INVALID_REQUEST_FIELD_CODE = 9011519

# 写方法名兜底识别（百度写接口动词前缀）。调用方应显式传 is_write=True；
# 这层前缀匹配是双保险，防止将来有人新增写调用忘了传标志而把真请求漏给百度。
_WRITE_METHOD_PREFIXES = (
    "update", "add", "delete", "del", "write",
    "pause", "shelve", "enable", "disable", "stop", "start",
)


def _looks_like_write(method: str) -> bool:
    m = method.lower()
    return any(m.startswith(p) for p in _WRITE_METHOD_PREFIXES)


class BaiduAPIError(Exception):
    def __init__(self, code: int | None, message: str, raw: dict | None = None):
        self.code = code
        self.message = message
        self.raw = raw or {}
        super().__init__(f"百度 API 失败 [code={code}]: {message}")

    @property
    def is_token_invalid(self) -> bool:
        return self.code in TOKEN_ERROR_CODES

    @property
    def is_invalid_request_field(self) -> bool:
        """当前错误是否明确表示请求字段不受支持。"""
        return str(self.code) == str(INVALID_REQUEST_FIELD_CODE)

    def is_missing_entity(self, entity: str) -> bool:
        """当前错误是否明确表示指定类型的百度资产不存在。"""
        message = self.message.casefold()
        entity_name = entity.casefold()
        missing_markers = (
            "not exist",
            "does not exist",
            "not found",
            "不存在",
            "已删除",
        )
        entity_pattern = rf"(?<![a-z0-9_]){re.escape(entity_name)}(?![a-z0-9_])"
        return bool(re.search(entity_pattern, message)) and any(
            marker in message for marker in missing_markers
        )


class BaiduLiveWriteBlockedError(RuntimeError):
    """A real Baidu write was rejected by the tenant/account allowlist."""


class BaiduAPIClient:
    """无状态客户端：一次调用一个 HTTP 连接（httpx.AsyncClient 上下文）。

    用法：
        client = BaiduAPIClient(username="苏尔寿UN", access_token="eyJ...")
        body = await client.call("AccountService", "getAccountInfo",
                                 {"accountFields": ["userId", "balance"]})
    """

    def __init__(
        self,
        username: str,
        access_token: str,
        timeout: float = 30.0,
        *,
        tenant_id: int | None = None,
        baidu_account_id: int | None = None,
    ):
        if not username or not access_token:
            raise ValueError("BaiduAPIClient 必须提供 username 和 access_token")
        self._username = username
        self._access_token = access_token
        self._timeout = timeout
        self._tenant_id = tenant_id
        self._baidu_account_id = baidu_account_id
        self._base_url = get_settings().baidu_api_base_url.rstrip("/")

    async def call(
        self,
        service: str,
        method: str,
        body: dict[str, Any] | None = None,
        *,
        is_write: bool = False,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/json/sms/service/{service}/{method}"
        payload = {
            "header": {
                "userName": self._username,
                "accessToken": self._access_token,
            },
            "body": body or {},
        }

        # dry-run 安全网：任何写请求（显式 is_write 或方法名像写）在演练开关开启时
        # 一律不发 HTTP，直接返回模拟成功体。保证开发/验证阶段绝无写请求落到百度线上。
        settings = get_settings()
        is_write_request = is_write or _looks_like_write(method)
        if is_write_request and settings.baidu_write_dry_run:
            logger.warning(
                "[DRY-RUN] 拦截写请求 service=%s method=%s body=%s（未发送，仅记台账）",
                service, method, body,
            )
            return {"_dry_run": True, "data": []}
        if is_write_request:
            try:
                allowed = settings.baidu_live_write_allowed(
                    self._tenant_id,
                    self._baidu_account_id,
                )
            except (TypeError, ValueError) as exc:
                raise BaiduLiveWriteBlockedError(
                    "百度真实回写白名单配置无效，已拒绝请求"
                ) from exc
            if not allowed:
                raise BaiduLiveWriteBlockedError(
                    "当前客户或推广账户不在百度真实回写白名单中，已拒绝请求"
                )

        async with httpx.AsyncClient(timeout=self._timeout) as http:
            resp = await http.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json;charset=utf-8"},
            )

        if resp.status_code != 200:
            raise BaiduAPIError(
                code=resp.status_code,
                message=f"HTTP {resp.status_code}: {resp.text[:500]}",
            )

        data = resp.json()
        header = data.get("header", {}) or {}
        status = header.get("status")
        failures = header.get("failures") or []

        if status != 0:
            first_fail = failures[0] if failures else {}
            err_code = first_fail.get("code") or status
            err_msg = first_fail.get("message") or header.get("desc") or "未知错误"
            logger.warning(
                "百度 API 失败 service=%s method=%s code=%s msg=%s",
                service, method, err_code, err_msg,
            )
            raise BaiduAPIError(code=err_code, message=err_msg, raw=data)

        return data.get("body", {})
