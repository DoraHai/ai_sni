"""Verified read-only session routing for a tenant bound by contract 0098."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database import async_session_factory, get_session
from app.geo.demo_tenant import DEMO_DATASET_KEY, GeoDemoBindingUnavailable
from app.geo.tenant_scope import ensure_geo_entitlement
from app.security.auth import AuthContext, require_scoped_auth


REQUIRED_SCHEMA_REVISION = "0098_demo_binding_no_truncate"
FIXTURE_REGISTRY_TABLE = "public.geo_demo_fixture_registry"


@dataclass(frozen=True)
class GeoDemoDatabaseTarget:
    database_url: str
    database: str
    username: str
    server_addresses: frozenset[str]
    schema_revision: str
    manifest_sha256: str


def _required(env: Mapping[str, str], key: str) -> str:
    value = str(env.get(key) or "").strip()
    if not value:
        raise GeoDemoBindingUnavailable("演示只读数据源配置不完整")
    return value


def resolve_demo_database_target(policy, env: Mapping[str, str] | None = None):
    """Resolve one fixed server mapping; request data never participates."""
    env = os.environ if env is None else env
    if not policy.is_demo or policy.dataset_key != DEMO_DATASET_KEY:
        raise GeoDemoBindingUnavailable()
    if _required(env, "GEO_DEMO_DATASET_KEY") != policy.dataset_key:
        raise GeoDemoBindingUnavailable("演示数据集标识不匹配")
    if _required(env, "GEO_DEMO_DATASET_VERSION") != policy.dataset_version:
        raise GeoDemoBindingUnavailable("演示数据集版本不匹配")

    raw_url = _required(env, "GEO_DEMO_DATABASE_URL")
    database = _required(env, "GEO_DEMO_DATABASE_NAME")
    username = _required(env, "GEO_DEMO_DATABASE_USER")
    if _required(env, "GEO_DEMO_SCHEMA_REVISION") != REQUIRED_SCHEMA_REVISION:
        raise GeoDemoBindingUnavailable("演示数据库结构版本配置不匹配")
    manifest_sha256 = _required(env, "GEO_DEMO_MANIFEST_SHA256").lower()
    if len(manifest_sha256) != 64 or any(
        value not in "0123456789abcdef" for value in manifest_sha256
    ):
        raise GeoDemoBindingUnavailable("演示夹具清单摘要无效")
    hosts = frozenset(
        value.strip().lower()
        for value in _required(env, "GEO_DEMO_DATABASE_HOST_ALLOWLIST").split(",")
        if value.strip()
    )
    server_addresses = frozenset(
        value.strip()
        for value in _required(env, "GEO_DEMO_DATABASE_SERVER_ADDR_ALLOWLIST").split(",")
        if value.strip()
    )
    if not hosts or not server_addresses or any(
        "*" in value for value in (*hosts, *server_addresses)
    ):
        raise GeoDemoBindingUnavailable("演示数据库白名单无效")
    try:
        target = make_url(raw_url)
        primary = make_url(str(get_settings().database_url))
    except Exception as exc:
        raise GeoDemoBindingUnavailable("演示数据库地址无效") from exc
    if (
        target.drivername != "postgresql+asyncpg"
        or not target.host
        or target.host.lower() not in hosts
        or target.database != database
        or target.username != username
        or "demo" not in database.lower()
        or "demo" not in username.lower()
        or database in {"postgres", "template0", "template1"}
        or (target.host, target.port, target.database)
        == (primary.host, primary.port, primary.database)
    ):
        raise GeoDemoBindingUnavailable("演示数据库目标未通过隔离校验")
    return GeoDemoDatabaseTarget(
        database_url=raw_url,
        database=database,
        username=username,
        server_addresses=server_addresses,
        schema_revision=REQUIRED_SCHEMA_REVISION,
        manifest_sha256=manifest_sha256,
    )


@lru_cache(maxsize=2)
def _demo_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        echo=False,
    )
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def validate_demo_session(session, policy, target: GeoDemoDatabaseTarget) -> None:
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
        raise GeoDemoBindingUnavailable("演示数据库连接身份校验失败")
    revisions = list(
        (
            await session.execute(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            )
        ).scalars()
    )
    if revisions != [target.schema_revision]:
        raise GeoDemoBindingUnavailable("演示数据库结构版本不匹配")
    receipt = (
        await session.execute(
            text(
                f"SELECT dataset_key, dataset_version, fixture_namespace, "
                f"manifest_sha256, status FROM {FIXTURE_REGISTRY_TABLE} "
                "WHERE tenant_id=:tenant_id"
            ),
            {"tenant_id": policy.demo_tenant_id},
        )
    ).one_or_none()
    if (
        receipt is None
        or receipt[0] != policy.dataset_key
        or receipt[1] != policy.dataset_version
        or receipt[2] != policy.fixture_namespace
        or str(receipt[3] or "").lower() != target.manifest_sha256
        or receipt[4] != "sealed"
    ):
        raise GeoDemoBindingUnavailable("演示夹具装载回执不匹配")
    tenant = (
        await session.execute(
            text(
                "SELECT id, strategy, business_desc FROM tenants WHERE id=:tenant_id"
            ),
            {"tenant_id": policy.demo_tenant_id},
        )
    ).one_or_none()
    marker = f"GEO_DEMO_FIXTURE:{policy.fixture_namespace}"
    if (
        tenant is None
        or int(tenant[0]) != policy.demo_tenant_id
        or str(tenant[1] or "").strip().lower() != "demo"
        or marker not in str(tenant[2] or "")
    ):
        raise GeoDemoBindingUnavailable("演示租户或夹具标记不匹配")
    total, compliant = (
        await session.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE simulated IS TRUE "
                "AND sample_mode='mock_persona' "
                "AND position(:visible_marker in coalesce(raw_text, '')) > 0 "
                "AND position(:visible_marker in coalesce(note, '')) > 0) "
                "FROM geo_answer_snapshots "
                "WHERE tenant_id=:tenant_id"
            ),
            {
                "tenant_id": policy.demo_tenant_id,
                "visible_marker": f"[全虚拟演示][{marker}]",
            },
        )
    ).one()
    if int(total or 0) <= 0 or int(total) != int(compliant or 0):
        raise GeoDemoBindingUnavailable("演示回答不是完整的全虚拟数据集")


async def production_read_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory(autoflush=False) as session:
        try:
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            yield session
        finally:
            await session.rollback()


async def tenant_read_session(
    request: Request,
    tenant_id: int,
    ctx: AuthContext = Depends(require_scoped_auth),
    control_session: AsyncSession = Depends(get_session),
) -> AsyncIterator[AsyncSession]:
    """Authenticate/entitle in production, then open exactly one verified source."""
    ctx.ensure_tenant(tenant_id)
    policy = await ensure_geo_entitlement(
        control_session,
        tenant_id,
        allow_demo_read=True,
        lock_binding=True,
    )
    if not policy.is_demo:
        async for session in production_read_session():
            session.info["geo_control_tenant_id"] = tenant_id
            session.info["geo_data_tenant_id"] = tenant_id
            yield session
        return
    try:
        target = resolve_demo_database_target(policy)
        factory = _demo_session_factory(target.database_url)
        async with factory(autoflush=False) as session:
            try:
                await session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )
                await validate_demo_session(session, policy, target)
                session.info["geo_control_tenant_id"] = tenant_id
                session.info["geo_data_tenant_id"] = policy.demo_tenant_id
                session.info["geo_demo_policy"] = policy
                yield session
            finally:
                await session.rollback()
    except GeoDemoBindingUnavailable:
        raise
    except Exception as exc:
        raise GeoDemoBindingUnavailable("演示只读数据源不可用") from exc


def data_tenant_id(session: AsyncSession, requested_tenant_id: int) -> int:
    info = getattr(session, "info", {}) or {}
    if not isinstance(info, Mapping):
        return requested_tenant_id
    return int(info.get("geo_data_tenant_id", requested_tenant_id))


def demo_policy(session: AsyncSession):
    info = getattr(session, "info", {}) or {}
    return info.get("geo_demo_policy") if isinstance(info, Mapping) else None
