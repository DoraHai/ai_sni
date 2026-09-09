"""Trusted SEM demo binding and isolated read-only data source routing.

Authentication and permissions always come from the primary production
database.  A server-side protected-tenant list identifies principals that must
have one active ``0098_demo_binding_no_truncate`` binding.  Request headers,
query parameters and tenant values never select a database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
import re

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings, parse_positive_id_csv
from app.database import get_session as get_primary_session
from app.security.auth import AuthContext, require_scoped_auth


SAFE_METHODS = frozenset({"GET"})
PRIMARY_IDENTITY_PATHS = frozenset(
    {
        "/api/v1/auth/me",
        "/api/v1/auth/modules",
        "/api/v1/auth/tenants",
    }
)
DEMO_READ_PATHS = frozenset(
    {
        "/api/v1/dashboard/cockpit",
        "/api/v1/keywords/cockpit",
        "/api/v1/search-terms/cockpit",
    }
)
_KEYWORD_DETAIL_RE = re.compile(r"^/api/v1/keywords/cockpit/[1-9][0-9]*$")
CLIENT_SOURCE_QUERY_KEYS = frozenset(
    {"data_source", "database", "dataset", "dataset_key", "demo_tenant_id"}
)
CLIENT_SOURCE_HEADER_KEYS = frozenset(
    {
        "x-data-source",
        "x-database",
        "x-dataset",
        "x-dataset-key",
        "x-demo-tenant-id",
        "x-tenant-id",
        "x-sem-data-source",
        "x-sem-database",
    }
)


class SemDemoSourceError(RuntimeError):
    """The binding or isolated demo target cannot be proved safe."""


@dataclass(frozen=True)
class SemDemoBinding:
    principal_tenant_id: int
    demo_tenant_id: int
    dataset_key: str
    dataset_version: str
    binding_version: int


@dataclass(frozen=True)
class SemDataSourceDecision:
    source: str
    binding: SemDemoBinding | None = None


_BINDING_REVISION_SQL = text(
    "SELECT version_num FROM alembic_version ORDER BY version_num"
)
_BINDING_SQL = text("""
    SELECT tenant_id, demo_tenant_id, dataset_key, dataset_version, status, version
    FROM public.demo_tenant_bindings
    WHERE tenant_id = :tenant_id
""")


def _protected_tenant_ids(settings: object) -> frozenset[int]:
    return parse_positive_id_csv(
        str(getattr(settings, "sem_demo_principal_tenant_ids", "") or ""),
        label="SEM_DEMO_PRINCIPAL_TENANT_IDS",
    )


def _reject_client_source_selector(request: Request) -> None:
    if CLIENT_SOURCE_QUERY_KEYS.intersection(request.query_params.keys()):
        raise HTTPException(400, "SEM 数据源只能由服务端身份绑定决定")
    headers = {name.lower() for name in request.headers.keys()}
    if CLIENT_SOURCE_HEADER_KEYS.intersection(headers):
        raise HTTPException(400, "SEM 数据源只能由服务端身份绑定决定")


def _is_demo_read_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    return normalized in DEMO_READ_PATHS or bool(_KEYWORD_DETAIL_RE.fullmatch(normalized))


def _enforce_bound_request(request: Request, binding: SemDemoBinding) -> None:
    path = request.url.path.rstrip("/") or "/"
    if request.method.upper() not in SAFE_METHODS:
        raise HTTPException(403, "SEM 演示身份只允许核准的只读接口")
    if path in PRIMARY_IDENTITY_PATHS:
        if path == "/api/v1/auth/tenants":
            if set(request.query_params.keys()) != {"module"} or request.query_params.get(
                "module"
            ) != "sem":
                raise HTTPException(403, "SEM 演示身份只允许读取 SEM 客户范围")
        elif request.query_params:
            raise HTTPException(400, "身份预检接口不接受额外查询参数")
        return
    if not _is_demo_read_path(path):
        raise HTTPException(403, "SEM 演示身份只允许核准的只读接口")

    tenant_values = request.query_params.getlist("tenant_id")
    tenant_values.extend(
        [str(value) for key, value in request.path_params.items() if key == "tenant_id"]
    )
    if len(tenant_values) != 1:
        raise HTTPException(422, "SEM 演示读取必须提供唯一 tenant_id")
    try:
        requested_tenant = int(tenant_values[0])
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "tenant_id 必须是整数") from exc
    if str(requested_tenant) != str(tenant_values[0]).strip():
        raise HTTPException(422, "tenant_id 必须是整数")
    if requested_tenant != binding.principal_tenant_id:
        raise HTTPException(403, "请求客户不属于当前生产身份")


def _binding_from_row(row: Mapping[str, object]) -> SemDemoBinding:
    try:
        principal_tenant_id = int(row["tenant_id"])
        demo_tenant_id = int(row["demo_tenant_id"])
        binding_version = int(row["version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SemDemoSourceError("SEM demo binding has invalid identifiers") from exc
    dataset_key = str(row.get("dataset_key") or "").strip()
    dataset_version = str(row.get("dataset_version") or "").strip()
    if (
        principal_tenant_id <= 0
        or demo_tenant_id <= 0
        or binding_version <= 0
        or not dataset_key
        or not dataset_version
        or row.get("status") != "active"
    ):
        raise SemDemoSourceError("SEM demo binding is inactive or malformed")
    return SemDemoBinding(
        principal_tenant_id=principal_tenant_id,
        demo_tenant_id=demo_tenant_id,
        dataset_key=dataset_key,
        dataset_version=dataset_version,
        binding_version=binding_version,
    )


async def resolve_sem_data_source(
    settings: object,
    ctx: AuthContext,
    primary_session: AsyncSession,
) -> SemDataSourceDecision:
    """Resolve the source from authenticated production tenant identity only."""
    protected = _protected_tenant_ids(settings)
    if ctx.tenant_id is None or ctx.tenant_id not in protected:
        return SemDataSourceDecision(source="primary")
    if not bool(getattr(settings, "sem_demo_data_source_enabled", False)):
        raise SemDemoSourceError("SEM demo data source is disabled")

    required_revision = str(
        getattr(
            settings,
            "sem_demo_binding_schema_revision",
            "0098_demo_binding_no_truncate",
        )
        or ""
    ).strip()
    revisions = list((await primary_session.execute(_BINDING_REVISION_SQL)).scalars())
    if revisions != [required_revision]:
        raise SemDemoSourceError("SEM demo binding schema revision is not trusted")

    rows = (
        await primary_session.execute(_BINDING_SQL, {"tenant_id": ctx.tenant_id})
    ).mappings().all()
    if len(rows) != 1:
        raise SemDemoSourceError("SEM demo binding is missing or ambiguous")
    binding = _binding_from_row(rows[0])
    if binding.principal_tenant_id != ctx.tenant_id:
        raise SemDemoSourceError("SEM demo binding identity mismatch")
    return SemDataSourceDecision(source="demo", binding=binding)


async def enforce_sem_demo_access(
    settings: object,
    request: Request,
    ctx: AuthContext,
    primary_session: AsyncSession,
) -> AuthContext:
    """Apply binding and route policy before an authenticated endpoint runs."""
    _reject_client_source_selector(request)
    try:
        decision = await resolve_sem_data_source(settings, ctx, primary_session)
    except (SemDemoSourceError, ValueError) as exc:
        raise HTTPException(503, "SEM 演示数据绑定暂不可用") from exc
    request.state.sem_data_source_decision = decision
    if decision.source == "demo":
        assert decision.binding is not None
        _enforce_bound_request(request, decision.binding)
    return ctx


def resolve_sem_data_tenant_id(request: Request, principal_tenant_id: int) -> int:
    decision = getattr(request.state, "sem_data_source_decision", None)
    if not isinstance(decision, SemDataSourceDecision):
        raise HTTPException(503, "SEM 数据源决策缺失")
    if decision.source == "primary":
        return principal_tenant_id
    if decision.binding is None or decision.binding.principal_tenant_id != principal_tenant_id:
        raise HTTPException(503, "SEM 演示数据绑定不一致")
    return decision.binding.demo_tenant_id


def present_sem_read_result(
    request: Request,
    principal_tenant_id: int,
    result: dict,
) -> dict:
    """Keep the production tenant identity stable in the public response."""
    decision = getattr(request.state, "sem_data_source_decision", None)
    if (
        isinstance(decision, SemDataSourceDecision)
        and decision.source == "demo"
        and decision.binding is not None
    ):
        if result.get("tenant_id") != decision.binding.demo_tenant_id:
            raise HTTPException(503, "SEM 演示响应租户范围不一致")
        return {**result, "tenant_id": principal_tenant_id}
    return result


def _csv_values(value: object) -> frozenset[str]:
    return frozenset(
        item.strip().lower() for item in str(value or "").split(",") if item.strip()
    )


def _demo_database_target(settings: object) -> tuple[str, str, frozenset[str], str]:
    raw_url = str(getattr(settings, "sem_demo_database_url", "") or "").strip()
    expected_name = str(getattr(settings, "sem_demo_database_name", "") or "").strip()
    hosts = _csv_values(getattr(settings, "sem_demo_database_host_allowlist", ""))
    addresses = frozenset(
        item.strip()
        for item in str(
            getattr(settings, "sem_demo_database_server_addr_allowlist", "") or ""
        ).split(",")
        if item.strip()
    )
    schema_revision = str(
        getattr(settings, "sem_demo_database_schema_revision", "") or ""
    ).strip()
    if (
        not raw_url
        or not expected_name
        or not hosts
        or not addresses
        or not schema_revision
        or any("*" in item for item in (*hosts, *addresses))
    ):
        raise SemDemoSourceError("SEM demo database target is incomplete")
    try:
        demo = make_url(raw_url)
        primary = make_url(str(getattr(settings, "database_url", "") or ""))
    except Exception as exc:
        raise SemDemoSourceError("SEM demo database URL is invalid") from exc
    if demo.drivername != "postgresql+asyncpg":
        raise SemDemoSourceError("SEM demo database must use postgresql+asyncpg")
    if not demo.host or demo.host.lower() not in hosts:
        raise SemDemoSourceError("SEM demo database host is not allowed")
    if demo.database != expected_name or expected_name in {
        "postgres",
        "template0",
        "template1",
    }:
        raise SemDemoSourceError("SEM demo database name is not allowed")
    demo_target = (demo.host.lower(), demo.port or 5432, demo.database)
    primary_target = (
        (primary.host or "").lower(),
        primary.port or 5432,
        primary.database,
    )
    if demo_target == primary_target:
        raise SemDemoSourceError("SEM demo database must be isolated from primary")
    return raw_url, expected_name, addresses, schema_revision


def validate_sem_demo_source_settings(settings: object) -> None:
    """Fail startup for a partial server-side demo routing configuration."""
    protected = _protected_tenant_ids(settings)
    enabled = bool(getattr(settings, "sem_demo_data_source_enabled", False))
    if not protected and not enabled:
        return
    if not protected or not enabled:
        raise RuntimeError(
            "SEM demo source requires both enabled=true and protected tenant IDs"
        )
    try:
        _demo_database_target(settings)
    except SemDemoSourceError as exc:
        raise RuntimeError(str(exc)) from exc


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
    binding: SemDemoBinding,
    expected_database: str,
    expected_addresses: frozenset[str],
    expected_revision: str,
) -> None:
    database, server_address, transaction_read_only = (
        await session.execute(
            text(
                "SELECT current_database(), inet_server_addr()::text, "
                "current_setting('transaction_read_only')"
            )
        )
    ).one()
    if (
        database != expected_database
        or server_address not in expected_addresses
        or transaction_read_only != "on"
    ):
        raise SemDemoSourceError("connected SEM demo database identity is not trusted")

    revisions = list(
        (
            await session.execute(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            )
        ).scalars()
    )
    if revisions != [expected_revision]:
        raise SemDemoSourceError("SEM demo database schema revision does not match")

    unsafe_table_grant = await session.scalar(text("""
        SELECT coalesce(bool_or(pg_catalog.has_table_privilege(
            current_user, c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
        )), false)
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
    """))
    unsafe_sequence_grant = await session.scalar(text("""
        SELECT coalesce(bool_or(pg_catalog.has_sequence_privilege(
            current_user, c.oid, 'USAGE,UPDATE'
        )), false)
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'S'
    """))
    if unsafe_table_grant or unsafe_sequence_grant:
        raise SemDemoSourceError("SEM demo database role has write privileges")

    marker_rows = (
        await session.execute(
            text("""
                SELECT tm.status,
                       tm.module_settings ->> 'data_mode' AS data_mode,
                       tm.module_settings ->> 'fixture_key' AS fixture_key,
                       tm.module_settings ->> 'dataset_version' AS dataset_version
                FROM public.tenants t
                JOIN public.tenant_modules tm ON tm.tenant_id = t.id
                WHERE t.id = :tenant_id AND tm.module_code = 'sem'
            """),
            {"tenant_id": binding.demo_tenant_id},
        )
    ).all()
    expected_marker = (
        "active",
        "demo",
        binding.dataset_key,
        binding.dataset_version,
    )
    if marker_rows != [expected_marker]:
        raise SemDemoSourceError("SEM demo dataset marker does not match its binding")

    account_counts = (
        await session.execute(
            text("""
                SELECT count(*),
                       count(*) FILTER (WHERE status = 'active'),
                       count(*) FILTER (
                           WHERE auth_mode <> 'demo' OR sync_status <> 'disabled'
                       )
                FROM public.baidu_accounts
                WHERE tenant_id = :tenant_id
            """),
            {"tenant_id": binding.demo_tenant_id},
        )
    ).one()
    if account_counts[0] < 1 or account_counts[1:] != (0, 0):
        raise SemDemoSourceError("SEM demo accounts are not fail-closed")


async def get_sem_read_session(
    request: Request,
    _ctx: AuthContext = Depends(require_scoped_auth),
    primary_session: AsyncSession = Depends(get_primary_session),
) -> AsyncIterator[AsyncSession]:
    """Yield the primary or verified demo session for four approved reads only."""
    decision = getattr(request.state, "sem_data_source_decision", None)
    if not isinstance(decision, SemDataSourceDecision):
        await enforce_sem_demo_access(get_settings(), request, _ctx, primary_session)
        decision = getattr(request.state, "sem_data_source_decision", None)
    if not isinstance(decision, SemDataSourceDecision):
        raise HTTPException(503, "SEM 数据源决策缺失")
    if decision.source == "primary":
        yield primary_session
        return
    if decision.binding is None or not _is_demo_read_path(request.url.path):
        raise HTTPException(403, "SEM 演示数据库只允许核准的只读接口")

    try:
        database_url, database_name, addresses, revision = _demo_database_target(
            get_settings()
        )
        factory = _demo_session_factory(database_url)
    except Exception as exc:
        raise HTTPException(503, "SEM 演示数据源校验失败") from exc

    try:
        async with factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await _validate_demo_session(
                session,
                decision.binding,
                database_name,
                addresses,
                revision,
            )
            try:
                yield session
            finally:
                await session.rollback()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "SEM 演示数据源校验失败") from exc
