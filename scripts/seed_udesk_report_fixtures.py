"""Seed enough real-looking snapshots for Udesk (tenant 4) report pages.

Does not wipe existing rows. Idempotent via note=udesk_report_fixture.

Usage:
  python scripts/seed_udesk_report_fixtures.py
  python scripts/seed_udesk_report_fixtures.py --tenant-id 4
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.database import async_session_factory
from app.geo.content.daily_metrics import rebuild_range
from app.models import (
    GeoAnswerSnapshot,
    GeoOptimizationUnit,
    GeoPrompt,
    Tenant,
)

SH = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc
NOTE = "udesk_report_fixture"
BRAND = "Udesk"
SITE = "https://www.udesk.cn/"
COMPETITORS = ["智齿", "网易七鱼", "美洽"]
ENGINES = ["deepseek", "doubao", "kimi"]

CATEGORY_PROMPTS = [
    "在线客服系统免费大概是什么价位？值不值？",
    "在线客服系统怎么选才不容易踩坑",
    "智能客服机器人和人工客服怎么配合",
    "在线客服系统有哪些品牌值得对比",
]


def utc_naive(day: date, hour: int = 10) -> datetime:
    local = datetime.combine(day, time(hour, 0), tzinfo=SH)
    return local.astimezone(UTC).replace(tzinfo=None)


def today_sh() -> date:
    return datetime.now(SH).date()


async def main(tenant_id: int) -> None:
    async with async_session_factory() as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise SystemExit(f"tenant {tenant_id} 不存在")

        existing_n = int(
            await session.scalar(
                select(func.count())
                .select_from(GeoAnswerSnapshot)
                .where(
                    GeoAnswerSnapshot.tenant_id == tenant_id,
                    GeoAnswerSnapshot.note == NOTE,
                )
            )
            or 0
        )
        if existing_n >= 24:
            print(f"already seeded {existing_n} fixture snapshots, skip insert")
        else:
            unit = await session.scalar(
                select(GeoOptimizationUnit)
                .where(GeoOptimizationUnit.tenant_id == tenant_id)
                .order_by(GeoOptimizationUnit.id.asc())
            )
            have = {
                p.question: p
                for p in await session.scalars(
                    select(GeoPrompt).where(
                        GeoPrompt.tenant_id == tenant_id,
                        GeoPrompt.status == "active",
                    )
                )
            }
            prompts: list[GeoPrompt] = []
            for q in CATEGORY_PROMPTS:
                row = have.get(q)
                if row is None:
                    row = GeoPrompt(
                        tenant_id=tenant_id,
                        unit_id=unit.id if unit else None,
                        question=q,
                        status="active",
                        source="report_fixture",
                        is_brand_probe=False,
                        tags=["report_fixture", "category"],
                        priority=12,
                    )
                    session.add(row)
                    await session.flush()
                prompts.append(row)

            today = today_sh()
            days = [today - timedelta(days=d) for d in (1, 3, 6, 9, 12)]
            texts_hit = (
                f"{BRAND} 适合中小团队先从免费版试用，官网 {SITE} 有产品说明。"
                "常见对比对象包括智齿、网易七鱼。"
            )
            texts_miss = (
                "免费在线客服可以先看网易七鱼、美洽和智齿，按渠道和工单能力选型。"
                "部分厂商提供试用。"
            )
            added = 0
            for i, prompt in enumerate(prompts):
                for j, engine in enumerate(ENGINES):
                    for k, day in enumerate(days):
                        mentions = (i + j + k) % 3 != 0
                        cite = mentions and k % 2 == 0
                        comps = COMPETITORS if (i + k) % 2 == 0 else COMPETITORS[:2]
                        urls = [SITE, "https://zhuanlan.zhihu.com/p/158746488"] if cite else (
                            ["https://qiyukf.com/"] if not mentions else []
                        )
                        session.add(
                            GeoAnswerSnapshot(
                                tenant_id=tenant_id,
                                prompt_id=prompt.id,
                                engine=engine,
                                raw_text=texts_hit if mentions else texts_miss,
                                captured_at=utc_naive(day, 9 + j),
                                mentions_brand=mentions,
                                cited_urls=urls or None,
                                competitors=comps,
                                brand_position="first" if mentions and k == 0 else (
                                    "mentioned" if mentions else "absent"
                                ),
                                sentiment="positive" if mentions else "neutral",
                                citation_format="linked" if cite else (
                                    "plaintext" if mentions else "none"
                                ),
                                citation_accuracy="accurate" if cite else "unknown",
                                sample_mode="openai_compat",
                                simulated=False,
                                note=NOTE,
                            )
                        )
                        added += 1
            await session.commit()
            print(f"inserted {added} snapshots for tenant {tenant_id} ({tenant.name})")

        end = today_sh()
        start = end - timedelta(days=13)
        stats = await rebuild_range(session, tenant_id, start, end)
        print("daily metrics rebuilt", stats.get("day_count"), "days")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=int, default=4)
    args = parser.parse_args()
    asyncio.run(main(args.tenant_id))
