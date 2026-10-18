"""Real locking and isolation using only a dedicated loopback CI database."""
import asyncio
import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.schema import CreateTable

from app.geo.content import routes
from app.geo.content.receipt_import import import_receipts, SCOPE_ERROR
from app.models import (Tenant, TenantModule, GeoProject, GeoOptimizationBusiness, GeoOptimizationUnit,
                        GeoPrompt, GeoContentTask, GeoArticleVersion, GeoChannelVariant,
                        GeoPublication, GeoPublishingChannel)
from app.security.auth import AuthContext

pytestmark = pytest.mark.skipif(not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires dedicated PostgreSQL")


def test_receipts_real_transactions_concurrency_and_scope():
    async def run():
        from ops.run_geo_checks import validate_ci_database

        url = os.environ["GEO_TEST_POSTGRES_URL"]
        validate_ci_database(url)
        schema = "geo_receipts_" + uuid4().hex
        engine = create_async_engine(url, connect_args={"server_settings": {
            "search_path": schema, "lock_timeout": "10000", "statement_timeout": "15000"}},
            execution_options={"schema_translate_map": {"public": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        created = False
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                created = True
                for model in (Tenant, TenantModule, GeoProject, GeoOptimizationBusiness, GeoOptimizationUnit,
                              GeoPrompt, GeoContentTask, GeoArticleVersion, GeoChannelVariant, GeoPublication,
                              GeoPublishingChannel):
                    await connection.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
                await connection.execute(text("CREATE TABLE demo_tenant_bindings (tenant_id bigint, demo_tenant_id bigint, "
                    "dataset_key varchar(64), dataset_version varchar(40), status varchar(16), version integer)"))
            async with sessions() as db:
                db.add_all([Tenant(id=7, name="synthetic seven"), Tenant(id=8, name="synthetic eight"),
                    TenantModule(id=1, tenant_id=7, module_code="geo", status="active")])
                for pid, business, prompt, tid, task_id, variant_id in ((5, 20, 30, 7, 12, 3), (6, 21, 31, 7, 14, 4), (7, 22, 32, 8, 13, 5)):
                    db.add(GeoProject(id=pid, tenant_id=tid, tenant_module_id=1, name="synthetic project",
                        primary_domain=f"p{pid}.example.invalid", canonical_domain=f"p{pid}.example.invalid", status="active",
                        project_settings={"geo_business_scope": {"revision": 1, "business_ids": [business]}}))
                    db.add(GeoOptimizationBusiness(id=business, tenant_id=tid, name=f"synthetic business {business}"))
                    db.add(GeoOptimizationUnit(id=business, tenant_id=tid, business_id=business, name="unit"))
                    db.add(GeoPrompt(id=prompt, tenant_id=tid, unit_id=business, question="synthetic question"))
                    db.add(GeoContentTask(id=task_id, tenant_id=tid, prompt_id=prompt, business_id=business,
                        period_id=100, title="synthetic article", status="ready", review_status="approved"))
                    db.add(GeoArticleVersion(id=task_id+100, task_id=task_id, title="synthetic", body_markdown="synthetic"))
                    db.add(GeoChannelVariant(id=variant_id, task_id=task_id, article_version_id=task_id+100,
                        channel="website", title="synthetic", body_markdown="synthetic", status="draft", adapt_meta={}))
                await db.commit()
            ctx = AuthContext(9, "synthetic", "editor", 7, {"geo.content": "edit"})
            def row(task_id=12):
                return {"article_id": str(task_id), "platform": "website", "public_url": "https://example.invalid/receipt"}

            async def call(task_id=12, project_id=5, dry_run=False, rows=None):
                async with sessions() as db:
                    return await import_receipts(db, ctx=ctx, tenant_id=7, project_id=project_id,
                        task_id=task_id, rows=rows or [row(task_id)], dry_run=dry_run)

            with patch.object(routes, "_build_rule_input", AsyncMock(return_value=None)), \
                 patch.object(routes, "_brand_context_for_task", AsyncMock(return_value=("synthetic", []))), \
                 patch.object(routes, "assert_can_publish"), \
                 patch.object(routes, "_sync_task_pipeline", AsyncMock()):
                # A foreign task, missing task, and same-tenant other-project task are indistinguishable.
                for task_id in (13, 14, 999):
                    with pytest.raises(HTTPException) as denied:
                        await call(task_id)
                    assert denied.value.status_code == 404 and denied.value.detail == SCOPE_ERROR
                preview = await call(dry_run=True)
                assert preview["can_confirm"] and not preview["committed"]
                async with sessions() as db:
                    assert await db.scalar(select(func.count()).select_from(GeoPublication)) == 0
                    (await db.get(GeoContentTask, 12)).review_status = "pending"
                    await db.commit()
                assert not (await call())["committed"]
                async with sessions() as db:
                    (await db.get(GeoContentTask, 12)).review_status = "approved"
                    await db.commit()
                results = await asyncio.gather(call(), call())
                assert sorted(r["changed"] for r in results) == [0, 1]
                async with sessions() as db:
                    assert await db.scalar(select(func.count()).select_from(GeoPublication)) == 1
                    assert (await db.get(GeoContentTask, 12)).status == "published"
                    assert (await db.get(GeoChannelVariant, 3)).status == "published"
                    assert (await db.get(GeoContentTask, 13)).status == "ready"
                    assert (await db.get(GeoContentTask, 14)).status == "ready"
                # A changed project binding after preview cannot authorize later confirmation.
                async with sessions() as db:
                    project = await db.get(GeoProject, 5)
                    project.project_settings = {"geo_business_scope": {"revision": 2, "business_ids": []}}
                    await db.commit()
                with pytest.raises(HTTPException) as denied:
                    await call()
                assert denied.value.detail == SCOPE_ERROR
        finally:
            try:
                if created:
                    assert schema.startswith("geo_receipts_") and len(schema) == len("geo_receipts_") + 32
                    async with engine.begin() as connection:
                        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            finally:
                await engine.dispose()
    asyncio.run(run())
