import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from app.geo.content import async_jobs, geo_scheduler, patrol, variant_execute
from app.geo.tenant_scope import GeoEntitlementUnavailable


def test_claimed_worker_rechecks_entitlement_before_business_executor():
    async def scenario():
        row = NS(
            id=42,
            tenant_id=7,
            kind=async_jobs.KIND_GENERATE,
            status="running",
            request_meta={},
            ref_id=None,
            started_at=None,
            finished_at=None,
            error=None,
            result_meta=None,
        )
        session = NS(
            scalar=AsyncMock(side_effect=[42, None]),
            commit=AsyncMock(),
            rollback=AsyncMock(),
            get=AsyncMock(return_value=row),
        )

        @asynccontextmanager
        async def factory(**_kwargs):
            yield session

        executor = AsyncMock(side_effect=AssertionError("executor must not run"))
        with (
            patch("app.database.async_session_factory", factory),
            patch.object(async_jobs, "_execute_generate", executor),
        ):
            result = await async_jobs._run_owned_job(42)

        assert result["status"] == "failed"
        assert result["error_type"] == "GeoEntitlementUnavailable"
        assert row.status == "failed"
        executor.assert_not_awaited()
        session.rollback.assert_awaited_once()

    asyncio.run(scenario())


def test_generation_discards_model_response_when_entitlement_changes_in_flight():
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        revoked = False
        task = NS(
            id=12,
            tenant_id=7,
            prompt_id=3,
            business_id=None,
            brief={"audience": "采购", "intent": "选型", "cta": "咨询", "content_type": "guide"},
            status="editing",
            title="old",
        )
        tenant = NS(id=7, name="Brand")
        prompt = NS(id=3, question="question")
        job = NS(
            id=8,
            tenant_id=7,
            ref_id=12,
            created_by=5,
            status="running",
            request_meta={},
        )

        async def get(model, _ident):
            return {
                "GeoContentTask": task,
                "Tenant": tenant,
                "GeoPrompt": prompt,
                "GeoAsyncJob": job,
            }.get(getattr(model, "__name__", ""))

        async def ensure(_session, tenant_id):
            assert tenant_id == 7
            if revoked:
                raise GeoEntitlementUnavailable()

        async def generate(**_kwargs):
            entered.set()
            await release.wait()
            return {"title": "new", "body_markdown": "body"}

        session = NS(
            get=AsyncMock(side_effect=get),
            execute=AsyncMock(return_value=NS(scalars=lambda: [])),
            scalar=AsyncMock(return_value=None),
            commit=AsyncMock(),
            add=Mock(),
        )
        with (
            patch("app.geo.tenant_scope.ensure_geo_entitlement", side_effect=ensure),
            patch("app.geo.content.brief.brief_ready", return_value=True),
            patch(
                "app.geo.content.evidence.prepare_facts_for_generation",
                return_value=([], {"ok": True}),
            ),
            patch(
                "app.geo.content.ai_settings.resolve_llm_credentials",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.geo.content.async_jobs.set_job_progress", AsyncMock()
            ),
            patch(
                "app.geo.content.generate_article.generate_master_article",
                side_effect=generate,
            ),
        ):
            running = asyncio.create_task(async_jobs._execute_generate(session, job))
            await asyncio.wait_for(entered.wait(), 3)
            revoked = True
            release.set()
            try:
                await running
                raise AssertionError("revoked generation unexpectedly succeeded")
            except GeoEntitlementUnavailable:
                pass

        session.add.assert_not_called()
        assert task.title == "old"

    asyncio.run(scenario())


def test_variant_generation_discards_results_when_entitlement_changes_in_flight():
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        revoked = False
        task = NS(
            id=12,
            tenant_id=7,
            business_id=None,
            target_channels=["website"],
            prompt_id=3,
            status="editing",
        )
        tenant = NS(id=7, name="Brand")
        article = NS(id=20, title="master", body_markdown="body", outline={})
        variant = NS(channel="website", title="old", body_markdown="old body")

        async def ensure(_session, tenant_id):
            assert tenant_id == 7
            if revoked:
                raise GeoEntitlementUnavailable()

        async def adapt(*_args, **_kwargs):
            entered.set()
            await release.wait()
            return "new", "new body", {}

        session = NS(
            get=AsyncMock(side_effect=[task, tenant]),
            refresh=AsyncMock(),
            scalars=AsyncMock(return_value=[]),
            execute=AsyncMock(return_value=NS(scalars=lambda: [])),
            add=Mock(),
            commit=AsyncMock(),
        )
        with (
            patch("app.geo.tenant_scope.ensure_geo_entitlement", side_effect=ensure),
            patch.object(
                variant_execute, "_latest_article", AsyncMock(return_value=article)
            ),
            patch.object(
                variant_execute, "_list_variants", AsyncMock(return_value=[variant])
            ),
            patch.object(
                variant_execute, "enabled_types_from_rows", return_value=["website"]
            ),
            patch.object(
                variant_execute, "resolve_for_channel", AsyncMock(return_value={})
            ),
            patch.object(variant_execute, "adapt_or_polish_for_channel", side_effect=adapt),
        ):
            running = asyncio.create_task(
                variant_execute.execute_variants_for_task(
                    session,
                    task_id=12,
                    tenant_id=7,
                    channels=["website"],
                    use_llm=False,
                )
            )
            await asyncio.wait_for(entered.wait(), 3)
            revoked = True
            release.set()
            try:
                await running
                raise AssertionError("revoked variant generation unexpectedly succeeded")
            except GeoEntitlementUnavailable:
                pass

        assert variant.title == "old"
        assert variant.body_markdown == "old body"
        session.add.assert_not_called()
        session.commit.assert_not_awaited()

    asyncio.run(scenario())


def test_patrol_discards_probe_response_when_entitlement_changes_in_flight():
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        revoked = False
        run = NS(
            id=9,
            tenant_id=7,
            status="pending",
            trigger="contract_retest",
            auto_persist=True,
            prefer_real=True,
            prompt_limit=1,
            engine_keys=["chatgpt"],
            summary=None,
            items=None,
            error=None,
            started_at=None,
            finished_at=None,
            created_by=5,
        )
        tenant = NS(id=7, name="Brand", brand_terms=["Brand"])
        prompt = NS(id=3, question="question", tags=[], priority=1, unit_id=None)
        engine = NS(
            id=1,
            engine_key="chatgpt",
            enabled=True,
            sort_order=0,
            sample_mode=patrol.SAMPLE_MODE_REAL,
            api_key_encrypted="encrypted",
        )

        async def get(model, _ident):
            return {
                "GeoVisibilityPatrolRun": run,
                "Tenant": tenant,
            }.get(getattr(model, "__name__", ""))

        async def ensure(_session, tenant_id):
            assert tenant_id == 7
            if revoked:
                raise GeoEntitlementUnavailable()

        async def probe(**_kwargs):
            entered.set()
            await release.wait()
            return {
                "raw_text": "Brand answer",
                "sample_mode": patrol.SAMPLE_MODE_REAL,
                "simulated": False,
                "suggested_mentions_brand": True,
            }

        scalar_batches = [[engine], [prompt]]
        session = NS(
            get=AsyncMock(side_effect=get),
            refresh=AsyncMock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
            flush=AsyncMock(),
            add=Mock(),
            scalars=AsyncMock(side_effect=lambda _q: scalar_batches.pop(0)),
        )
        snapshot = Mock()
        with (
            patch("app.geo.content.patrol.ensure_geo_entitlement", side_effect=ensure),
            patch(
                "app.geo.content.ai_settings.resolve_llm_credentials",
                AsyncMock(return_value={"api_key": "test"}),
            ),
            patch(
                "app.geo.content.patrol.resolve_engine_llm",
                return_value=({"api_key": "test"}, patrol.SAMPLE_MODE_REAL, None),
            ),
            patch("app.geo.content.patrol.run_probe_draft", side_effect=probe),
            patch("app.geo.content.patrol.GeoAnswerSnapshot", snapshot),
        ):
            running = asyncio.create_task(patrol.execute_patrol_run(session, 9))
            await asyncio.wait_for(entered.wait(), 3)
            revoked = True
            release.set()
            result = await running

        assert result.status == "failed"
        assert "geo_not_available" in (result.error or "")
        snapshot.assert_not_called()
        session.add.assert_not_called()
        session.rollback.assert_awaited_once()

    asyncio.run(scenario())


def test_queued_patrol_expired_before_claim_is_closed_without_probe():
    async def scenario():
        run = NS(
            id=10,
            tenant_id=7,
            status="pending",
            error=None,
            finished_at=None,
        )
        session = NS(
            get=AsyncMock(return_value=run),
            refresh=AsyncMock(),
            commit=AsyncMock(),
        )
        probe = AsyncMock(side_effect=AssertionError("probe must not run"))
        with (
            patch(
                "app.geo.content.patrol.ensure_geo_entitlement",
                AsyncMock(side_effect=GeoEntitlementUnavailable()),
            ),
            patch("app.geo.content.patrol.run_probe_draft", probe),
        ):
            result = await patrol.execute_patrol_run(session, 10)

        assert result.status == "failed"
        assert "geo_not_available" in result.error
        probe.assert_not_awaited()
        session.commit.assert_awaited_once()

    asyncio.run(scenario())


def test_scheduler_rechecks_entitlement_under_tenant_lock_before_creating_run():
    async def scenario():
        setting = NS(tenant_id=7, enabled=True)
        session = NS(
            scalars=AsyncMock(return_value=[setting]),
            add=Mock(),
            commit=AsyncMock(),
        )

        @asynccontextmanager
        async def factory():
            yield session

        execute = AsyncMock(side_effect=AssertionError("patrol must not start"))
        with (
            patch("app.database.async_session_factory", factory),
            patch.object(
                geo_scheduler, "lock_scheduler_tenant", AsyncMock(return_value=True)
            ),
            patch.object(
                geo_scheduler,
                "current_patrol_settings",
                AsyncMock(return_value=setting),
            ),
            patch(
                "app.geo.tenant_scope.ensure_geo_entitlement",
                AsyncMock(side_effect=GeoEntitlementUnavailable()),
            ),
            patch(
                "app.geo.content.patrol.execute_patrol_run_owned", execute
            ),
        ):
            await geo_scheduler.run_geo_visibility_patrols()

        session.add.assert_not_called()
        execute.assert_not_awaited()
        session.commit.assert_awaited_once()

    asyncio.run(scenario())
