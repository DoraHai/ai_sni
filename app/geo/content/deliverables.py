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
    scope: dict[str, Any] | None = None,
    daily_series: list[dict[str, Any]] | None = None,
    business_slices: list[dict[str, Any]] | None = None,
    unit_slices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble a client-facing pack payload (no AI narrative in MVP)."""
    return {
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "period": period,
        "scope": scope
        or {
            "level": "tenant",
            "business_id": None,
            "unit_id": None,
            "business_name": None,
            "unit_name": None,
            "label": "租户全量",
        },
        "summary": summary,
        "citations_top": citations_top,
        "tasks": tasks,
        "snapshots_sample": snapshots_sample,
        "daily_series": daily_series or [],
        "business_slices": business_slices or [],
        "unit_slices": unit_slices or [],
        "generated_kind": "geo_deliverables_pack_v3",
        "sample_composition": (summary or {}).get("sample_composition"),
        "has_simulated_samples": bool(
            ((summary or {}).get("sample_composition") or {}).get("has_simulated")
        ),
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
    scope = pack.get("scope") or {}
    lines = [
        f"# GEO 交付摘要 · {pack.get('tenant_name') or ('租户' + str(pack.get('tenant_id')))}",
        "",
        f"- 客户 ID：{pack.get('tenant_id')}",
        f"- 周期：{period.get('from') or '—'} ~ {period.get('to') or '—'}",
        f"- 切片范围：{scope.get('label') or '租户全量'}",
        f"- 生成类型：{pack.get('generated_kind')}",
        "",
        "## 概览",
        "",
        f"- 优化意图词：{summary.get('prompts', '—')}",
        f"- 优化文章：{summary.get('tasks', '—')}（已发布 {summary.get('published', '—')}）",
        f"- 样本构成：{(pack.get('sample_composition') or {}).get('label') or '—'}",
        f"- 对外结论：{pack.get('verdict') or (pack.get('sample_composition') or {}).get('verdict') or '—'}",
        f"- 效果口径：{pack.get('impact_language') or '发布后观察到的相关变化（非确定因果）'}",
        f"- 品牌提及率（排除探测题）：{_pct(summary.get('visibility_mention_rate'))}",
        f"- 首位推荐率 top1：{_pct(summary.get('visibility_top1_rate'))}",
        f"- 品牌点名认知率（仅探测题）：{_pct(summary.get('probe_recognition_rate'))}",
        f"- 可见度快照：{summary.get('snapshots_visibility', summary.get('snapshots', '—'))}"
        f"（探测题快照 {summary.get('snapshots_probe', '—')}）",
        f"- 覆盖引擎数：{summary.get('visibility_engines_covered', '—')}",
        f"- AI 引用次数（独立被引域名数）：{summary.get('distinct_cited_domains', '—')}",
        f"- AI 引用次数（URL 出现总次）：{summary.get('citation_count', '—')}",
        f"- 待复测意图词：{summary.get('prompts_need_recheck', '—')}",
        "",
        "> 口径：无可见性样本时品牌提及率记为「—」而非 0；探测题不计入提及率分母；"
        "AI 引用次数来自回答快照 cited_urls 聚合（独立域名 / 出现次数），非全网抓取；"
        "业务/单元切片仅统计挂在该业务/单元下意图词的快照。",
        "",
    ]

    daily = pack.get("daily_series") or []
    if daily:
        lines.extend(["## 按天汇总（切片）", ""])
        for row in daily:
            lines.append(
                f"- {row.get('metric_date') or '—'} · 提及 {_pct(row.get('brand_mention_rate'))}"
                f" · 点名 {_pct(row.get('brand_probe_recognition_rate'))}"
                f" · AI 引用 {row.get('citation_count', 0)}"
                f" · 独立域名 {row.get('distinct_cited_domains', 0)}"
            )
        lines.append("")

    biz_slices = pack.get("business_slices") or []
    if biz_slices and (scope.get("level") or "tenant") == "tenant":
        lines.extend(["## 优化业务切片（周期内末次/汇总）", ""])
        for row in biz_slices:
            lines.append(
                f"- {row.get('business_name') or ('业务#' + str(row.get('business_id')))}"
                f" · 提及 {_pct(row.get('brand_mention_rate'))}"
                f" · AI 引用 {row.get('citation_count', 0)}"
                f" · 快照 {row.get('snapshots_visibility', 0)}+{row.get('snapshots_probe', 0)}"
            )
        lines.append("")

    unit_slices = pack.get("unit_slices") or []
    if unit_slices and (scope.get("level") or "tenant") in ("tenant", "business"):
        lines.extend(["## 优化单元切片（周期内末次/汇总）", ""])
        for row in unit_slices:
            label = row.get("unit_name") or f"单元#{row.get('unit_id')}"
            if row.get("business_name"):
                label = f"{row['business_name']} / {label}"
            lines.append(
                f"- {label}"
                f" · 提及 {_pct(row.get('brand_mention_rate'))}"
                f" · AI 引用 {row.get('citation_count', 0)}"
                f" · 快照 {row.get('snapshots_visibility', 0)}+{row.get('snapshots_probe', 0)}"
            )
        lines.append("")

    lines.extend(["## AI 引用次数 · 域名 Top", ""])
    cites = pack.get("citations_top") or []
    if not cites:
        lines.append("_本期无 AI 引用数据_")
    else:
        for row in cites:
            engines = ", ".join(row.get("engines") or []) or "—"
            bp = row.get("blueprint_channel_name") or row.get("blueprint_channel_key") or "—"
            own = "自有" if row.get("is_own_domain") else "外部"
            lines.append(
                f"- `{row.get('domain')}` · {row.get('cite_count', 0)} 次 · {own} · 蓝图 {bp} · 引擎 {engines}"
            )
    lines.extend(["", "## 优化文章", ""])
    tasks = pack.get("tasks") or []
    if not tasks:
        lines.append("_本期无优化文章_")
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
