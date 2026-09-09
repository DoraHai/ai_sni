"""Trusted dual-data-source routing for same-site SEO demonstrations.

Authentication always uses the primary database.  Only a production identity
listed by server configuration can be mapped to the isolated demo database;
no request parameter, header, tenant id, site id or dataset key selects a data
source.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database import get_session as get_primary_session
from app.security.auth import AuthContext, enforce_scoped_request, require_auth


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CLIENT_DATA_SOURCE_QUERY_KEYS = frozenset({"dataset", "data_source", "database"})
CLIENT_DATA_SOURCE_HEADER_KEYS = frozenset(
    {"x-seo-dataset", "x-seo-data-source", "x-seo-database"}
)


class DemoDataSourceError(RuntimeError):
    """The trusted demo binding or target cannot be proved safe."""


@dataclass(frozen=True)
class SeoDemoBinding:
    principal_user_id: int
    principal_tenant_id: int
    tenant_id: int
    site_ids: tuple[int, ...]
    dataset_key: str
    schema_revision: str
    enabled: bool


@dataclass(frozen=True)
class SeoDataSourceDecision:
    source: str
    binding: SeoDemoBinding | None = None


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise DemoDataSourceError(f"{field} must be a positive integer")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise DemoDataSourceError(f"{field} must be a positive integer") from exc
    if str(value).strip() != str(parsed) or parsed <= 0:
        raise DemoDataSourceError(f"{field} must be a positive integer")
    return parsed


def _principal_ids(raw: object) -> frozenset[int]:
    values: set[int] = set()
    for entry in str(raw or "").split(","):
        if not entry.strip():
            continue
        value = _positive_int(entry.strip(), "SEO demo principal user id")
        if value in values:
            raise DemoDataSourceError("duplicate SEO demo principal user id")
        values.add(value)
    return frozenset(values)


def _binding(row: object) -> SeoDemoBinding:
    if not isinstance(row, Mapping):
        raise DemoDataSourceError("SEO demo binding must be an object")
    allowed = {
        "principal_user_id",
        "principal_tenant_id",
        "tenant_id",
        "site_ids",
        "dataset_key",
        "schema_revision",
        "enabled",
    }
    if set(row) != allowed:
        raise DemoDataSourceError("SEO demo binding fields do not match the reviewed contract")
    raw_sites = row.get("site_ids")
    if not isinstance(raw_sites, list) or not raw_sites:
        raise DemoDataSourceError("SEO demo binding requires at least one site id")
    site_ids = tuple(_positive_int(value, "SEO demo site id") for value in raw_sites)
    if len(set(site_ids)) != len(site_ids):
        raise DemoDataSourceError("SEO demo binding contains duplicate site ids")
    dataset_key = str(row.get("dataset_key") or "").strip()
    revision = str(row.get("schema_revision") or "").strip()
    if not dataset_key or not revision:
        raise DemoDataSourceError("SEO demo binding requires dataset key and schema revision")
    if not isinstance(row.get("enabled"), bool):
        raise DemoDataSourceError("SEO demo binding enabled must be boolean")
    return SeoDemoBinding(
        principal_user_id=_positive_int(row.get("principal_user_id"), "principal_user_id"),
        principal_tenant_id=_positive_int(row.get("principal_tenant_id"), "principal_tenant_id"),
        tenant_id=_positive_int(row.get("tenant_id"), "tenant_id"),
        site_ids=site_ids,
        dataset_key=dataset_key,
        schema_revision=revision,
        enabled=bool(row["enabled"]),
    )


def _bindings(raw: object) -> tuple[SeoDemoBinding, ...]:
    try:
        value = json.loads(str(raw or "[]"))
    except json.JSONDecodeError as exc:
        raise DemoDataSourceError("SEO demo bindings are not valid JSON") from exc
    if not isinstance(value, list):
        raise DemoDataSourceError("SEO demo bindings must be a JSON list")
    return tuple(_binding(row) for row in value)


def resolve_seo_data_source(settings: object, ctx: AuthContext) -> SeoDataSourceDecision:
    """Resolve from authenticated identity and server configuration only."""
    protected = _principal_ids(getattr(settings, "seo_demo_principal_user_ids", ""))
    if ctx.user_id is None or ctx.user_id not in protected:
        return SeoDataSourceDecision(source="primary")
    if not bool(getattr(settings, "seo_demo_data_source_enabled", False)):
        raise DemoDataSourceError("SEO demo data source is disabled")
    matches = [
        item
        for item in _bindings(getattr(settings, "seo_demo_bindings_json", "[]"))
        if item.principal_user_id == ctx.user_id
    ]
    if not matches:
        raise DemoDataSourceError("SEO demo binding is missing")
    if len(matches) != 1:
        raise DemoDataSourceError("SEO demo binding is ambiguous")
    binding = matches[0]
    if not binding.enabled:
        raise DemoDataSourceError("SEO demo binding is disabled")
    if ctx.tenant_id != binding.principal_tenant_id:
        raise DemoDataSourceError("SEO demo identity tenant does not match its binding")
    return SeoDataSourceDecision(source="demo", binding=binding)


def _request_int(value: object, field: str) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"{field} 必须是整数") from exc
    if str(value).strip() != str(parsed):
        raise HTTPException(422, f"{field} 必须是整数")
    return parsed


def _reject_client_data_source_selector(request: Request) -> None:
    if CLIENT_DATA_SOURCE_QUERY_KEYS.intersection(request.query_params.keys()):
        raise HTTPException(400, "数据源只能由服务端身份绑定决定")
    header_names = {key.lower() for key in request.headers.keys()}
    if CLIENT_DATA_SOURCE_HEADER_KEYS.intersection(header_names):
        raise HTTPException(400, "数据源只能由服务端身份绑定决定")


def _enforce_demo_request(request: Request, binding: SeoDemoBinding) -> None:
    method = request.method.upper()
    path = request.url.path.rstrip("/") or "/"
    if method not in SAFE_METHODS:
        raise HTTPException(403, "演示客户仅允许只读访问")
    if "/oauth/" in path or path.startswith("/api/v1/oauth/"):
        raise HTTPException(403, "演示客户禁止 OAuth 操作")
    tenant_values = [
        value
        for value in (
            request.query_params.get("tenant_id"),
            request.path_params.get("tenant_id"),
        )
        if value is not None
    ]
    if tenant_values:
        tenant_ids = {_request_int(value, "tenant_id") for value in tenant_values}
        if tenant_ids != {binding.tenant_id}:
            raise HTTPException(403, "请求客户不属于服务端演示绑定")
    site_values = [
        value
        for value in (
            request.query_params.get("site_id"),
            request.path_params.get("site_id"),
        )
        if value is not None
    ]
    if site_values:
        site_ids = {_request_int(value, "site_id") for value in site_values}
        if len(site_ids) != 1 or not site_ids.issubset(binding.site_ids):
            raise HTTPException(403, "请求网站不属于服务端演示绑定")


def _demo_database_target(settings: object) -> tuple[str, str, frozenset[str]]:
    raw_url = str(getattr(settings, "seo_demo_database_url", "") or "").strip()
    expected_name = str(getattr(settings, "seo_demo_database_name", "") or "").strip()
    hosts = {
        entry.strip().lower()
        for entry in str(
            getattr(settings, "seo_demo_database_host_allowlist", "") or ""
        ).split(",")
        if entry.strip()
    }
    server_addresses = frozenset(
        entry.strip()
        for entry in str(
            getattr(settings, "seo_demo_database_server_addr_allowlist", "") or ""
        ).split(",")
        if entry.strip()
    )
    if (
        not raw_url
        or not expected_name
        or not hosts
        or not server_addresses
        or any("*" in value for value in (*hosts, *server_addresses))
    ):
        raise DemoDataSourceError("SEO demo database target is incomplete")
    try:
        url = make_url(raw_url)
    except Exception as exc:
        raise DemoDataSourceError("SEO demo database URL is invalid") from exc
    if url.drivername != "postgresql+asyncpg":
        raise DemoDataSourceError("SEO demo database must use postgresql+asyncpg")
    if not url.host or url.host.lower() not in hosts:
        raise DemoDataSourceError("SEO demo database host is not allowed")
    if url.database != expected_name or expected_name in {"postgres", "template0", "template1"}:
        raise DemoDataSourceError("SEO demo database name is not allowed")
    primary = make_url(str(getattr(settings, "database_url", "")))
    if (primary.host, primary.port, primary.database) == (url.host, url.port, url.database):
        raise DemoDataSourceError("SEO demo database must be isolated from the primary database")
    return raw_url, expected_name, server_addresses


@lru_cache(maxsize=4)
def _demo_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        echo=False,
    )
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _validate_demo_session(
    session: AsyncSession,
    binding: SeoDemoBinding,
    expected_database: str,
    expected_server_addresses: frozenset[str],
) -> None:
    database, server_address = (
        await session.execute(
            text("SELECT current_database(), inet_server_addr()::text")
        )
    ).one()
    if database != expected_database or server_address not in expected_server_addresses:
        raise DemoDataSourceError("connected SEO demo database identity does not match")
    revisions = list(
        (
            await session.execute(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            )
        ).scalars()
    )
    if revisions != [binding.schema_revision]:
        raise DemoDataSourceError("SEO demo database schema revision does not match")
    rows = (
        await session.execute(
            text(
                """
                SELECT id, tenant_id,
                       site_settings ->> 'fixture_marker' AS fixture_marker,
                       site_settings ->> 'synthetic' AS synthetic,
                       site_settings ->> 'scheduler_excluded' AS scheduler_excluded,
                       site_settings ->> 'external_actions_disabled' AS external_actions_disabled
                FROM seo_sites
                WHERE tenant_id = :tenant_id AND id = ANY(CAST(:site_ids AS bigint[]))
                ORDER BY id
                """
            ),
            {"tenant_id": binding.tenant_id, "site_ids": list(binding.site_ids)},
        )
    ).all()
    expected_rows = {
        site_id: (binding.tenant_id, binding.dataset_key, "true", "true", "true")
        for site_id in binding.site_ids
    }
    actual_rows = {
        int(site_id): (
            int(tenant_id),
            fixture_marker,
            synthetic,
            scheduler_excluded,
            external_actions_disabled,
        )
        for site_id, tenant_id, fixture_marker, synthetic, scheduler_excluded, external_actions_disabled in rows
    }
    if actual_rows != expected_rows:
        raise DemoDataSourceError("SEO demo dataset marker or safety flags do not match")


async def require_seo_auth(
    request: Request,
    ctx: AuthContext = Depends(require_auth),
) -> AuthContext:
    """Authenticate in primary DB, then apply a trusted SEO-only binding."""
    _reject_client_data_source_selector(request)
    try:
        decision = resolve_seo_data_source(get_settings(), ctx)
    except DemoDataSourceError as exc:
        raise HTTPException(503, "SEO 演示数据源暂不可用") from exc
    request.state.seo_data_source_decision = decision
    if decision.source == "primary":
        return ctx
    assert decision.binding is not None
    _enforce_demo_request(request, decision.binding)
    return replace(ctx, tenant_id=decision.binding.tenant_id, is_superadmin=False)


async def require_seo_scoped_auth(
    request: Request,
    ctx: AuthContext = Depends(require_seo_auth),
) -> AuthContext:
    return await enforce_scoped_request(request, ctx)


async def get_seo_session(
    request: Request,
    _ctx: AuthContext = Depends(require_seo_auth),
    primary_session: AsyncSession = Depends(get_primary_session),
) -> AsyncIterator[AsyncSession]:
    """Yield primary or verified demo session; demo transaction is read-only."""
    decision: SeoDataSourceDecision = request.state.seo_data_source_decision
    if decision.source == "primary":
        # FastAPI caches get_primary_session, so this is the same primary
        # session already used by require_auth rather than a second connection.
        yield primary_session
        return
    assert decision.binding is not None
    try:
        database_url, expected_database, expected_server_addresses = _demo_database_target(
            get_settings()
        )
        factory = _demo_session_factory(database_url)
        async with factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await _validate_demo_session(
                session,
                decision.binding,
                expected_database,
                expected_server_addresses,
            )
            try:
                yield session
            finally:
                await session.rollback()
    except DemoDataSourceError as exc:
        raise HTTPException(503, "SEO 演示数据源校验失败") from exc
