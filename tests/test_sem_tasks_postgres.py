"""Opt-in isolated PostgreSQL test, no migrations and no production URLs."""
import asyncio
import os
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import test_writeback_approval  # noqa: F401
from sqlalchemy import BigInteger, ForeignKeyConstraint, MetaData, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import sem_tasks as api
from app.models.sem_task import SemTask
from app.models import Tenant, TenantModule, BaiduAccount, KwReportSnapshot, WritebackApproval
from app.api import sem_metrics
from test_sem_tasks import context, evidence


@pytest.mark.parametrize("tenant_id", [3, 2**31, 2**53 + 1, 2**63 - 1])
@pytest.mark.parametrize("schema_source", ["model", "review_ddl", "migration_proposal"])
def test_native_task_constraints_lifecycle_and_concurrent_verify(tenant_id, schema_source):
    url = os.getenv("SEM_TASK_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires dedicated local sem_tasks_test database")
    parsed = make_url(url)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database == "sem_tasks_test"
    assert not parsed.query  # No alternate host/service routing.
    schema = "sem_tasks_test_" + uuid.uuid4().hex

    def scoped_evidence(value, when=None):
        result = evidence(value, when)
        result["tenant_id"] = tenant_id
        return result

    async def run():
        admin = create_async_engine(url, poolclass=NullPool)
        engine = create_async_engine(url, poolclass=NullPool,
                                     connect_args={"server_settings": {"search_path": schema}})
        created = False
        try:
            async with admin.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                created = True
            metadata = MetaData()
            # Mirror the operator-confirmed BIGINT tenant PK in this isolated DB;
            # leave the legacy shared application mapper unchanged.
            for model in (Tenant, TenantModule, BaiduAccount, KwReportSnapshot, WritebackApproval):
                table = model.__table__.to_metadata(metadata)
                for constraint in list(table.constraints):
                    if isinstance(constraint, ForeignKeyConstraint):
                        table.constraints.remove(constraint)
                table.foreign_keys.clear()
                for column in table.c:
                    column.foreign_keys.clear()
            tenant = metadata.tables["tenants"]
            tenant.c.id.type = BigInteger()
            SemTask.__table__.to_metadata(metadata)
            async with engine.begin() as conn:
                if schema_source == "model":
                    await conn.run_sync(metadata.create_all)
                else:
                    tables = [t for t in metadata.tables.values() if t.name != "sem_tasks"]
                    await conn.run_sync(lambda sync: metadata.create_all(sync, tables=tables))
                    # Execute the repository-owned review DDL only inside this
                    # dedicated local test schema, never against production.
                    if schema_source == "migration_proposal":
                        # Compile the proposal with an in-memory op recorder;
                        # never import Alembic or write its version table.
                        from test_sem_task_migration_proposal import proposal_definitions
                        from sqlalchemy.schema import CreateTable, CreateIndex
                        from sqlalchemy.dialects.postgresql import dialect
                        _, recorder = proposal_definitions()
                        proposed = recorder.metadata.tables["sem_tasks"]
                        ddl = str(CreateTable(proposed).compile(dialect=dialect())) + ";"
                        ddl += ";".join(str(CreateIndex(i).compile(dialect=dialect())) for i in proposed.indexes)
                    else:
                        ddl = Path("docs/SEM_TASK_SCHEMA_REVIEW.sql").read_text(encoding="utf-8")
                    ddl = "\n".join(line for line in ddl.splitlines() if not line.lstrip().startswith("--"))
                    for statement in ddl.split(";"):
                        if statement.strip():
                            await conn.execute(text(statement))
                await conn.execute(tenant.insert().values(id=tenant_id, name="local-test"))
                await conn.execute(metadata.tables["tenant_modules"].insert().values(
                    tenant_id=tenant_id, module_code="sem", status="active"))
            # Exercise real metric SQL and its bigint bind, not only mocked evidence.
            # Include actual module entitlement and identity queries in this path.
            async with AsyncSession(engine) as session:
                metrics = await sem_metrics.snapshot(tenant_id=tenant_id, ctx=context(tenant=tenant_id), session=session)
                assert metrics["tenant_id"] == tenant_id
                assert next(x for x in metrics["items"] if x["metric_key"] == "sem.accounts.active_count")["value"] == 0
            with patch.object(api, "observation", AsyncMock(return_value=scoped_evidence(3))):
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    result = await api.create(api.CreateTask(title="核对审批", params={
                        "metric_key": "sem.approvals.pending_count", "direction": "down", "target_value": 1}),
                        tenant_id=tenant_id, ctx=context(tenant=tenant_id), session=session)
                    task_id = result["id"]
                    assert result["created_at"].tzinfo is not None
                    assert result["created_by"] == "user:9"
                    assert result["tenant_id"] == tenant_id
                    # Deterministic baseline precedes the verified observation.
                    row = await api.load(session, task_id, tenant_id, lock=True)
                    row.baseline_snapshot = scoped_evidence(3, datetime.now(timezone.utc)-timedelta(hours=1))
                    await session.commit()

            entered, release = asyncio.Event(), asyncio.Event()
            calls = 0
            async def observe(*args):
                nonlocal calls
                calls += 1
                entered.set()
                await release.wait()
                return scoped_evidence(1)

            async def verify():
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    return await api.verify(task_id=task_id, tenant_id=tenant_id, ctx=context(tenant=tenant_id), session=session)

            with patch.object(api, "observation", observe):
                first = asyncio.create_task(verify())
                await asyncio.wait_for(entered.wait(), 5)
                second = asyncio.create_task(verify())
                await asyncio.sleep(0.1)
                assert not second.done()
                release.set()
                one, two = await asyncio.wait_for(asyncio.gather(first, second), 10)
                assert one["status"] == two["status"] == "done"
                assert one["completion_evidence"] == two["completion_evidence"]
                assert calls == 1

            from sqlalchemy.exc import IntegrityError
            async with AsyncSession(engine) as session:
                with pytest.raises(IntegrityError):
                    await session.execute(text("UPDATE sem_tasks SET completion_evidence = NULL WHERE id=:id"), {"id": task_id})
                await session.rollback()
                with pytest.raises(IntegrityError):
                    await session.execute(tenant.delete().where(tenant.c.id == tenant_id))
                await session.rollback()
                assert await session.scalar(select(func.count()).select_from(SemTask)) == 1
                assert (await api.load(session, task_id, tenant_id)).status == "done"
        finally:
            await engine.dispose()
            if created:
                async with admin.begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()
    asyncio.run(run())
