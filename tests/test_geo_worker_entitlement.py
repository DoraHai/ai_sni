import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.geo.content import async_jobs, geo_scheduler, patrol, variant_execute
from app.geo import scheduler as legacy_scheduler
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


def test_worker_failure_never_reads_rolled_back_job_and_restores_task():
    async def scenario():
        class ExpiringJob:
            expired = False

            def __init__(self):
                self.id = 42
                self.tenant_id = 7
                self.kind = async_jobs.KIND_GENERATE
                self.ref_id = 12
                self.status = "running"
                self.request_meta = {}
                self.started_at = None
                self.finished_at = None
                self.error = None
                self.result_meta = None

            def __getattribute__(self, name):
                if name in {"kind", "ref_id", "tenant_id"} and object.__getattribute__(
                    self, "expired"
                ):
                    raise RuntimeError(f"expired ORM attribute read: {name}")
                return object.__getattribute__(self, name)

        old = ExpiringJob()
        live = NS(
            id=42,
            tenant_id=7,
            kind=async_jobs.KIND_GENERATE,
            ref_id=12,
            status="running",
            request_meta={"execution_protocol": async_jobs.JOB_EXECUTION_PROTOCOL},
            started_at=None,
            finished_at=None,
            error=None,
            result_meta=None,
        )
        task = NS(id=12, status="generating")
        job_reads = 0

        async def get(model, _ident):
            nonlocal job_reads
            if getattr(model, "__name__", "") == "GeoContentTask":
                return task
            job_reads += 1
            return old if job_reads == 1 else live

        async def rollback():
            old.expired = True

        session = NS(
            scalar=AsyncMock(side_effect=[42, object()]),
            get=AsyncMock(side_effect=get),
            commit=AsyncMock(),
            rollback=AsyncMock(side_effect=rollback),
        )

        @asynccontextmanager
        async def factory(**_kwargs):
            yield session

        with (
            patch("app.database.async_session_factory", factory),
            patch.object(
                async_jobs,
                "_execute_generate",
                AsyncMock(side_effect=ValueError("synthetic failure")),
            ),
        ):
            result = await async_jobs._run_owned_job(42)

        assert result["status"] == "failed"
        assert result["error_type"] == "ValueError"
        assert task.status == "editing"
        assert live.status == "failed"
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


def test_legacy_scheduler_inactive_first_does_not_block_active_second():
    async def scenario():
        scanned = [NS(tenant_id=7), NS(tenant_id=8)]
        active = NS(
            tenant_id=8,
            enabled=True,
            daily_hour=6,
            window_start_hour=0,
            window_end_hour=23,
            interval_hours=1,
            last_scheduled_at=None,
            auto_persist=True,
            prefer_real=True,
            prompt_limit=1,
            engine_keys=["chatgpt"],
        )
        session = NS(
            scalars=AsyncMock(return_value=scanned),
            scalar=AsyncMock(return_value=None),
            add=Mock(side_effect=lambda row: setattr(row, "id", 99)),
            commit=AsyncMock(),
            rollback=AsyncMock(),
            refresh=AsyncMock(),
        )

        @asynccontextmanager
        async def factory():
            yield session

        async def ensure(_session, tenant_id):
            if tenant_id == 7:
                raise GeoEntitlementUnavailable()

        execute = AsyncMock()
        with (
            patch.object(legacy_scheduler, "async_session_factory", factory),
            patch("app.geo.tenant_scope.ensure_geo_entitlement", side_effect=ensure),
            patch(
                "app.geo.content.geo_scheduler.current_patrol_settings",
                AsyncMock(return_value=active),
            ) as current,
            patch.object(legacy_scheduler, "should_run_scheduled_patrol", return_value=True),
            patch.object(
                legacy_scheduler, "count_patrol_runs_today", AsyncMock(return_value=0)
            ),
            patch.object(legacy_scheduler, "execute_patrol_run_owned", execute),
        ):
            await legacy_scheduler.run_geo_visibility_patrols()

        current.assert_awaited_once_with(session, 8)
        assert session.add.call_args.args[0].tenant_id == 8
        execute.assert_awaited_once_with(session, 99)
        session.rollback.assert_not_awaited()

    asyncio.run(scenario())


def test_push_batch_stops_before_next_target_after_entitlement_revocation():
    async def scenario():
        task = NS(id=12, tenant_id=7)
        variant = NS(channel="website")
        account = NS(id=4)
        channel = NS(id=5)
        job = NS(ref_id=12, tenant_id=7, request_meta={"mode": "draft"})
        revoked = False

        async def get(model, _ident):
            return {
                "GeoContentTask": task,
                "GeoChannelAccount": account,
                "GeoPublishingChannel": channel,
            }.get(getattr(model, "__name__", ""))

        async def ensure(_session, _tenant_id):
            if revoked:
                raise GeoEntitlementUnavailable()

        async def push(*_args, **_kwargs):
            nonlocal revoked
            revoked = True
            return {"connector": "test", "channel": "website"}

        targets = [
            {"ready": True, "adapt_key": "website", "account_id": 4, "channel_id": 5},
            {"ready": True, "adapt_key": "website", "account_id": 4, "channel_id": 5},
        ]
        session = NS(
            get=AsyncMock(side_effect=get),
            scalars=AsyncMock(return_value=[variant]),
            scalar=AsyncMock(return_value=None),
            commit=AsyncMock(),
        )
        with (
            patch("app.geo.tenant_scope.ensure_geo_entitlement", side_effect=ensure),
            patch(
                "app.geo.content.multi_push.list_push_targets",
                AsyncMock(return_value=targets),
            ),
            patch(
                "app.geo.content.multi_push.execute_single_push",
                AsyncMock(side_effect=push),
            ) as execute,
        ):
            with pytest.raises(GeoEntitlementUnavailable):
                await async_jobs._execute_push_batch(session, job)

        execute.assert_awaited_once()
        session.commit.assert_not_awaited()

    asyncio.run(scenario())


def test_safe_daily_metrics_rebuild_skips_expired_tenant_without_write():
    async def scenario():
        from app.geo.content import daily_metrics

        session = NS()

        @asynccontextmanager
        async def factory():
            yield session

        load = AsyncMock(side_effect=AssertionError("metric rebuild must not run"))
        with (
            patch("app.database.async_session_factory", factory),
            patch(
                "app.geo.tenant_scope.ensure_geo_entitlement",
                AsyncMock(side_effect=GeoEntitlementUnavailable()),
            ),
            patch.object(daily_metrics, "load_day_snapshots", load),
        ):
            result = await daily_metrics.safe_rebuild_day(7)

        assert result["skipped"] == "geo_entitlement"
        load.assert_not_awaited()

    asyncio.run(scenario())


def test_daily_metrics_does_not_commit_when_entitlement_changes_during_rebuild():
    async def scenario():
        from datetime import date
        from app.geo.content import daily_metrics

        checks = 0

        async def ensure(_session, _tenant_id):
            nonlocal checks
            checks += 1
            if checks == 2:
                raise GeoEntitlementUnavailable()

        session = NS(scalars=AsyncMock(return_value=[]), commit=AsyncMock())
        with (
            patch("app.geo.tenant_scope.ensure_geo_entitlement", side_effect=ensure),
            patch.object(
                daily_metrics, "load_day_snapshots", AsyncMock(return_value=[])
            ),
            patch.object(
                daily_metrics,
                "load_prompt_unit_maps",
                AsyncMock(return_value=({}, {}, {})),
            ),
            patch.object(daily_metrics, "upsert_metric_row", AsyncMock()),
            pytest.raises(GeoEntitlementUnavailable),
        ):
            await daily_metrics.rebuild_day(
                session, 7, date(2026, 9, 8), enforce_entitlement=True
            )

        session.commit.assert_not_awaited()

    asyncio.run(scenario())
