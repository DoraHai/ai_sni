import os
import time
import unittest
from datetime import date
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

from app.rules.budget_overrun import BudgetOverrunRule
from app.rules.engine import _dedupe_alert_records
from app.rules.site_health import SiteHealthRule


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class SemAlertRuleTests(unittest.IsolatedAsyncioTestCase):
    def test_entity_ref_records_are_idempotent_before_bulk_upsert(self):
        report_date = date(2026, 8, 14)
        records = [
            {
                "tenant_id": 1,
                "rule_code": "R-SITE",
                "priority": "P0",
                "title": "first",
                "message": "old",
                "report_date": report_date,
                "keyword_id": None,
                "keyword": None,
                "campaign_id": None,
                "campaign_name": None,
                "entity_ref": "url:abc123",
                "metrics": {"elapsed_ms": 5000},
            },
            {
                "tenant_id": 1,
                "rule_code": "R-SITE",
                "priority": "P0",
                "title": "second",
                "message": "new",
                "report_date": report_date,
                "keyword_id": None,
                "keyword": None,
                "campaign_id": None,
                "campaign_name": None,
                "entity_ref": "url:abc123",
                "metrics": {"elapsed_ms": 6000},
            },
        ]

        deduped = _dedupe_alert_records(records)

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["entity_ref"], "url:abc123")
        self.assertEqual(deduped[0]["title"], "second")
        self.assertEqual(deduped[0]["metrics"]["elapsed_ms"], 6000)

    async def test_account_budget_overrun_accepts_string_budget_type(self):
        tenant = SimpleNamespace(id=1)
        account = SimpleNamespace(
            id=7,
            tenant_id=1,
            baidu_username="test-account",
            status="active",
        )
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=96),
            scalars=AsyncMock(return_value=_Rows([account])),
            execute=AsyncMock(return_value=_Rows([])),
        )
        service = SimpleNamespace(
            get_account_info=AsyncMock(
                return_value={
                    "data": {
                        "budgetType": "1",
                        "budget": "100.00",
                        "cost": "96.00",
                    }
                }
            )
        )

        with (
            patch("app.rules.budget_overrun._account_client", return_value=object()),
            patch("app.rules.budget_overrun.AccountService", return_value=service),
        ):
            drafts = await BudgetOverrunRule()._account_alerts(
                session, tenant, date(2026, 8, 14)
            )

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].entity_ref, "account:7")
        self.assertEqual(
            drafts[0].metrics,
            {
                "budget": 100.0,
                "cost": 96.0,
                "usage_pct": 96.0,
                "cost_source": "kw_report_snapshots",
                "budget_as_of": "当前实时值，非历史快照",
            },
        )
        self.assertIn("96.0%", drafts[0].title)
        self.assertIn("100.00", drafts[0].message)

    async def test_campaign_budget_overrun_message_and_metrics(self):
        tenant = SimpleNamespace(id=1)
        campaign = SimpleNamespace(
            campaign_id=88,
            campaign_name="High Cost Campaign",
            budget=100,
            pause=False,
        )
        session = SimpleNamespace(
            scalars=AsyncMock(return_value=_Rows([campaign])),
            execute=AsyncMock(return_value=_Rows([(88, 97)])),
        )

        drafts = await BudgetOverrunRule()._campaign_alerts(
            session, tenant, date(2026, 8, 14)
        )

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].entity_ref, "campaign:88")
        self.assertEqual(drafts[0].campaign_id, 88)
        self.assertEqual(drafts[0].metrics, {"budget": 100.0, "cost": 97.0, "usage_pct": 97.0})
        self.assertIn("97.0%", drafts[0].title)
        self.assertIn("97.00", drafts[0].message)

    async def test_site_health_rule_can_probe_once_without_real_network(self):
        tenant = SimpleNamespace(id=1)
        adgroup = SimpleNamespace(
            tenant_id=1,
            adgroup_id=3,
            adgroup_name="Landing Unit",
            pause=False,
            pc_final_url="https://example.test/broken",
            mobile_final_url=None,
        )
        session = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([adgroup])))

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, url):
                return SimpleNamespace(status_code=500)

        started = time.monotonic()
        with patch("app.rules.site_health.httpx.AsyncClient", FakeClient):
            drafts = await SiteHealthRule().evaluate(
                session, tenant, date(2026, 8, 14)
            )
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 1)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].rule_code, "R-SITE")
        self.assertEqual(drafts[0].priority, "P0")
        self.assertTrue(drafts[0].entity_ref.startswith("url:"))
        self.assertEqual(drafts[0].metrics["status_code"], 500)


if __name__ == "__main__":
    unittest.main()
