"""P10：仅生成明确标识的内部JSON样例；没有CSV/XLSX百度执行出口。"""
from __future__ import annotations

import json
from pathlib import Path

NOTICE = "内部演练/不可上传百度"
OFFICIAL_API_OVERVIEW = "https://bce-cdn.bj.bcebos.com/p3m/pdf/bce-doc/online/SEM/SEM.pdf?timeStamp=1629849600124"


def synthetic_sample() -> dict:
    # 官方历史API文档仅证明相应服务概念，不证明当下批量文件表头/可用性。
    rows = [
        {"internal_id": "demo-plan", "internal_kind": "campaign", "internal_parent": None,
         "internal_label": "合成产品线演练计划", "internal_daily_budget_cents": 12345,
         "evidence": "CampaignService.addCampaign（历史官方API，文件能力待核实）"},
        {"internal_id": "demo-unit", "internal_kind": "adgroup", "internal_parent": "demo-plan",
         "internal_label": "合成意图单元", "internal_landing_url": "https://example.invalid/demo",
         "evidence": "AdgroupService.addAdgroup（历史官方API，文件能力待核实）"},
        {"internal_id": "demo-word", "internal_kind": "keyword", "internal_parent": "demo-unit",
         "internal_text": "合成产品演练词", "evidence": "KeywordService.addWord（历史官方API，文件能力待核实）"},
        {"internal_id": "demo-creative", "internal_kind": "basic_creative", "internal_parent": "demo-unit",
         "internal_title": "合成演练文案", "internal_description": "仅用于契约自测，所有内容均为虚构。",
         "evidence": "CreativeService.addCreative（历史官方API，文件能力待核实）"},
    ]
    return {"notice": NOTICE, "schema": "sem-phase0-internal-v1", "synthetic": True,
            "execution_export_enabled": False, "official_headers": None,
            "source": OFFICIAL_API_OVERVIEW, "rows": rows,
            "pending_verification": ["批量文件新建计划/单元/关键词/基础创意", "高级创意各类型",
                                     "否词层级和匹配", "预算/地域/时段文件格式", "全部当前表头、枚举、限制、回执"]}


def write_internal_sample(path: Path) -> None:
    if Path(path).suffix.lower() != ".json":
        raise ValueError("内部样例只允许JSON，不提供百度上传格式")
    Path(path).write_text(json.dumps(synthetic_sample(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export_baidu_execution_file(*args, **kwargs):
    raise PermissionError("阶段0正式执行文件出口关闭；模板、客户批准及后续阶段均未放行")
