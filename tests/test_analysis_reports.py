import os
import unittest
from datetime import date
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64",
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from fastapi import HTTPException

from app.ai.monthly_report import _build_prompt, _suggestion_business_score, _suggestion_impact
from app.api.reports import _rows_from_report, _validate_period


class AnalysisReportTests(unittest.TestCase):
    def test_report_suggestions_rank_material_zero_conversion_risk_first(self):
        base = {
            "priority": "P1",
            "confidence": "mid",
            "suggestion_type": "lower",
        }
        costly = SimpleNamespace(**base, signals={
            "cost": 800,
            "risk_factors": {"zero_conversion": True, "high_cpc": True},
        })
        ordinary = SimpleNamespace(**base, signals={"cost": 20})

        self.assertGreater(_suggestion_business_score(costly), _suggestion_business_score(ordinary))
        self.assertEqual(_suggestion_impact(costly), "近 7 天消耗 ¥800，暂无转化")

    def test_custom_period_validation(self):
        _validate_period(date(2026, 7, 1), date(2026, 7, 30))
        with self.assertRaises(HTTPException):
            _validate_period(date(2026, 7, 30), date(2026, 7, 1))
        with self.assertRaises(HTTPException):
            _validate_period(date(2025, 1, 1), date(2026, 1, 2))

    def test_prompt_uses_custom_period_language(self):
        data = {
            "tenant": {"name": "测试客户"},
            "period": {
                "start_date": "2026-07-03",
                "end_date": "2026-07-19",
                "active_days": 9,
                "days": 17,
            },
            "kpi": {
                key: {"current": 1, "previous": 1, "change_pct": 0}
                for key in ("cost", "click", "impression", "cpc", "ctr")
            },
            "budget": {
                "monthly_budget": None,
                "period_cost": 1,
                "usage_pct": None,
            },
            "by_category": [],
            "top_keywords": [],
            "device_split": [],
            "alerts_review": {},
            "operations": {
                "total": 0,
                "by_level": {},
                "over_limit": 0,
                "ai_suggestions_adopted": 0,
            },
        }
        prompt = _build_prompt(data)
        self.assertIn("2026-07-03~2026-07-19", prompt)
        self.assertIn("上一等长区间", prompt)
        self.assertNotIn("报告月份", prompt)

    def test_export_rows_use_period_labels(self):
        report = {
            "data": {
                "tenant": {"name": "测试客户"},
                "period": {
                    "start_date": "2026-07-03",
                    "end_date": "2026-07-19",
                    "active_days": 9,
                    "days": 17,
                },
                "kpi": {
                    key: {"current": 1, "previous": 1, "change_pct": 0}
                    for key in ("cost", "click", "impression", "cpc", "ctr")
                },
                "budget": {
                    "period_cost": 100,
                    "monthly_budget": 500,
                    "usage_pct": 20,
                },
                "trend": [],
                "by_category": [],
                "top_keywords": [],
                "device_split": [],
                "alerts_review": {},
                "operations": {
                    "total": 0,
                    "by_level": {},
                    "over_limit": 0,
                    "ai_suggestions_adopted": 0,
                },
            },
            "narrative": {"next_period_plan": ["继续观察"]},
        }
        rows = _rows_from_report(report)
        flattened = "\n".join(" | ".join(map(str, row)) for row in rows)
        self.assertIn("自定义区间", flattened)
        self.assertIn("上一等长区间值", flattened)
        self.assertIn("后续计划", flattened)


if __name__ == "__main__":
    unittest.main()
