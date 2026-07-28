"""生产试探：波动归因接口（文档 1033）对苏尔寿账户到底返回什么。

背景：接入「波动归因进每日洞察」前必须确认——该接口对普通 CPC 计划（非 OCPC
目标转化成本模式）是否给数据、factors 里的 description/topKeywords 长什么样、
哪些 dimension/compareType 组合有料。文档没写空数据行为，只能实拉。

queryFluctuationReasons 是读接口（不触发写），真写模式下安全。在 ECS 上跑：

    cd /opt/sem-backend && sudo -u sem .venv/bin/python scripts/probe_fluctuation.py
"""
import asyncio
import json
from datetime import date, timedelta

from app.baidu.client import BaiduAPIClient, BaiduAPIError
from app.baidu.services.campaign import CampaignService
from app.baidu.services.diagnosis import (
    COMPARE_LABELS,
    DIMENSION_LABELS,
    ID_TYPE_CAMPAIGN,
    ID_TYPE_OCPC,
    FluctuationService,
)
from app.config import get_settings


async def probe(svc, entity_id, label, id_type, diag_date, dim, cmp_type, time_range=1):
    try:
        factors = await svc.query_fluctuation_reasons(
            entity_id, diag_date, dim,
            id_type=id_type, compare_type=cmp_type, time_range=time_range,
        )
    except BaiduAPIError as e:
        print(f"  ❌ {label} {DIMENSION_LABELS[dim]}/{COMPARE_LABELS[cmp_type]}: code={e.code} {e.message}")
        return 0
    if factors:
        print(f"  ✅ {label} {DIMENSION_LABELS[dim]}/{COMPARE_LABELS[cmp_type]}: {len(factors)} 条")
        for f in factors:
            print("     " + json.dumps(f, ensure_ascii=False)[:300])
    return len(factors)


async def main() -> None:
    s = get_settings()
    client = BaiduAPIClient(
        username=s.baidu_default_username,
        access_token=s.baidu_self_access_token,
    )
    svc = FluctuationService(client)

    campaigns = await CampaignService(client).get_all_campaigns()
    print(f"账户计划 {len(campaigns)} 个\n")

    yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    total = 0

    print(f"=== 计划层级 idType=3，diagnosisDate={yesterday}，timeRange=1 ===")
    for c in campaigns:
        cid = c.get("campaignId")
        label = f"[{c.get('campaignName')}]"
        for dim in DIMENSION_LABELS:
            for cmp_type in (1, 2, 3):
                total += await probe(svc, cid, label, ID_TYPE_CAMPAIGN, yesterday, dim, cmp_type)

    print("\n=== OCPC 出价策略层级 idType=48（PS/EO 两个投放包），timeRange=7 ===")
    # getTargetPackageList level=1 需 userId（≠ ucid），同 sync_ocpc 先取
    from app.baidu.services.account import AccountService
    from app.baidu.services.ocpc import OcpcService

    packages = []
    try:
        info = (await AccountService(client).get_account_info(["userId"])).get("data") or {}
        if isinstance(info, list):
            info = info[0] if info else {}
        user_id = info.get("userId")
        if user_id:
            packages = await OcpcService(client).get_target_packages(int(user_id))
    except Exception as e:  # noqa: BLE001
        print(f"  拉投放包失败：{e}")
    for p in packages:
        pid = p.get("targetPackageId")
        label = f"[包 {p.get('targetPackageName') or pid}]"
        if pid is None:
            continue
        for dim in DIMENSION_LABELS:
            for cmp_type in (1, 2, 3):
                total += await probe(svc, pid, label, ID_TYPE_OCPC, yesterday, dim, cmp_type, time_range=7)

    print(f"\n汇总：共拿到 {total} 条归因。全 0 = 接口对本账户形态无料，接入洞察会静默无归因（不报错）。")


if __name__ == "__main__":
    asyncio.run(main())
