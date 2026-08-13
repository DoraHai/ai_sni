"""GEO 开户向导：官网 URL → 业务线 / 意图词 / 事实卡草稿。

复用 fetch_page_text、expand_candidates；只产草稿，apply 时由运营确认写入。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.geo.content.expand import expand_candidates
from app.geo.content.prompt_taxonomy import resolve_is_brand_probe
from app.geo.content.snapshots import extract_cited_domain
from app.urlwords import UrlFetchError, extract_words, fetch_page_text, validate_url

# 业务线启发：标题/H 中的产品短语
_BIZ_SPLIT = re.compile(r"[|｜/\-—·,，、;；\s\[\]【】]+")
_SENT_SPLIT = re.compile(r"[。！？!?\n]+")

_WEAK_ROOTS = {
    "官网",
    "首页",
    "网站",
    "公司",
    "企业",
    "我们",
    "服务",
    "产品",
    "智能",
    "场景",
    "客户",
    "渠道",
    "平台",
    "系统",
    "方案",
    "联系",
    "国际化",
    "数字化",
    "信息化",
}
_LATIN_WEAK_ROOTS = {"agent", "agents", "ai", "app", "web", "www"}

# 标题含这些产品信号时，补不带品牌的品类根（否则拓词全是「智齿科技怎么样」）
_CATEGORY_SEEDS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"客服|呼叫中心|联络"), ["智能客服", "在线客服", "呼叫中心"]),
    (re.compile(r"工单"), ["工单系统"]),
    (re.compile(r"泵|离心"), ["工业泵", "离心泵"]),
]

_VIS_TEMPLATES: list[tuple[str, str]] = [
    ("{t}哪个好", "推荐"),
    ("{t}对比怎么选", "比较"),
    ("{t}怎么选", "推荐"),
    ("{t}价格大概多少", "价格"),
]
_PROBE_TEMPLATES: list[tuple[str, str]] = [
    ("{t}怎么样", "品牌验证"),
    ("{t}是哪家公司", "品牌验证"),
]


def _usable_category_root(word: str, pool: list[str]) -> bool:
    r = (word or "").strip()
    if not (2 <= len(r) <= 16):
        return False
    if r in _WEAK_ROOTS or r.lower() in _LATIN_WEAK_ROOTS:
        return False
    if re.search(r"官网|首页|welcome|home", r, re.I):
        return False
    if re.match(r"^(的|了|着|过|和|与|及|驱动)", r):
        return False
    # 两字根已被更长短语覆盖时丢掉（智齿 ⊂ 智齿客服）
    if len(r) <= 2 and any(r != other and r in other for other in pool):
        return False
    return True


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


def match_prompt_business(
    question: str,
    business_names: list[str],
    explicit: str | None = None,
) -> str | None:
    """把意图词挂到名称出现在问句里的业务；跳过 AI 这类碎片名。"""
    names = [str(n).strip() for n in business_names if str(n).strip()]
    if not names:
        return None

    def usable(n: str) -> bool:
        if n in _WEAK_ROOTS or n.lower() in _LATIN_WEAK_ROOTS:
            return False
        return not re.fullmatch(r"[A-Za-z]{1,4}", n)

    q = question or ""
    for n in sorted(names, key=len, reverse=True):
        if usable(n) and n in q:
            return n
    if explicit and explicit in names and usable(explicit):
        return explicit
    for n in names:
        if usable(n):
            return n
    return names[0]


def website_channel_name(existing_names: set[str] | list[str], domain: str | None = None) -> str:
    """同一租户渠道名唯一：已有「官网」则用「官网 · 域名」。"""
    taken = {str(n).strip() for n in existing_names if n}
    if "官网" not in taken:
        return "官网"
    if domain:
        alt = f"官网 · {domain}"
        if alt not in taken:
            return alt
        n = 2
        while f"{alt} ({n})" in taken:
            n += 1
        return f"{alt} ({n})"
    n = 2
    while f"官网 {n}" in taken:
        n += 1
    return f"官网 {n}"


def _title_brand(title: str) -> str | None:
    """标题里的中文品牌段；不用 ASCII 域名（zhichi 会被百度扩成拼音噪声）。"""
    for seg in _BIZ_SPLIT.split(title or ""):
        s = re.sub(r"\s+", " ", (seg or "").strip())
        if not (2 <= len(s) <= 16):
            continue
        if not re.search(r"[一-鿿]{2,}", s):
            continue
        if re.search(r"官网|首页|welcome|home", s, re.I):
            continue
        return s
    return None


def brand_tokens_for_onboarding(
    title: str,
    url: str = "",
    extra: list[str] | None = None,
) -> list[str]:
    """品牌全称 + 二字简称，用来识别探测题、避开品类根。"""
    out: list[str] = []

    def add(raw: str | None) -> None:
        t = (raw or "").strip()
        if len(t) < 2:
            return
        if t.lower() in {x.lower() for x in out}:
            return
        out.append(t)

    add(_title_brand(title))
    host = _host_brand(url)
    if host and re.search(r"[一-鿿]", host):
        add(host)
    for item in extra or []:
        add(item)
    for token in list(out):
        cjk = "".join(re.findall(r"[一-鿿]", token))
        if len(cjk) >= 4:
            add(cjk[:2])
    return out


def contains_brand(text: str, brand_tokens: list[str]) -> bool:
    blob = text or ""
    return any(t and t in blob for t in brand_tokens)


def category_seed_roots(title: str, words: list[str]) -> list[str]:
    blob = f"{title} {' '.join(words)}"
    seeds: list[str] = []
    for rx, extras in _CATEGORY_SEEDS:
        if rx.search(blob):
            for s in extras:
                if s not in seeds:
                    seeds.append(s)
    return seeds


def onboarding_expand_roots(
    words: list[str],
    *,
    title: str = "",
    url: str = "",
) -> list[dict[str, str]]:
    """品类根不带品牌（测可见度）；品牌根单独保留（探测题）。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    title_segs = [
        re.sub(r"\s+", " ", (seg or "").strip())
        for seg in _BIZ_SPLIT.split(title or "")
        if (seg or "").strip()
    ]
    pool = title_segs + list(words)
    tokens = brand_tokens_for_onboarding(title, url)

    def add(root: str | None, kind: str) -> None:
        r = (root or "").strip()
        if len(r) < 2 or r.lower() in seen:
            return
        if kind == "category":
            if contains_brand(r, tokens):
                return
            if not _usable_category_root(r, pool):
                return
        seen.add(r.lower())
        out.append({"root": r, "kind": kind, "market": "cn"})

    brand = _title_brand(title)
    add(brand, "brand")
    for seed in category_seed_roots(title, words):
        add(seed, "category")
    for seg in title_segs:
        if brand and seg == brand:
            continue
        add(seg, "category")
    for w in words:
        add(w, "category")
        if sum(1 for r in out if r["kind"] == "category") >= 6:
            break
    long_cjk = [
        r
        for r in out
        if r["kind"] == "category" and len(re.findall(r"[一-鿿]", r["root"])) >= 3
    ]
    if len(long_cjk) >= 2:
        out[:] = [
            r
            for r in out
            if not (
                r["kind"] == "category"
                and (
                    re.fullmatch(r"[一-鿿]{1,2}", r["root"])
                    or re.fullmatch(r"[A-Za-z][A-Za-z0-9\-]*", r["root"])
                )
            )
        ]
    if not out:
        host = _host_brand(url)
        if host and re.search(r"[一-鿿]", host):
            add(host, "brand")
    return out


def finalize_onboarding_prompts(
    expand_items: list[dict[str, Any]],
    *,
    words: list[str],
    title: str,
    url: str,
    max_items: int = 24,
    existing_questions: set[str] | None = None,
) -> list[dict[str, Any]]:
    """扩词结果 + 模板：品类可见度优先，带品牌的标探测题。"""
    tokens = brand_tokens_for_onboarding(title, url)
    existing = {q.strip().lower() for q in (existing_questions or set()) if q}
    seen: set[str] = set(existing)
    vis: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []

    def push(question: str, group: str, *, term: str, root: str, kind: str) -> None:
        q = (question or "").strip()
        key = q.lower()
        if len(q) < 4 or key in seen:
            return
        probe = resolve_is_brand_probe(
            question=q,
            brand_names=tokens,
            question_group=group,
        )
        item = {
            "question": q,
            "question_group": group or "推荐",
            "priority": 8 if probe else 14,
            "tags": ["from_onboarding", "from_expand"]
            + (["brand_probe"] if probe else ["brand_missing"]),
            "term": term,
            "root": root,
            "kind": kind,
            "is_brand_probe": probe,
        }
        seen.add(key)
        (probes if probe else vis).append(item)

    for it in expand_items:
        if it.get("in_bank"):
            continue
        push(
            str(it.get("question") or it.get("term") or ""),
            str(it.get("question_group") or "推荐"),
            term=str(it.get("term") or ""),
            root=str(it.get("root") or ""),
            kind=str(it.get("kind") or "category"),
        )

    cat_roots = [
        r["root"]
        for r in onboarding_expand_roots(words, title=title, url=url)
        if r["kind"] == "category"
    ]
    for w in cat_roots[:4]:
        for tpl, grp in _VIS_TEMPLATES:
            push(tpl.format(t=w), grp, term=w, root=w, kind="category")
    brand = tokens[0] if tokens else ""
    if brand:
        for tpl, grp in _PROBE_TEMPLATES:
            push(tpl.format(t=brand), grp, term=brand, root=brand, kind="brand")

    # 先品类（默认勾选最多 8），再少量探测题（最多 2）
    picked = vis[: max(8, max_items - 4)] + probes[:4]
    picked = picked[:max_items]
    vis_sel = 0
    probe_sel = 0
    for item in picked:
        if item["is_brand_probe"]:
            item["selected"] = probe_sel < 2
            if item["selected"]:
                probe_sel += 1
        else:
            item["selected"] = vis_sel < 8
            if item["selected"]:
                vis_sel += 1
    return picked


def _business_candidates(title: str, words: list[str], headings_blob: str) -> list[dict[str, Any]]:
    """Suggest 1–4 business lines from page title/words."""
    cands: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(name: str, reason: str) -> None:
        n = re.sub(r"\s+", " ", (name or "").strip())[:80]
        if len(n) < 2:
            return
        if n in _WEAK_ROOTS or n.lower() in _LATIN_WEAK_ROOTS:
            return
        if re.fullmatch(r"[A-Za-z]{1,4}", n):
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
        roots = onboarding_expand_roots(words, title=title, url=url)
        context_tokens = list(words)
        for b in businesses:
            nm = str(b.get("name") or "").strip()
            if nm:
                context_tokens.append(nm)
        try:
            result = await expand_candidates(
                roots=roots,
                existing_questions=existing_questions,
                max_terms=max_prompt_candidates,
                max_per_root=8,
                throttle_s=0.03,
                context_tokens=context_tokens,
            )
            expand_meta = {
                "calls": result.get("calls"),
                "errors": (result.get("errors") or [])[:5],
                "roots": result.get("roots"),
            }
            prompt_items = finalize_onboarding_prompts(
                list(result.get("items") or []),
                words=words,
                title=title,
                url=url,
                max_items=max_prompt_candidates,
                existing_questions=existing_questions,
            )
        except Exception as exc:  # noqa: BLE001
            expand_meta["errors"] = [str(exc)]
            expand = False

    if not prompt_items:
        prompt_items = finalize_onboarding_prompts(
            [],
            words=words,
            title=title,
            url=url,
            max_items=max_prompt_candidates,
            existing_questions=existing_questions,
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
        "brand_guess": _title_brand(title) or brand,
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


def _check(key: str, ok: bool, title: str, hint: str, href: str) -> dict[str, Any]:
    return {"key": key, "ok": bool(ok), "title": title, "hint": hint, "href": href}


def build_readiness_items(
    *,
    has_brand_terms: bool,
    business_count: int,
    prompt_count: int,
    fact_count: int,
    verified_fact_count: int,
    engine_count: int,
    real_engine_count: int,
    ai_key_configured: bool,
    patrol_enabled: bool,
    channel_count: int,
    stance: str = "hybrid",
) -> dict[str, Any]:
    """开户完成后「还差什么」检查表（纯函数，便于单测）。"""
    items = [
        _check(
            "brand_terms",
            has_brand_terms,
            "品牌词",
            "已填写" if has_brand_terms else "提及率依赖品牌词，请在客户资料补上",
            "/geo/onboarding",
        ),
        _check(
            "businesses",
            business_count > 0,
            "优化业务",
            f"已建 {business_count} 条" if business_count else "还没有业务线，向导写入或手动新建",
            "/geo/businesses",
        ),
        _check(
            "prompts",
            prompt_count > 0,
            "意图词",
            f"已建 {prompt_count} 条" if prompt_count else "没有意图词就无法巡检和写稿",
            "/geo/prompts",
        ),
        _check(
            "facts",
            verified_fact_count >= 3 or fact_count >= 3,
            "事实卡",
            (
                f"已核验 {verified_fact_count} / 共 {fact_count}"
                if fact_count
                else "生成母稿至少需要 3 条已核验事实"
            ),
            "/geo/facts",
        ),
        _check(
            "engines",
            engine_count > 0,
            "监测引擎",
            f"已启用 {engine_count} 个" if engine_count else "还没配引擎，巡检无处可跑",
            "/geo/engines",
        ),
        _check(
            "engine_keys",
            real_engine_count > 0 or stance == "simulation",
            "引擎真采样 Key",
            (
                f"{real_engine_count} 个引擎已配 Key"
                if real_engine_count
                else (
                    "当前是模拟评估，交付须标注"
                    if stance == "simulation"
                    else "hybrid 下无 Key 的引擎会走模拟，客户报表会被标「含模拟」"
                )
            ),
            "/geo/engines",
        ),
        _check(
            "ai_key",
            ai_key_configured,
            "AI 能力 Key",
            "已配置" if ai_key_configured else "写稿 / 审稿 / 探测需要租户 LLM Key",
            "/geo/ai-settings",
        ),
        _check(
            "patrol",
            patrol_enabled,
            "定时巡检",
            "已打开" if patrol_enabled else "打开后才会按窗口自动采样",
            "/geo/visibility/patrol",
        ),
        _check(
            "channel",
            channel_count > 0,
            "发布渠道",
            f"已配 {channel_count} 条" if channel_count else "至少配一条官网/文档渠道才能回填 URL",
            "/geo/publishing",
        ),
    ]
    ready = sum(1 for i in items if i["ok"])
    blocking = [i["key"] for i in items if not i["ok"] and i["key"] in {"businesses", "prompts"}]
    return {
        "items": items,
        "ready_count": ready,
        "total": len(items),
        "ready": ready == len(items),
        "blocking": blocking,
        "stance": stance,
    }


async def tenant_readiness(session: Any, tenant_id: int) -> dict[str, Any]:
    """查库组装开户就绪检查表。"""
    from sqlalchemy import func, select

    from app.geo.content.ai_settings import get_ai_setting_row, settings_public_payload
    from app.geo.content.monitoring_stance import normalize_stance
    from app.models import (
        GeoFact,
        GeoOptimizationBusiness,
        GeoPrompt,
        GeoPublishingChannel,
        GeoTrackingEngine,
        GeoVisibilityPatrolSettings,
        Tenant,
    )

    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        return {
            "tenant_id": tenant_id,
            "items": [],
            "ready_count": 0,
            "total": 0,
            "ready": False,
            "blocking": ["tenant"],
            "error": "客户不存在",
        }

    biz_n = int(
        await session.scalar(
            select(func.count())
            .select_from(GeoOptimizationBusiness)
            .where(
                GeoOptimizationBusiness.tenant_id == tenant_id,
                GeoOptimizationBusiness.status == "active",
            )
        )
        or 0
    )
    prompt_n = int(
        await session.scalar(
            select(func.count())
            .select_from(GeoPrompt)
            .where(GeoPrompt.tenant_id == tenant_id, GeoPrompt.status == "active")
        )
        or 0
    )
    fact_n = int(
        await session.scalar(
            select(func.count())
            .select_from(GeoFact)
            .where(GeoFact.tenant_id == tenant_id, GeoFact.status == "active")
        )
        or 0
    )
    verified_n = int(
        await session.scalar(
            select(func.count())
            .select_from(GeoFact)
            .where(
                GeoFact.tenant_id == tenant_id,
                GeoFact.status == "active",
                GeoFact.trust_level == "verified",
            )
        )
        or 0
    )
    engines = list(
        await session.scalars(
            select(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id == tenant_id)
        )
    )
    enabled = [e for e in engines if e.enabled]
    real = [
        e
        for e in enabled
        if (e.sample_mode or "") == "openai_compat" and bool(e.api_key_encrypted)
    ]
    setting = await get_ai_setting_row(session, tenant_id)
    ai_pub = settings_public_payload(setting) if setting is not None else {}
    patrol = await session.get(GeoVisibilityPatrolSettings, tenant_id)
    ch_n = int(
        await session.scalar(
            select(func.count())
            .select_from(GeoPublishingChannel)
            .where(
                GeoPublishingChannel.tenant_id == tenant_id,
                GeoPublishingChannel.enabled.is_(True),
            )
        )
        or 0
    )
    stance = normalize_stance(getattr(setting, "monitoring_stance", None) if setting else None)
    payload = build_readiness_items(
        has_brand_terms=bool(tenant.brand_terms),
        business_count=biz_n,
        prompt_count=prompt_n,
        fact_count=fact_n,
        verified_fact_count=verified_n,
        engine_count=len(enabled),
        real_engine_count=len(real),
        ai_key_configured=bool(ai_pub.get("api_key_configured")),
        patrol_enabled=bool(patrol and patrol.enabled),
        channel_count=ch_n,
        stance=stance,
    )
    payload["tenant_id"] = tenant_id
    payload["tenant_name"] = tenant.name
    return payload
