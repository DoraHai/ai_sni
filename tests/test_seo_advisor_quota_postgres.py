"""Native row-lock proof using the existing guarded disposable CI database."""
import asyncio

from fastapi import HTTPException
from sqlalchemy import select

from app.models.module_workspace import TenantModule
from app.security.seo_advisor_quota import KEY, reserve
from app.seo_ai_operations import claim_seo_ai_operation
from test_advisor_scoped_writes_postgres import store
from test_seo_workflow_postgres import requires_pg

pytestmark = requires_pg


def test_twenty_concurrent_requests_admit_exactly_ten_and_preserve_other_actors():
    async def run():
        async with store() as sessions:
            async def take(number):
                async with sessions() as session:
                    module = await session.scalar(select(TenantModule).where(
                        TenantModule.tenant_id == 4, TenantModule.module_code == "seo",
                    ).with_for_update().execution_options(populate_existing=True))
                    try:
                        module.module_settings, _ = reserve(module.module_settings, 7,
                            "/api/v1/seo/content-ai/assist", {"action": "title", "request_id": str(number)})
                    except HTTPException as exc:
                        await session.rollback()
                        return exc.status_code
                    await session.commit()
                    return 200
            results = await asyncio.gather(*(take(i) for i in range(20)))
            assert results.count(200) == 10 and results.count(429) == 10
            async with sessions() as session:
                module = await session.scalar(select(TenantModule).where(TenantModule.tenant_id == 4))
                assert len(module.module_settings[KEY]["actors"]["7"]) == 10
                assert reserve(module.module_settings, 8, "other-advice", {})[1]["used"] == 1
    asyncio.run(run())


def test_mother_draft_claims_are_unlimited_and_never_spend_legacy_tenant_budget():
    async def run():
        async with store() as sessions:
            async with sessions() as session:
                module = await session.scalar(select(TenantModule).where(TenantModule.tenant_id == 4))
                module.module_settings = {"seo_daily_usage": {"date": "2026-10-18", "ai_requests": 100}}
                await session.commit()
                session._seo_advisor_ai_kind = "generation"
                for i in range(12):
                    receipt = await claim_seo_ai_operation(session, 4, request_key=f"draft-{i}",
                        payload={"site_id": 2, "title": str(i)}, actor="7", kind="content_assist", limit=1)
                    assert receipt["limit"] is None
                await session.refresh(module)
                assert module.module_settings["seo_daily_usage"]["ai_requests"] == 100
    asyncio.run(run())
