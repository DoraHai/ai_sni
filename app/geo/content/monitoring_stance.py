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


# Human-readable reasons for UI skip preview (aligned with probe.resolve_engine_llm)
_SKIP_REASON_LABELS: dict[str, str] = {
    "skipped:real_only_no_engine_key": "仅真采样：引擎未配置 Key",
    "skipped:real_only_missing_base_or_model": "仅真采样：缺 Base URL 或 Model",
    "skipped:real_only_persona_engine_disabled": "仅真采样：人设模拟引擎不参与",
    "simulation 定位：强制人设模拟": "模拟评估：强制人设路径",
    "simulation 定位：无租户 LLM": "模拟评估：无租户 LLM",
}


def preview_engine_skip(
    *,
    monitoring_stance: str | None,
    sample_mode: str | None,
    api_key_configured: bool,
    has_base_url: bool,
    has_model: bool,
    enabled: bool = True,
) -> dict[str, Any]:
    """Dry-run resolve: would this engine be skipped under current stance?

    Mirrors resolve_engine_llm skip branches without decrypting keys.
    """
    stance = normalize_stance(monitoring_stance)
    mode = (sample_mode or "mock_persona").strip() or "mock_persona"
    if not enabled:
        return {
            "will_run": False,
            "will_skip": True,
            "reason": "engine_disabled",
            "reason_label": "已停用",
            "sample_mode_effective": None,
        }
    if stance == "simulation":
        return {
            "will_run": True,
            "will_skip": False,
            "reason": None,
            "reason_label": "模拟评估：走租户 LLM 人设",
            "sample_mode_effective": "mock_persona",
        }
    if stance == "real_only":
        if mode != "openai_compat":
            return {
                "will_run": False,
                "will_skip": True,
                "reason": "skipped:real_only_persona_engine_disabled",
                "reason_label": _SKIP_REASON_LABELS[
                    "skipped:real_only_persona_engine_disabled"
                ],
                "sample_mode_effective": None,
            }
        if not api_key_configured:
            return {
                "will_run": False,
                "will_skip": True,
                "reason": "skipped:real_only_no_engine_key",
                "reason_label": _SKIP_REASON_LABELS[
                    "skipped:real_only_no_engine_key"
                ],
                "sample_mode_effective": None,
            }
        if not has_base_url or not has_model:
            return {
                "will_run": False,
                "will_skip": True,
                "reason": "skipped:real_only_missing_base_or_model",
                "reason_label": _SKIP_REASON_LABELS[
                    "skipped:real_only_missing_base_or_model"
                ],
                "sample_mode_effective": None,
            }
        return {
            "will_run": True,
            "will_skip": False,
            "reason": None,
            "reason_label": "真采样就绪",
            "sample_mode_effective": "openai_compat",
        }
    # hybrid
    if mode == "openai_compat" and api_key_configured and has_base_url and has_model:
        return {
            "will_run": True,
            "will_skip": False,
            "reason": None,
            "reason_label": "真采样",
            "sample_mode_effective": "openai_compat",
        }
    return {
        "will_run": True,
        "will_skip": False,
        "reason": None,
        "reason_label": "混合：无真 Key 时人设模拟",
        "sample_mode_effective": "mock_persona",
    }


def build_skip_preview(
    engines: list[Any],
    *,
    monitoring_stance: str | None,
) -> dict[str, Any]:
    """Per-engine skip preview for engines config UI."""
    items: list[dict[str, Any]] = []
    for e in engines:
        mode = getattr(e, "sample_mode", None) or "mock_persona"
        key_ok = bool(getattr(e, "api_key_encrypted", None))
        base_ok = bool(str(getattr(e, "api_base_url", None) or "").strip())
        model_ok = bool(str(getattr(e, "model", None) or "").strip())
        enabled = bool(getattr(e, "enabled", True))
        pred = preview_engine_skip(
            monitoring_stance=monitoring_stance,
            sample_mode=mode,
            api_key_configured=key_ok,
            has_base_url=base_ok,
            has_model=model_ok,
            enabled=enabled,
        )
        items.append(
            {
                "engine_key": getattr(e, "engine_key", None),
                "display_name": getattr(e, "display_name", None),
                "enabled": enabled,
                "sample_mode": mode,
                "api_key_configured": key_ok,
                **pred,
            }
        )
    skip_n = sum(1 for it in items if it.get("will_skip") and it.get("enabled"))
    run_n = sum(1 for it in items if it.get("will_run") and it.get("enabled"))
    return {
        "monitoring_stance": normalize_stance(monitoring_stance),
        "items": items,
        "enabled_will_run": run_n,
        "enabled_will_skip": skip_n,
        "summary": (
            f"当前定位下：{run_n} 个启用引擎将执行，{skip_n} 个将被跳过"
            if any(it.get("enabled") for it in items)
            else "无启用引擎"
        ),
    }
