"""GEO 内容规则引擎单测。"""

import unittest

from app.geo.content.rules import RuleInput, build_fix_patches, is_ready, run_checks


def _base(**kwargs) -> RuleInput:
    data = dict(
        question="数据分析平台哪个好用",
        title="数据分析平台怎么选",
        body_markdown=(
            "直接回答：应结合场景与可核验事实选择。\n\n"
            "## 定义\n\n数据分析平台是一种用于汇聚与分析业务数据的系统。\n\n"
            "## 对比选型\n\n与传统报表工具相比，自助分析平台更适合跨部门协作。\n\n"
            "## 操作步骤\n\n"
            "步骤 1：明确分析场景。\n"
            "步骤 2：核对事实卡来源。\n"
            "步骤 3：完成试点验证。\n\n"
            "## FAQ\n\n"
            "- **Q：** 需要关注什么？\n"
            "  **A：** 来源与时效。\n"
            "- **Q：** 如何验证？\n"
            "  **A：** 核对应事实卡。\n\n"
            "## 结论\n\n优先核验来源后再决策。\n\n"
            "## 来源\n\n"
            "- 白皮书\n- 文档\n- 案例\n\n"
            "覆盖 80% 场景，实施约 14 天，服务 120 家客户。\n\n"
            "*作者：GEO Demo*\n"
            "*更新时间：2026-07-28*\n"
        ),
        outline={
            "direct_answer": "应结合场景与可核验事实选择数据分析平台。",
            "author_name": "GEO Demo",
            "sections": [
                {"type": "definition", "heading": "定义", "body": "是一种用于汇聚与分析业务数据的系统。"},
                {
                    "type": "faq",
                    "items": [
                        {"q": "需要关注什么？", "a": "来源与时效"},
                        {"q": "如何验证？", "a": "核对事实卡"},
                    ],
                },
                {"type": "conclusion", "heading": "结论", "body": "优先核验来源后再决策。"},
            ],
            "faq": [
                {"q": "需要关注什么？", "a": "来源与时效"},
                {"q": "如何验证？", "a": "核对事实卡"},
            ],
            "conclusion": "优先核验来源后再决策。",
            "updated_at": "2026-07-28",
        },
        facts=[
            {"id": 1, "statement": "支持私有化部署，覆盖 80% 场景", "source_name": "白皮书", "trust_level": "verified", "status": "active"},
            {"id": 2, "statement": "标准实施约 14 天", "source_name": "文档", "trust_level": "verified", "status": "active"},
            {"id": 3, "statement": "已服务 120 家制造客户", "source_name": "案例", "trust_level": "verified", "status": "active"},
        ],
        target_channels=["website", "zhihu"],
        variants=["website", "zhihu"],
    )
    data.update(kwargs)
    return RuleInput(**data)


class GeoContentRulesTests(unittest.TestCase):
    def test_all_pass_when_complete(self):
        checks = run_checks(_base())
        self.assertTrue(is_ready(checks, require_channels=True))
        self.assertTrue(all(c.passed for c in checks))

    def test_facts_bound_min_fails(self):
        checks = {c.code: c for c in run_checks(_base(facts=[{"id": 1, "source_name": "a", "statement": "x"}]))}
        self.assertFalse(checks["facts_bound_min"].passed)

    def test_facts_sourced_fails(self):
        facts = [
            {"id": 1, "statement": "a", "source_name": "s"},
            {"id": 2, "statement": "b", "source_name": ""},
            {"id": 3, "statement": "c", "source_name": "s"},
        ]
        checks = {c.code: c for c in run_checks(_base(facts=facts))}
        self.assertFalse(checks["facts_sourced"].passed)

    def test_faq_min_fails(self):
        checks = {
            c.code: c
            for c in run_checks(
                _base(
                    outline={"direct_answer": "答案足够长用于通过", "sections": [], "faq": [{"q": "仅一条", "a": "a"}], "conclusion": "结", "updated_at": "2026-07-28"},
                    body_markdown="答案足够长用于通过\n\n## 定义\n\nx\n\n## 结论\n\n结\n\n*更新时间：2026-07-28*\n",
                )
            )
        }
        self.assertFalse(checks["faq_min"].passed)

    def test_definition_fails(self):
        checks = {
            c.code: c
            for c in run_checks(
                _base(
                    outline={
                        "direct_answer": "应结合场景选择平台。",
                        "sections": [{"type": "conclusion", "body": "结"}],
                        "faq": [{"q": "a", "a": "b"}, {"q": "c", "a": "d"}],
                        "conclusion": "结",
                        "updated_at": "2026-07-28",
                    },
                    body_markdown="应结合场景选择平台。\n\n## FAQ\n\n- **Q：** a\n  **A：** b\n- **Q：** c\n  **A：** d\n\n## 结论\n\n结\n\n*更新时间：2026-07-28*\n",
                )
            )
        }
        self.assertFalse(checks["definition"].passed)

    def test_conclusion_fails(self):
        checks = {
            c.code: c
            for c in run_checks(
                _base(
                    outline={
                        "direct_answer": "应结合场景选择平台。",
                        "sections": [{"type": "definition", "body": "定义内容"}],
                        "faq": [{"q": "a", "a": "b"}, {"q": "c", "a": "d"}],
                        "conclusion": "",
                        "updated_at": "2026-07-28",
                    },
                    body_markdown="应结合场景选择平台。\n\n## 定义\n\n定义内容\n\n## FAQ\n\n- **Q：** a\n  **A：** b\n- **Q：** c\n  **A：** d\n\n*更新时间：2026-07-28*\n",
                )
            )
        }
        self.assertFalse(checks["conclusion_extractable"].passed)

    def test_channel_optional_for_ready(self):
        checks = run_checks(_base(variants=[]))
        self.assertTrue(is_ready(checks, require_channels=False))
        self.assertFalse(is_ready(checks, require_channels=True))

    def test_channel_variant_ready_normalizes_aliases(self):
        from app.geo.content.rules import check_channel_variant_ready

        data = _base(
            target_channels=["website", "wechat", "zhihu"],
            variants=["website", "wechat", "zhihu"],
        )
        self.assertTrue(check_channel_variant_ready(data).passed)

        # empty variants fail with clear missing list
        empty = _base(target_channels=["website", "wechat", "zhihu"], variants=[])
        r = check_channel_variant_ready(empty)
        self.assertFalse(r.passed)
        self.assertIn("website", r.message)
        self.assertIn("wechat", r.message)

    def test_updated_at_fails(self):
        checks = {
            c.code: c
            for c in run_checks(
                _base(
                    outline={
                        "direct_answer": "应结合场景选择平台。",
                        "sections": [
                            {"type": "definition", "body": "定义"},
                            {"type": "conclusion", "body": "结论段"},
                        ],
                        "faq": [{"q": "a", "a": "b"}, {"q": "c", "a": "d"}],
                        "conclusion": "结论段",
                        "updated_at": None,
                    },
                    body_markdown="应结合场景选择平台。\n\n## 定义\n\n定义\n\n## FAQ\n\n- **Q：** a\n  **A：** b\n- **Q：** c\n  **A：** d\n\n## 结论\n\n结论段\n",
                )
            )
        }
        self.assertFalse(checks["updated_at_visible"].passed)


class GeoTaskBrandContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_tenant_brand_fallback_is_available_during_task_check(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

        settings = {
            "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
            "BAIDU_APP_ID": "test",
            "BAIDU_SECRET_KEY": "test",
            "BAIDU_DEFAULT_USERNAME": "test",
            "BAIDU_DEFAULT_UCID": "0",
            "BAIDU_SELF_ACCESS_TOKEN": "test",
            "BAIDU_SELF_TOKEN_EXPIRES_AT": "2099-01-01T00:00:00Z",
            "CRYPTO_MASTER_KEY_B64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "ADMIN_API_KEY": "test-admin-key",
        }
        with patch.dict("os.environ", settings, clear=False):
            from app.geo.content.routes import _brand_context_for_prompt

            brand, names = await _brand_context_for_prompt(
                AsyncMock(),
                SimpleNamespace(tenant_id=1, unit_id=None, business_id=None),
                SimpleNamespace(id=1, name="示例品牌", brand_terms=["示例别名"]),
            )

        self.assertEqual(brand, "示例品牌")
        self.assertEqual(names, ["示例品牌"])


class GeoGenerateDeterministicTests(unittest.TestCase):
    def test_deterministic_has_required_structure(self):
        from app.geo.content.generate_article import deterministic_article, to_markdown

        facts = [
            {"id": 1, "title": "部署", "statement": "支持私有化", "source_name": "白皮书"},
            {"id": 2, "title": "API", "statement": "开放接口", "source_name": "文档"},
            {"id": 3, "title": "行业", "statement": "服务制造", "source_name": "案例"},
        ]
        payload = deterministic_article(
            tenant_name="示例品牌", question="数据分析平台哪个好用", facts=facts
        )
        md = to_markdown(payload)
        self.assertTrue("## FAQ" in md or "## 常见问题" in md)
        self.assertTrue("## 结论" in md or "## 结论与建议" in md)
        self.assertIn("更新时间", md)
        self.assertGreaterEqual(len(payload["sections"]), 3)


class GeoVariantsTests(unittest.TestCase):
    def test_zhihu_shortens(self):
        from app.geo.content.variants import adapt_for_channel

        body = (
            "# 标题\n\n直接答案段落足够长。\n\n## 定义\n\n定义段\n\n"
            "## FAQ\n\n- **Q：** a\n  **A：** b\n- **Q：** c\n  **A：** d\n\n"
            "## 结论\n\n结论段\n\n*更新时间：2026-07-28*\n"
        )
        title, out = adapt_for_channel(
            "zhihu",
            "很长的标题" * 10,
            body,
            {"direct_answer": "直接答案段落足够长。", "updated_at": "2026-07-28"},
        )
        self.assertLessEqual(len(title), 40)
        self.assertIn("直接答案", out)


class GeoFixPatchesTests(unittest.TestCase):
    def test_patches_for_missing_faq_conclusion_updated_at(self):
        patches = {
            p["code"]: p
            for p in build_fix_patches(
                _base(
                    body_markdown="直接回答：只有一句。\n",
                    outline={"direct_answer": "只有一句。", "sections": []},
                )
            )
        }
        self.assertIn("faq_min", patches)
        self.assertIn("conclusion_extractable", patches)
        self.assertIn("updated_at_visible", patches)
        self.assertIn("numbers_extractable", patches)
        self.assertIn("comparison_extractable", patches)
        self.assertIn("howto_extractable", patches)
        self.assertIn("## FAQ", patches["faq_min"]["insert_markdown"])
        self.assertIn("## 结论", patches["conclusion_extractable"]["insert_markdown"])
        self.assertIn("更新时间", patches["updated_at_visible"]["insert_markdown"])
        self.assertIn("80%", patches["numbers_extractable"]["insert_markdown"])
        self.assertIn("120 家", patches["numbers_extractable"]["insert_markdown"])

    def test_numbers_patch_uses_bound_facts_not_demo_stats(self):
        from app.geo.content.rules import check_numbers_extractable

        data = _base(
            body_markdown="直接回答：化工离心泵怎么选才不容易腐蚀。\n",
            facts=[
                {
                    "id": 1,
                    "statement": "机械密封适用于 98% 浓硫酸工况",
                    "source_name": "产品手册",
                    "trust_level": "verified",
                    "status": "active",
                },
                {
                    "id": 2,
                    "statement": "标准交期约 14 天",
                    "source_name": "商务资料",
                    "trust_level": "verified",
                    "status": "active",
                },
                {
                    "id": 3,
                    "statement": "过流件设计寿命约 5 年",
                    "source_name": "产品手册",
                    "trust_level": "verified",
                    "status": "active",
                },
            ],
        )
        self.assertFalse(check_numbers_extractable(data).passed)
        patch = next(p for p in build_fix_patches(data) if p["code"] == "numbers_extractable")
        insert = patch["insert_markdown"]
        self.assertNotIn("120 家", insert)
        self.assertNotIn("80% 典型场景", insert)
        self.assertIn("98%", insert)
        if patch.get("cursor_hint") == "rewrite":
            new_body = insert
        else:
            new_body = data.body_markdown.rstrip() + insert
        fixed = _base(body_markdown=new_body, facts=data.facts)
        self.assertTrue(check_numbers_extractable(fixed).passed)

    def test_numbers_patch_strips_invented_demo_line(self):
        from app.geo.content.rules import check_numbers_extractable

        facts = [
            {
                "id": 1,
                "statement": "耐腐蚀离心泵用于化工介质输送",
                "source_name": "官网",
                "trust_level": "verified",
                "status": "active",
            },
            {
                "id": 2,
                "statement": "机械密封需按介质选型",
                "source_name": "手册",
                "trust_level": "verified",
                "status": "active",
            },
            {
                "id": 3,
                "statement": "低液位储罐需校核吸入管路",
                "source_name": "手册",
                "trust_level": "verified",
                "status": "active",
            },
        ]
        data = _base(
            body_markdown=(
                "直接回答：化工离心泵怎么选。\n\n"
                "关键指标：覆盖 80% 典型场景，实施约 14 天，已服务 120 家制造业客户。\n"
            ),
            facts=facts,
        )
        self.assertFalse(check_numbers_extractable(data).passed)
        patch = next(p for p in build_fix_patches(data) if p["code"] == "numbers_extractable")
        self.assertEqual(patch.get("cursor_hint"), "rewrite")
        new_body = patch["insert_markdown"]
        self.assertNotIn("80%", new_body)
        self.assertNotIn("120 家", new_body)
        fixed = _base(body_markdown=new_body, facts=facts)
        self.assertTrue(check_numbers_extractable(fixed).passed)

    def test_apply_faq_patch_flips_check_even_with_stale_outline_faq(self):
        """Stale outline.faq of length 1 must not block body markdown FAQ from counting."""
        from app.geo.content.rules import check_faq_min

        body = "直接回答：选型先看合规与集成。\n"
        data = _base(
            body_markdown=body,
            outline={"direct_answer": "选型先看合规与集成。", "faq": [{"q": "only one"}]},
        )
        self.assertFalse(check_faq_min(data, min_items=2).passed)
        patch = next(p for p in build_fix_patches(data) if p["code"] == "faq_min")
        new_body = body.rstrip() + patch["insert_markdown"]
        fixed = _base(
            body_markdown=new_body,
            outline={"direct_answer": "选型先看合规与集成。", "faq": [{"q": "only one"}]},
        )
        self.assertTrue(
            check_faq_min(fixed, min_items=2).passed,
            "body FAQ should count even when outline.faq is short",
        )

    def test_definition_patch_flips_definition_check(self):
        from app.geo.content.rules import check_definition

        data = _base(body_markdown="直接回答：只有一句足够长的回答。\n", outline={})
        self.assertFalse(check_definition(data).passed)
        patch = next(p for p in build_fix_patches(data) if p["code"] == "definition")
        fixed = _base(
            body_markdown=data.body_markdown + patch["insert_markdown"],
            outline={},
        )
        self.assertTrue(check_definition(fixed).passed)

    def test_no_structural_patches_when_complete(self):
        codes = {p["code"] for p in build_fix_patches(_base())}
        self.assertNotIn("faq_min", codes)
        self.assertNotIn("conclusion_extractable", codes)
        self.assertNotIn("updated_at_visible", codes)
        self.assertNotIn("numbers_extractable", codes)
        self.assertNotIn("comparison_extractable", codes)
        self.assertNotIn("howto_extractable", codes)

    def test_evidence_publishable_requires_verified_fresh_facts(self):
        from datetime import date, timedelta

        today = date.today()
        stale = [
            {"id": 1, "statement": "a", "source_name": "s", "trust_level": "needs_review", "status": "active"},
            {"id": 2, "statement": "b", "source_name": "s", "trust_level": "verified", "status": "active"},
            {
                "id": 3,
                "statement": "c",
                "source_name": "s",
                "trust_level": "verified",
                "status": "active",
                "expires_at": (today - timedelta(days=1)).isoformat(),
            },
        ]
        checks = {c.code: c for c in run_checks(_base(facts=stale))}
        self.assertFalse(checks["evidence_publishable"].passed)


if __name__ == "__main__":
    unittest.main()
