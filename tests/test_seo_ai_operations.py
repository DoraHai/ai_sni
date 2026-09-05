import asyncio
import importlib.util
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models.seo import SeoAiOperation
from app.seo_ai_operations import (
    SeoAiReplay, claim_seo_ai_operation, settle_seo_ai_operation, reconcile_seo_ai_operations,
)

pytestmark = pytest.mark.skipif(not os.getenv("SEO_USAGE_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")


@asynccontextmanager
async def database():
    schema = "seo_ai_test_" + uuid4().hex
    engine = create_async_engine(os.environ["SEO_USAGE_TEST_DATABASE_URL"],
                                 connect_args={"server_settings": {"search_path": schema}})
    path = Path(__file__).parents[1] / "migrations/versions/20260905_0090_seo_ai_operations.py"
    spec = importlib.util.spec_from_file_location("ai_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text("CREATE TABLE tenants (id bigint PRIMARY KEY)"))
            await connection.execute(text("INSERT INTO tenants VALUES (1),(2)"))
            await connection.execute(text("""CREATE TABLE tenant_modules (
                id bigint PRIMARY KEY, tenant_id bigint NOT NULL, module_code varchar(16),
                status varchar(20), opened_at timestamp, expires_at date, module_settings jsonb,
                created_at timestamp, updated_at timestamp)"""))
            await connection.execute(text("""INSERT INTO tenant_modules (id, tenant_id, module_code, module_settings)
                VALUES (1,1,'seo','{}'),(2,2,'seo','{}')"""))

            def migrate(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    migration.upgrade()
            await connection.run_sync(migrate)
        yield async_sessionmaker(engine, expire_on_commit=False), migration
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def claim(session, key="request-key-00001", tenant=1, **overrides):
    args = dict(request_key=key, payload={"draft": "中文资料"}, actor="7", kind="assist", limit=5)
    args.update(overrides)
    return await claim_seo_ai_operation(session, tenant, **args)


async def used(sessions, tenant=1):
    async with sessions() as session:
        settings = await session.scalar(text("SELECT module_settings FROM tenant_modules WHERE tenant_id=:tenant"), {"tenant": tenant})
        return (settings.get("seo_daily_usage") or {}).get("ai_requests", 0)


def test_concurrent_same_key_charges_once_and_replays_full_result():
    async def scenario():
        async with database() as (sessions, _):
            async def start():
                async with sessions() as session:
                    try:
                        return await claim(session)
                    except HTTPException as exc:
                        assert exc.detail["code"] == "operation_running"
            claims = await asyncio.gather(*(start() for _ in range(20)))
            receipts = [item for item in claims if item]
            assert len(receipts) == 1
            assert await used(sessions) == 1
            result = {"action": "title", "title": "已验证中文标题", "keyword_coverage": {"missing": []}}
            async with sessions() as session:
                await settle_seo_ai_operation(session, 1, receipts[0]["operation_id"], result=result)
            async with sessions() as session:
                with pytest.raises(SeoAiReplay) as replay:
                    await claim(session)
                assert replay.value.result == result
            # Even a late failed request cannot refund a completed operation.
            async with sessions() as session:
                await settle_seo_ai_operation(session, 1, receipts[0]["operation_id"])
            assert await used(sessions) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("change", [{"payload": {"draft": "different"}}, {"actor": "8"}, {"kind": "other"}])
def test_same_key_rejects_changed_payload_actor_or_endpoint(change):
    async def scenario():
        async with database() as (sessions, _):
            async with sessions() as session:
                await claim(session)
            async with sessions() as session:
                with pytest.raises(HTTPException) as exc:
                    await claim(session, **change)
                assert exc.value.detail["code"] == "request_conflict"
            async with sessions() as session:
                await claim(session, tenant=2)
            assert await used(sessions, 1) == await used(sessions, 2) == 1
    asyncio.run(scenario())


def test_repeated_refunds_and_late_success_cannot_change_settled_quota():
    async def scenario():
        async with database() as (sessions, _):
            async with sessions() as session:
                receipt = await claim(session)
            async def refund():
                async with sessions() as session:
                    await settle_seo_ai_operation(session, 1, receipt["operation_id"])
            await asyncio.gather(*(refund() for _ in range(20)))
            assert await used(sessions) == 0
            async with sessions() as session:
                with pytest.raises(HTTPException) as exc:
                    await settle_seo_ai_operation(session, 1, receipt["operation_id"], result={"title": "late"})
                assert exc.value.detail["code"] == "operation_refunded"
            async with sessions() as session:
                with pytest.raises(HTTPException) as exc:
                    await claim(session)
                assert exc.value.detail["code"] == "operation_refunded"
            assert await used(sessions) == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("commit_reached_db", [False, True])
def test_charge_and_claim_survive_uncertain_commit_without_double_charge(commit_reached_db):
    async def scenario():
        async with database() as (sessions, _):
            async with sessions() as session:
                original_commit = session.commit
                async def broken_commit():
                    if commit_reached_db:
                        await original_commit()
                    raise RuntimeError("connection lost during commit")
                with patch.object(session, "commit", new=broken_commit):
                    with pytest.raises(RuntimeError):
                        await claim(session)
            assert await used(sessions) == int(commit_reached_db)
            async with sessions() as session:
                if commit_reached_db:
                    with pytest.raises(HTTPException) as exc:
                        await claim(session)
                    assert exc.value.detail["code"] == "operation_running"
                else:
                    await claim(session)
            assert await used(sessions) == 1
    asyncio.run(scenario())


def test_failed_refund_is_eventually_reconciled_and_does_not_touch_next_day():
    async def scenario():
        async with database() as (sessions, _):
            async with sessions() as session:
                receipt = await claim(session)
            async with sessions() as session:
                with patch.object(session, "commit", new=AsyncMock(side_effect=RuntimeError("offline"))):
                    with pytest.raises(RuntimeError):
                        await settle_seo_ai_operation(session, 1, receipt["operation_id"])
            assert await used(sessions) == 1
            async with sessions() as session:
                row = await session.get(SeoAiOperation, receipt["operation_id"])
                assert row.status == "running"
                row.expires_at = datetime.utcnow() - timedelta(seconds=1)
                row.charged_on = "2000-01-01"  # another day's quota must be left intact
                await session.commit()
            with patch("app.seo_ai_operations.async_session_factory", new=sessions):
                await asyncio.gather(reconcile_seo_ai_operations(), reconcile_seo_ai_operations())
            assert await used(sessions) == 1
            async with sessions() as session:
                row = await session.get(SeoAiOperation, receipt["operation_id"])
                assert row.status == "refunded"
    asyncio.run(scenario())


def test_expired_claim_refunded_before_replay_and_downgrade_refuses_unsettled_claims():
    async def scenario():
        async with database() as (sessions, migration):
            async with sessions() as session:
                receipt = await claim(session)
            async with sessions() as session:
                def downgrade(sync):
                    with Operations.context(MigrationContext.configure(sync.connection())):
                        migration.downgrade()
                with pytest.raises(Exception, match="Unsettled SEO AI"):
                    await session.run_sync(downgrade)
                await session.rollback()
                row = await session.get(SeoAiOperation, receipt["operation_id"])
                row.expires_at = datetime.utcnow() - timedelta(seconds=1)
                await session.commit()
            async with sessions() as session:
                with pytest.raises(HTTPException) as exc:
                    await claim(session)
                assert exc.value.detail["code"] == "operation_refunded"
            assert await used(sessions) == 0
            async with sessions() as session:
                await session.run_sync(downgrade)
                await session.commit()
    asyncio.run(scenario())


@pytest.mark.parametrize("provider_fails", [False, True])
def test_assist_route_uses_durable_result_and_refund(provider_fails):
    from app.api.seo import SeoContentAssistRequest, assist_seo_content
    from app.ai.deepseek import DeepSeekError
    from app.models import Tenant, SeoKeywordAsset
    from app.security.auth import AuthContext
    from types import SimpleNamespace

    async def scenario():
        async with database() as (sessions, _):
            request = SeoContentAssistRequest(tenant_id=1, request_id="route-request-0001", action="title", keyword_ids=[11])
            ctx = AuthContext(user_id=7, username="operator", role_name="运营", tenant_id=1, permissions={"seo.content": "edit"})
            provider = AsyncMock(side_effect=DeepSeekError("offline")) if provider_fails else AsyncMock(return_value={"title": "目标词标题", "feedback": "已验证"})
            with (
                patch("app.api.seo._tenant", new=AsyncMock(return_value=Tenant(id=1, name="测试品牌"))),
                patch("app.api.seo._content_keywords", new=AsyncMock(return_value=[SeoKeywordAsset(id=11, tenant_id=1, keyword="目标词")])),
                patch("app.api.seo.is_enabled", return_value=True),
                patch("app.api.seo.get_settings", return_value=SimpleNamespace(seo_ai_max_requests_per_tenant_per_day=5)),
                patch("app.api.seo.chat_json", new=provider),
                patch("app.seo_ai_operations.async_session_factory", new=sessions),
            ):
                async with sessions() as session:
                    if provider_fails:
                        with pytest.raises(HTTPException) as exc:
                            await assist_seo_content(request, session, ctx)
                        assert exc.value.status_code == 502
                    else:
                        result = await assist_seo_content(request, session, ctx)
                async with sessions() as session:
                    if provider_fails:
                        with pytest.raises(HTTPException) as exc:
                            await assist_seo_content(request, session, ctx)
                        assert exc.value.detail["code"] == "operation_refunded"
                    else:
                        assert await assist_seo_content(request, session, ctx) == result
                provider.assert_awaited_once()
                assert await used(sessions) == int(not provider_fails)
                wrong_tenant = AuthContext(user_id=8, username="other", role_name="运营", tenant_id=2)
                async with sessions() as session:
                    with pytest.raises(HTTPException) as exc:
                        await assist_seo_content(request, session, wrong_tenant)
                    assert exc.value.status_code == 403
    asyncio.run(scenario())


def test_distribution_route_replays_original_result_without_new_provider_call():
    from app.api.seo import DistributionAdaptRequest, adapt_content_distribution
    from app.models import Tenant, SeoKeywordAsset
    from app.models.seo import SeoContentAsset, SeoDistributionConnection
    from app.security.auth import AuthContext
    from types import SimpleNamespace

    async def scenario():
        async with database() as (sessions, _):
            content = SeoContentAsset(id=5, tenant_id=1, site_id=8, keyword_id=11, keyword_ids=[11],
                title="目标词指南", draft="<p>目标词原稿</p>", version_count=2)
            connection = SeoDistributionConnection(id=9, tenant_id=1, platform_code="zhihu", name="知乎", enabled=True)
            request = DistributionAdaptRequest(tenant_id=1, site_id=8, content_id=5, connection_id=9,
                use_ai=True, request_id="distribution-00001")
            ctx = AuthContext(user_id=7, username="operator", role_name="运营", tenant_id=1, permissions={"seo.content": "edit"})
            provider = AsyncMock(return_value={"title": "目标词实践", "content": "<p>目标词修订稿</p>", "feedback": "已改写"})
            with (
                patch("app.api.seo._seo_site", new=AsyncMock()),
                patch("app.api.seo._distribution_content", new=AsyncMock(return_value=content)),
                patch("app.api.seo._distribution_connection", new=AsyncMock(return_value=connection)),
                patch("app.api.seo._tenant", new=AsyncMock(return_value=Tenant(id=1, name="测试品牌"))),
                patch("app.api.seo._content_keywords", new=AsyncMock(return_value=[SeoKeywordAsset(id=11, tenant_id=1, keyword="目标词")])),
                patch("app.api.seo.is_enabled", return_value=True),
                patch("app.api.seo.get_settings", return_value=SimpleNamespace(seo_ai_max_requests_per_tenant_per_day=5)),
                patch("app.api.seo.chat_json", new=provider),
            ):
                async with sessions() as session:
                    first = await adapt_content_distribution(request, session, ctx)
                async with sessions() as session:
                    assert await adapt_content_distribution(request, session, ctx) == first
                provider.assert_awaited_once()
                assert first["source_version"] == 2
                assert await used(sessions) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("commit_reached_db", [False, True])
def test_result_commit_uncertainty_replays_or_reconciles(commit_reached_db):
    async def scenario():
        async with database() as (sessions, _):
            async with sessions() as session:
                receipt = await claim(session)
            result = {"title": "completed"}
            async with sessions() as session:
                original_commit = session.commit
                async def broken_commit():
                    if commit_reached_db:
                        await original_commit()
                    raise RuntimeError("result acknowledgement lost")
                with patch.object(session, "commit", new=broken_commit):
                    with pytest.raises(RuntimeError):
                        await settle_seo_ai_operation(session, 1, receipt["operation_id"], result=result)
            async with sessions() as session:
                if commit_reached_db:
                    with pytest.raises(SeoAiReplay) as replay:
                        await claim(session)
                    assert replay.value.result == result
                else:
                    row = await session.get(SeoAiOperation, receipt["operation_id"])
                    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
                    await session.commit()
            with patch("app.seo_ai_operations.async_session_factory", new=sessions):
                await reconcile_seo_ai_operations()
            assert await used(sessions) == int(commit_reached_db)
    asyncio.run(scenario())


def test_result_retention_clears_content_but_keeps_deduplication():
    async def scenario():
        async with database() as (sessions, _):
            async with sessions() as session:
                receipt = await claim(session)
                await settle_seo_ai_operation(session, 1, receipt["operation_id"], result={"title": "private result"})
                row = await session.get(SeoAiOperation, receipt["operation_id"])
                row.completed_at = datetime.utcnow() - timedelta(days=31)
                await session.commit()
            with patch("app.seo_ai_operations.async_session_factory", new=sessions):
                assert (await reconcile_seo_ai_operations())["results_cleared"] == 1
                assert (await reconcile_seo_ai_operations())["results_cleared"] == 0
            async with sessions() as session:
                row = await session.get(SeoAiOperation, receipt["operation_id"])
                assert row.result is None and row.status == "succeeded"
                with pytest.raises(HTTPException) as exc:
                    await claim(session)
                assert exc.value.detail["code"] == "operation_result_expired"
            assert await used(sessions) == 1
    asyncio.run(scenario())
