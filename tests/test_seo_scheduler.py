import os
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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

from app.seo_ranking_jobs import (
    _SHANGHAI_TZ,
    _group_keyword_ids_by_site,
    _limited_batches,
    _local_day_start_utc,
    _scheduled_rank_engines,
    collect_daily_seo_rankings,
)
from app.seo_scheduler import shutdown_seo_scheduler, start_seo_scheduler
from app.config import Settings


class SeoSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def test_daily_rank_collection_is_opt_in(self):
        self.assertIs(Settings.model_fields["seo_rank_scheduler_enabled"].default, False)
        env_example = (Path(__file__).parents[1] / ".env.example").read_text(encoding="utf-8")
        self.assertIn("SEO_RANK_SCHEDULER_ENABLED=false", env_example)

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
        self.assertEqual(add_job.call_count, 4)
        self.assertEqual(
            {call.kwargs["id"] for call in add_job.call_args_list},
            {
                "collect_daily_seo_rankings",
                "collect_scheduled_seo_competitors",
                "verify_scheduled_seo_backlinks",
                "fail_stale_seo_crawl_runs",
            },
        )
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
