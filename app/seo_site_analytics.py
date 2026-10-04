"""Fixed-host Baidu Tongji and GA4 clients for manually pulled site analytics."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select

from app.models.seo_site_analytics import SeoSiteAnalyticsSource, SeoSiteAnalyticsMonthly

from app.security.crypto import encrypt, decrypt
from app.seo_publication_export import BEIJING, month_bounds, DEFAULT_PUBLICATION_LIST_TEMPLATE

BAIDU_TOKEN = "https://openapi.baidu.com/oauth/2.0/token"
BAIDU_DATA = "https://openapi.baidu.com/rest/2.0/tongji/report/getData"
BAIDU_SITES = "https://openapi.baidu.com/rest/2.0/tongji/config/getSiteList"
BAIDU_BUSINESS = "https://api.baidu.com/json/tongji/v1/ReportService"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GA4_API = "https://analyticsdata.googleapis.com/v1beta/properties"
GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
# Mainland servers usually cannot reach Google; never blame the uploaded JSON for a network failure.
GA4_UNREACHABLE = "无法连接 Google 接口，服务器网络可能无法访问 Google，请为 SEO 服务配置可访问 Google 的出口代理后重试"


class AnalyticsError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def secrets_of(row) -> dict:
    return json.loads(decrypt(row.secret_ciphertext)) if row.secret_ciphertext else {}


def save_secrets(row, values: dict) -> None:
    row.secret_ciphertext = encrypt(json.dumps(values, ensure_ascii=False)) if values else None


def validate_source(source: str):
    if source not in {"baidu_tongji", "ga4"}:
        raise AnalyticsError("invalid_source", "不支持的数据源")


def normalize_config(source: str, config: dict) -> dict:
    validate_source(source)
    if source == "ga4":
        prop = str(config.get("property_id") or "").strip().removeprefix("properties/")
        if not prop.isdigit():
            raise AnalyticsError("invalid_property", "GA4 媒体资源 ID 必须是数字")
        return {"property_id": prop}
    mode = config.get("mode", "account")
    if mode not in {"account", "business"}:
        raise AnalyticsError("invalid_mode", "请选择百度账号授权或商业账号 Token")
    site_id = str(config.get("tongji_site_id") or "").strip()
    if not site_id.isdigit():
        raise AnalyticsError("invalid_site_id", "百度统计站点 ID 必须是数字")
    field = "api_key" if mode == "account" else "username"
    value = str(config.get(field) or "").strip()
    if not value:
        raise AnalyticsError("invalid_config", f"请填写{ 'API Key' if mode == 'account' else '商业账号用户名'}")
    result = {"mode": mode, "tongji_site_id": site_id, field: value}
    if mode == "business" and config.get("token_entered_at"):
        result["token_entered_at"] = str(config["token_entered_at"])
    return result


def validate_service_account(raw: str) -> dict:
    try:
        value = json.loads(raw)
        if (value.get("type") != "service_account" or not value.get("client_email")
                or not value.get("private_key") or value.get("token_uri") != GOOGLE_TOKEN):
            raise ValueError()
        return value
    except (TypeError, AttributeError, ValueError) as exc:
        raise AnalyticsError("invalid_credentials", "服务账号 JSON 无效，请检查 client_email、private_key 和 token_uri") from exc


def public_source(row) -> dict:
    secret = secrets_of(row)
    return {"source": row.source, "enabled": row.enabled, "config": row.config,
            "has_secret_key": bool(secret.get("secret_key")),
            "refresh_token_set": bool(secret.get("refresh_token")),
            "access_token_set": bool(secret.get("access_token")),
            "service_account_email": (secret.get("service_account_json") or {}).get("client_email"),
            "last_test_at": row.last_test_at, "last_test_status": row.last_test_status,
            "last_test_message": row.last_test_message, "token_expires_at": row.token_expires_at}


def authorization_url(api_key: str) -> str:
    return "https://openapi.baidu.com/oauth/2.0/authorize?" + urlencode({
        "response_type": "code", "client_id": api_key, "redirect_uri": "oob", "scope": "basic", "display": "popup"})


def validate_month(month: str, now: datetime | None = None):
    try:
        start, end = month_bounds(month)
    except (ValueError, OverflowError) as exc:
        raise AnalyticsError("invalid_month", "月份须为 YYYY-MM") from exc
    today = (now or datetime.now(timezone.utc)).astimezone(BEIJING)
    if month > today.strftime("%Y-%m"):
        raise AnalyticsError("future_month", "不能拉取未来月份")
    first = datetime.fromisoformat(month + "-01").date()
    final = (end.replace(tzinfo=timezone.utc).astimezone(BEIJING) - timedelta(days=1)).date()
    if month == today.strftime("%Y-%m"):
        final = today.date()
    return first.isoformat(), final.isoformat(), month == today.strftime("%Y-%m")


def validate_template(columns: list) -> list[dict]:
    if not isinstance(columns, list) or not columns:
        raise AnalyticsError("invalid_template", "至少选择一列")
    allowed = {column["key"]: column for column in DEFAULT_PUBLICATION_LIST_TEMPLATE}
    seen = set()
    result = []
    for column in columns:
        if not isinstance(column, dict) or column.get("key") not in allowed or column["key"] in seen:
            raise AnalyticsError("invalid_template", "导出列无效或重复")
        seen.add(column["key"])
        title = str(column.get("title") or "").strip()
        if not 1 <= len(title) <= 30:
            raise AnalyticsError("invalid_template", "列名须为 1 至 30 个字符")
        spec = {"key": column["key"], "title": title}
        if "width" in column:
            width = column["width"]
            if isinstance(width, bool) or not isinstance(width, (int, float)) or not 5 <= width <= 80:
                raise AnalyticsError("invalid_template", "列宽须为 5 至 80")
            spec["width"] = width
        result.append(spec)
    return result


def parse_baidu_result(result: dict) -> tuple[int | None, int | None, dict]:
    fields = result.get("fields") or []
    def number(value):
        if isinstance(value, list):
            value = value[0] if value else None
        if value is None or value == "--" or isinstance(value, bool):
            return None
        try:
            return int(float(str(value).replace(",", "")))
        except (ValueError, TypeError):
            return None
    def pair(values):
        if isinstance(values, dict):
            return number(values.get("visitor_count")), number(values.get("pv_count"))
        if isinstance(values, list):
            metric_fields = [name for name in fields if name in {"visitor_count", "pv_count"}]
            aligned = fields if len(values) >= len(fields) else metric_fields
            names = {name: i for i, name in enumerate(aligned)}
            return (number(values[names["visitor_count"]]) if names.get("visitor_count", -1) < len(values) and "visitor_count" in names else None,
                    number(values[names["pv_count"]]) if names.get("pv_count", -1) < len(values) and "pv_count" in names else None)
        return None, None
    items = result.get("items") or []
    data = items[1] if isinstance(items, list) and len(items) > 1 and isinstance(items[1], list) else items
    if isinstance(data, list) and len(data) == 1:
        uv, pv = pair(data[0])
        if uv is not None or pv is not None:
            return uv, pv, {"method": "item"}
    sums = result.get("sum") or []
    uv, pv = pair(sums[0] if isinstance(sums, list) and sums else sums)
    return uv, pv, {"method": "sum" if uv is not None or pv is not None else "none"}


class ProviderClient:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def _json(self, method, url, **kwargs):
        try:
            response = await self.http.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            raise AnalyticsError("provider_http_error", "数据源接口暂时不可用") from None
        except (httpx.RequestError, ValueError):
            raise AnalyticsError("provider_error", "数据源连接失败，请稍后重试") from None

    async def _baidu_token(self, grant_type, params):
        try:
            response = await self.http.request("GET", BAIDU_TOKEN, params={"grant_type": grant_type, **params})
            data = response.json()
            if response.status_code >= 400 or data.get("error"):
                error = data.get("error")
                if error == "invalid_client":
                    raise AnalyticsError("baidu_invalid_client", "API Key 或 Secret Key 不正确")
                if grant_type == "refresh_token" and error == "invalid_grant":
                    raise AnalyticsError("baidu_auth_expired", "百度授权已失效，请重新授权（重新打开授权页并粘贴授权码）")
                if grant_type == "authorization_code":
                    raise AnalyticsError("baidu_code_invalid", "授权码无效或已过期（授权码只能使用一次且很快过期，请重新打开授权页获取）")
                raise AnalyticsError("baidu_auth_failed", "百度授权失败，请重新授权")
            return data
        except AnalyticsError:
            raise
        except (httpx.RequestError, ValueError):
            raise AnalyticsError("provider_error", "数据源连接失败，请稍后重试") from None

    async def exchange(self, config, secret, code):
        data = await self._baidu_token("authorization_code", {"code": code,
            "client_id": config["api_key"], "client_secret": secret["secret_key"], "redirect_uri": "oob"})
        return self._token_pair(data, secret)

    def _token_pair(self, data, secret):
        if not data.get("access_token") or not data.get("refresh_token"):
            raise AnalyticsError("baidu_auth_failed", "百度授权失败，请检查授权码或重新授权")
        result = {**secret, "access_token": data["access_token"], "refresh_token": data["refresh_token"]}
        result["access_token_expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in") or 2592000))).isoformat()
        return result

    async def _refresh(self, config, secret):
        data = await self._baidu_token("refresh_token", {"refresh_token": secret["refresh_token"],
            "client_id": config["api_key"], "client_secret": secret["secret_key"]})
        return self._token_pair(data, secret)

    async def baidu(self, config, secret, start, end, *, sites=False, on_refresh=None):
        mode = config["mode"]
        if mode == "account":
            if not secret.get("secret_key") or not secret.get("refresh_token"):
                raise AnalyticsError("baidu_auth_missing", "请先完成百度账号授权")
            expiry = secret.get("access_token_expires_at")
            try:
                expires_at = datetime.fromisoformat(str(expiry).replace("Z", "+00:00")) if expiry else None
                if expires_at and expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
            except ValueError:
                expires_at = None
            if not secret.get("access_token") or (expires_at and expires_at <= datetime.now(timezone.utc)):
                secret = await self._refresh(config, secret)
                if on_refresh:
                    on_refresh(secret)
            params = {"access_token": secret["access_token"]}
            if not sites:
                params.update({"site_id": config["tongji_site_id"], "method": "trend/time/a",
                    "start_date": start.replace("-", ""), "end_date": end.replace("-", ""),
                    "metrics": "pv_count,visitor_count", "gran": "month", "max_results": 0})
            url = BAIDU_SITES if sites else BAIDU_DATA
            data = await self._json("GET", url, params=params)
            def failed(payload):
                return str(payload.get("error_code") or "0") != "0" or bool(payload.get("error"))
            if failed(data):
                if str(data.get("error_code")) in {"110", "111", "112", "100"}:
                    secret = await self._refresh(config, secret)
                    if on_refresh:
                        on_refresh(secret)
                    params["access_token"] = secret["access_token"]
                    data = await self._json("GET", url, params=params)
                if failed(data):
                    error_code = str(data.get("error_code") or "")
                    if error_code in {"110", "111"}:
                        raise AnalyticsError("baidu_auth_expired", "百度授权已失效，请重新授权")
                    message = str(data.get("error_msg") or data.get("error") or "未知错误")[:100]
                    for value in secret.values():
                        if isinstance(value, str) and value:
                            message = message.replace(value, "[已隐藏]")
                    if error_code in {"403", "1002", "3"} or any(word in message.lower() for word in ("permission", "权限", "站点")):
                        raise AnalyticsError("baidu_site_forbidden", f"无该站点权限，请确认授权的百度账号能在百度统计中查看站点 ID {config['tongji_site_id']}")
                    raise AnalyticsError("baidu_api_error", f"百度统计接口返回错误：{message}")
            return data, secret
        if not secret.get("access_token"):
            raise AnalyticsError("baidu_auth_missing", "请填写商业账号 Access Token")
        body = {"site_id": config["tongji_site_id"], "method": "trend/time/a",
                "start_date": start.replace("-", ""), "end_date": end.replace("-", ""),
                "metrics": "pv_count,visitor_count", "gran": "month", "max_results": 0}
        data = await self._json("POST", BAIDU_BUSINESS + ("/getSiteList" if sites else "/getData"),
            json={"header": {"userName": config["username"], "accessToken": secret["access_token"]},
                  "body": {} if sites else body})
        header = data.get("header") or {}
        if header.get("status") not in (None, 0, "0"):
            failures = header.get("failures") or []
            codes = {str(item.get("code")) for item in failures if isinstance(item, dict)}
            if codes & {"2", "1001", "110", "111", "894061"}:
                message = "百度商业账号 Token 无效或已过期，请在数据 API 页面更新"
            elif codes & {"3", "1002", "403"}:
                message = "百度商业账号无该站点的访问权限，请核对用户名和站点 ID"
            else:
                message = "百度商业账号请求失败，请检查用户名、Token 和站点权限"
            raise AnalyticsError("baidu_api_error", message)
        return data, secret

    async def ga4(self, config, secret, start, end, *, metadata=False):
        account = secret.get("service_account_json")
        if not account:
            raise AnalyticsError("ga4_auth_missing", "请上传 GA4 服务账号 JSON")
        now = int(datetime.now(timezone.utc).timestamp())
        try:
            assertion = jwt.encode({"iss": account["client_email"], "scope": GA4_SCOPE,
                "aud": GOOGLE_TOKEN, "iat": now, "exp": now + 3600}, account["private_key"], algorithm="RS256")
            response = await self.http.request("POST", GOOGLE_TOKEN, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
            response.raise_for_status()
            token_data = response.json()
            token = token_data["access_token"]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise AnalyticsError("ga4_quota", "GA4 配额已用尽，请稍后再试") from exc
            raise AnalyticsError("ga4_token_failed", "服务账号 JSON 无效或已被禁用") from exc
        except httpx.RequestError as exc:
            raise AnalyticsError("ga4_unreachable", GA4_UNREACHABLE) from exc
        except (KeyError, jwt.PyJWTError, ValueError) as exc:
            raise AnalyticsError("ga4_token_failed", "服务账号 JSON 无效或已被禁用") from exc
        url = f"{GA4_API}/{config['property_id']}" + ("/metadata" if metadata else ":runReport")
        try:
            response = await self.http.request("GET" if metadata else "POST", url,
                headers={"Authorization": f"Bearer {token}"},
                **({} if metadata else {"json": {"dateRanges": [{"startDate": start, "endDate": end}],
                    "metrics": [{"name": "totalUsers"}, {"name": "screenPageViews"}]}}))
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 403:
                raise AnalyticsError("ga4_forbidden", "服务账号没有该 GA4 媒体资源的查看权限，请在 GA4 管理-媒体资源访问管理 中添加为查看者") from exc
            if status == 401:
                raise AnalyticsError("ga4_token_failed", "服务账号 JSON 无效或已被禁用") from exc
            if status == 429:
                raise AnalyticsError("ga4_quota", "GA4 配额已用尽，请稍后再试") from exc
            raise AnalyticsError("ga4_not_found" if status == 404 else "ga4_bad_request" if status == 400 else "ga4_http_error",
                "媒体资源 ID 不存在" if status == 404 else "参数错误" if status == 400 else "GA4 接口暂时不可用") from exc
        except httpx.RequestError as exc:
            raise AnalyticsError("ga4_unreachable", GA4_UNREACHABLE) from exc
        except ValueError as exc:
            raise AnalyticsError("ga4_error", "GA4 连接失败，请稍后重试") from exc


def parse_ga4(data):
    rows = data.get("rows") or []
    if not rows:
        return None, None
    values = rows[0].get("metricValues") or []
    try:
        return int(values[0]["value"]), int(values[1]["value"])
    except (IndexError, KeyError, ValueError, TypeError):
        return None, None


async def fetch_provider(provider: ProviderClient, row, start: str, end: str, *, test=False):
    """Fetch a fixed-host provider result; a caller holds the source row lock."""
    secret = secrets_of(row)
    if row.source == "ga4":
        data = await provider.ga4(row.config, secret, start, end)
        return (*parse_ga4(data), {"method": "runReport"})
    def persist_refresh(updated_secret):
        save_secrets(row, updated_secret)
        row.token_expires_at = datetime.fromisoformat(updated_secret["access_token_expires_at"])
    data, updated_secret = await provider.baidu(row.config, secret, start, end, sites=test, on_refresh=persist_refresh)
    if updated_secret != secret:
        persist_refresh(updated_secret)
    if row.config["mode"] == "business":
        items = (data.get("body") or {}).get("data") or []
        result = items[0] if items else {}
        result = result.get("result", result) if isinstance(result, dict) else {}
    else:
        result = data
        if not test:
            result = data.get("result") or {}
    if test:
        sites = result if isinstance(result, list) else next((result[key] for key in ("list", "sites", "site_list", "items") if key in result), []) if isinstance(result, dict) else []
        if not any(str(item.get("site_id", item.get("siteId", item.get("id")))) == row.config["tongji_site_id"] for item in sites if isinstance(item, dict)):
            raise AnalyticsError("baidu_site_missing", f"该百度统计账号下找不到站点ID {row.config['tongji_site_id']}")
        return None, None, {"method": "getSiteList"}
    return parse_baidu_result(result if isinstance(result, dict) else {})


async def pull_site_month(session, *, tenant_id: int, site_id: int, month: str,
                          source: str | None = None, fetched_by: int | None = None,
                          provider: ProviderClient | None = None):
    """Pull once under source locks; injectable provider allows offline jobs/tests."""
    start, end, partial = validate_month(month)
    if source:
        validate_source(source)
    query = select(SeoSiteAnalyticsSource).where(SeoSiteAnalyticsSource.tenant_id == tenant_id,
        SeoSiteAnalyticsSource.site_id == site_id, SeoSiteAnalyticsSource.enabled.is_(True))
    if source:
        query = query.where(SeoSiteAnalyticsSource.source == source)
    sources = (await session.scalars(query.with_for_update())).all()
    if not sources:
        raise AnalyticsError("not_configured", "没有启用的数据源")
    async def run(client):
        results = []
        for configured in sources:
            row = await session.scalar(select(SeoSiteAnalyticsMonthly).where(
                SeoSiteAnalyticsMonthly.tenant_id == tenant_id, SeoSiteAnalyticsMonthly.site_id == site_id,
                SeoSiteAnalyticsMonthly.source == configured.source, SeoSiteAnalyticsMonthly.month == month).with_for_update())
            if row is None:
                row = SeoSiteAnalyticsMonthly(tenant_id=tenant_id, site_id=site_id,
                    source=configured.source, month=month, status="failed", raw_meta={})
                session.add(row)
            now = datetime.now(timezone.utc)
            row.last_attempt_at = now
            try:
                uv, pv, meta = await fetch_provider(client, configured, start, end)
                row.uv, row.pv = uv, pv
                row.status = "ok" if uv is not None or pv is not None else "no_data"
                row.error_code = row.error_message = row.last_error_code = row.last_error_message = None
                row.fetched_at, row.fetched_by = now, fetched_by
                row.raw_meta = {**meta, "partial": partial, "start_date": start, "end_date": end}
            except AnalyticsError as exc:
                row.last_error_code, row.last_error_message = exc.code, str(exc)
                if row.status != "ok":
                    row.status, row.error_code, row.error_message = "failed", exc.code, str(exc)
            results.append(row)
        await session.commit()
        return results
    if provider is not None:
        return await run(provider)
    async with httpx.AsyncClient(timeout=30) as http:
        return await run(ProviderClient(http))
