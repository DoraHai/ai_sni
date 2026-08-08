"""交付摘要 Markdown / pack 切片字段。"""

from __future__ import annotations

from app.geo.content.deliverables import build_deliverables_pack, render_deliverables_markdown


def test_pack_v2_scope_and_daily():
    pack = build_deliverables_pack(
        tenant_id=1,
        tenant_name="演示客户",
        period={"from": "2026-08-01", "to": "2026-08-07", "days": 7},
        summary={
            "prompts": 3,
            "tasks": 1,
            "published": 0,
            "visibility_mention_rate": 0.5,
            "probe_recognition_rate": 1.0,
            "distinct_cited_domains": 2,
            "citation_count": 5,
        },
        citations_top=[{"domain": "a.com", "cite_count": 3, "engines": ["deepseek"]}],
        tasks=[{"id": 1, "status": "draft", "title": "t1"}],
        snapshots_sample=[],
        scope={
            "level": "business",
            "business_id": 9,
            "unit_id": None,
            "business_name": "产品线A",
            "unit_name": None,
            "label": "优化业务 · 产品线A",
        },
        daily_series=[
            {
                "metric_date": "2026-08-01",
                "brand_mention_rate": 0.4,
                "brand_probe_recognition_rate": None,
                "citation_count": 1,
                "distinct_cited_domains": 1,
            }
        ],
        business_slices=[],
        unit_slices=[
            {
                "unit_id": 2,
                "unit_name": "价格",
                "business_name": "产品线A",
                "brand_mention_rate": 0.6,
                "citation_count": 2,
                "snapshots_visibility": 3,
                "snapshots_probe": 0,
            }
        ],
    )
    assert pack["generated_kind"] == "geo_deliverables_pack_v2"
    assert pack["scope"]["label"] == "优化业务 · 产品线A"
    md = render_deliverables_markdown(pack)
    assert "切片范围：优化业务 · 产品线A" in md
    assert "按天汇总" in md
    assert "优化单元切片" in md
    assert "产品线A / 价格" in md
    assert "AI 引用次数（URL 出现总次）" in md


def test_pack_default_tenant_scope():
    pack = build_deliverables_pack(
        tenant_id=1,
        tenant_name="x",
        period={},
        summary={},
        citations_top=[],
        tasks=[],
        snapshots_sample=[],
    )
    assert pack["scope"]["level"] == "tenant"
    assert pack["daily_series"] == []
