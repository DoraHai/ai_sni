"""GEO D3 验收 checker（GeoLook verify.py 精简适配）。

单页诊断 + 媒体布局，不做全站 crawl / metrics 验收。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# finding code → auto checker expression
CODE_TO_CHECK: dict[str, str] = {
    "llms": "site.has_llms_txt",
    "schema": "pages.has_jsonld",
    "entity_schema": "finding.passed:entity_schema",
    "robots": "finding.passed:robots",
    "https": "finding.passed:https",
    "title": "finding.passed:title",
    "description": "finding.passed:description",
    "canonical": "finding.passed:canonical",
    "indexable": "finding.passed:indexable",
    "h1": "finding.passed:h1",
    "heading_depth": "finding.passed:heading_depth",
    "substantial": "finding.passed:substantial",
    "faq": "finding.passed:faq",
    "citations": "finding.passed:citations",
    "freshness": "finding.passed:freshness",
    "language": "finding.passed:language",
    "block_definition": "pages.block:definition",
    "block_numbers": "pages.block:numbers",
    "block_comparison": "pages.block:comparison",
    "block_howto": "pages.block:howto",
    "block_faq": "pages.block:faq",
}

BLOCK_LABELS = {
    "definition": "定义",
    "numbers": "数字事实",
    "comparison": "对比",
    "howto": "操作步骤",
    "faq": "FAQ",
}


def _findings_by_code(audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in audit.get("findings") or audit.get("checks") or []:
        if isinstance(item, dict) and item.get("code"):
            out[str(item["code"])] = item
    return out


def _blocks_map(audit: dict[str, Any]) -> dict[str, bool]:
    snap = audit.get("snapshot") or {}
    blocks = snap.get("blocks") if isinstance(snap, dict) else None
    if isinstance(blocks, dict) and blocks:
        # snapshot may nest {blocks: {definition: bool, ...}} or store flat
        if any(isinstance(v, bool) for v in blocks.values()):
            return {str(k): bool(v) for k, v in blocks.items()}
    top = audit.get("blocks")
    if isinstance(top, dict):
        inner = top.get("blocks") if isinstance(top.get("blocks"), dict) else top
        if isinstance(inner, dict):
            return {str(k): bool(v) for k, v in inner.items() if isinstance(v, bool)}
    return {}


def _finding_passed(audit: dict[str, Any], code: str) -> tuple[bool | None, str]:
    item = _findings_by_code(audit).get(code)
    if item is None:
        return None, f"本次诊断无检查项 `{code}`"
    ok = bool(item.get("passed"))
    evidence = str(item.get("evidence") or "")
    return ok, (f"`{code}` 已通过" if ok else f"`{code}` 未通过：{evidence}")


def evaluate_check(
    expr: str,
    *,
    audit: dict[str, Any] | None = None,
    media_placements: list[dict[str, Any]] | None = None,
) -> tuple[bool | None, str, dict[str, Any] | None]:
    """Return (passed?, note, progress). passed=None means needs human."""
    check = (expr or "").strip()
    if not check:
        return None, "无自动验收表达式，需人工确认", None

    audit = audit or {}
    media = media_placements or []

    try:
        if check == "site.has_llms_txt":
            ok, note = _finding_passed(audit, "llms")
            return ok, note, None

        if check == "pages.has_jsonld":
            ok, note = _finding_passed(audit, "schema")
            return ok, note, None

        if check.startswith("finding.passed:"):
            code = check.split(":", 1)[1].strip()
            ok, note = _finding_passed(audit, code)
            cur = 1 if ok else 0
            return (
                ok,
                note,
                {"label": f"检查项 {code}", "cur": cur, "target": 1, "op": "gte"},
            )

        if check.startswith("pages.block:"):
            blk = check.split(":", 1)[1].strip()
            blocks = _blocks_map(audit)
            present = bool(blocks.get(blk))
            label = BLOCK_LABELS.get(blk, blk)
            return (
                present,
                f"页面「{label}」块{'已具备' if present else '仍缺失'}",
                {
                    "label": f"缺「{label}」块",
                    "cur": 0 if present else 1,
                    "target": 0,
                    "op": "lte",
                },
            )

        if check == "media.any_published":
            published = [
                m
                for m in media
                if str(m.get("status") or "") == "published"
                and str(m.get("published_url") or "").strip()
            ]
            ok = bool(published)
            return (
                ok,
                (
                    f"已铺设 {len(published)} 个阵地"
                    if ok
                    else "尚无带 URL 的已铺设阵地"
                ),
                {
                    "label": "已铺设阵地数",
                    "cur": len(published),
                    "target": 1,
                    "op": "gte",
                },
            )

        if check.startswith("media.published:"):
            key = check.split(":", 1)[1].strip()
            hit = next(
                (
                    m
                    for m in media
                    if str(m.get("channel_key") or "") == key
                    and str(m.get("status") or "") == "published"
                    and str(m.get("published_url") or "").strip()
                ),
                None,
            )
            ok = hit is not None
            return (
                ok,
                (
                    f"阵地 `{key}` 已铺设：{hit.get('published_url')}"
                    if ok
                    else f"阵地 `{key}` 尚未 published + URL"
                ),
                {
                    "label": f"阵地 {key}",
                    "cur": 1 if ok else 0,
                    "target": 1,
                    "op": "gte",
                },
            )

        if check.startswith("media.placement_published:"):
            pid = int(check.split(":", 1)[1].strip())
            hit = next((m for m in media if int(m.get("id") or 0) == pid), None)
            if hit is None:
                return None, f"找不到媒体布局 #{pid}", None
            ok = (
                str(hit.get("status") or "") == "published"
                and bool(str(hit.get("published_url") or "").strip())
            )
            return (
                ok,
                (
                    f"布局已铺设：{hit.get('published_url')}"
                    if ok
                    else f"布局「{hit.get('name')}」尚未 published + URL"
                ),
                None,
            )
    except Exception as exc:  # noqa: BLE001
        return None, f"检查器出错：{type(exc).__name__}: {exc}", None

    return None, f"未知检查器 `{check}`（需人工确认）", None


def resolve_acceptance(
    *,
    code: str | None,
    finding: dict[str, Any] | None = None,
    acceptance_text: str | None = None,
) -> tuple[str, str | None, str]:
    """Return (acceptance_type, acceptance_check, acceptance_desc)."""
    code = (code or "").strip()
    finding = finding or {}
    desc = (acceptance_text or "").strip() or (
        f"重新诊断后「{finding.get('title') or code}」检查通过。"
    )
    mapped = CODE_TO_CHECK.get(code)
    automatable = bool(finding.get("automatable")) or mapped is not None
    if mapped and automatable:
        return "auto", mapped, desc
    if mapped:
        return "auto", mapped, desc
    return "manual", None, desc


def materialize_ticket_specs(
    *,
    advice: list[dict[str, Any]] | None,
    findings: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Build ticket create specs from advice (preferred) or failed findings."""
    by_code = {
        str(f.get("code")): f
        for f in (findings or [])
        if isinstance(f, dict) and f.get("code")
    }
    source = advice if advice else []
    if not source:
        source = [
            {
                "code": f["code"],
                "priority": f.get("severity") or "medium",
                "title": f.get("title") or f["code"],
                "action": f.get("recommendation") or "",
                "acceptance": f"重新诊断后“{f.get('title') or f['code']}”检查通过。",
            }
            for f in (findings or [])
            if isinstance(f, dict) and not f.get("passed")
        ][:8]

    specs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in source:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        finding = by_code.get(code) or {}
        acc_type, acc_check, acc_desc = resolve_acceptance(
            code=code,
            finding=finding,
            acceptance_text=str(row.get("acceptance") or "") or None,
        )
        baseline = None
        if finding:
            baseline = {
                "code": code,
                "passed": finding.get("passed"),
                "evidence": finding.get("evidence"),
                "score_hint": finding.get("deduction"),
            }
        specs.append(
            {
                "advice_code": code,
                "priority": str(row.get("priority") or finding.get("severity") or "medium"),
                "title": str(row.get("title") or finding.get("title") or code)[:300],
                "action": str(row.get("action") or finding.get("recommendation") or "")
                or None,
                "acceptance_type": acc_type,
                "acceptance_check": acc_check,
                "acceptance_desc": acc_desc,
                "baseline_snapshot": baseline,
                "status": "todo",
            }
        )
    return specs


def apply_verdict_to_status(
    *,
    current_status: str,
    ok: bool | None,
) -> tuple[str, str]:
    """Return (new_status, verdict_label)."""
    if ok is True:
        return "done", "pass"
    if ok is False:
        if current_status == "done":
            return "reopened", "fail"
        return current_status if current_status != "done" else "todo", "fail"
    return current_status, "manual"


def append_evidence(
    existing: list[dict[str, Any]] | None,
    *,
    check: str | None,
    result: str,
    note: str,
    limit: int = 6,
) -> list[dict[str, Any]]:
    row = {
        "at": datetime.utcnow().isoformat() + "Z",
        "check": check,
        "result": result,
        "note": note,
    }
    out = list(existing or [])
    out.append(row)
    return out[-limit:]


def ticket_public_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "audit_id": row.audit_id,
        "advice_code": row.advice_code,
        "content_task_id": row.content_task_id,
        "media_placement_id": row.media_placement_id,
        "priority": row.priority,
        "title": row.title,
        "action": row.action,
        "status": row.status,
        "acceptance_type": row.acceptance_type,
        "acceptance_check": row.acceptance_check,
        "acceptance_desc": row.acceptance_desc,
        "baseline_snapshot": row.baseline_snapshot,
        "progress_first": row.progress_first,
        "progress": row.progress,
        "evidence": row.evidence or [],
        "last_verify_at": row.last_verify_at.isoformat() if row.last_verify_at else None,
        "last_verdict": row.last_verdict,
        "last_note": row.last_note,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
