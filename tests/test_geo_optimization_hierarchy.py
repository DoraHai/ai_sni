"""GEO 三级结构：优化业务 / 单元 + 意图词 unit_id。"""

from __future__ import annotations

from datetime import date

from app.geo.content.schemas import (
    OptimizationBusinessCreate,
    OptimizationUnitCreate,
    PromptCreate,
    PromptUpdate,
)
from app.models.geo_optimization import GeoDailyMetric, GeoOptimizationBusiness, GeoOptimizationUnit
from app.models.geo_prompt import GeoPrompt


def test_schema_unit_id_on_prompt():
    p = PromptCreate(tenant_id=1, question="适合什么场景的智能客服")
    assert p.unit_id is None
    p2 = PromptCreate(tenant_id=1, question="适合什么场景的智能客服", unit_id=9)
    assert p2.unit_id == 9
    u = PromptUpdate(unit_id=3)
    assert u.unit_id == 3


def test_business_unit_schemas():
    b = OptimizationBusinessCreate(tenant_id=1, name="产品线A")
    assert b.name == "产品线A"
    un = OptimizationUnitCreate(tenant_id=1, business_id=1, name="价格", keyword="价格对比")
    assert un.keyword == "价格对比"


def test_model_table_names_and_prompt_unit_fk():
    assert GeoOptimizationBusiness.__tablename__ == "geo_optimization_businesses"
    assert GeoOptimizationUnit.__tablename__ == "geo_optimization_units"
    assert GeoDailyMetric.__tablename__ == "geo_daily_metrics"
    assert "unit_id" in GeoPrompt.__table__.c
    assert "scope_key" in GeoDailyMetric.__table__.c
    assert GeoDailyMetric.__table__.c.metric_date.type.__class__.__name__ in ("Date", "DATE")


def test_daily_metric_construct():
    m = GeoDailyMetric(
        tenant_id=1,
        metric_date=date(2026, 8, 7),
        scope_key="t",
        brand_mentions=2,
        citation_count=5,
        distinct_cited_domains=3,
    )
    assert m.scope_key == "t"
    assert m.citation_count == 5
    assert m.distinct_cited_domains == 3
