"""诊断桥：事实卡与目标问题对齐。"""

import unittest
from types import SimpleNamespace

from app.geo.content.bridge import build_diagnosis_fact_payloads


def _run(**kwargs):
    base = dict(
        url="https://example.com/",
        page_title="Example Domain",
        findings=[
            {
                "code": "entity_schema",
                "title": "品牌实体 Schema 完整",
                "evidence": "识别类型：无",
                "recommendation": "用 Organization/Brand 描述品牌。",
            }
        ],
        advice=[
            {
                "code": "entity_schema",
                "title": "品牌实体 Schema 完整",
                "action": "补充 Organization JSON-LD，包含 name/url。",
                "acceptance": "重新诊断后该项通过。",
                "expected_impact": "提升实体可识别性。",
            }
        ],
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


class DiagnosisFactBridgeTests(unittest.TestCase):
    def test_builds_aligned_facts_for_advice(self):
        payloads = build_diagnosis_fact_payloads(
            _run(), advice_code="entity_schema"
        )
        self.assertGreaterEqual(len(payloads), 3)
        titles = " ".join(p["title"] for p in payloads)
        statements = " ".join(p["statement"] for p in payloads)
        self.assertIn("Schema", titles)
        self.assertIn("Organization", statements)
        self.assertTrue(all(p["source_name"].startswith("GEO 诊断") for p in payloads))
        self.assertTrue(all(p["meta"].get("from_diagnosis") for p in payloads))

    def test_pads_page_entity_when_advice_thin(self):
        payloads = build_diagnosis_fact_payloads(
            _run(findings=[], advice=[{"code": "x", "title": "补强", "action": "写清楚"}]),
            advice_code="x",
        )
        self.assertGreaterEqual(len(payloads), 2)
        self.assertTrue(any("页面实体" in p["title"] for p in payloads))


if __name__ == "__main__":
    unittest.main()
