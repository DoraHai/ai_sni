"""Seed GEO content demo data for a tenant.

Usage:
  python -m scripts.seed_geo_demo --tenant-id 1
  python -m scripts.seed_geo_demo --tenant-id 1 --verify-facts

Requires DATABASE_URL / .env and an existing tenant row.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import func, select

from app.database import async_session_factory
from app.models import GeoFact, GeoPrompt, Tenant

PROMPTS = [
    ("数据分析平台哪个好用", 20, ["high_demand", "brand_missing"]),
    ("如何选择企业级 BI 工具", 18, ["high_demand"]),
    ("私有化部署的数据分析软件有哪些", 15, ["high_demand", "competitor_present"]),
    ("制造业数据分析平台推荐", 12, ["brand_missing"]),
    ("数据分析平台是否支持开放 API", 10, ["high_demand"]),
    ("企业数据中台和 BI 有什么区别", 9, ["high_demand"]),
    ("国产数据分析平台怎么选型", 8, ["competitor_present"]),
    ("中小企业适合什么数据分析工具", 8, ["high_demand"]),
    ("数据分析平台的数据安全如何保障", 7, ["high_demand"]),
    ("报表工具和自助分析平台怎么选", 6, ["brand_missing"]),
]

FACTS = [
    ("私有化部署", "产品支持私有化部署，数据可留存于客户内网环境。", "product", "产品白皮书 2026"),
    ("开放 API", "提供开放 API 与常见数据源连接器，便于与现有系统集成。", "product", "开发者文档"),
    ("制造行业案例", "已在制造业客户中落地生产质检与供应链分析场景。", "case", "公开客户案例页"),
    ("权限体系", "支持基于角色的数据权限与操作审计，满足内控要求。", "policy", "安全说明文档"),
    ("更新节奏", "产品版本按季度发布，关键缺陷修复按优先级热修。", "metric", "发布说明 2026Q2"),
    ("实施周期", "标准实施周期通常为 4–8 周，视数据源复杂度调整。", "product", "实施服务手册"),
    ("可视化能力", "内置报表、仪表盘与自助探索分析能力。", "product", "产品功能清单"),
    ("国产适配", "可部署于常见国产服务器与数据库环境（以官方兼容列表为准）。", "product", "兼容性清单"),
]


async def seed(tenant_id: int, *, verify_facts: bool = False) -> None:
    async with async_session_factory() as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise SystemExit(f"tenant {tenant_id} 不存在")

        existing_prompts = await session.scalar(
            select(GeoPrompt.id).where(GeoPrompt.tenant_id == tenant_id).limit(1)
        )
        if existing_prompts is None:
            for question, priority, tags in PROMPTS:
                session.add(
                    GeoPrompt(
                        tenant_id=tenant_id,
                        question=question,
                        priority=priority,
                        tags=tags,
                        source="demo",
                        demand_note="demo seed",
                    )
                )

        existing_facts = await session.scalar(
            select(GeoFact.id).where(GeoFact.tenant_id == tenant_id).limit(1)
        )
        if existing_facts is None:
            for title, statement, fact_type, source_name in FACTS:
                session.add(
                    GeoFact(
                        tenant_id=tenant_id,
                        title=title,
                        statement=statement,
                        fact_type=fact_type,
                        source_name=source_name,
                        trust_level="needs_review",
                        status="active",
                    )
                )

        await session.flush()

        if verify_facts:
            # Ensure ≥3 verified active facts for generate gate demos
            rows = list(
                await session.scalars(
                    select(GeoFact)
                    .where(GeoFact.tenant_id == tenant_id, GeoFact.status == "active")
                    .order_by(GeoFact.id.asc())
                )
            )
            verified_n = sum(1 for f in rows if f.trust_level == "verified")
            for f in rows:
                if verified_n >= 3:
                    break
                if f.trust_level != "verified":
                    f.trust_level = "verified"
                    verified_n += 1
            print(f"  verified facts now ≥ {min(verified_n, 3)} (target 3)")

        await session.commit()
        n_facts = await session.scalar(
            select(func.count()).select_from(GeoFact).where(GeoFact.tenant_id == tenant_id)
        )
        n_prompts = await session.scalar(
            select(func.count()).select_from(GeoPrompt).where(GeoPrompt.tenant_id == tenant_id)
        )
        print(
            f"GEO demo seed done for tenant_id={tenant_id} ({tenant.name}) "
            f"prompts={n_prompts} facts={n_facts}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument(
        "--verify-facts",
        action="store_true",
        help="Mark at least 3 active facts as verified (for generate demos)",
    )
    args = parser.parse_args()
    asyncio.run(seed(args.tenant_id, verify_facts=bool(args.verify_facts)))


if __name__ == "__main__":
    main()
