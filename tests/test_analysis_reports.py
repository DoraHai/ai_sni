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
from app.api.reports import _client_report_view, _rows_from_report, _validate_period


class AnalysisReportTests(unittest.TestCase):
    def test_client_view_removes_internal_work_and_keeps_only_evidenced_actions(self):
        report = {
            "data": {
                "period": {"start_date": "2026-08-01", "end_date": "2026-08-07"},
                "operational_focus": {"pending_suggestions": 9},
                "alerts_review": {"open": 3},
                "pending_modules": {"conversion": "内部缺口"},
                "operations": {"total": 99, "ai_suggestions_adopted": 8},
                "client_delivery": {
                    "completed_count": 1,
                    "ready_effects": 0,
                    "observing_effects": 1,
                    "completed_actions": [{
                        "id": 1,
                        "object": "关键词A",
                        "action": "关键词出价",
                        "old_value": "1.0",
                        "new_value": "1.1",
                        "evidence": "百度操作记录",
                        "effect": {"sample": {"state": "collecting", "message": "效果观察中"}},
                    }],
                },
            },
            "narrative": {
                "summary": "内部摘要",
                "module_comments": {"overview": "公开数据", "alerts": "内部异常", "operations": "内部操作"},
                "next_period_plan": ["内部待办"],
            },
        }

        client = _client_report_view(report)
        self.assertNotIn("operational_focus", client["data"])
        self.assertNotIn("alerts_review", client["data"])
        self.assertNotIn("pending_modules", client["data"])
        self.assertEqual(client["data"]["operations"]["total"], 1)
        self.assertEqual(client["narrative"]["module_comments"], {"overview": "公开数据"})
        self.assertEqual(client["narrative"]["next_period_plan"], [])
        self.assertIn("百度操作记录确认 1 项", client["narrative"]["summary"])

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
