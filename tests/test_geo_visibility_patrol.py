"""GEO visibility auto patrol unit tests."""

from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.geo.content.patrol import (
    STALE_PENDING_SECONDS,
    clamp_interval_hours,
    execute_patrol_run,
    hour_in_window,
    mark_patrol_run_failed,
    patrol_run_payload,
    reconcile_stale_patrol_run,
    should_run_scheduled_patrol,
)
from app.geo.content.probe import SAMPLE_MODE_PERSONA, SAMPLE_MODE_REAL


class StalePatrolReconcileTests(unittest.IsolatedAsyncioTestCase):
    async def test_mark_failed_only_open_statuses(self):
        row = SimpleNamespace(
            id=2,
            status="pending",
            error=None,
            finished_at=None,
            summary=None,
            items=None,
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=row)
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        out = await mark_patrol_run_failed(session, 2, "boom")
        self.assertEqual(out.status, "failed")
        self.assertIn("boom", out.error)
        session.commit.assert_awaited()

    async def test_reconcile_stale_pending(self):
        from datetime import timedelta

        old = datetime.utcnow() - timedelta(seconds=STALE_PENDING_SECONDS + 10)
        row = SimpleNamespace(
            id=3,
            status="pending",
            started_at=None,
            created_at=old,
            error=None,
            finished_at=None,
            summary=None,
            items=None,
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=row)
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        out = await reconcile_stale_patrol_run(session, row)
        self.assertEqual(out.status, "failed")
        self.assertIn("后台任务", out.error or "")


class ScheduleWindowTests(unittest.TestCase):
    def test_hour_in_window_same_day(self):
        self.assertTrue(hour_in_window(8, 8, 20))
        self.assertTrue(hour_in_window(20, 8, 20))
        self.assertFalse(hour_in_window(7, 8, 20))
        self.assertFalse(hour_in_window(21, 8, 20))

    def test_hour_in_window_overnight(self):
        self.assertTrue(hour_in_window(23, 22, 6))
        self.assertTrue(hour_in_window(0, 22, 6))
        self.assertTrue(hour_in_window(6, 22, 6))
        self.assertFalse(hour_in_window(12, 22, 6))

    def test_clamp_interval(self):
        self.assertEqual(clamp_interval_hours(4), 4)
        self.assertEqual(clamp_interval_hours(5), 4)  # nearest
        self.assertEqual(clamp_interval_hours(100), 24)

    def test_should_run_respects_window_and_interval(self):
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Shanghai")
        now = datetime(2026, 8, 6, 10, 5, tzinfo=tz)
        self.assertTrue(
            should_run_scheduled_patrol(
                now=now,
                window_start_hour=8,
                window_end_hour=20,
                interval_hours=4,
                last_scheduled_at=None,
            )
        )
        self.assertFalse(
            should_run_scheduled_patrol(
                now=datetime(2026, 8, 6, 7, 5, tzinfo=tz),
                window_start_hour=8,
                window_end_hour=20,
                interval_hours=4,
                last_scheduled_at=None,
            )
        )
        # last run 1h ago, interval 4h → skip
        self.assertFalse(
            should_run_scheduled_patrol(
                now=now,
                window_start_hour=8,
                window_end_hour=20,
                interval_hours=4,
                last_scheduled_at=datetime(2026, 8, 6, 1, 5, 0),  # UTC naive ~9h earlier wall depends
            )
        )
        # last run long ago → run
        self.assertTrue(
            should_run_scheduled_patrol(
                now=now,
                window_start_hour=8,
                window_end_hour=20,
                interval_hours=4,
                last_scheduled_at=datetime(2026, 8, 5, 1, 0, 0),
            )
        )


class PatrolPayloadTests(unittest.TestCase):
    def test_patrol_run_payload_shape(self):
        row = SimpleNamespace(
            id=3,
            tenant_id=1,
            status="completed",
            trigger="manual",
            auto_persist=True,
            prefer_real=True,
            prompt_limit=10,
            engine_keys=["deepseek"],
            summary={"cells_ok": 1},
            items=[{"ok": True}],
            error=None,
            started_at=datetime(2026, 8, 6, 1, 0, 0),
            finished_at=datetime(2026, 8, 6, 1, 5, 0),
            created_by=9,
            created_at=datetime(2026, 8, 6, 0, 59, 0),
        )
        payload = patrol_run_payload(row)
        self.assertEqual(payload["id"], 3)
        self.assertEqual(payload["status"], "completed")
        self.assertTrue(payload["auto_persist"])
        self.assertEqual(payload["summary"]["cells_ok"], 1)
        self.assertIsNotNone(payload["started_at"])


class ExecutePatrolRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_patrol_persists_snapshot(self):
        prompt = SimpleNamespace(
            id=11,
            question="哪家最好？",
            tags=["high_demand"],
            priority=10,
        )
        engine_row = SimpleNamespace(
            id=1,
            engine_key="deepseek",
            enabled=True,
            sort_order=0,
            sample_mode="mock_persona",
            api_key_encrypted=None,
        )
        tenant = SimpleNamespace(id=1, name="Acme", brand_terms=["Acme"])

        run = SimpleNamespace(
            id=99,
            tenant_id=1,
            status="pending",
            trigger="manual",
            auto_persist=True,
            prefer_real=True,
            prompt_limit=5,
            engine_keys=["deepseek"],
            summary=None,
            items=None,
            error=None,
            started_at=None,
            finished_at=None,
            created_by=1,
        )

        session = AsyncMock()
        session.get = AsyncMock(side_effect=lambda model, pk: {
            # GeoVisibilityPatrolRun lookups by id
            99: run,
            1: tenant if model.__name__ == "Tenant" else run,
        }.get(pk, run if model.__name__ == "GeoVisibilityPatrolRun" else (
            tenant if model.__name__ == "Tenant" else None
        )))

        # scalars: engines then prompts
        scalars_results = [
            [engine_row],
            [prompt],
        ]

        async def scalars(stmt):
            if not scalars_results:
                return []
            return scalars_results.pop(0)

        session.scalars = AsyncMock(side_effect=scalars)
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()

        draft = {
            "raw_text": "推荐 Acme。https://acme.example/p",
            "sample_mode": SAMPLE_MODE_PERSONA,
            "simulated": True,
            "suggested_mentions_brand": True,
            "competitors": ["竞品甲"],
            "brand_position": "first",
            "sentiment": "positive",
            "model": "m",
            "provider": "dashscope",
        }

        with (
            patch("app.ai.deepseek.chat_json", new_callable=AsyncMock),
            patch(
                "app.geo.content.ai_settings.resolve_llm_credentials",
                new_callable=AsyncMock,
                return_value={
                    "api_key": "sk-test",
                    "base_url": "https://example.com/v1",
                    "model": "m",
                    "provider": "dashscope",
                },
            ),
            patch(
                "app.geo.content.patrol.resolve_engine_llm",
                return_value=(
                    {
                        "api_key": "sk-test",
                        "base_url": "https://example.com/v1",
                        "model": "m",
                        "provider": "dashscope",
                    },
                    SAMPLE_MODE_PERSONA,
                    None,
                ),
            ),
            patch(
                "app.geo.content.patrol.run_probe_draft",
                new_callable=AsyncMock,
                return_value=draft,
            ),
            patch(
                "app.geo.content.patrol.GeoAnswerSnapshot",
                side_effect=lambda **kw: SimpleNamespace(id=501, **kw),
            ),
        ):
            # Fix session.get to route by model name properly
            async def get_row(model, pk):
                name = getattr(model, "__name__", str(model))
                if name == "GeoVisibilityPatrolRun":
                    return run
                if name == "Tenant":
                    return tenant
                return None

            session.get = AsyncMock(side_effect=get_row)

            result = await execute_patrol_run(session, 99)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.summary["cells_ok"], 1)
        self.assertEqual(result.summary["snapshots_created"], 1)
        self.assertEqual(result.summary["persona_samples"], 1)
        self.assertEqual(len(result.items), 1)
        self.assertTrue(result.items[0]["ok"])
        self.assertEqual(result.items[0]["snapshot_id"], 501)
        session.add.assert_called()

    async def test_execute_patrol_fails_without_prompts(self):
        engine_row = SimpleNamespace(
            id=1,
            engine_key="deepseek",
            enabled=True,
            sort_order=0,
            sample_mode="mock_persona",
            api_key_encrypted=None,
        )
        tenant = SimpleNamespace(id=1, name="Acme", brand_terms=None)
        run = SimpleNamespace(
            id=7,
            tenant_id=1,
            status="pending",
            trigger="manual",
            auto_persist=True,
            prefer_real=True,
            prompt_limit=5,
            engine_keys=None,
            summary=None,
            items=None,
            error=None,
            started_at=None,
            finished_at=None,
            created_by=None,
        )
        session = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()

        # engines once, then active prompts empty, then any prompts empty
        scalars_results = [[engine_row], [], []]

        async def scalars(_stmt):
            return scalars_results.pop(0) if scalars_results else []

        session.scalars = AsyncMock(side_effect=scalars)

        async def get_row(model, pk):
            name = getattr(model, "__name__", str(model))
            if name == "GeoVisibilityPatrolRun":
                return run
            if name == "Tenant":
                return tenant
            return None

        session.get = AsyncMock(side_effect=get_row)

        with (
            patch(
                "app.geo.content.ai_settings.resolve_llm_credentials",
                new_callable=AsyncMock,
                return_value={"api_key": "k", "base_url": "u", "model": "m", "provider": "p"},
            ),
        ):
            result = await execute_patrol_run(session, 7)

        self.assertEqual(result.status, "failed")
        self.assertIn("机会词", result.error or "")

    async def test_real_sample_counted(self):
        prompt = SimpleNamespace(id=1, question="q", tags=[], priority=1)
        engine_row = SimpleNamespace(
            id=1,
            engine_key="chatgpt",
            enabled=True,
            sort_order=0,
            sample_mode=SAMPLE_MODE_REAL,
            api_key_encrypted="enc",
        )
        tenant = SimpleNamespace(id=1, name="Acme", brand_terms=["Acme"])
        run = SimpleNamespace(
            id=2,
            tenant_id=1,
            status="pending",
            trigger="schedule",
            auto_persist=False,
            prefer_real=True,
            prompt_limit=5,
            engine_keys=["chatgpt"],
            summary=None,
            items=None,
            error=None,
            started_at=None,
            finished_at=None,
            created_by=None,
        )
        session = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        scalars_results = [[engine_row], [prompt]]

        async def scalars(_stmt):
            return scalars_results.pop(0) if scalars_results else []

        session.scalars = AsyncMock(side_effect=scalars)

        async def get_row(model, _pk):
            name = getattr(model, "__name__", str(model))
            if name == "GeoVisibilityPatrolRun":
                return run
            if name == "Tenant":
                return tenant
            return None

        session.get = AsyncMock(side_effect=get_row)

        draft = {
            "raw_text": "real answer Acme",
            "sample_mode": SAMPLE_MODE_REAL,
            "simulated": False,
            "suggested_mentions_brand": True,
            "competitors": [],
            "brand_position": "mentioned",
            "sentiment": "neutral",
        }

        with (
            patch(
                "app.geo.content.ai_settings.resolve_llm_credentials",
                new_callable=AsyncMock,
                return_value={"api_key": "k", "base_url": "u", "model": "m", "provider": "p"},
            ),
            patch(
                "app.geo.content.patrol.resolve_engine_llm",
                return_value=(
                    {"api_key": "k", "base_url": "u", "model": "m", "provider": "engine:chatgpt"},
                    SAMPLE_MODE_REAL,
                    None,
                ),
            ),
            patch(
                "app.geo.content.patrol.run_probe_draft",
                new_callable=AsyncMock,
                return_value=draft,
            ),
        ):
            result = await execute_patrol_run(session, 2)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.summary["real_samples"], 1)
        self.assertEqual(result.summary["snapshots_created"], 0)
        self.assertFalse(result.items[0]["simulated"])


if __name__ == "__main__":
    unittest.main()
