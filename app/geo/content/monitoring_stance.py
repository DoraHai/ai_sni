"""引擎商业定位：模拟评估 / 混合 / 仅真采样。

产品默认 hybrid：允许 mock_persona，但报表必须标注样本构成；
real_only 时巡检/交付可提示缺真采样 Key。
"""

from __future__ import annotations

from typing import Any, Literal

Stance = Literal["simulation", "hybrid", "real_only"]

STANCES: dict[str, dict[str, Any]] = {
    "simulation": {
        "key": "simulation",
        "label": "AI 回答模拟评估",
        "summary": "用租户 LLM 扮演各引擎输出；适合方法论演练与内容质量自检，不宣称真实外站可见度。",
        "deliverable_ok": False,
        "badge": "模拟评估",
        "client_facing_warning": "本报告样本为人设模拟，不可作为真实引擎收录证明。",
    },
    "hybrid": {
        "key": "hybrid",
        "label": "混合模式（推荐）",
        "summary": "有 Key 的引擎真采样，无 Key 的引擎模拟；所有报表强制展示样本构成。",
        "deliverable_ok": True,
        "badge": "混合采样",
        "client_facing_warning": "交付时须披露模拟样本占比；仅真采样部分可作对外可见度依据。",
    },
    "real_only": {
        "key": "real_only",
        "label": "仅真采样",
        "summary": "仅统计 openai_compat 且已配置 Key 的样本；适合签约交付与对外证明。",
        "deliverable_ok": True,
        "badge": "真采样",
        "client_facing_warning": "模拟样本不计入交付指标。",
    },
}


def normalize_stance(raw: str | None) -> Stance:
    v = str(raw or "hybrid").strip().lower()
    if v in STANCES:
        return v  # type: ignore[return-value]
    return "hybrid"


def stance_payload(raw: str | None) -> dict[str, Any]:
    key = normalize_stance(raw)
    return dict(STANCES[key])


def compose_stance_banner(
    stance: str | None,
    *,
    simulated_share: float | None = None,
    real_ready_engines: int = 0,
    enabled_engines: int = 0,
) -> dict[str, Any]:
    info = stance_payload(stance)
    msgs = [info["client_facing_warning"]]
    if info["key"] == "simulation":
        msgs.append("当前定位为模拟评估，勿将数字直接写入客户合同附件。")
    elif info["key"] == "hybrid" and real_ready_engines == 0 and enabled_engines > 0:
        msgs.append("尚未配置任何真采样引擎 Key，实际运行将全部为模拟。")
    elif info["key"] == "real_only" and real_ready_engines == 0:
        msgs.append("定位为仅真采样，但无引擎就绪——巡检结果将为空或被过滤。")
    if simulated_share is not None and simulated_share > 0.5:
        msgs.append(f"近窗模拟样本约占 {simulated_share:.0%}，解读请谨慎。")
    return {
        **info,
        "messages": msgs,
        "real_ready_engines": real_ready_engines,
        "enabled_engines": enabled_engines,
        "simulated_share": simulated_share,
    }
