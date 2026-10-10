"""Durable provider-attempt metering, independent of business transactions.

Disabled until the additive schema has been reviewed and installed. Enabled
calls must commit their reservation before sending a request. A crash or an
unavailable usage field leaves an unknown amount, never an invented zero.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import text

from app.config import get_settings
from app.database import async_session_factory
from app import api_controls

logger = logging.getLogger(__name__)


class MeteringUnavailable(RuntimeError):
    """Fail before a paid call when its accounting reservation cannot be saved."""


@dataclass(frozen=True)
class MeterScope:
    tenant_id: int | None = None
    user_id: int | None = None
    origin: str = 'unattributed'
    module: str = 'unknown'
    operation: str = 'provider_call'
    job_ref: str | None = None


scope: ContextVar[MeterScope] = ContextVar('api_meter_scope', default=MeterScope())


def enabled() -> bool:
    return os.environ.get('API_METERING_ENABLED', '').lower() == 'true'


def bind_identity(ctx):
    scope.set(replace(scope.get(), user_id=ctx.user_id, tenant_id=ctx.tenant_id,
                      origin='interactive' if ctx.user_id is not None else 'system'))
    return ctx


def bind_tenant(tenant_id: int) -> None:
    # Invoked only after server-side tenant authorization has succeeded.
    scope.set(replace(scope.get(), tenant_id=int(tenant_id)))


@contextmanager
def background_scope(*, tenant_id: int, module: str, operation: str,
                     user_id: int | None = None, job_ref: str | None = None):
    token = scope.set(MeterScope(tenant_id, user_id, 'job' if user_id else 'system',
                                module, operation, job_ref))
    try:
        yield
    finally:
        scope.reset(token)


def business_scope(module: str, tenant_arg: str = 'tenant_id'):
    """Trusted service function arguments, also used by non-HTTP schedulers."""
    def decorate(func):
        signature = inspect.signature(func)
        @wraps(func)
        async def run(*args, **kwargs):
            tenant = signature.bind(*args, **kwargs).arguments.get(tenant_arg)
            tenant_id = getattr(tenant, 'id', tenant)
            if tenant_id is None:
                return await func(*args, **kwargs)
            current = scope.get()
            token = scope.set(replace(current, tenant_id=int(tenant_id), module=module,
                                      operation=func.__name__,
                                      origin='system' if current.origin == 'unattributed' else current.origin))
            try:
                return await func(*args, **kwargs)
            finally:
                scope.reset(token)
        return run
    return decorate


class MeteringScopeMiddleware:
    """Pure ASGI isolation: identity comes from existing auth, never headers/body."""
    def __init__(self, app, module: str):
        self.app, self.module = app, module

    async def __call__(self, asgi_scope, receive, send):
        if asgi_scope['type'] != 'http':
            return await self.app(asgi_scope, receive, send)
        token = scope.set(MeterScope(module=self.module))
        try:
            await self.app(asgi_scope, receive, send)
        finally:
            scope.reset(token)


def safe_code(value, limit=100):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,' + str(limit) + '}', value) else None


def endpoint_name(url: str) -> str:
    parsed = urlsplit(url)
    # No query, fragments, credentials, or port-dependent secrets.
    return ((parsed.hostname or '') + parsed.path)[:200]


def credential_ref(key: str | None) -> str | None:
    if not key:
        return None
    settings = get_settings()
    salt = settings.jwt_secret or settings.admin_api_key
    return hmac.new(salt.encode(), key.encode(), hashlib.sha256).hexdigest()


def token_count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**12 else None


def extract_usage(data):
    usage = data.get('usage') if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return None, None, None
    prompt = token_count(usage.get('prompt_tokens', usage.get('input_tokens')))
    completion = token_count(usage.get('completion_tokens', usage.get('output_tokens')))
    details = usage.get('prompt_tokens_details')
    cached = token_count(details.get('cached_tokens')) if isinstance(details, dict) else None
    if cached is None:
        cached = token_count(usage.get('prompt_cache_hit_tokens'))
    if prompt is None or cached is None or cached > prompt:
        return prompt, None, completion
    return prompt, cached, completion


OFFICIAL_SOURCE = 'https://help.aliyun.com/zh/model-studio/model-pricing'
# Mainland real-time rates checked 2026-10-10. Other regions/models and cache
# discounts must use an explicitly reviewed override; never guess an alias.
DEFAULT_RATES = [
    {'host': 'dashscope.aliyuncs.com', 'model': 'deepseek-v4-flash',
     'input': '1', 'output': '2', 'max_input': 1000000,
     'version': 'aliyun-cn-list-20261010', 'source': OFFICIAL_SOURCE},
    {'host': 'dashscope.aliyuncs.com', 'model': 'qwen3.8-max',
     'input': '12', 'output': '36', 'max_input': 1000000,
     'version': 'aliyun-cn-list-20261010', 'source': OFFICIAL_SOURCE},
]


def quote_rate(url, model):
    """Exact host/model lookup. Freeze the approved quote on each attempt."""
    host = urlsplit(url).hostname
    rates = DEFAULT_RATES
    raw = os.environ.get('API_METERING_RATES_JSON')
    if raw:
        try:
            rates = json.loads(raw)
        except (ValueError, TypeError):
            raise MeteringUnavailable('API 计价配置无效，请检查服务器配置') from None
    if not isinstance(rates, list):
        raise MeteringUnavailable('API 计价配置必须是列表')
    for row in rates:
        if not isinstance(row, dict) or row.get('host') != host or row.get('model') != model:
            continue
        try:
            # This first ledger version totals CNY only; no implicit FX conversion.
            if row.get('currency', 'CNY') != 'CNY':
                return None
            unit = row.get('unit', 'tokens')
            if unit not in {'tokens','request'}:
                raise ValueError
            result = {k: str(Decimal(str(row[k]))) for k in (('per_request',) if unit == 'request' else ('input', 'output'))}
            if 'cached' in row:
                result['cached'] = str(Decimal(str(row['cached'])))
            if any(not Decimal(v).is_finite() or Decimal(v) < 0 for v in result.values()):
                raise ValueError
            result.update(unit=unit,currency='CNY', version=safe_code(row.get('version'), 80),
                          max_input=token_count(row.get('max_input')),
                          source=str(row.get('source', 'configured'))[:200])
            if result['version'] is None:
                raise ValueError
            return result
        except (KeyError, ValueError, InvalidOperation):
            raise MeteringUnavailable('API 单价或版本配置无效') from None
    return None


def estimate(quote, prompt, cached, completion):
    if quote is not None and quote.get('unit') == 'request':
        return Decimal(quote['per_request'])
    if quote is None or None in (prompt, cached, completion):
        return None
    if quote['max_input'] is not None and prompt > quote['max_input']:
        return None
    if cached and 'cached' not in quote:
        return None
    return ((Decimal(prompt - cached) * Decimal(quote['input'])
             + Decimal(cached) * Decimal(quote.get('cached', '0'))
             + Decimal(completion) * Decimal(quote['output'])) / Decimal(1000000))


async def _write(sql, params):
    try:
        async with asyncio.timeout(5), async_session_factory() as session:
            await session.execute(text("SET LOCAL statement_timeout = '3000ms'"))
            await session.execute(text(sql), params)
            await session.commit()
    except Exception:
        # Do not log DB URL, payload, headers, or provider exceptions.
        logger.error('API metering write failed; event=%s', params.get('id'))
        raise MeteringUnavailable('API 费用台账暂时不可写，请稍后重试') from None


async def metered_request(client, method: str, url: str, *, api_key=None,
                          model=None, provider=None, tenant_id=None,
                          operation=None, classify_response=None, **kwargs):
    """Wrap only known provider clients, preserving their existing transport."""
    if not enabled():
        if api_controls.enabled():
            raise MeteringUnavailable('API 管理必须与费用计量同时启用')
        return await getattr(client, method)(url, **kwargs)
    context = scope.get()
    if context.module == 'unknown':
        context = replace(context, module=api_controls.SERVICE_MODULE)
    if tenant_id is not None:
        context = replace(context, tenant_id=int(tenant_id))
    quote = quote_rate(url, model or endpoint_name(url))
    event_id = str(uuid4())
    params = dict(id=event_id, tenant_id=context.tenant_id, user_id=context.user_id,
                  origin=context.origin, module=context.module,
                  operation=operation or context.operation, job_ref=context.job_ref,
                  provider=provider or urlsplit(url).hostname or 'unknown',
                  credential_ref=credential_ref(api_key), model=safe_code(model, 120),
                  endpoint=endpoint_name(url), pricing_version=quote['version'] if quote else None,
                  rate_quote=json.dumps(quote) if quote else None)
    if api_controls.enabled():
        quote, kwargs = await api_controls.admit(params, url, api_key, quote, kwargs)
    else:
        await _write('''INSERT INTO api_usage_events
        (id,tenant_id,user_id,origin,module,operation,job_ref,provider,credential_ref,
         model,endpoint,state,pricing_version,rate_quote)
        VALUES (CAST(:id AS uuid),:tenant_id,:user_id,:origin,:module,:operation,:job_ref,
        :provider,:credential_ref,:model,:endpoint,'requested',:pricing_version,CAST(:rate_quote AS jsonb))''', params)
    started = time.monotonic()
    response = None
    try:
        response = await getattr(client, method)(url, **kwargs)
    finally:
        prompt = cached = completion = None
        amount = request_id = None
        state = 'unknown'
        if response is not None:
            state = 'succeeded' if response.is_success else 'error'
            try:
                data = response.json()
                if isinstance(data, dict):
                    if data.get('StateCode', 1) != 1 or isinstance(data.get('header'),dict) and data['header'].get('status',0) != 0:
                        state = 'error'
                if response.is_success and classify_response is not None:
                    state = classify_response(data)
                    if state not in {'succeeded', 'error', 'unknown'}:
                        state = 'unknown'
                prompt, cached, completion = extract_usage(data)
                request_id = safe_code(data.get('id')) if isinstance(data, dict) else None
                # An error response without token usage cannot be assumed free.
                if state == 'succeeded' or prompt is not None:
                    amount = estimate(quote, prompt, cached, completion)
            except (ValueError, TypeError):
                if response.is_success and classify_response is not None:
                    state = 'unknown'
            request_id = request_id or safe_code(response.headers.get('x-request-id'))
        # Independent committed transaction: later parse/business failure cannot
        # erase a charged provider call. Interrupted attempts remain requested.
        await _write('''UPDATE api_usage_events SET state=:state,status_code=:status_code,
            provider_request_id=:request_id,latency_ms=:latency_ms,prompt_tokens=:prompt,
            cached_tokens=:cached,completion_tokens=:completion,currency=:currency,
            estimated_amount=:amount,finished_at=CURRENT_TIMESTAMP
            WHERE id=CAST(:id AS uuid) AND state='requested' ''',
            dict(id=event_id, state=state, status_code=response.status_code if response is not None else None,
                 request_id=request_id, latency_ms=min(int((time.monotonic()-started)*1000), 2147483647),
                 prompt=prompt,cached=cached,completion=completion,
                 currency='CNY' if amount is not None else None, amount=amount))
    return response
