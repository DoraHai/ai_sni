"""Trusted SEM demo binding, action gate, and isolated read-only routing."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import re

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings, parse_positive_id_csv
from app.database import get_session as get_primary_session
from app.security.auth import AuthContext, require_scoped_auth


REQUIRED_SCHEMA_REVISION = "0098_demo_binding_no_truncate"
FIXTURE_REGISTRY_TABLE = "demo_control.fixture_registry"
SAFE_METHODS = frozenset({"GET"})
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
        "x-data-source", "x-database", "x-dataset", "x-dataset-key",
        "x-demo-tenant-id", "x-tenant-id", "x-sem-data-source", "x-sem-database",
    }
)


class SemDemoSourceError(RuntimeError):
    """The binding or isolated demo target cannot be proved safe."""


class SemDemoActionBlockedError(RuntimeError):
    """A production-side action cannot prove that its tenant is non-demo."""


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


@dataclass(frozen=True)
class SemDemoDatabaseTarget:
    database_url: str
    database: str
    username: str
    server_addresses: frozenset[str]
    dataset_key: str
    dataset_version: str
    manifest_sha256: str


_BINDING_REVISION_SQL = text("SELECT version_num FROM alembic_version ORDER BY version_num")
_BINDING_SQL = text("""
    SELECT tenant_id, demo_tenant_id, dataset_key, dataset_version, status, version
    FROM public.demo_tenant_bindings
    WHERE tenant_id = :tenant_id
""")
_ALL_BINDING_STATES_SQL = text(
    "SELECT tenant_id, status FROM public.demo_tenant_bindings"
)


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


async def _require_control_revision(primary_session: AsyncSession) -> None:
    revisions = list((await primary_session.execute(_BINDING_REVISION_SQL)).scalars())
    if revisions != [REQUIRED_SCHEMA_REVISION]:
        raise SemDemoSourceError("SEM demo binding schema revision is not trusted")


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
        principal_tenant_id <= 0 or demo_tenant_id <= 0 or binding_version <= 0
        or not dataset_key or not dataset_version or row.get("status") != "active"
    ):
        raise SemDemoSourceError("SEM demo binding is inactive or malformed")
    return SemDemoBinding(
        principal_tenant_id, demo_tenant_id, dataset_key, dataset_version, binding_version
    )


async def _binding_rows(primary_session: AsyncSession, tenant_id: int):
    return (
        await primary_session.execute(_BINDING_SQL, {"tenant_id": tenant_id})
    ).mappings().all()


async def resolve_sem_data_source(
    settings: object,
    ctx: AuthContext,
    primary_session: AsyncSession,
    effective_tenant_id: int | None = None,
) -> SemDataSourceDecision:
    """Resolve only after production authentication, scope, RBAC and entitlement."""
    tenant_id = effective_tenant_id if effective_tenant_id is not None else ctx.tenant_id
    if tenant_id is None:
        return SemDataSourceDecision(source="primary")
    protected = _protected_tenant_ids(settings)
    if (
        not bool(getattr(settings, "sem_demo_data_source_enabled", False))
        and tenant_id not in protected
    ):
        return SemDataSourceDecision(source="primary")
    try:
        await _require_control_revision(primary_session)
        rows = await _binding_rows(primary_session, tenant_id)
    except Exception as exc:
        if tenant_id in protected:
            raise SemDemoSourceError("SEM demo binding cannot be verified") from exc
        raise
    if not rows:
        if tenant_id in protected:
            raise SemDemoSourceError("SEM demo binding is missing")
        return SemDataSourceDecision(source="primary")
    if len(rows) != 1:
        raise SemDemoSourceError("SEM demo binding is ambiguous")
    row = rows[0]
    if row.get("status") != "active":
        if tenant_id in protected:
            raise SemDemoSourceError("SEM demo binding is disabled")
        return SemDataSourceDecision(source="primary")
    if not bool(getattr(settings, "sem_demo_data_source_enabled", False)):
        raise SemDemoSourceError("SEM demo data source is disabled")
    binding = _binding_from_row(row)
    if binding.principal_tenant_id != tenant_id:
        raise SemDemoSourceError("SEM demo binding identity mismatch")
    if (
        binding.dataset_key != str(getattr(settings, "sem_demo_dataset_key", "") or "")
        or binding.dataset_version
        != str(getattr(settings, "sem_demo_dataset_version", "") or "")
    ):
        raise SemDemoSourceError("SEM demo dataset is not server-approved")
    return SemDataSourceDecision(source="demo", binding=binding)


async def blocked_sem_demo_tenant_ids(
    settings: object, primary_session: AsyncSession, tenant_ids: set[int] | frozenset[int]
) -> frozenset[int]:
    """Return tenants whose background/action path must fail closed."""
    if not tenant_ids:
        return frozenset()
    protected = _protected_tenant_ids(settings)
    enabled = bool(getattr(settings, "sem_demo_data_source_enabled", False))
    if not enabled and not protected:
        return frozenset()
    if not enabled or not protected:
        raise SemDemoActionBlockedError("SEM demo action guard configuration is incomplete")
    try:
        await _require_control_revision(primary_session)
        rows = (await primary_session.execute(_ALL_BINDING_STATES_SQL)).mappings().all()
    except Exception as exc:
        raise SemDemoActionBlockedError("SEM demo binding state unavailable") from exc
    active = {
        int(row["tenant_id"])
        for row in rows
        if row.get("status") == "active" and int(row["tenant_id"]) in tenant_ids
    }
    return frozenset(active | (protected & tenant_ids))


async def ensure_sem_production_action_allowed(
    settings: object, primary_session: AsyncSession, tenant_id: int
) -> None:
    blocked = await blocked_sem_demo_tenant_ids(settings, primary_session, {int(tenant_id)})
    if int(tenant_id) in blocked:
        raise SemDemoActionBlockedError("SEM demo tenant actions are blocked")


def _enforce_bound_request(request: Request, binding: SemDemoBinding) -> None:
    path = request.url.path.rstrip("/") or "/"
    if request.method.upper() not in SAFE_METHODS or not _is_demo_read_path(path):
        raise HTTPException(403, "SEM 演示身份只允许核准的只读接口")
    tenant_values = request.query_params.getlist("tenant_id")
    tenant_values.extend(
        str(value) for key, value in request.path_params.items() if key == "tenant_id"
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


async def enforce_sem_demo_access(
    settings: object, request: Request, ctx: AuthContext, primary_session: AsyncSession
) -> AuthContext:
    """Apply the binding only after require_scoped_auth completed production checks."""
    _reject_client_source_selector(request)
    effective_tenant_id = getattr(request.state, "sem_effective_tenant_id", None)
    try:
        decision = await resolve_sem_data_source(
            settings, ctx, primary_session, effective_tenant_id
        )
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


def resolve_sem_data_account_id(request: Request, account_id: int | None) -> int | None:
    if account_id is None:
        return None
    decision = getattr(request.state, "sem_data_source_decision", None)
    if not isinstance(decision, SemDataSourceDecision) or decision.source == "primary":
        return account_id
    mapping = getattr(request.state, "sem_demo_account_alias_to_id", None)
    if not isinstance(mapping, dict) or account_id not in mapping:
        raise HTTPException(404, "演示范围不存在此账户")
    return int(mapping[account_id])


def _present_account_ids(value, reverse: dict[int, int], key: str | None = None):
    if isinstance(value, dict):
        return {name: _present_account_ids(item, reverse, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_present_account_ids(item, reverse, key) for item in value]
    if isinstance(value, int) and (
        key == "baidu_account_id" or (key is not None and key.endswith("account_ids"))
    ):
        if value not in reverse:
            raise HTTPException(503, "SEM 演示响应账户范围不一致")
        return reverse[value]
    return value


def present_sem_read_result(request: Request, principal_tenant_id: int, result: dict) -> dict:
    """Keep production tenant identity and opaque account aliases in public output."""
    decision = getattr(request.state, "sem_data_source_decision", None)
    if not isinstance(decision, SemDataSourceDecision) or decision.source != "demo":
        return result
    if decision.binding is None or result.get("tenant_id") != decision.binding.demo_tenant_id:
        raise HTTPException(503, "SEM 演示响应租户范围不一致")
    reverse = getattr(request.state, "sem_demo_account_id_to_alias", None)
    if not isinstance(reverse, dict):
        raise HTTPException(503, "SEM 演示账户映射缺失")
    presented = _present_account_ids(result, reverse)
    return {
        **presented,
        "tenant_id": principal_tenant_id,
        "is_demo": True,
        "workspace_mode": "demo",
        "data_label": "全虚拟演示数据",
        "dataset_version": decision.binding.dataset_version,
    }


def _csv_values(value: object) -> frozenset[str]:
    return frozenset(
        item.strip().lower() for item in str(value or "").split(",") if item.strip()
    )


def _demo_database_target(settings: object) -> SemDemoDatabaseTarget:
    raw_url = str(getattr(settings, "sem_demo_database_url", "") or "").strip()
    expected_name = str(getattr(settings, "sem_demo_database_name", "") or "").strip()
    expected_user = str(getattr(settings, "sem_demo_database_user", "") or "").strip()
    hosts = _csv_values(getattr(settings, "sem_demo_database_host_allowlist", ""))
    addresses = frozenset(
        item.strip()
        for item in str(
            getattr(settings, "sem_demo_database_server_addr_allowlist", "") or ""
        ).split(",")
        if item.strip()
    )
    binding_revision = str(
        getattr(settings, "sem_demo_binding_schema_revision", "") or ""
    ).strip()
    demo_revision = str(
        getattr(settings, "sem_demo_database_schema_revision", "") or ""
    ).strip()
    dataset_key = str(getattr(settings, "sem_demo_dataset_key", "") or "").strip()
    dataset_version = str(getattr(settings, "sem_demo_dataset_version", "") or "").strip()
    manifest = str(getattr(settings, "sem_demo_manifest_sha256", "") or "").strip().lower()
    if (
        not raw_url or not expected_name or not expected_user or not hosts or not addresses
        or not dataset_key or not dataset_version
        or binding_revision != REQUIRED_SCHEMA_REVISION
        or demo_revision != REQUIRED_SCHEMA_REVISION
        or len(manifest) != 64 or any(ch not in "0123456789abcdef" for ch in manifest)
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
    if demo.username != expected_user:
        raise SemDemoSourceError("SEM demo database user is not allowed")
    if demo.database != expected_name or expected_name in {"postgres", "template0", "template1"}:
        raise SemDemoSourceError("SEM demo database name is not allowed")
    demo_target = (demo.host.lower(), demo.port or 5432, demo.database)
    primary_target = ((primary.host or "").lower(), primary.port or 5432, primary.database)
    if demo_target == primary_target:
        raise SemDemoSourceError("SEM demo database must be isolated from primary")
    return SemDemoDatabaseTarget(
        raw_url, expected_name, expected_user, addresses, dataset_key, dataset_version, manifest
    )


def validate_sem_demo_source_settings(settings: object) -> None:
    """Fail startup for partial or revision-downgraded routing configuration."""
    protected = _protected_tenant_ids(settings)
    enabled = bool(getattr(settings, "sem_demo_data_source_enabled", False))
    if not protected and not enabled:
        return
    if not protected or not enabled:
        raise RuntimeError("SEM demo source requires enabled=true and protected tenant IDs")
    try:
        _demo_database_target(settings)
    except SemDemoSourceError as exc:
        raise RuntimeError(str(exc)) from exc


@lru_cache(maxsize=4)
def _demo_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        database_url, pool_pre_ping=True, pool_size=5, max_overflow=5, echo=False
    )
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _account_alias(binding: SemDemoBinding, account_id: int) -> int:
    digest = hashlib.sha256(
        f"sem:{binding.principal_tenant_id}:{binding.binding_version}:"
        f"{binding.dataset_key}:{binding.dataset_version}:{account_id}".encode()
    ).digest()
    return (int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)) or 1


async def _validate_demo_session(
    session: AsyncSession, binding: SemDemoBinding, target: SemDemoDatabaseTarget
) -> tuple[dict[int, int], dict[int, int]]:
    identity = (
        await session.execute(
            text(
                "SELECT current_database(), current_user, inet_server_addr()::text, "
                "current_setting('transaction_read_only')"
            )
        )
    ).one()
    if (
        identity[0] != target.database
        or identity[1] != target.username
        or identity[2] not in target.server_addresses
        or identity[3] != "on"
    ):
        raise SemDemoSourceError("connected SEM demo database identity is not trusted")
    role = (
        await session.execute(
            text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
                "rolbypassrls, rolcanlogin FROM pg_catalog.pg_roles WHERE rolname=current_user"
            )
        )
    ).one_or_none()
    if role != (False, False, False, False, False, True):
        raise SemDemoSourceError("SEM demo reader role attributes are unsafe")
    revisions = list((await session.execute(_BINDING_REVISION_SQL)).scalars())
    if revisions != [REQUIRED_SCHEMA_REVISION]:
        raise SemDemoSourceError("SEM demo database schema revision does not match")

    unsafe_table_grant = await session.scalar(text("""
        SELECT coalesce(bool_or(pg_catalog.has_table_privilege(
            current_user, c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
        )), false)
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('public','demo_control') AND c.relkind IN ('r','p')
    """))
    unsafe_sequence_grant = await session.scalar(text("""
        SELECT coalesce(bool_or(pg_catalog.has_sequence_privilege(
            current_user, c.oid, 'USAGE,UPDATE'
        )), false)
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('public','demo_control') AND c.relkind='S'
    """))
    unsafe_schema_create = await session.scalar(text("""
        SELECT pg_catalog.has_schema_privilege(current_user, 'public', 'CREATE')
            OR pg_catalog.has_schema_privilege(current_user, 'demo_control', 'CREATE')
    """))
    unsafe_database_grant = await session.scalar(text("""
        SELECT pg_catalog.has_database_privilege(current_user, current_database(), 'CREATE')
            OR pg_catalog.has_database_privilege(current_user, current_database(), 'TEMPORARY')
    """))
    if any((unsafe_table_grant, unsafe_sequence_grant, unsafe_schema_create, unsafe_database_grant)):
        raise SemDemoSourceError("SEM demo database role has mutation privileges")

    receipts = (
        await session.execute(
            text(
                f"SELECT dataset_key, dataset_version, manifest_sha256, schema_revision, "
                f"tenant_id, load_status, loaded_at, verified_at FROM {FIXTURE_REGISTRY_TABLE} "
                "WHERE module='sem' AND tenant_id=:tenant_id"
            ),
            {"tenant_id": binding.demo_tenant_id},
        )
    ).all()
    expected_prefix = (
        binding.dataset_key, binding.dataset_version, target.manifest_sha256,
        REQUIRED_SCHEMA_REVISION, binding.demo_tenant_id, "ready",
    )
    if (
        len(receipts) != 1 or tuple(receipts[0][:6]) != expected_prefix
        or receipts[0][6] is None or receipts[0][7] is None
        or binding.dataset_key != target.dataset_key
        or binding.dataset_version != target.dataset_version
    ):
        raise SemDemoSourceError("SEM fixture loader registry is not ready or does not match")

    marker_rows = (
        await session.execute(
            text("""
                SELECT tm.status, tm.module_settings ->> 'data_mode',
                       tm.module_settings ->> 'fixture_key',
                       tm.module_settings ->> 'dataset_version'
                FROM public.tenants t JOIN public.tenant_modules tm ON tm.tenant_id=t.id
                WHERE t.id=:tenant_id AND tm.module_code='sem'
            """),
            {"tenant_id": binding.demo_tenant_id},
        )
    ).all()
    if marker_rows != [("active", "demo", binding.dataset_key, binding.dataset_version)]:
        raise SemDemoSourceError("SEM demo dataset marker does not match its binding")

    accounts = (
        await session.execute(
            text("""
                SELECT id, status, auth_mode, sync_status FROM public.baidu_accounts
                WHERE tenant_id=:tenant_id ORDER BY id
            """),
            {"tenant_id": binding.demo_tenant_id},
        )
    ).all()
    if not accounts or any(tuple(row[1:]) != ("disabled", "demo", "disabled") for row in accounts):
        raise SemDemoSourceError("SEM demo accounts are not fail-closed")
    alias_to_id: dict[int, int] = {}
    id_to_alias: dict[int, int] = {}
    for row in accounts:
        account_id = int(row[0])
        alias = _account_alias(binding, account_id)
        if alias in alias_to_id:
            raise SemDemoSourceError("SEM demo account aliases collide")
        alias_to_id[alias] = account_id
        id_to_alias[account_id] = alias
    return alias_to_id, id_to_alias


async def get_sem_read_session(
    request: Request,
    _ctx: AuthContext = Depends(require_scoped_auth),
    primary_session: AsyncSession = Depends(get_primary_session),
) -> AsyncIterator[AsyncSession]:
    """Yield a verified source only after the production scope dependency completes."""
    decision = getattr(request.state, "sem_data_source_decision", None)
    if not isinstance(decision, SemDataSourceDecision):
        raise HTTPException(503, "SEM 数据源决策缺失")
    if decision.source == "primary":
        yield primary_session
        return
    if decision.binding is None or not _is_demo_read_path(request.url.path):
        raise HTTPException(403, "SEM 演示数据库只允许核准的只读接口")
    try:
        target = _demo_database_target(get_settings())
        factory = _demo_session_factory(target.database_url)
        async with factory() as session:
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            alias_to_id, id_to_alias = await _validate_demo_session(
                session, decision.binding, target
            )
            session.info["sem_demo_read"] = True
            session.info["sem_demo_account_alias_to_id"] = alias_to_id
            request.state.sem_demo_account_alias_to_id = alias_to_id
            request.state.sem_demo_account_id_to_alias = id_to_alias
            try:
                yield session
            finally:
                await session.rollback()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "SEM 演示数据源校验失败") from exc
