"""生产试探：苏尔寿有没有「基木鱼营销通」线索数据（LeadsNoticeService/getNoticeList）。

背景：文档 0819 证明线索明细能直接从营销 API 拿（含 keywordId/keyword 词级归因），纠正了
旧判断"爱番番线索明细拿不到"。但该接口拉的是基木鱼落地页/广告线索组件的线索——苏尔寿是
电话类（Detail2 电话点击），得实测电话/咨询/表单等组件到底有没有数据、能不能归因到词。

只读接口（getNoticeList，不触发写）。按 solutionType 分类型查（必填），窗口 ≤30 天。
在 ECS 上跑（读 .env）：

    cd /opt/sem-backend && sudo -u sem PYTHONPATH=/opt/sem-backend .venv/bin/python scripts/probe_leads.py
"""
import asyncio
from datetime import datetime, timedelta

from app.baidu.client import BaiduAPIClient, BaiduAPIError
from app.config import get_settings

# 组件类型枚举（文档 0819）。苏尔寿电话为主，全扫一遍看哪些有数据
SOLUTION_TYPES = [
    ("phone", "电话"),
    ("consult", "咨询"),
    ("form", "表单"),
    ("wechat", "微信"),
    ("callback", "回呼"),
    ("follow", "粉丝关注"),
]


def _mask(phone: str | None) -> str:
    if not phone or len(phone) < 7:
        return phone or "—"
    return phone[:3] + "****" + phone[-4:]


async def probe_type(client: BaiduAPIClient, sol: str, label: str, start: str, end: str) -> None:
    body = {"solutionType": sol, "startDate": start, "endDate": end, "pageNo": 1, "pageSize": 50}
    try:
        resp = await client.call("LeadsNoticeService", "getNoticeList", body)
    except BaiduAPIError as e:
        print(f"  ❌ {label}({sol}) 调用失败 code={e.code} msg={e.message}")
        return
    data = resp.get("data") or []
    block = data[0] if data else {}
    total = block.get("totalNum") or 0
    rows = block.get("noticeDetailList") or []
    if not total:
        print(f"  ⚪ {label}({sol}) 无数据")
        return
    # 归因覆盖率：多少条带 keyword
    with_kw = sum(1 for r in rows if r.get("keyword") or r.get("keywordId"))
    print(f"  ✅ {label}({sol}) 共 {total} 条；本页 {len(rows)} 条，其中 {with_kw} 条可归因到关键词")
    for r in rows[:3]:
        print(
            f"     · {r.get('commitTime','?')} | {_mask(r.get('cluePhoneNumber'))}"
            f" | 词={r.get('keyword') or '—'} | 计划={r.get('campaignName') or '—'}"
            f" | 接通={r.get('connect')} | 渠道={r.get('flowChannelName') or '—'}"
        )


async def main() -> None:
    s = get_settings()
    client = BaiduAPIClient(
        username=s.baidu_default_username,
        access_token=s.baidu_self_access_token,
    )
    end = datetime.now()
    start = end - timedelta(days=29)  # 窗口 ≤30 天
    start_s = start.strftime("%Y-%m-%d 00:00:00")
    end_s = end.strftime("%Y-%m-%d %H:%M:%S")
    print(f"窗口 {start_s} ~ {end_s}\n按组件类型扫基木鱼营销通线索：")

    for sol, label in SOLUTION_TYPES:
        await probe_type(client, sol, label, start_s, end_s)

    print("\n结论：有「✅」= 苏尔寿线索走基木鱼组件，可直接 API 自动同步线索明细（含词级归因）；")
    print("全「⚪ 无数据」= 苏尔寿没用基木鱼（自有网站/电话），线索只能手动录入，归因退守账户/计划级。")


if __name__ == "__main__":
    asyncio.run(main())
