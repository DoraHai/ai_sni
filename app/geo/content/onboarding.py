"""GEO 开户向导：官网 URL → 业务线 / 意图词 / 事实卡草稿。

复用 fetch_page_text、expand_candidates；只产草稿，apply 时由运营确认写入。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.geo.content.expand import expand_candidates
from app.geo.content.snapshots import extract_cited_domain
from app.urlwords import UrlFetchError, extract_words, fetch_page_text, validate_url

# 业务线启发：标题/H 中的产品短语
_BIZ_SPLIT = re.compile(r"[|｜/\-—·,，、;；\s]+")
_SENT_SPLIT = re.compile(r"[。！？!?\n]+")


def _host_brand(url: str) -> str | None:
    d = extract_cited_domain(url)
    if not d:
        return None
    # example.com → example；sub.brand.com.cn → brand
    parts = d.split(".")
    if len(parts) >= 2 and parts[-1] in {"cn", "com", "net", "org", "io", "ai"}:
        if len(parts) >= 3 and parts[-2] in {"com", "co", "net", "org"}:
            return parts[-3]
        return parts[-2]
    return parts[0] if parts else None


def _business_candidates(title: str, words: list[str], headings_blob: str) -> list[dict[str, Any]]:
    """Suggest 1–4 business lines from page title/words."""
    cands: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(name: str, reason: str) -> None:
        n = re.sub(r"\s+", " ", (name or "").strip())[:80]
        if len(n) < 2:
            return
        key = n.lower()
        if key in seen:
            return
        seen.add(key)
        cands.append({"name": n, "description": reason, "selected": len(cands) < 3})

    # Title segments often: "产品A - 公司名" or "公司｜解决方案"
    for seg in _BIZ_SPLIT.split(title or ""):
        if 2 <= len(seg) <= 24 and not re.search(r"官网|首页|welcome|home", seg, re.I):
            add(seg, "来自页面标题")
        if len(cands) >= 4:
            break

    for w in words[:12]:
        if 2 <= len(w) <= 16:
            add(w, "来自站点关键词")
        if len(cands) >= 6:
            break

    if not cands and title:
        add(title[:40], "页面标题")
    if not cands:
        add("核心业务", "默认业务线（请改名）")
    return cands[:6]


def _fact_drafts(
    *,
    title: str,
    text: str,
    url: str,
    words: list[str],
    brand: str | None,
) -> list[dict[str, Any]]:
    """Lightweight fact card drafts from page text (needs_review)."""
    drafts: list[dict[str, Any]] = []
    domain = extract_cited_domain(url) or url

    if title:
        drafts.append(
            {
                "title": (brand or title)[:80],
                "statement": f"{title}。来源：官网 {domain}。",
                "fact_type": "product",
                "source_name": domain,
                "source_url": url,
                "trust_level": "needs_review",
                "selected": True,
            }
        )

    # First few descriptive sentences
    body = re.sub(r"\s+", " ", text or "")[:4000]
    sents = [s.strip() for s in _SENT_SPLIT.split(body) if 20 <= len(s.strip()) <= 200]
    for s in sents[:5]:
        # skip nav junk
        if re.search(r"登录|注册|cookie|copyright|版权所有", s, re.I):
            continue
        title_guess = (words[0] if words else s[:24])[:80]
        drafts.append(
            {
                "title": title_guess,
                "statement": s,
                "fact_type": "product",
                "source_name": domain,
                "source_url": url,
                "trust_level": "needs_review",
                "selected": len(drafts) < 6,
            }
        )
        if len(drafts) >= 8:
            break

    # Keyword as short product facts
    for w in words[:5]:
        if any(w in (d.get("title") or "") for d in drafts):
            continue
        drafts.append(
            {
                "title": w[:80],
                "statement": f"官网提及关键词「{w}」，待运营补全产品说明与证据链接。",
                "fact_type": "product",
                "source_name": domain,
                "source_url": url,
                "trust_level": "draft",
                "selected": False,
            }
        )
        if len(drafts) >= 12:
            break
    return drafts


def _engine_suggestions() -> list[dict[str, Any]]:
    """Default engine combo for CN GEO monitoring."""
    return [
        {
            "engine_key": "deepseek",
            "display_name": "DeepSeek",
            "sample_mode": "mock_persona",
            "note": "国内易得；可先模拟，再配真 Key",
            "recommended": True,
        },
        {
            "engine_key": "doubao",
            "display_name": "豆包",
            "sample_mode": "mock_persona",
            "note": "国内场景常见",
            "recommended": True,
        },
        {
            "engine_key": "kimi",
            "display_name": "Kimi",
            "sample_mode": "mock_persona",
            "note": "长文/引用场景",
            "recommended": True,
        },
        {
            "engine_key": "chatgpt",
            "display_name": "ChatGPT",
            "sample_mode": "mock_persona",
            "note": "真采样需海外 API Key；默认模拟",
            "recommended": False,
        },
        {
            "engine_key": "perplexity",
            "display_name": "Perplexity",
            "sample_mode": "mock_persona",
            "note": "强引用；真采样门槛高",
            "recommended": False,
        },
    ]


async def preview_from_website(
    url: str,
    *,
    expand: bool = True,
    max_prompt_candidates: int = 24,
    existing_questions: set[str] | None = None,
    include_audit: bool = True,
) -> dict[str, Any]:
    """Fetch site → businesses / prompt candidates / fact drafts / engine tips / audit score."""
    try:
        url = validate_url(url.strip())
    except UrlFetchError as exc:
        raise ValueError(str(exc)) from exc

    try:
        title, text = await fetch_page_text(url)
    except UrlFetchError as exc:
        raise ValueError(str(exc)) from exc

    # GEO 站点体检分数（可失败降级，不影响开户草稿）
    audit_summary: dict[str, Any] | None = None
    if include_audit:
        try:
            from app.geo.audit import audit_url

            raw = await audit_url(url)
            checks = list(raw.get("checks") or [])
            failed = [c for c in checks if not c.get("passed")]
            # Top issues by severity weight
            sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            failed_sorted = sorted(
                failed,
                key=lambda c: (
                    sev_rank.get(str(c.get("severity") or "medium"), 2),
                    -int(c.get("deduction") or 0),
                ),
            )
            audit_summary = {
                "score": raw.get("score"),
                "url": raw.get("url") or url,
                "final_url": raw.get("final_url"),
                "title": raw.get("title") or title,
                "description": (raw.get("description") or "")[:300],
                "passed": sum(1 for c in checks if c.get("passed")),
                "total": len(checks),
                "failed_count": len(failed),
                "top_issues": [
                    {
                        "code": c.get("code"),
                        "title": c.get("title"),
                        "severity": c.get("severity"),
                        "recommendation": c.get("recommendation"),
                        "evidence": (c.get("evidence") or "")[:160],
                    }
                    for c in failed_sorted[:8]
                ],
                "snapshot": {
                    "schema_types": (raw.get("snapshot") or {}).get("schema_types") or [],
                    "content_units": (raw.get("snapshot") or {}).get("content_units"),
                    "ai_crawlers": (raw.get("snapshot") or {}).get("ai_crawlers"),
                    "block_issue_codes": (raw.get("snapshot") or {}).get(
                        "block_issue_codes"
                    )
                    or [],
                },
            }
            # Prefer audit title if richer
            if raw.get("title") and len(str(raw.get("title"))) > len(title or ""):
                title = str(raw["title"])
        except Exception as exc:  # noqa: BLE001
            audit_summary = {
                "score": None,
                "error": str(exc)[:300],
                "failed_count": None,
                "top_issues": [],
            }

    words = extract_words(title, text, max_words=24)
    brand = _host_brand(url)
    businesses = _business_candidates(title, words, text[:2000])
    facts = _fact_drafts(title=title, text=text, url=url, words=words, brand=brand)

    prompt_items: list[dict[str, Any]] = []
    expand_meta: dict[str, Any] = {"calls": 0, "errors": [], "skipped": not expand}
    if expand and words:
        roots = []
        for w in words[:5]:
            roots.append({"root": w, "kind": "category", "market": "cn"})
        if brand and brand not in {r["root"] for r in roots}:
            roots.insert(0, {"root": brand, "kind": "brand", "market": "cn"})
        try:
            result = await expand_candidates(
                roots=roots,
                existing_questions=existing_questions,
                max_terms=max_prompt_candidates,
                throttle_s=0.03,
            )
            expand_meta = {
                "calls": result.get("calls"),
                "errors": (result.get("errors") or [])[:5],
                "roots": result.get("roots"),
            }
            for it in result.get("items") or []:
                if it.get("in_bank"):
                    continue
                prompt_items.append(
                    {
                        "question": it.get("question") or it.get("term"),
                        "question_group": it.get("question_group") or "推荐",
                        "priority": 15 if it.get("kind") == "brand" else 10,
                        "tags": ["from_onboarding", "brand_missing", "from_expand"],
                        "term": it.get("term"),
                        "root": it.get("root"),
                        "selected": len(prompt_items) < 12,
                    }
                )
                if len(prompt_items) >= max_prompt_candidates:
                    break
        except Exception as exc:  # noqa: BLE001
            expand_meta["errors"] = [str(exc)]
            expand = False

    # Fallback templates if expand empty
    if not prompt_items and words:
        templates = [
            ("{t}哪个好", "推荐"),
            ("{t}怎么样", "品牌验证"),
            ("{t}对比怎么选", "比较"),
            ("{t}价格大概多少", "价格"),
        ]
        for w in words[:4]:
            for tpl, grp in templates:
                q = tpl.format(t=w)
                prompt_items.append(
                    {
                        "question": q,
                        "question_group": grp,
                        "priority": 10,
                        "tags": ["from_onboarding", "brand_missing"],
                        "term": w,
                        "root": w,
                        "selected": len(prompt_items) < 10,
                    }
                )

    parsed = urlparse(url if "://" in url else f"https://{url}")
    hints = [
        "请确认业务线名称是否与客户汇报口径一致",
        "意图词默认带 brand_missing，进入缺口工作台后可建任务",
        "事实卡为 needs_review/draft，核验后再用于生成母稿",
        "引擎默认模拟；真采样请在引擎配置页填写各家 Key",
    ]
    if audit_summary and audit_summary.get("score") is not None:
        score = int(audit_summary["score"])
        if score < 60:
            hints.insert(
                0,
                f"官网 GEO 体检 {score} 分偏低，优先修 top_issues 再铺内容（技术基础/可引用性）",
            )
        elif score < 80:
            hints.insert(0, f"官网 GEO 体检 {score} 分：有可优化项，见下方 failed 列表")
        else:
            hints.insert(0, f"官网 GEO 体检 {score} 分，站点基础较好，可专注意图词与内容生产")

    return {
        "source_url": url,
        "page_title": title,
        "brand_guess": brand,
        "domain": extract_cited_domain(url),
        "keywords": words,
        "businesses": businesses,
        "prompt_candidates": prompt_items,
        "fact_drafts": facts,
        "engine_suggestions": _engine_suggestions(),
        "audit": audit_summary,
        "publishing_channel": {
            "channel_type": "website",
            "name": "官网",
            "base_url": f"{parsed.scheme or 'https'}://{parsed.netloc}" if parsed.netloc else url,
            "enabled": True,
        },
        "expand": expand_meta,
        "hints": hints,
    }
