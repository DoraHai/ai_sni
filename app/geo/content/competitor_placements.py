"""竞品 GEO 阵地库 + 逆向发布建议（最小可用）。

有引用 URL 时仍以快照为准；没有 URL 时用本表推定官网/帮助中心，
再按提问组给出可一键建任务的补位建议。
"""

from __future__ import annotations

import re
from typing import Any

from app.geo.content.cn_blueprint import CHANNELS_CN, GROUP_PLAN
from app.geo.content.expand import classify_term

_CHANNEL_TO_TASK = {
    "official": "website",
    "zhihu": "zhihu",
    "wechat": "wechat",
    "tech": "website",
    "baike": "website",
    "ranking": "website",
}

# 智能客服赛道常见竞品。aliases 用于名称模糊匹配。
COMPETITOR_PLACEMENTS: list[dict[str, Any]] = [
    {
        "canonical": "网易七鱼",
        "aliases": ["网易七鱼", "七鱼", "qiyukf", "qiyu"],
        "placements": [
            {"channel_key": "official", "url": "https://qiyukf.com/", "label": "官网"},
            {"channel_key": "zhihu", "url": None, "label": "知乎（品类问答高发）"},
        ],
    },
    {
        "canonical": "Udesk",
        "aliases": ["udesk", "Udesk"],
        "placements": [
            {"channel_key": "official", "url": "https://www.udesk.cn/", "label": "官网"},
            {"channel_key": "zhihu", "url": None, "label": "知乎（品类问答高发）"},
        ],
    },
    {
        "canonical": "容联七陌",
        "aliases": ["容联七陌", "七陌", "7moor", "容联"],
        "placements": [
            {"channel_key": "official", "url": "https://www.7moor.com/", "label": "官网"},
            {"channel_key": "zhihu", "url": None, "label": "知乎（品类问答高发）"},
        ],
    },
    {
        "canonical": "小能科技",
        "aliases": ["小能科技", "小能", "xiaoneng"],
        "placements": [
            {"channel_key": "official", "url": "https://www.xiaoneng.cn/", "label": "官网"},
        ],
    },
    {
        "canonical": "美洽",
        "aliases": ["美洽", "meiqia"],
        "placements": [
            {"channel_key": "official", "url": "https://www.meiqia.com/", "label": "官网"},
        ],
    },
    {
        "canonical": "Zendesk",
        "aliases": ["zendesk", "Zendesk"],
        "placements": [
            {"channel_key": "official", "url": "https://www.zendesk.com/cn/", "label": "官网"},
        ],
    },
    {
        "canonical": "环信",
        "aliases": ["环信", "easemob"],
        "placements": [
            {"channel_key": "official", "url": "https://www.easemob.com/", "label": "官网"},
        ],
    },
]


def _fold(name: str | None) -> str:
    return re.sub(r"[\s\-_.·•]+", "", (name or "").strip()).casefold()


def resolve_placement_profile(name: str | None) -> dict[str, Any] | None:
    needle = _fold(name)
    if len(needle) < 2:
        return None
    for profile in COMPETITOR_PLACEMENTS:
        aliases = [_fold(a) for a in list(profile.get("aliases") or []) + [profile["canonical"]]]
        if needle in aliases:
            return profile
        for alias in aliases:
            if len(alias) >= 2 and (alias in needle or needle in alias):
                return profile
    return None


def _channel_name(channel_key: str) -> str:
    for ch in CHANNELS_CN:
        if ch["id"] == channel_key:
            return str(ch["name"])
    return channel_key


def inferred_placements_for(name: str | None) -> list[dict[str, Any]]:
    profile = resolve_placement_profile(name)
    if not profile:
        return []
    out: list[dict[str, Any]] = []
    for raw in profile.get("placements") or []:
        key = str(raw.get("channel_key") or "official")
        out.append(
            {
                "canonical": profile["canonical"],
                "channel_key": key,
                "channel_name": _channel_name(key),
                "url": raw.get("url"),
                "label": raw.get("label") or _channel_name(key),
                "inferred": True,
            }
        )
    return out


def inferred_platforms(placements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for p in placements:
        key = p.get("channel_key") or "official"
        b = buckets.setdefault(
            key,
            {
                "channel_key": key,
                "channel_name": p.get("channel_name") or _channel_name(key),
                "cite_count": 0,
                "sample_urls": [],
                "domains": set(),
                "inferred": True,
            },
        )
        url = p.get("url")
        if url and url not in b["sample_urls"]:
            b["sample_urls"].append(url)
            host = re.sub(r"^https?://", "", url).split("/")[0]
            if host:
                b["domains"].add(host)
    return [
        {
            **{k: v for k, v in b.items() if k != "domains"},
            "domains": sorted(b["domains"]),
            "cite_count": 0,
        }
        for b in buckets.values()
    ]


def inferred_sources(placements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in placements:
        url = p.get("url")
        if not url:
            continue
        host = re.sub(r"^https?://", "", url).split("/")[0]
        out.append(
            {
                "url": url,
                "domain": host,
                "cite_count": 0,
                "prompt_count": 0,
                "engines": [],
                "latest_captured_at": None,
                "observations": [],
                "channel_key": p.get("channel_key") or "official",
                "channel_name": p.get("channel_name") or p.get("label"),
                "inferred": True,
            }
        )
    return out


def _question_group(question: str, explicit: str | None) -> str:
    g = (explicit or "").strip()
    if g in GROUP_PLAN:
        return g
    return classify_term(question or "", "category")


def build_competitor_geo_recs(
    *,
    competitor: str,
    mention_prompt_ids: list[int],
    questions: dict[int, str],
    question_groups: dict[int, str] | None = None,
    max_recs: int = 5,
) -> list[dict[str, Any]]:
    """按该竞品赢下的提问组给出 3–5 条发布建议。"""
    groups = question_groups or {}
    counts: dict[str, dict[str, Any]] = {}
    for pid in mention_prompt_ids:
        q = (questions.get(pid) or "").strip()
        if not q:
            continue
        grp = _question_group(q, groups.get(pid))
        bucket = counts.setdefault(
            grp, {"group": grp, "count": 0, "prompt_id": pid, "question": q}
        )
        bucket["count"] += 1
        if len(q) < len(bucket["question"]):
            bucket["prompt_id"] = pid
            bucket["question"] = q

    ranked = sorted(counts.values(), key=lambda x: (-x["count"], x["group"]))
    recs: list[dict[str, Any]] = []

    def add(
        *,
        key: str,
        title: str,
        reason: str,
        channel_key: str,
        group: str,
        prompt_id: int | None,
        question: str,
    ) -> None:
        if any(r["key"] == key for r in recs):
            return
        form, tip = GROUP_PLAN.get(group, ("内容页", "补可被抽取的对比/定义内容"))
        recs.append(
            {
                "key": key,
                "title": title[:200],
                "reason": reason,
                "form": form,
                "tip": tip,
                "channel_key": channel_key,
                "target_channel": _CHANNEL_TO_TASK.get(channel_key, "website"),
                "question_group": group,
                "prompt_id": prompt_id,
                "sample_question": question,
            }
        )

    name = (competitor or "该竞品").strip() or "该竞品"
    for item in ranked[:3]:
        grp = item["group"]
        form, _tip = GROUP_PLAN.get(grp, ("内容页", ""))
        add(
            key=f"official-{grp}",
            title=f"补官网{form}：回应「{item['question'][:32]}」",
            reason=f"{name} 在「{grp}」类提问出现 {item['count']} 次，本品需有同口径页面。",
            channel_key="official",
            group=grp,
            prompt_id=item["prompt_id"],
            question=item["question"],
        )
        if grp in {"推荐", "比较", "替代", "风险"}:
            add(
                key=f"zhihu-{grp}",
                title=f"补知乎问答：覆盖「{item['question'][:32]}」",
                reason=f"{name} 在该类提问被点名；知乎是 B2B 选型高发阵地。",
                channel_key="zhihu",
                group=grp,
                prompt_id=item["prompt_id"],
                question=item["question"],
            )
        if len(recs) >= max_recs:
            break

    if not recs:
        add(
            key="official-generic",
            title=f"补官网对比页，正面回应与{name}的差异",
            reason=f"巡检多次提到{name}，但缺少可引用的本品对比内容。",
            channel_key="official",
            group="比较",
            prompt_id=mention_prompt_ids[0] if mention_prompt_ids else None,
            question=questions.get(mention_prompt_ids[0], "") if mention_prompt_ids else "",
        )
    return recs[:max_recs]


def compose_suggested_copy(*, competitor: str, recs: list[dict[str, Any]]) -> dict[str, str]:
    name = (competitor or "该竞品").strip() or "该竞品"
    if not recs:
        return {
            "insight": f"{name} 在巡检回答中被点名，但未见引用 URL，无法确认具体页面。",
            "action": "先补官网对比/选型页，再在知乎覆盖同类提问。",
        }
    lines = [f"{name} 在以下问法上被 AI 点名，推定阵地见上方："]
    for r in recs:
        lines.append(f"- {r['question_group']}：{r['sample_question'] or r['title']}")
    actions = [r["title"] for r in recs]
    return {"insight": "\n".join(lines), "action": "；".join(actions)}


def attach_geo_reverse(
    trace: dict[str, Any],
    *,
    competitor: str,
    mention_prompt_ids: list[int],
    questions: dict[int, str],
    question_groups: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Mutates and returns trace with inferred placements + recs."""
    inferred = inferred_placements_for(competitor)
    trace["inferred_placements"] = inferred
    # 推定阵地不得写入 platforms / sources_agg，避免和真实引用混计。
    trace["cited_url_count"] = len(trace.get("sources_agg") or [])
    trace["has_real_citations"] = bool(trace.get("sources_agg") or trace.get("sources"))
    trace["unique_url_count"] = int(trace.get("unique_url_count") or len(trace.get("sources_agg") or []))
    recs = build_competitor_geo_recs(
        competitor=competitor,
        mention_prompt_ids=mention_prompt_ids,
        questions=questions,
        question_groups=question_groups,
    )
    copy = compose_suggested_copy(competitor=competitor, recs=recs)
    trace["recommendations"] = recs
    trace["suggested_insight"] = copy["insight"]
    trace["suggested_action"] = copy["action"]
    return trace
