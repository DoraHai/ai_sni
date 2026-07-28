"""生产试探：苏尔寿账户的百度报告里转化字段到底有没有数据。

背景：决定要不要接「转化层」（L1 小白模式前提）。当前关键词/搜索词报告 columns
都没收转化列，落库数据查不到，必须实打实调一次 getReportData 带转化列才知道。

做法（同 probe_price_ratio 思路）：逐个候选转化列单独追加到最小列集试拉，
一坏列名会让整请求失败，所以一列一试；被接受的列再跨行求和，看是否非零。

getReportData 是读接口（不触发写），真写模式下安全。在 ECS 上跑（读 .env）：

    cd /opt/sem-backend && sudo -u sem .venv/bin/python scripts/probe_conversion.py
"""
import asyncio
from datetime import date, timedelta

from app.baidu.client import BaiduAPIClient, BaiduAPIError
from app.baidu.services.report import ReportService
from app.config import get_settings

# 关键词报告转化列：全谱扫 ocpcConversionsDetail1~30，定位苏尔寿配了哪几种转化类型
KEYWORD_CONV_CANDIDATES = [f"ocpcConversionsDetail{n}" for n in range(1, 31)]

# 最小有效列集（确认能拉到行）
BASE = ["date", "wInfoId", "wInfoNameStatus", "cost", "click"]


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


async def probe_column(svc: ReportService, start: str, end: str, col: str) -> str:
    """返回 'data' / 'zero' / 'rejected'，有数据时打印明细。"""
    try:
        rows = await svc.get_keyword_report(
            start, end, columns=BASE + [col], time_unit="SUMMARY",
        )
    except BaiduAPIError:
        return "rejected"
    total = sum(_num(r.get(col)) for r in rows)
    nonzero = sum(1 for r in rows if _num(r.get(col)) > 0)
    if total > 0:
        print(f"  ✅ {col:<26} 非零词={nonzero:<4} 合计={total:g}")
        return "data"
    return "zero"


async def main() -> None:
    s = get_settings()
    client = BaiduAPIClient(
        username=s.baidu_default_username,
        access_token=s.baidu_self_access_token,
    )
    svc = ReportService(client)

    end = date.today() - timedelta(days=1)        # 昨天（今天数据未结算）
    start = end - timedelta(days=29)              # 近 30 天
    start_s, end_s = start.isoformat(), end.isoformat()
    print(f"窗口 {start_s} ~ {end_s}（关键词报告 SUMMARY）\n")

    # 先确认基础列能拉到行（账户有没有在投）
    try:
        base_rows = await svc.get_keyword_report(start_s, end_s, columns=BASE, time_unit="SUMMARY")
        cost = sum(_num(r.get("cost")) for r in base_rows)
        print(f"基础校验：{len(base_rows)} 行，总消费 {cost:g}（cost 单位见账户，通常分）\n")
    except BaiduAPIError as e:
        print(f"基础列就失败了：code={e.code} msg={e.message}")
        return

    print("全谱扫 ocpcConversionsDetail1~30（只列有数据的）：")
    stat = {"data": [], "zero": [], "rejected": []}
    for col in KEYWORD_CONV_CANDIDATES:
        r = await probe_column(svc, start_s, end_s, col)
        stat[r].append(col)
    if not stat["data"]:
        print("  （没有任何 DetailN 有非零数据）")
    print(f"\n汇总：有数据 {len(stat['data'])} 种 | 全 0 {len(stat['zero'])} 种 | 列不存在 {len(stat['rejected'])} 种")
    print(f"有数据的类型代号：{[c.replace('ocpcConversionsDetail','') for c in stat['data']] or '无'}")
    print("（DetailN 的 N=百度转化目标类型代号，需对照账户转化追踪配置翻译成 到站/咨询/表单/电话…）")


if __name__ == "__main__":
    asyncio.run(main())
