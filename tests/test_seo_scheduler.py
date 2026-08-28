import os
import unittest
from datetime import datetime
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
    collect_daily_seo_rankings,
)
from app.seo_scheduler import shutdown_seo_scheduler, start_seo_scheduler


class SeoSchedulerTests(unittest.IsolatedAsyncioTestCase):
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

    def test_scheduler_lock_contention_does_not_register_or_start(self):
        with (
            patch("app.seo_scheduler._acquire_scheduler_lock", return_value=False),
            patch("app.seo_scheduler.seo_scheduler.add_job") as add_job,
            patch("app.seo_scheduler.seo_scheduler.start") as scheduler_start,
        ):
            start_seo_scheduler()
        add_job.assert_not_called()
        scheduler_start.assert_not_called()

    def test_scheduler_registers_only_daily_rank_job(self):
        with (
            patch("app.seo_scheduler._acquire_scheduler_lock", return_value=True),
            patch("app.seo_scheduler.seo_scheduler.add_job") as add_job,
            patch("app.seo_scheduler.seo_scheduler.start") as scheduler_start,
        ):
            start_seo_scheduler()
        add_job.assert_called_once()
        self.assertEqual(add_job.call_args.kwargs["id"], "collect_daily_seo_rankings")
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
