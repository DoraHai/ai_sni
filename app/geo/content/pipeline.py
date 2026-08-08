"""GEO 内容任务流水线步骤推导。"""

from __future__ import annotations

STEPS = ("opportunity", "evidence", "draft", "adapt", "publish")

STEP_LABELS = {
    "opportunity": "提问缺口",
    "evidence": "证据注入",
    "draft": "生成编辑",
    "adapt": "渠道适配",
    "publish": "发布回填",
}


def derive_pipeline_step(
    task_status: str,
    fact_count: int,
    has_article: bool,
    variant_count: int,
) -> str:
    if task_status == "published":
        return "publish"
    if variant_count > 0 or task_status in {"exported", "ready"}:
        return "adapt"
    if has_article or task_status in {"editing", "needs_fix", "generating", "failed"}:
        return "draft"
    if fact_count >= 3 or task_status == "facts_bound":
        return "evidence"
    return "opportunity"


def blocked_reason_from_checks(checks: list[dict] | None) -> str | None:
    if not checks:
        return None
    failed = [c.get("code") for c in checks if not c.get("passed")]
    if not failed:
        return None
    return ", ".join(str(c) for c in failed if c)


def sync_pipeline_fields(
    task,
    *,
    fact_count: int,
    has_article: bool,
    variant_count: int,
    blocked_reason: str | None = None,
) -> None:
    task.pipeline_step = derive_pipeline_step(
        task.status, fact_count, has_article, variant_count
    )
    task.blocked_reason = blocked_reason
