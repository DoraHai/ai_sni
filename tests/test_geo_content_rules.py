"""GEO 内容规则引擎单测。"""

import unittest

from app.geo.content.rules import RuleInput, is_ready, run_checks


def _base(**kwargs) -> RuleInput:
    data = dict(
        question="数据分析平台哪个好用",
        title="数据分析平台怎么选",
        body_markdown=(
            "直接回答：应结合场景与可核验事实选择。\n\n"
            "## 定义\n\n数据分析平台用于汇聚与分析业务数据。\n\n"
            "## FAQ\n\n"
            "- **Q：** 需要关注什么？\n"
            "  **A：** 来源与时效。\n"
            "- **Q：** 如何验证？\n"
            "  **A：** 核对应事实卡。\n\n"
            "## 结论\n\n优先核验来源后再决策。\n\n"
            "*更新时间：2026-07-28*\n"
        ),
        outline={
            "direct_answer": "应结合场景与可核验事实选择数据分析平台。",
            "sections": [
                {"type": "definition", "heading": "定义", "body": "用于汇聚与分析业务数据。"},
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
            {"id": 1, "statement": "支持私有化部署", "source_name": "白皮书"},
            {"id": 2, "statement": "提供开放 API", "source_name": "文档"},
            {"id": 3, "statement": "已服务制造行业", "source_name": "案例"},
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
        self.assertIn("## FAQ", md)
        self.assertIn("## 结论", md)
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
