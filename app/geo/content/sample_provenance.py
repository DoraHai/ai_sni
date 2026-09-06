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


def sample_exclusion_reasons(snapshot):
    """Shared row-level reasons; weekly coverage is deliberately separate."""
    from types import SimpleNamespace
    if isinstance(snapshot, dict):
        snapshot = SimpleNamespace(**snapshot)
    source = sample_provenance(snapshot)
    reasons = []
    if source['sample_kind'] != 'real':
        reasons.append({'manual': 'manual_sample', 'simulated': 'simulated_sample'}.get(source['sample_kind'], 'unknown_source'))
    if source['sampling_method'] != 'unprimed_json_v2':
        reasons.append('unsupported_sampling_method')
    if source['analysis_status'] != 'completed':
        reasons.append('analysis_incomplete')
    if getattr(snapshot, 'citation_accuracy', None) == 'inaccurate':
        reasons.append('citation_inaccurate')
    if getattr(snapshot, 'is_brand_probe', False):
        reasons.append('brand_probe')
    return reasons


def eligible_visibility_sample(snapshot):
    return not sample_exclusion_reasons(snapshot)
