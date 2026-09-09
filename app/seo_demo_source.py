"""Trusted dual-data-source routing for same-site SEO demonstrations.

Authentication and the trusted tenant binding always use the primary database.
An active production control record can map that authenticated tenant to the
isolated demo database; no request parameter, header, tenant id, site id or
dataset key selects a data source.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import visitors
from sqlalchemy.sql.elements import BindParameter

from app.config import get_settings
from app.database import get_session as get_primary_session
from app.models.demo_tenant_binding import DemoTenantBinding
from app.security.auth import AuthContext, enforce_scoped_request, require_auth


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DEMO_SCHEMA_REVISION = "0098_demo_binding_no_truncate"
DATASET_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DATASET_VERSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
CLIENT_DATA_SOURCE_QUERY_KEYS = frozenset({"dataset", "data_source", "database"})
CLIENT_DATA_SOURCE_HEADER_KEYS = frozenset(
    {"x-seo-dataset", "x-seo-data-source", "x-seo-database"}
)


class DemoDataSourceError(RuntimeError):
    """The trusted demo binding or target cannot be proved safe."""


@dataclass(frozen=True)
class SeoDemoBinding:
    principal_tenant_id: int
    tenant_id: int
    dataset_key: str
    dataset_version: str
    binding_version: int
    schema_revision: str = DEMO_SCHEMA_REVISION


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


def _binding(row: DemoTenantBinding) -> SeoDemoBinding:
    if row.status != "active" or row.disabled_at is not None:
        raise DemoDataSourceError("SEO demo binding is disabled")
    dataset_key = str(row.dataset_key or "")
    dataset_version = str(row.dataset_version or "")
    if not DATASET_KEY_PATTERN.fullmatch(dataset_key):
        raise DemoDataSourceError("SEO demo binding dataset key is invalid")
    if not DATASET_VERSION_PATTERN.fullmatch(dataset_version):
        raise DemoDataSourceError("SEO demo binding dataset version is invalid")
    return SeoDemoBinding(
        principal_tenant_id=_positive_int(row.tenant_id, "tenant_id"),
        tenant_id=_positive_int(row.demo_tenant_id, "demo_tenant_id"),
        dataset_key=dataset_key,
        dataset_version=dataset_version,
        binding_version=_positive_int(row.version, "version"),
    )


async def resolve_seo_data_source(
    settings: object,
    ctx: AuthContext,
    primary_session: AsyncSession,
) -> SeoDataSourceDecision:
    """Resolve from primary authentication and the reviewed control table only."""
    if ctx.user_id is None or ctx.tenant_id is None:
        return SeoDataSourceDecision(source="primary")
    if not bool(getattr(settings, "seo_demo_data_source_enabled", False)):
        return SeoDataSourceDecision(source="primary")
    try:
        matches = list(
            (
                await primary_session.execute(
                    select(DemoTenantBinding).where(
                        DemoTenantBinding.tenant_id == ctx.tenant_id
                    )
                )
            ).scalars()
        )
    except Exception as exc:
        raise DemoDataSourceError("SEO demo binding lookup failed") from exc
    if not matches:
        return SeoDataSourceDecision(source="primary")
    if len(matches) != 1:
        raise DemoDataSourceError("SEO demo binding is ambiguous")
    binding = _binding(matches[0])
    if ctx.tenant_id != binding.principal_tenant_id:
        raise DemoDataSourceError("SEO demo authenticated tenant does not match its binding")
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
        if tenant_ids != {binding.principal_tenant_id}:
            raise HTTPException(403, "请求客户不属于服务端演示绑定")
    for value in (request.query_params.get("site_id"), request.path_params.get("site_id")):
        if value is not None:
            _request_int(value, "site_id")


def _mapped_value(value: Any, source_tenant_id: int, target_tenant_id: int) -> Any:
    if value == source_tenant_id:
        return target_tenant_id
    if isinstance(value, tuple):
        return tuple(_mapped_value(item, source_tenant_id, target_tenant_id) for item in value)
    if isinstance(value, list):
        return [_mapped_value(item, source_tenant_id, target_tenant_id) for item in value]
    if isinstance(value, set):
        return {_mapped_value(item, source_tenant_id, target_tenant_id) for item in value}
    return value


def _map_tenant_statement(statement: Any, binding: SeoDemoBinding) -> Any:
    def replace_bind(element: Any) -> Any:
        if isinstance(element, BindParameter) and getattr(element, "_orig_key", None) == "tenant_id":
            mapped = _mapped_value(
                element.value, binding.principal_tenant_id, binding.tenant_id
            )
            if mapped != element.value:
                return element._with_value(mapped, maintain_key=True)
        return None

    try:
        return visitors.replacement_traverse(statement, {}, replace_bind)
    except TypeError:
        return statement


def _map_tenant_parameters(parameters: Any, binding: SeoDemoBinding) -> Any:
    if isinstance(parameters, dict):
        return {
            key: (
                _mapped_value(value, binding.principal_tenant_id, binding.tenant_id)
                if key == "tenant_id" or key.endswith("_tenant_id")
                else value
            )
            for key, value in parameters.items()
        }
    if isinstance(parameters, list):
        return [_map_tenant_parameters(item, binding) for item in parameters]
    return parameters


class SeoDemoSession:
    """Read-only facade that maps only server-trusted tenant predicates."""

    def __init__(self, session: AsyncSession, binding: SeoDemoBinding):
        self._session = session
        self._binding = binding

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    async def execute(self, statement: Any, params: Any = None, **kwargs: Any) -> Any:
        return await self._session.execute(
            _map_tenant_statement(statement, self._binding),
            _map_tenant_parameters(params, self._binding),
            **kwargs,
        )

    async def scalar(self, statement: Any, params: Any = None, **kwargs: Any) -> Any:
        return await self._session.scalar(
            _map_tenant_statement(statement, self._binding),
            _map_tenant_parameters(params, self._binding),
            **kwargs,
        )

    async def scalars(self, statement: Any, params: Any = None, **kwargs: Any) -> Any:
        return await self._session.scalars(
            _map_tenant_statement(statement, self._binding),
            _map_tenant_parameters(params, self._binding),
            **kwargs,
        )

    async def stream(self, statement: Any, params: Any = None, **kwargs: Any) -> Any:
        return await self._session.stream(
            _map_tenant_statement(statement, self._binding),
            _map_tenant_parameters(params, self._binding),
            **kwargs,
        )

    async def stream_scalars(self, statement: Any, params: Any = None, **kwargs: Any) -> Any:
        return await self._session.stream_scalars(
            _map_tenant_statement(statement, self._binding),
            _map_tenant_parameters(params, self._binding),
            **kwargs,
        )

    async def get(self, entity: Any, ident: Any, **kwargs: Any) -> Any:
        if getattr(getattr(entity, "__table__", None), "name", None) == "tenants":
            ident = _mapped_value(
                ident, self._binding.principal_tenant_id, self._binding.tenant_id
            )
        return await self._session.get(entity, ident, **kwargs)


def hide_demo_tenant_ids(value: Any, binding: SeoDemoBinding) -> Any:
    """Map demo tenant ids in JSON payloads back to the public tenant."""
    if isinstance(value, dict):
        return {
            key: (
                binding.principal_tenant_id
                if key == "tenant_id" and item == binding.tenant_id
                else hide_demo_tenant_ids(item, binding)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [hide_demo_tenant_ids(item, binding) for item in value]
    return value


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
                       site_settings ->> 'dataset_version' AS dataset_version,
                       site_settings ->> 'synthetic' AS synthetic,
                       site_settings ->> 'scheduler_excluded' AS scheduler_excluded,
                       site_settings ->> 'external_actions_disabled' AS external_actions_disabled
                FROM seo_sites
                WHERE tenant_id = :tenant_id
                ORDER BY id
                """
            ),
            {"tenant_id": binding.tenant_id},
        )
    ).all()
    actual_rows = {
        int(site_id): (
            int(tenant_id),
            fixture_marker,
            dataset_version,
            synthetic,
            scheduler_excluded,
            external_actions_disabled,
        )
        for site_id, tenant_id, fixture_marker, dataset_version, synthetic, scheduler_excluded, external_actions_disabled in rows
    }
    expected_marker = (
        binding.tenant_id,
        binding.dataset_key,
        binding.dataset_version,
        "true",
        "true",
        "true",
    )
    if not actual_rows or any(row != expected_marker for row in actual_rows.values()):
        raise DemoDataSourceError("SEO demo dataset marker or safety flags do not match")


async def require_seo_auth(
    request: Request,
    ctx: AuthContext = Depends(require_auth),
    primary_session: AsyncSession = Depends(get_primary_session),
) -> AuthContext:
    """Authenticate in primary DB, then apply a trusted SEO-only binding."""
    _reject_client_data_source_selector(request)
    try:
        decision = await resolve_seo_data_source(get_settings(), ctx, primary_session)
    except DemoDataSourceError as exc:
        raise HTTPException(503, "SEO 演示数据源暂不可用") from exc
    request.state.seo_data_source_decision = decision
    if decision.source == "primary":
        return ctx
    assert decision.binding is not None
    _enforce_demo_request(request, decision.binding)
    return ctx


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
                yield SeoDemoSession(session, decision.binding)
            finally:
                await session.rollback()
    except DemoDataSourceError as exc:
        raise HTTPException(503, "SEO 演示数据源校验失败") from exc
