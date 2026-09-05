import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64",
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.config import Settings
from app.seo_ranking_jobs import (
    _SHANGHAI_TZ,
    _actionable_error_labels,
    _collection_due,
    _engine_interval_days,
    _group_keyword_ids_by_site,
    _isolated_tenant_session,
    _latest_successful_collections,
    _limited_batches,
    _local_day_start_utc,
    _rotate_daily,
    _rollback_tenant_session,
    _scheduled_health_summary,
    _scheduled_rank_engines,
    collect_daily_seo_rankings,
)
from app.seo_scheduler import shutdown_seo_scheduler, start_seo_scheduler


class SeoSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_tenant_session_contains_body_and_exit_failures(self):
        session = SimpleNamespace()

        class BrokenExitContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *_args):
                raise RuntimeError("connection lost during close")

        with patch(
            "app.seo_ranking_jobs.async_session_factory",
            return_value=BrokenExitContext(),
        ):
            async with _isolated_tenant_session(7) as actual:
                self.assertIs(actual, session)

    async def test_failed_rollback_is_contained_inside_tenant_session(self):
        session = SimpleNamespace(
            rollback=AsyncMock(side_effect=RuntimeError("connection lost")),
            close=AsyncMock(),
        )

        await _rollback_tenant_session(session, 7)

        session.rollback.assert_awaited_once()
        session.close.assert_awaited_once()

    def test_default_rank_schedule_enables_domestic_cadence(self):
        defaults = Settings.model_fields
        self.assertEqual(
            defaults["seo_rank_scheduler_engines"].default,
            "baidu,sogou,360,google,bing",
        )
        self.assertEqual(
            defaults["seo_rank_scheduler_engine_interval_days"].default,
            "baidu:1,sogou:2,360:2",
        )

    def test_request_budget_truncates_batches(self):
        self.assertEqual(_limited_batches([1, 2, 3, 4, 5], 2, 3), [[1, 2], [3]])
        self.assertEqual(_limited_batches([1, 2], 2, 0), [])

    def test_keywords_are_grouped_by_site_without_losing_order(self):
        self.assertEqual(
            _group_keyword_ids_by_site([(11, 3), (12, 4), (13, 3), (14, None)]),
            [(3, [11, 13]), (4, [12])],
        )

    def test_daily_window_uses_shanghai_midnight(self):
        local_now = datetime(2026, 8, 22, 2, 0, tzinfo=_SHANGHAI_TZ)
        self.assertEqual(
            _local_day_start_utc(local_now),
            datetime(2026, 8, 21, 16, 0),
        )

    def test_constrained_work_rotates_across_shanghai_days(self):
        values = ["baidu", "sogou", "360"]
        first_items = {
            _rotate_daily(
                values,
                datetime(2026, 9, day, 2, 0),
                salt=7,
            )[0]
            for day in (1, 2, 3)
        }
        self.assertEqual(first_items, set(values))
        self.assertEqual(set(_rotate_daily(values, datetime(2026, 9, 1))), set(values))

    def test_scheduled_engines_require_dataforseo_credentials(self):
        settings = SimpleNamespace(
            seo_rank_scheduler_engines="baidu,google,bing,unknown,google"
        )
        self.assertEqual(
            _scheduled_rank_engines(settings, dataforseo_configured=False),
            ["baidu"],
        )
        self.assertEqual(
            _scheduled_rank_engines(settings, dataforseo_configured=True),
            ["baidu", "google", "bing"],
        )

    def test_engine_cadence_uses_last_success_and_retries_after_failure(self):
        settings = SimpleNamespace(
            seo_rank_scheduler_engine_interval_days="baidu:1,sogou:2,360:2"
        )
        self.assertEqual(
            _engine_interval_days(settings),
            {"baidu": 1, "sogou": 2, "360": 2},
        )
        last_success = datetime(2026, 9, 1, 18, 0)
        self.assertFalse(
            _collection_due(last_success, 2, datetime(2026, 9, 3, 17, 59))
        )
        self.assertTrue(
            _collection_due(last_success, 2, datetime(2026, 9, 3, 18, 0))
        )
        self.assertTrue(_collection_due(None, 2, datetime(2026, 9, 2, 18, 0)))

    def test_invalid_engine_cadence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cadence"):
            _engine_interval_days(SimpleNamespace(
                seo_rank_scheduler_engine_interval_days="sogou:not-a-number"
            ))

    async def test_latest_domestic_success_uses_available_health_only(self):
        health_at = datetime(2026, 9, 1, 4, 0)
        session = SimpleNamespace(execute=AsyncMock(return_value=
            SimpleNamespace(all=lambda: [
                (3, "sogou:desktop", "available", health_at)
            ])))
        latest = await _latest_successful_collections(
            session,
            tenant_id=7,
            site_ids={3},
            engines={"sogou"},
        )
        self.assertEqual(latest[(3, "sogou", "desktop")], health_at)
        self.assertEqual(session.execute.await_count, 1)
        statement = str(session.execute.await_args.args[0])
        self.assertIn("seo_metric_snapshots.site_id IN", statement)
        self.assertIn("seo_metric_snapshots.metric_type =", statement)
        self.assertIn("seo_metric_snapshots.source =", statement)

    def test_scheduled_health_preserves_supplier_failure(self):
        health = _scheduled_health_summary(
            incomplete=True,
            successful_observations=0,
            errors=[{
                "code": "provider_quota_exceeded",
                "status_code": 436,
                "message": "站长之家接口额度不足",
            }],
        )
        self.assertEqual(health["status"], "failed")
        self.assertEqual(health["code"], "provider_quota_exceeded")
        self.assertEqual(health["status_code"], 436)
        self.assertEqual(health["error_message"], "站长之家接口额度不足")

    def test_scheduled_health_keeps_supplier_code_for_partial_run(self):
        health = _scheduled_health_summary(
            incomplete=True,
            successful_observations=2,
            errors=[{
                "code": "provider_ip_rejected",
                "status_code": 437,
                "message": "生产出口 IP 未加入白名单",
            }],
        )
        self.assertEqual(health["status"], "partial")
        self.assertEqual(health["code"], "provider_ip_rejected")
        self.assertEqual(health["status_code"], 437)

    def test_scheduled_health_prioritizes_supplier_error_over_timeout(self):
        health = _scheduled_health_summary(
            incomplete=True,
            successful_observations=1,
            errors=[
                {"code": "provider_timeout", "message": "请求超时"},
                {
                    "code": "provider_quota_exceeded",
                    "status_code": 436,
                    "message": "接口额度不足",
                },
            ],
        )
        self.assertEqual(health["status"], "partial")
        self.assertEqual(health["code"], "provider_quota_exceeded")
        self.assertEqual(health["status_code"], 436)

    def test_scheduled_health_marks_complete_run_available(self):
        health = _scheduled_health_summary(
            incomplete=False,
            successful_observations=3,
            errors=[],
        )
        self.assertEqual(health["status"], "available")
        self.assertIsNone(health["code"])

    async def test_recent_success_skips_non_daily_engine_in_full_job(self):
        settings = SimpleNamespace(
            seo_rank_scheduler_enabled=True,
            seo_rank_scheduler_engines="sogou",
            seo_rank_scheduler_engine_interval_days="sogou:2",
            seo_rank_scheduler_max_keywords_per_tenant=200,
            seo_rank_scheduler_max_requests_per_run=1000,
            seo_rank_scheduler_batch_size=20,
            seo_rank_scheduler_use_ai=False,
        )
        recent = datetime.utcnow()
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[
                SimpleNamespace(all=lambda: []),
                SimpleNamespace(all=lambda: [(101, 3)]),
                SimpleNamespace(all=lambda: [
                    (3, "sogou:desktop", "available", recent),
                    (3, "sogou:mobile", "available", recent),
                ]),
            ]),
            scalars=AsyncMock(return_value=[7]),
        )

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *_args):
                return False

        with (
            patch("app.seo_ranking_jobs.get_settings", return_value=settings),
            patch("app.seo_ranking_jobs.chinaz_rank_status", return_value={
                "sogou": {"configured": True}
            }),
            patch("app.seo_ranking_jobs.acquire_file_lock", return_value=object()),
            patch(
                "app.seo_ranking_jobs.list_active_module_tenants",
                new=AsyncMock(return_value=[SimpleNamespace(id=7)]),
            ),
            patch(
                "app.seo_ranking_jobs.async_session_factory",
                return_value=SessionContext(),
            ) as session_factory,
            patch(
                "app.api.seo.collect_rank_serp_for_tenant",
                new=AsyncMock(),
            ) as collector,
            patch(
                "app.seo_ranking_jobs.start_automation_run",
                new=AsyncMock(),
            ) as start_run,
            patch("app.seo_ranking_jobs.release_file_lock"),
        ):
            await collect_daily_seo_rankings()

        collector.assert_not_awaited()
        start_run.assert_not_awaited()
        self.assertEqual(session_factory.call_count, 2)

    async def test_disabled_collection_does_not_take_run_lock(self):
        settings = SimpleNamespace(seo_rank_scheduler_enabled=False)
        with (
            patch("app.seo_ranking_jobs.get_settings", return_value=settings),
            patch("app.seo_ranking_jobs.acquire_file_lock") as acquire_lock,
        ):
            await collect_daily_seo_rankings()
        acquire_lock.assert_not_called()

    async def test_collection_lock_contention_skips_run(self):
        settings = SimpleNamespace(seo_rank_scheduler_enabled=True)
        with (
            patch("app.seo_ranking_jobs.get_settings", return_value=settings),
            patch("app.seo_ranking_jobs.acquire_file_lock", return_value=None),
        ):
            await collect_daily_seo_rankings()

    async def test_unassigned_keywords_are_reported_without_collection(self):
        settings = SimpleNamespace(
            seo_rank_scheduler_enabled=True,
            seo_rank_scheduler_max_keywords_per_tenant=200,
            seo_rank_scheduler_max_requests_per_run=1000,
            seo_rank_scheduler_batch_size=20,
            seo_rank_scheduler_use_ai=False,
        )
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(1, 2)])),
            scalars=AsyncMock(return_value=[]),
        )

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *_args):
                return False

        with (
            patch("app.seo_ranking_jobs.get_settings", return_value=settings),
            patch("app.seo_ranking_jobs.chinaz_rank_status", return_value={"baidu": {"configured": True}}),
            patch("app.seo_ranking_jobs.acquire_file_lock", return_value=object()),
            patch(
                "app.seo_ranking_jobs.list_active_module_tenants",
                new=AsyncMock(return_value=[SimpleNamespace(id=1)]),
            ),
            patch(
                "app.seo_ranking_jobs.async_session_factory",
                return_value=SessionContext(),
            ),
            patch("app.seo_ranking_jobs.logger.warning") as warning,
            patch("app.seo_ranking_jobs.release_file_lock"),
        ):
            await collect_daily_seo_rankings()

        warning.assert_called_once_with(
            "[scheduler][SEO] 客户 %s 有 %s 个启用关键词未关联网站，已跳过",
            1,
            2,
        )

    async def test_collection_skips_keyword_queries_without_entitled_seo_tenants(self):
        settings = SimpleNamespace(
            seo_rank_scheduler_enabled=True,
            seo_rank_scheduler_max_keywords_per_tenant=200,
            seo_rank_scheduler_max_requests_per_run=1000,
            seo_rank_scheduler_batch_size=20,
            seo_rank_scheduler_use_ai=False,
        )
        session = SimpleNamespace(execute=AsyncMock(), scalars=AsyncMock())

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *_args):
                return False

        with (
            patch("app.seo_ranking_jobs.get_settings", return_value=settings),
            patch("app.seo_ranking_jobs.chinaz_rank_status", return_value={"baidu": {"configured": True}}),
            patch("app.seo_ranking_jobs.acquire_file_lock", return_value=object()),
            patch(
                "app.seo_ranking_jobs.list_active_module_tenants",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.seo_ranking_jobs.async_session_factory",
                return_value=SessionContext(),
            ),
            patch("app.seo_ranking_jobs.release_file_lock"),
        ):
            await collect_daily_seo_rankings()

        session.execute.assert_not_awaited()
        session.scalars.assert_not_awaited()

    async def test_ranking_collection_persists_a_tenant_run_summary(self):
        settings = SimpleNamespace(
            seo_rank_scheduler_enabled=True,
            seo_rank_scheduler_max_keywords_per_tenant=200,
            seo_rank_scheduler_max_requests_per_run=1000,
            seo_rank_scheduler_batch_size=20,
            seo_rank_scheduler_use_ai=False,
        )
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    SimpleNamespace(all=lambda: []),
                    SimpleNamespace(all=lambda: [(101, 3)]),
                    SimpleNamespace(all=lambda: []),
                ]
            ),
            scalars=AsyncMock(return_value=[7]),
            rollback=AsyncMock(),
        )

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *_args):
                return False

        collect_batch = AsyncMock(
            return_value={"snapshots": 1, "serp_results": 1, "errors": []}
        )
        finish_run = AsyncMock()
        with (
            patch("app.seo_ranking_jobs.get_settings", return_value=settings),
            patch("app.seo_ranking_jobs.chinaz_rank_status", return_value={"baidu": {"configured": True}}),
            patch("app.seo_ranking_jobs.acquire_file_lock", return_value=object()),
            patch(
                "app.seo_ranking_jobs.list_active_module_tenants",
                new=AsyncMock(return_value=[SimpleNamespace(id=7)]),
            ),
            patch(
                "app.seo_ranking_jobs.async_session_factory",
                return_value=SessionContext(),
            ),
            patch(
                "app.api.seo.collect_rank_serp_for_tenant",
                new=collect_batch,
            ),
            patch(
                "app.seo_ranking_jobs.start_automation_run",
                new=AsyncMock(return_value=71),
            ) as start_run,
            patch(
                "app.seo_ranking_jobs.finish_automation_run",
                new=finish_run,
            ),
            patch("app.seo_ranking_jobs.release_file_lock"),
        ):
            await collect_daily_seo_rankings()

        self.assertEqual(collect_batch.await_count, 2)
        start_run.assert_awaited_once_with(
            tenant_id=7,
            job_type="ranking",
            planned_count=2,
        )
        finish_run.assert_awaited_once_with(
            71,
            planned_count=2,
            success_count=2,
            failed_count=0,
            skipped_count=0,
            error_summary="",
        )

    async def test_unexpected_batch_failure_conservatively_exhausts_hard_budget(self):
        settings = SimpleNamespace(
            seo_rank_scheduler_enabled=True,
            seo_rank_scheduler_engines="baidu",
            seo_rank_scheduler_max_keywords_per_tenant=200,
            seo_rank_scheduler_max_requests_per_run=1,
            seo_rank_scheduler_batch_size=20,
            seo_rank_scheduler_use_ai=False,
        )
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[
                SimpleNamespace(all=lambda: []),
                SimpleNamespace(all=lambda: [(101, 3)]),
                SimpleNamespace(all=lambda: []),
            ]),
            scalars=AsyncMock(return_value=[7]),
            rollback=AsyncMock(),
        )

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *_args):
                return False

        collector = AsyncMock(side_effect=RuntimeError("post-provider failure"))
        finish_run = AsyncMock()
        info = MagicMock()
        with (
            patch("app.seo_ranking_jobs.get_settings", return_value=settings),
            patch(
                "app.seo_ranking_jobs.chinaz_rank_status",
                return_value={"baidu": {"configured": True}},
            ),
            patch("app.seo_ranking_jobs.acquire_file_lock", return_value=object()),
            patch(
                "app.seo_ranking_jobs.list_active_module_tenants",
                new=AsyncMock(return_value=[SimpleNamespace(id=7)]),
            ),
            patch(
                "app.seo_ranking_jobs.async_session_factory",
                return_value=SessionContext(),
            ),
            patch(
                "app.api.seo.collect_rank_serp_for_tenant",
                new=collector,
            ),
            patch(
                "app.seo_ranking_jobs.start_automation_run",
                new=AsyncMock(return_value=73),
            ),
            patch(
                "app.seo_ranking_jobs.finish_automation_run",
                new=finish_run,
            ),
            patch("app.seo_ranking_jobs.logger.info", new=info),
            patch("app.seo_ranking_jobs.release_file_lock"),
        ):
            await collect_daily_seo_rankings()

        self.assertEqual(collector.await_count, 1)
        self.assertEqual(collector.await_args.kwargs["provider_request_budget"], 1)
        attempted_device = collector.await_args.kwargs["devices"][0]
        finish_run.assert_awaited_once_with(
            73,
            planned_count=2,
            success_count=0,
            failed_count=1,
            skipped_count=1,
            error_summary=f"baidu/{attempted_device}:RuntimeError",
        )
        completion = next(
            call for call in info.call_args_list
            if call.args and "每日多引擎自然排名采集完成" in call.args[0]
        )
        totals = completion.args[2]
        self.assertEqual(totals["requests"], 0)
        self.assertEqual(totals["unknown_request_batches"], 1)

    def test_expected_domain_keyword_misses_do_not_hide_provider_errors(self):
        labels = _actionable_error_labels(
            "sogou",
            "desktop",
            [
                {"code": "keyword_not_found"},
                {"code": "provider_timeout"},
                {"code": "keyword_not_found"},
            ],
        )
        self.assertEqual(labels, ["sogou/desktop:provider_timeout"])

    async def test_configured_google_and_bing_join_daily_collection(self):
        settings = SimpleNamespace(
            seo_rank_scheduler_enabled=True,
            seo_rank_scheduler_engines="baidu,google,bing",
            seo_rank_scheduler_max_keywords_per_tenant=200,
            seo_rank_scheduler_max_requests_per_run=1000,
            seo_dataforseo_scheduler_max_requests_per_run=200,
            seo_rank_scheduler_batch_size=20,
            seo_rank_scheduler_use_ai=False,
        )
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    SimpleNamespace(all=lambda: []),
                    SimpleNamespace(all=lambda: [(101, 3)]),
                    SimpleNamespace(all=lambda: []),
                ]
            ),
            scalars=AsyncMock(return_value=[7]),
            rollback=AsyncMock(),
        )

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *_args):
                return False

        collect_batch = AsyncMock(
            return_value={"snapshots": 1, "serp_results": 1, "errors": []}
        )
        finish_run = AsyncMock()
        with (
            patch("app.seo_ranking_jobs.get_settings", return_value=settings),
            patch(
                "app.seo_ranking_jobs.dataforseo_status",
                return_value={"configured": True},
            ),
            patch("app.seo_ranking_jobs.chinaz_rank_status", return_value={"baidu": {"configured": True}}),
            patch("app.seo_ranking_jobs.acquire_file_lock", return_value=object()),
            patch(
                "app.seo_ranking_jobs.list_active_module_tenants",
                new=AsyncMock(return_value=[SimpleNamespace(id=7)]),
            ),
            patch(
                "app.seo_ranking_jobs.async_session_factory",
                return_value=SessionContext(),
            ),
            patch(
                "app.api.seo.collect_rank_serp_for_tenant",
                new=collect_batch,
            ),
            patch(
                "app.seo_ranking_jobs.start_automation_run",
                new=AsyncMock(return_value=72),
            ) as start_run,
            patch(
                "app.seo_ranking_jobs.finish_automation_run",
                new=finish_run,
            ),
            patch("app.seo_ranking_jobs.release_file_lock"),
        ):
            await collect_daily_seo_rankings()

        self.assertEqual(collect_batch.await_count, 6)
        self.assertEqual(
            [call.kwargs["engine"] for call in collect_batch.await_args_list],
            ["baidu", "baidu", "google", "google", "bing", "bing"],
        )
        start_run.assert_awaited_once_with(
            tenant_id=7,
            job_type="ranking",
            planned_count=6,
        )
        finish_run.assert_awaited_once_with(
            72,
            planned_count=6,
            success_count=6,
            failed_count=0,
            skipped_count=0,
            error_summary="",
        )

    def test_scheduler_lock_contention_does_not_register_or_start(self):
        with (
            patch("app.seo_scheduler._acquire_scheduler_lock", return_value=False),
            patch("app.seo_scheduler.seo_scheduler.add_job") as add_job,
            patch("app.seo_scheduler.seo_scheduler.start") as scheduler_start,
        ):
            start_seo_scheduler()
        add_job.assert_not_called()
        scheduler_start.assert_not_called()

    def test_scheduler_registers_bounded_daily_seo_jobs(self):
        with (
            patch("app.seo_scheduler._acquire_scheduler_lock", return_value=True),
            patch("app.seo_scheduler.seo_scheduler.add_job") as add_job,
            patch("app.seo_scheduler.seo_scheduler.start") as scheduler_start,
        ):
            start_seo_scheduler()
        self.assertEqual(add_job.call_count, 10)
        self.assertEqual(
            {call.kwargs["id"] for call in add_job.call_args_list},
            {
                "collect_daily_seo_rankings",
                "collect_scheduled_seo_competitors",
                "verify_scheduled_seo_backlinks",
                "verify_scheduled_seo_qa",
                "discover_published_seo_backlinks",
                "fail_stale_seo_crawl_runs",
                "prune_old_seo_single_page_snapshots",
                "reconcile_seo_ai_operations",
                "verify_seo_images",
                "collect_seo_cockpit_metrics",
            },
        )
        qa_job = next(call for call in add_job.call_args_list if call.kwargs['id'] == 'verify_scheduled_seo_qa')
        self.assertEqual(qa_job.args[1].interval.total_seconds(), 3600)
        self.assertEqual(qa_job.kwargs['max_instances'], 1)
        scheduler_start.assert_called_once_with()

    def test_start_failure_releases_owner_lock(self):
        with (
            patch("app.seo_scheduler._acquire_scheduler_lock", return_value=True),
            patch(
                "app.seo_scheduler.seo_scheduler.add_job",
                side_effect=RuntimeError("boom"),
            ),
            patch("app.seo_scheduler._release_scheduler_lock") as release_lock,
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                start_seo_scheduler()
        release_lock.assert_called_once_with()

    def test_shutdown_releases_owner_lock(self):
        with (
            patch(
                "app.seo_scheduler.seo_scheduler",
                SimpleNamespace(running=False),
            ),
            patch("app.seo_scheduler._release_scheduler_lock") as release_lock,
        ):
            shutdown_seo_scheduler()
        release_lock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
