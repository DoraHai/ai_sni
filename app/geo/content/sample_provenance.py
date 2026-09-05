"""Read existing snapshot provenance without a schema change or rewriting history."""

import re
from typing import Any


def sample_provenance(snapshot: Any) -> dict[str, str]:
    note = str(getattr(snapshot, "note", None) or "")
    mode = str(getattr(snapshot, "sample_mode", None) or "unknown").strip()
    # Old manual saves sometimes lost the mode but retained a simulation note.
    if getattr(snapshot, "simulated", False) or mode == "mock_persona" or "模拟" in note:
        kind = "simulated"
    elif mode == "openai_compat":
        kind = "real"
    elif mode == "manual":
        kind = "manual"
    elif "真采样" in note or "openai_compat" in note:
        kind = "real"
    else:
        kind = "unknown"

    def marker(name: str, fallback: str) -> str:
        values = re.findall(r"(?:^|[·\s])" + name + r"=([a-zA-Z0-9_]+)(?=$|[·\s])", note)
        if len(set(values)) > 1:
            return "conflicting"
        return values[0] if values else fallback

    method = marker("method", "legacy" if kind in {"real", "simulated"} else "unknown")
    analysis = marker("analysis", "unknown")
    if analysis == "conflicting":
        analysis = "needs_review"
    if analysis not in {"completed", "needs_review"}:
        analysis = "unknown"
    return {
        "sample_kind": kind,
        "source_label": {"real": "API 采样", "simulated": "模拟", "manual": "人工登记", "unknown": "来源未知"}[kind],
        "sampling_method": method,
        "analysis_status": analysis,
    }


def eligible_visibility_sample(snapshot):
    """Evidence population for comparable visibility numbers (prompt filtering is also required)."""
    from types import SimpleNamespace
    if isinstance(snapshot, dict):
        snapshot = SimpleNamespace(**snapshot)
    source = sample_provenance(snapshot)
    return (source['sample_kind'] == 'real' and source['sampling_method'] == 'unprimed_json_v2'
            and source['analysis_status'] == 'completed'
            and getattr(snapshot, 'citation_accuracy', None) != 'inaccurate'
            and not getattr(snapshot, 'is_brand_probe', False))
