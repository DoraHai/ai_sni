"""GEO client deliverables pack (MVP): compose existing visibility/content stats."""

from __future__ import annotations

from typing import Any


def build_deliverables_pack(
    *,
    tenant_id: int,
    tenant_name: str,
    period: dict[str, Any],
    summary: dict[str, Any],
    citations_top: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    snapshots_sample: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble a client-facing pack payload (no AI narrative in MVP)."""
    return {
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "period": period,
        "summary": summary,
        "citations_top": citations_top,
        "tasks": tasks,
        "snapshots_sample": snapshots_sample,
        "generated_kind": "geo_deliverables_pack_v1",
    }


def _pct(rate: Any) -> str:
    if rate is None:
        return "—"
    try:
        return f"{float(rate) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def render_deliverables_markdown(pack: dict[str, Any]) -> str:
    """Render pack as a single Markdown report for copy/download."""
    summary = pack.get("summary") or {}
    period = pack.get("period") or {}
    lines = [
        f"# GEO 交付摘要 · {pack.get('tenant_name') or ('租户' + str(pack.get('tenant_id')))}",
        "",
        f"- 客户 ID：{pack.get('tenant_id')}",
        f"- 周期：{period.get('from') or '—'} ~ {period.get('to') or '—'}",
        f"- 生成类型：{pack.get('generated_kind')}",
        "",
        "## 概览",
        "",
        f"- 活跃提示词：{summary.get('prompts', '—')}",
        f"- 内容任务：{summary.get('tasks', '—')}（已发布 {summary.get('published', '—')}）",
        f"- 可见性提及率：{_pct(summary.get('visibility_mention_rate'))}",
        f"- 可见度快照：{summary.get('snapshots_visibility', summary.get('snapshots', '—'))}",
        f"- 覆盖引擎数：{summary.get('visibility_engines_covered', '—')}",
        f"- 独立引用域名：{summary.get('distinct_cited_domains', '—')}",
        f"- 待复测提示词：{summary.get('prompts_need_recheck', '—')}",
        "",
        "## 引用域名 Top",
        "",
    ]
    cites = pack.get("citations_top") or []
    if not cites:
        lines.append("_本期无引用域名数据_")
    else:
        for row in cites:
            engines = ", ".join(row.get("engines") or []) or "—"
            bp = row.get("blueprint_channel_name") or row.get("blueprint_channel_key") or "—"
            own = "自有" if row.get("is_own_domain") else "外部"
            lines.append(
                f"- `{row.get('domain')}` · {row.get('cite_count', 0)} 次 · {own} · 蓝图 {bp} · 引擎 {engines}"
            )
    lines.extend(["", "## 内容任务", ""])
    tasks = pack.get("tasks") or []
    if not tasks:
        lines.append("_本期无任务_")
    else:
        for t in tasks:
            lines.append(
                f"- #{t.get('id')} [{t.get('status')}] {t.get('title') or t.get('prompt_question') or '—'}"
            )
    lines.extend(["", "## 可见度快照抽样", ""])
    snaps = pack.get("snapshots_sample") or []
    if not snaps:
        lines.append("_本期无快照_")
    else:
        for s in snaps:
            mention = "提及" if s.get("mentions_brand") else "未提及"
            q = s.get("prompt_question") or f"#{s.get('prompt_id')}"
            lines.append(
                f"- {s.get('captured_at') or '—'} · {s.get('engine')} · {mention} · {q}"
            )
    lines.append("")
    return "\n".join(lines)
