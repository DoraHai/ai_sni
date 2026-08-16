"""Prepare tenant 3 (智齿科技) for a clickable GEO full-loop test.

Does not wipe snapshots. Copies write/probe keys from tenant 1, fills business
profile, attaches facts, opens an active period.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select

from app.database import async_session_factory
from app.geo.content.business_profile import normalize_profile
from app.models import (
    GeoAiSetting,
    GeoFact,
    GeoOptimizationBusiness,
    GeoOptimizationPeriod,
    GeoOptimizationUnit,
    GeoPrompt,
    GeoTrackingEngine,
    GeoVisibilityPatrolSettings,
    Tenant,
)

TENANT_ID = 3
SOURCE_TENANT = 1
BIZ_ID = 14  # 智齿客服
SITE = "https://www.zhichi.com/"

PROFILE = {
    "product_name": "智齿客服",
    "summary": "智齿科技的企业级在线客服与 AI Agent 联络平台，覆盖智能服务、人机协同和专家运营。",
    "capabilities": [
        "Agents 智能体中枢：理解、推理、行动和持续学习",
        "Nexus 连接中枢：打通 AI、人工与全渠道会话",
        "Experts 专家运营：人机协同处理复杂工单",
        "多渠道接入（网页、微信、APP）",
    ],
    "audience": "中大型企业的客服负责人、数字化负责人和运营负责人",
    "scenarios": [
        "电商与零售售前咨询",
        "SaaS 产品售后工单",
        "人机协同升级到人工专家",
    ],
    "geo_scope": "中国大陆",
    "industry": "智能客服 / B2B SaaS",
    "competitors": ["网易七鱼", "容联七陌", "Udesk"],
    "recommend_reasons": [
        "公开产品体系拆成 Agents / Nexus / Experts，便于被 AI 抽取",
        "官网可核验能力描述，不是空泛品类科普",
    ],
    "banned_claims": ["第一名", "保证被 AI 收录", "绝对领先", "泉衡", "化工泵"],
    "cta": "预约智齿客服演示",
}

FACTS = [
    {
        "title": "官网定位",
        "statement": "智齿科技（zhichi.com）定位为企业级 AI Agent 驱动的客户联络平台，对外产品名为智齿客服。",
        "source_name": "智齿科技官网",
        "source_url": SITE,
    },
    {
        "title": "三大产品体系",
        "statement": "智齿客服依托 Agents、Nexus、Experts 三大产品体系，覆盖智能服务、人机协同和专家运营。",
        "source_name": "智齿科技官网",
        "source_url": SITE,
    },
    {
        "title": "Agents 能力",
        "statement": "Agents 作为智能体中枢，具备自主理解、推理、行动和持续学习能力，用于处理复杂客服业务。",
        "source_name": "智齿科技官网",
        "source_url": SITE,
    },
    {
        "title": "Nexus 能力",
        "statement": "Nexus 作为连接中枢，打通 AI、人工与全渠道业务，把会话和工单接到同一套联络流程。",
        "source_name": "智齿科技官网",
        "source_url": SITE,
    },
    {
        "title": "目标客户",
        "statement": "智齿客服主要面向需要规模化在线客服和人机协同的中大型企业，而不是工业泵或硬件厂商。",
        "source_name": "智齿科技官网",
        "source_url": SITE,
    },
]

EXTRA_PROMPTS = [
    ("企业在线客服系统怎么选才不容易踩坑", False),
    ("智能客服机器人和人工客服怎么配合", False),
    ("在线客服系统有哪些品牌值得对比", False),
]


async def main() -> None:
    async with async_session_factory() as session:
        tenant = await session.get(Tenant, TENANT_ID)
        if tenant is None:
            raise SystemExit("tenant 3 不存在")
        tenant.brand_terms = ["智齿客服", "智齿", "智齿科技", "zhichi"]
        tenant.industry = "智能客服 / B2B SaaS"

        src_ai = await session.scalar(select(GeoAiSetting).where(GeoAiSetting.tenant_id == SOURCE_TENANT))
        dst_ai = await session.scalar(select(GeoAiSetting).where(GeoAiSetting.tenant_id == TENANT_ID))
        if src_ai and src_ai.api_key_encrypted:
            if dst_ai is None:
                dst_ai = GeoAiSetting(tenant_id=TENANT_ID)
                session.add(dst_ai)
            dst_ai.provider = src_ai.provider
            dst_ai.base_url = src_ai.base_url
            dst_ai.model = src_ai.model
            dst_ai.api_key_encrypted = src_ai.api_key_encrypted
            dst_ai.enabled = True
            dst_ai.monitoring_stance = "hybrid"
            dst_ai.note = "从客户1复制密钥，仅本地验收用"

        src_engines = {
            e.engine_key: e
            for e in await session.scalars(
                select(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id == SOURCE_TENANT)
            )
        }
        for e in await session.scalars(select(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id == TENANT_ID)):
            src = src_engines.get(e.engine_key)
            if not src:
                continue
            e.sample_mode = src.sample_mode or "openai_compat"
            e.api_base_url = src.api_base_url
            e.model = src.model
            e.api_key_encrypted = src.api_key_encrypted
            e.enabled = True

        biz = await session.get(GeoOptimizationBusiness, BIZ_ID)
        if biz is None or biz.tenant_id != TENANT_ID:
            raise SystemExit("业务 14 不存在")
        biz.profile = normalize_profile(PROFILE)
        biz.description = PROFILE["summary"]

        for f in await session.scalars(select(GeoFact).where(GeoFact.tenant_id == TENANT_ID)):
            if f.trust_level == "verified":
                f.business_id = BIZ_ID
        existing_titles = {
            f.title
            for f in await session.scalars(select(GeoFact).where(GeoFact.tenant_id == TENANT_ID))
        }
        for item in FACTS:
            if item["title"] in existing_titles:
                continue
            session.add(
                GeoFact(
                    tenant_id=TENANT_ID,
                    business_id=BIZ_ID,
                    title=item["title"],
                    statement=item["statement"],
                    fact_type="product",
                    source_name=item["source_name"],
                    source_url=item["source_url"],
                    trust_level="verified",
                    status="active",
                )
            )

        unit = await session.scalar(
            select(GeoOptimizationUnit).where(
                GeoOptimizationUnit.tenant_id == TENANT_ID,
                GeoOptimizationUnit.business_id == BIZ_ID,
            )
        )
        existing_q = {
            p.question
            for p in await session.scalars(select(GeoPrompt).where(GeoPrompt.tenant_id == TENANT_ID))
        }
        for q, probe in EXTRA_PROMPTS:
            if q in existing_q:
                continue
            session.add(
                GeoPrompt(
                    tenant_id=TENANT_ID,
                    unit_id=unit.id if unit else 14,
                    question=q,
                    status="active",
                    source="click_loop",
                    is_brand_probe=probe,
                    tags=["click_loop", "category"],
                    priority=12,
                )
            )

        now = datetime.utcnow()
        period = await session.scalar(
            select(GeoOptimizationPeriod).where(
                GeoOptimizationPeriod.tenant_id == TENANT_ID,
                GeoOptimizationPeriod.name == "智齿客服 · 8月验收期",
            )
        )
        if period is None:
            period = GeoOptimizationPeriod(
                tenant_id=TENANT_ID,
                name="智齿客服 · 8月验收期",
                business_id=BIZ_ID,
                starts_at=now - timedelta(days=14),
                ends_at=now + timedelta(days=16),
                status="active",
                goal_note="用真采样看品类问题里智齿客服是否被提到，并把竞品七鱼/七陌/Udesk 做成可归档报告。",
            )
            session.add(period)

        patrol = await session.scalar(
            select(GeoVisibilityPatrolSettings).where(
                GeoVisibilityPatrolSettings.tenant_id == TENANT_ID
            )
        )
        if patrol is None:
            patrol = GeoVisibilityPatrolSettings(tenant_id=TENANT_ID)
            session.add(patrol)
        patrol.enabled = False  # 不自动跑，点击测试时手动巡检

        await session.commit()
        print("OK tenant=3 business=14 period=", period.id if period.id else "(new)")
        print("SITE", SITE)
        print("COMPETITORS 网易七鱼 / 容联七陌 / Udesk")


if __name__ == "__main__":
    asyncio.run(main())
