"""竞品来源溯源：从标注了竞品的快照 cited_urls 反推发布平台，并拼手工报告。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from app.geo.content.cn_blueprint import match_blueprint_for_domain
from app.geo.content.snapshots import extract_cited_domain


def _norm_name(name: str | None) -> str:
    return (name or "").strip().casefold()


def snapshot_mentions_competitor(competitors: Iterable[Any] | None, name: str) -> bool:
    target = _norm_name(name)
    if not target:
        return False
    for item in competitors or []:
        if _norm_name(str(item)) == target:
            return True
    return False


def build_competitor_trace(
    *,
    competitor: str,
    rows: list[Any],
    questions: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Aggregate sources/platforms from snapshot rows that mention ``competitor``.

    ``rows`` are objects/dicts with: competitors, cited_urls, engine, prompt_id,
    captured_at, id (or snapshot_id).
    """
    questions = questions or {}
    name = (competitor or "").strip()
    if not name:
        return {
            "competitor": "",
            "mention_count": 0,
            "prompt_count": 0,
            "engines": [],
            "sources": [],
            "sources_agg": [],
            "unique_url_count": 0,
            "platforms": [],
        }

    mention_count = 0
    prompt_ids: set[int] = set()
    engines: set[str] = set()
    sources: list[dict[str, Any]] = []
    seen_source_keys: set[str] = set()
    platform_buckets: dict[str, dict[str, Any]] = {}

    for row in rows:
        comps = getattr(row, "competitors", None)
        if comps is None and isinstance(row, dict):
            comps = row.get("competitors")
        if not snapshot_mentions_competitor(comps, name):
            continue
        mention_count += 1

        engine = getattr(row, "engine", None)
        if engine is None and isinstance(row, dict):
            engine = row.get("engine")
        engine = str(engine or "other")
        engines.add(engine)

        prompt_id = getattr(row, "prompt_id", None)
        if prompt_id is None and isinstance(row, dict):
            prompt_id = row.get("prompt_id")
        if prompt_id is not None:
            try:
                prompt_ids.add(int(prompt_id))
            except (TypeError, ValueError):
                pass

        captured = getattr(row, "captured_at", None)
        if captured is None and isinstance(row, dict):
            captured = row.get("captured_at")
        if hasattr(captured, "isoformat"):
            captured_at = captured.isoformat()
        else:
            captured_at = str(captured) if captured else None

        snap_id = getattr(row, "id", None)
        if snap_id is None and isinstance(row, dict):
            snap_id = row.get("id") or row.get("snapshot_id")

        urls = getattr(row, "cited_urls", None)
        if urls is None and isinstance(row, dict):
            urls = row.get("cited_urls")
        for url in urls or []:
            u = str(url or "").strip()
            if not u:
                continue
            domain = extract_cited_domain(u) or "unknown"
            key = f"{u}|{snap_id}"
            if key not in seen_source_keys:
                seen_source_keys.add(key)
                sources.append(
                    {
                        "url": u,
                        "domain": domain,
                        "engine": engine,
                        "prompt_id": prompt_id,
                        "prompt_question": questions.get(int(prompt_id))
                        if prompt_id is not None
                        else None,
                        "captured_at": captured_at,
                        "snapshot_id": snap_id,
                    }
                )

            bp = match_blueprint_for_domain(domain)
            channel_key = bp["channel_key"] if bp else "other"
            channel_name = bp["channel_name"] if bp else "其他/未知"
            bucket = platform_buckets.setdefault(
                channel_key,
                {
                    "channel_key": channel_key,
                    "channel_name": channel_name,
                    "cite_count": 0,
                    "sample_urls": [],
                    "domains": set(),
                },
            )
            bucket["cite_count"] += 1
            bucket["domains"].add(domain)
            if u not in bucket["sample_urls"] and len(bucket["sample_urls"]) < 8:
                bucket["sample_urls"].append(u)

    platforms = []
    for bucket in platform_buckets.values():
        platforms.append(
            {
                "channel_key": bucket["channel_key"],
                "channel_name": bucket["channel_name"],
                "cite_count": bucket["cite_count"],
                "sample_urls": bucket["sample_urls"],
                "domains": sorted(bucket["domains"]),
            }
        )
    platforms.sort(key=lambda x: (-x["cite_count"], x["channel_key"]))
    sources.sort(
        key=lambda x: (x.get("captured_at") or "", x.get("url") or ""),
        reverse=True,
    )
    sources_agg = aggregate_sources_by_url(sources)
    # Attach channel_key on each aggregated row for platform filtering
    for item in sources_agg:
        bp = match_blueprint_for_domain(item.get("domain") or "")
        item["channel_key"] = bp["channel_key"] if bp else "other"
        item["channel_name"] = bp["channel_name"] if bp else "其他/未知"

    return {
        "competitor": name,
        "mention_count": mention_count,
        "prompt_count": len(prompt_ids),
        "engines": sorted(engines),
        "sources": sources,
        "sources_agg": sources_agg,
        "unique_url_count": len(sources_agg),
        "platforms": platforms,
    }


def aggregate_sources_by_url(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated snapshot rows of the same URL into one operational row."""
    buckets: dict[str, dict[str, Any]] = {}
    for s in sources or []:
        url = str(s.get("url") or "").strip()
        if not url:
            continue
        b = buckets.setdefault(
            url,
            {
                "url": url,
                "domain": s.get("domain") or extract_cited_domain(url) or "unknown",
                "cite_count": 0,
                "prompt_ids": set(),
                "engines": set(),
                "latest_captured_at": None,
                "observations": [],
            },
        )
        b["cite_count"] += 1
        if s.get("prompt_id") is not None:
            try:
                b["prompt_ids"].add(int(s["prompt_id"]))
            except (TypeError, ValueError):
                pass
        if s.get("engine"):
            b["engines"].add(str(s["engine"]))
        captured = s.get("captured_at")
        if captured and (
            b["latest_captured_at"] is None or str(captured) > str(b["latest_captured_at"])
        ):
            b["latest_captured_at"] = captured
        b["observations"].append(
            {
                "snapshot_id": s.get("snapshot_id"),
                "engine": s.get("engine"),
                "prompt_id": s.get("prompt_id"),
                "prompt_question": s.get("prompt_question"),
                "captured_at": captured,
            }
        )
    out = []
    for b in buckets.values():
        out.append(
            {
                "url": b["url"],
                "domain": b["domain"],
                "cite_count": b["cite_count"],
                "prompt_count": len(b["prompt_ids"]),
                "engines": sorted(b["engines"]),
                "latest_captured_at": b["latest_captured_at"],
                "observations": sorted(
                    b["observations"],
                    key=lambda x: x.get("captured_at") or "",
                    reverse=True,
                ),
            }
        )
    # cite_count DESC, then latest_captured_at DESC
    out.sort(
        key=lambda x: (
            -int(x.get("cite_count") or 0),
            str(x.get("latest_captured_at") or ""),
        ),
    )
    # secondary string ascending is wrong for "latest first"; flip with reverse on second key:
    out.sort(key=lambda x: str(x.get("latest_captured_at") or ""), reverse=True)
    out.sort(key=lambda x: -int(x.get("cite_count") or 0))
    return out


def build_competitor_report_markdown(
    *,
    competitor: str,
    trace: dict[str, Any],
    source_urls: list[str] | None = None,
    platform_keys: list[str] | None = None,
    note: str | None = None,
    insight: str | None = None,
    action: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a manual Markdown report from a trace payload + operator selections."""
    name = (competitor or trace.get("competitor") or "").strip() or "未命名竞品"
    selected_urls = {str(u).strip() for u in (source_urls or []) if str(u).strip()}
    selected_platforms = {
        str(k).strip() for k in (platform_keys or []) if str(k).strip()
    }

    all_agg = list(trace.get("sources_agg") or aggregate_sources_by_url(trace.get("sources") or []))
    all_platforms = list(trace.get("platforms") or [])

    if selected_platforms:
        platforms = [
            p for p in all_platforms if p.get("channel_key") in selected_platforms
        ]
    else:
        platforms = all_platforms

    if selected_urls:
        sources = [s for s in all_agg if s.get("url") in selected_urls]
    else:
        sources = list(all_agg)
        if selected_platforms:
            sources = [
                s
                for s in sources
                if (s.get("channel_key") or "other") in selected_platforms
            ]

    now = generated_at or datetime.utcnow()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    title = f"竞品来源溯源报告 · {name}"

    lines: list[str] = [
        f"# {title}",
        "",
        f"- 生成时间：{stamp}",
        f"- 竞品：{name}",
        f"- 快照提及次数：{trace.get('mention_count') or 0}",
        f"- 关联提问数：{trace.get('prompt_count') or 0}",
        f"- 引擎：{', '.join(trace.get('engines') or []) or '—'}",
        f"- 已选来源：{len(sources)} 条（去重 URL）",
        f"- 已选平台：{len(platforms)}",
        "",
        "## 发布平台分布（反向溯源）",
        "",
    ]
    if platforms:
        lines.append("| 平台 | 引用次数 | 样例域名 |")
        lines.append("| --- | ---: | --- |")
        for p in platforms:
            domains = "、".join((p.get("domains") or [])[:5]) or "—"
            lines.append(
                f"| {p.get('channel_name') or p.get('channel_key')} "
                f"| {p.get('cite_count') or 0} | {domains} |"
            )
        lines.append("")
    else:
        lines.append("（无平台数据：请确认快照已填写竞品并提取引用 URL）")
        lines.append("")

    lines.append("## 来源明细（按 URL 去重）")
    lines.append("")
    if sources:
        for i, s in enumerate(sources, 1):
            lines.append(f"{i}. {s.get('url')}")
            meta = [
                f"引用 {s.get('cite_count') or 1} 次",
                f"提问 {s.get('prompt_count') or 0}",
            ]
            if s.get("domain"):
                meta.append(f"域名 {s['domain']}")
            if s.get("engines"):
                meta.append("引擎 " + "、".join(s["engines"]))
            if s.get("latest_captured_at"):
                meta.append(f"最近 {s['latest_captured_at']}")
            lines.append(f"   - {' · '.join(meta)}")
        lines.append("")
    else:
        lines.append("（未勾选或无可用来源 URL）")
        lines.append("")

    if (insight or "").strip():
        lines.append("## 洞察")
        lines.append("")
        lines.append(insight.strip())
        lines.append("")
    if (action or "").strip():
        lines.append("## 行动建议")
        lines.append("")
        lines.append(action.strip())
        lines.append("")
    if (note or "").strip():
        lines.append("## 运营备注")
        lines.append("")
        lines.append(note.strip())
        lines.append("")

    lines.append("---")
    lines.append(
        "*本报告由可见度快照中的竞品标注与引用 URL 反向归集生成，非外网实时检索。*"
    )
    lines.append("")

    return {
        "title": title,
        "markdown": "\n".join(lines),
        "generated_at": now.isoformat(),
        "source_count": len(sources),
        "platform_count": len(platforms),
    }


def build_competitor_compare(
    *,
    rows: list[Any],
    questions: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Same-prompt brand vs competitor mention / position comparison.

    Each item is one prompt with snapshot aggregates for brand and competitors.
    """
    questions = questions or {}
    by_prompt: dict[int, dict[str, Any]] = {}

    for row in rows:
        pid = getattr(row, "prompt_id", None)
        if pid is None and isinstance(row, dict):
            pid = row.get("prompt_id")
        if pid is None:
            continue
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue

        bucket = by_prompt.setdefault(
            pid,
            {
                "prompt_id": pid,
                "question": questions.get(pid) or "",
                "snapshot_count": 0,
                "brand_mentions": 0,
                "brand_first": 0,
                "competitor_hits": {},  # name -> {mentions, first_with_brand?}
                "engines": set(),
            },
        )
        bucket["snapshot_count"] += 1

        engine = getattr(row, "engine", None)
        if engine is None and isinstance(row, dict):
            engine = row.get("engine")
        if engine:
            bucket["engines"].add(str(engine))

        mentions_brand = getattr(row, "mentions_brand", None)
        if mentions_brand is None and isinstance(row, dict):
            mentions_brand = row.get("mentions_brand")
        position = getattr(row, "brand_position", None)
        if position is None and isinstance(row, dict):
            position = row.get("brand_position")
        position = str(position or "unknown")

        if mentions_brand:
            bucket["brand_mentions"] += 1
            if position == "first":
                bucket["brand_first"] += 1

        comps = getattr(row, "competitors", None)
        if comps is None and isinstance(row, dict):
            comps = row.get("competitors")
        for raw in comps or []:
            name = str(raw or "").strip()
            if not name:
                continue
            hit = bucket["competitor_hits"].setdefault(
                name, {"name": name, "mentions": 0}
            )
            hit["mentions"] += 1

    items: list[dict[str, Any]] = []
    brand_lead = 0
    competitor_lead = 0
    tie = 0
    for bucket in by_prompt.values():
        n = max(1, bucket["snapshot_count"])
        brand_rate = bucket["brand_mentions"] / n
        brand_first_rate = bucket["brand_first"] / n
        comps = []
        best_comp_rate = 0.0
        best_comp_name = None
        for hit in bucket["competitor_hits"].values():
            rate = hit["mentions"] / n
            comps.append(
                {
                    "name": hit["name"],
                    "mention_count": hit["mentions"],
                    "mention_rate": round(rate, 4),
                }
            )
            if rate > best_comp_rate:
                best_comp_rate = rate
                best_comp_name = hit["name"]
        comps.sort(key=lambda x: (-x["mention_rate"], x["name"]))

        if brand_rate > best_comp_rate + 1e-9:
            winner = "brand"
            brand_lead += 1
        elif best_comp_rate > brand_rate + 1e-9:
            winner = "competitor"
            competitor_lead += 1
        else:
            winner = "tie"
            tie += 1

        items.append(
            {
                "prompt_id": bucket["prompt_id"],
                "question": bucket["question"] or f"#{bucket['prompt_id']}",
                "snapshot_count": bucket["snapshot_count"],
                "engines": sorted(bucket["engines"]),
                "brand_mention_count": bucket["brand_mentions"],
                "brand_mention_rate": round(brand_rate, 4),
                "brand_first_count": bucket["brand_first"],
                "brand_first_rate": round(brand_first_rate, 4),
                "competitors": comps,
                "top_competitor": best_comp_name,
                "top_competitor_rate": round(best_comp_rate, 4),
                "winner": winner,
            }
        )

    items.sort(
        key=lambda x: (
            0 if x["winner"] == "competitor" else 1 if x["winner"] == "tie" else 2,
            -(x["top_competitor_rate"] - x["brand_mention_rate"]),
            x["prompt_id"],
        )
    )
    return {
        "items": items,
        "summary": {
            "prompt_count": len(items),
            "brand_lead": brand_lead,
            "competitor_lead": competitor_lead,
            "tie": tie,
        },
    }
