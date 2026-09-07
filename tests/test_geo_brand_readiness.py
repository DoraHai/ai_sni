"""Brand readiness remains a hard fact after evidence fallback generation."""

import unittest
from contextlib import ExitStack
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.geo.content.rules import RuleInput


def _article_body(brand: str | None = None) -> str:
    opening = f"{brand} 的已核验资料如下。" if brand else "已核验资料如下。"
    conclusion = f"{brand} 的结论仅限上述资料。" if brand else "结论仅限上述资料。"
    return f"# 参考资料\n\n{opening}\n\n## 定义\n\n资料原文。\n\n## 结论与建议\n\n{conclusion}"


def _rule_input(body: str) -> RuleInput:
    return RuleInput(
        question="产品资料是什么？", title="参考资料", body_markdown=body,
        outline={}, facts=[], target_channels=[], variants=[],
    )


class BrandReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def _evaluate(self, task, article):
        settings_env = {
            "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
            "BAIDU_APP_ID": "test", "BAIDU_SECRET_KEY": "test",
            "BAIDU_DEFAULT_USERNAME": "test", "BAIDU_DEFAULT_UCID": "0",
            "BAIDU_SELF_ACCESS_TOKEN": "test",
            "BAIDU_SELF_TOKEN_EXPIRES_AT": "2099-01-01T00:00:00Z",
            "CRYPTO_MASTER_KEY_B64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "ADMIN_API_KEY": "test-admin-key",
        }
        with patch.dict(os.environ, settings_env, clear=False):
            from app.geo.content.routes import _evaluate_and_store_rules

        passed_check = SimpleNamespace(
            code="ordinary_rule",
            passed=True,
            to_dict=lambda: {
                "code": "ordinary_rule", "passed": True,
                "message": "其他规则通过", "action": "",
            },
        )
        settings = SimpleNamespace(geo_score_gate=False, geo_score_threshold=60)
        patches = (
            patch("app.geo.content.routes._build_rule_input", new=AsyncMock(return_value=_rule_input(article.body_markdown))),
            patch("app.geo.content.routes.run_checks", return_value=[passed_check]),
            patch("app.geo.content.routes.build_fix_patches", return_value=[]),
            patch("app.geo.content.draft_lint.lint_draft", return_value=[]),
            patch("app.geo.content.draft_lint.lint_summary", return_value={"blocks_ready": True, "high": 0, "issues": []}),
            patch("app.geo.content.extractable_blocks.blocks_payload", return_value={}),
            patch("app.geo.content.geo_score.compute_geo_score", return_value={"geo_score": 100, "geo_subscores": {}, "geo_actions": []}),
            patch("app.geo.content.routes._ensure_tenant_exists", new=AsyncMock(return_value=SimpleNamespace(id=7))),
            patch("app.geo.content.routes._brand_context_for_task", new=AsyncMock(return_value=("工业齿轮箱", ["工业齿轮箱"]))),
            patch("app.geo.content.routes._sync_task_pipeline", new=AsyncMock()),
            patch("app.config.get_settings", return_value=settings),
        )
        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            return await _evaluate_and_store_rules(AsyncMock(), task, article)

    async def test_brand_failure_blocks_ready_with_score_gate_off_and_manual_edit_rechecks(self):
        task = SimpleNamespace(
            tenant_id=7, brief={}, rule_result={}, target_channels=[],
            status="editing", ready_at=None,
        )
        article = SimpleNamespace(
            title="参考资料", body_markdown=_article_body(),
            generation_meta={"brand_validation": {"passed": False, "brand": "工业齿轮箱"}},
        )

        result = await self._evaluate(task, article)
        self.assertFalse(result["ready"])
        self.assertFalse(result["brand_validation"]["passed"])
        self.assertEqual(task.status, "needs_fix")
        self.assertTrue(any(
            c["code"] == "geo_brand_standard" and not c["passed"]
            for c in result["checks"]
        ))
        self.assertTrue(all(
            c["passed"] for c in result["checks"]
            if c["code"] != "geo_brand_standard"
        ))

        # Re-evaluate the current Markdown; do not inherit the old warning forever.
        article.body_markdown = _article_body("工业齿轮箱")
        task.status = "editing"
        result = await self._evaluate(task, article)
        self.assertTrue(result["ready"])
        self.assertTrue(result["brand_validation"]["passed"])
        self.assertEqual(task.status, "ready")


if __name__ == "__main__":
    unittest.main()
