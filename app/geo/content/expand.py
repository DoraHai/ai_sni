"""GEO D4 拓词候选（GeoLook expand.py 适配）。

只产候选，入库由运营显式确认。默认走百度下拉（cn）；global 走 Google suggest。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import httpx

SuggestFn = Callable[[str, str], Awaitable[list[str]]]

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)

MODS: dict[str, dict[str, list[str]]] = {
    "cn": {
        "brand": ["", " 怎么样", " 靠谱吗", " 替代", " 对比", " 价格"],
        "competitor": ["", " 怎么样", " 替代", " 对比", " 缺点"],
        "category": ["", " 推荐", " 哪个好", " 对比", " 价格"],
    },
    "global": {
        "brand": ["", " review", " alternative", " vs", " pricing"],
        "competitor": ["", " review", " alternative", " vs"],
        "category": ["", " best", " comparison", " pricing"],
    },
}

GROUP_CUES: list[tuple[str, list[str]]] = [
    ("替代", ["替代", "平替", "alternative", "instead of", "替换"]),
    ("比较", [" vs", "对比", "比较", "区别", "哪个好", "comparison", "compare", "versus"]),
    ("价格", ["价格", "多少钱", "收费", "免费", "pricing", "price", "cost", "free"]),
    ("风险", ["靠谱", "骗", "投诉", "缺点", "坑", "scam", "safe", "problem", "缺陷"]),
    ("品牌验证", ["怎么样", "评测", "测评", "好用吗", "review", "worth it"]),
    ("推荐", ["推荐", "排行", "排名", "best", "top", "哪家"]),
]

TEMPLATES: dict[str, dict[str, str]] = {
    "cn": {
        "推荐": "{t}，有值得推荐的吗？",
        "比较": "{t}，到底该怎么选？",
        "替代": "{t}，有哪些替代方案？",
        "价格": "{t}大概是什么价位？值不值？",
        "风险": "{t}，有什么要避的坑吗？",
        "品牌验证": "{t}？用过的说说实际体验。",
        "场景": "{t}，实际用起来怎么样？",
    },
    "global": {
        "推荐": "Any recommendations for {t}?",
        "比较": "How should I choose between options for {t}?",
        "替代": "What are good alternatives for {t}?",
        "价格": "Is {t} worth the price?",
        "风险": "Any pitfalls to watch out for with {t}?",
        "品牌验证": "Is {t} actually good in practice?",
        "场景": "How does {t} work in real use?",
    },
}

STOP_BIGRAMS = {
    "工具",
    "软件",
    "智能",
    "平台",
    "系统",
    "服务",
    "在线",
    "免费",
    "是什",
    "什么",
    "怎么",
    "么样",
    "怎样",
    "如何",
    "哪个",
    "哪些",
    "没有",
    "有没",
    "可以",
    "一个",
    "这个",
    "为什",
    "推荐",
    "好用",
    "用吗",
}

NAV_RX = re.compile(
    r"下载|官网|官方网站|安装|登录|注册|入口|客户端|手机版|破解|激活|会员|app\b|"
    r"download|install|login|sign ?in|sign ?up|app store",
    re.I,
)


def _bigrams(s: str) -> set[str]:
    cjk = re.findall(r"[一-鿿]{2,}", s)
    out: set[str] = set()
    for w in cjk:
        out.update(w[i : i + 2] for i in range(len(w) - 1))
    out.update(w.lower() for w in re.findall(r"[A-Za-z]{3,}", s))
    return out - STOP_BIGRAMS


def classify_term(term: str, kind: str) -> str:
    low = term.lower()
    for grp, cues in GROUP_CUES:
        if any(c in low for c in cues):
            if grp == "品牌验证" and kind == "category":
                return "推荐"
            return grp
    return "场景"


def is_relevant(term: str, root: str) -> bool:
    if NAV_RX.search(term):
        return False
    tl = term.lower().replace(" ", "")
    latin = re.findall(r"[A-Za-z]{4,}", root.lower())
    if latin:
        return any(w in tl for w in latin)
    rb = {b for b in _bigrams(root) if re.match(r"[一-鿿]", b)}
    if not rb:
        return False
    tb = _bigrams(term)
    return len(rb & tb) * 2 >= len(rb)


def to_question(term: str, *, group: str, market: str) -> str:
    st = (term or "").strip()
    mk = "global" if market == "global" else "cn"
    if re.search(r"[？?]$", st):
        return st
    if re.search(
        r"是什么|怎么|如何|哪个|哪些|多少钱|吗$|^how |^what |^which |^is |^can ",
        st,
        re.I,
    ):
        return st + ("？" if mk == "cn" else "?")
    tmpl = TEMPLATES[mk].get(group) or TEMPLATES[mk]["场景"]
    return tmpl.format(t=st)


def build_roots(
    *,
    brand_names: list[str] | None = None,
    industry: str | None = None,
    competitors: list[str] | None = None,
    products: list[str] | None = None,
    market: str = "cn",
    explicit_roots: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """词根 = 显式 roots 或 品牌/竞品/品类。上限 14。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(root: str | None, kind: str, mk: str) -> None:
        r = (root or "").strip()
        if len(r) < 2 or r.lower() in seen:
            return
        seen.add(r.lower())
        out.append({"root": r, "kind": kind, "market": mk})

    for item in explicit_roots or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "category")
        if kind not in {"brand", "competitor", "category"}:
            kind = "category"
        mk = str(item.get("market") or market or "cn")
        if mk not in {"cn", "global", "both"}:
            mk = "cn"
        add(str(item.get("root") or ""), kind, mk)

    if not out:
        mk = market if market in {"cn", "global", "both"} else "cn"
        names = [n for n in (brand_names or []) if str(n).strip()]
        if names:
            add(names[0], "brand", mk)
            for al in names[1:3]:
                add(al, "brand", mk)
        for c in (competitors or [])[:6]:
            add(c, "competitor", mk)
        add(industry, "category", mk)
        for p in (products or [])[:4]:
            add(p, "category", mk)

    return out[:14]


async def suggest_baidu(query: str, *, timeout: float = 6.0) -> list[str]:
    url = f"https://suggestion.baidu.com/su?wd={quote(query)}&ie=utf-8&oe=utf-8"
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": UA}) as client:
        r = await client.get(url)
        r.raise_for_status()
        m = re.search(r"s:(\[.*?\])", r.text)
        return json.loads(m.group(1)) if m else []


async def suggest_google(
    query: str, *, hl: str = "en", timeout: float = 6.0
) -> list[str]:
    url = (
        "https://suggestqueries.google.com/complete/search"
        f"?client=firefox&hl={hl}&q={quote(query)}"
    )
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": UA}) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
        return [s for s in (data[1] if len(data) > 1 else []) if isinstance(s, str)]


async def default_suggest(query: str, market: str) -> list[str]:
    if market == "global":
        return await suggest_google(query)
    return await suggest_baidu(query)


async def expand_candidates(
    *,
    roots: list[dict[str, str]],
    existing_questions: set[str] | None = None,
    suggest: SuggestFn | None = None,
    max_terms: int = 200,
    max_per_root: int = 25,
    throttle_s: float = 0.05,
) -> dict[str, Any]:
    """Run suggest × mods → classify → template questions. Never writes prompts."""
    suggest_fn = suggest or default_suggest
    existing = {q.strip().lower() for q in (existing_questions or set()) if q}
    seen: set[str] = set()
    terms: list[dict[str, Any]] = []
    root_n: dict[str, int] = {r["root"]: 0 for r in roots}
    n_calls = 0
    errors: list[str] = []

    for r in roots:
        base_mk = r.get("market") or "cn"
        markets = ["cn", "global"] if base_mk == "both" else [base_mk]
        kind = r.get("kind") or "category"
        for mk in markets:
            mods = MODS.get(mk, MODS["cn"]).get(kind, MODS["cn"]["category"])
            for mod in mods:
                if len(terms) >= max_terms:
                    break
                q = r["root"] + mod
                sugs: list[str] | None = None
                last_err = ""
                for _ in range(2):
                    try:
                        sugs = await suggest_fn(q, mk)
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_err = f"{type(exc).__name__}: {exc}"
                        await asyncio.sleep(0.2)
                if sugs is None:
                    errors.append(f"{q}: {last_err}")
                    continue
                n_calls += 1
                if throttle_s > 0:
                    await asyncio.sleep(throttle_s)
                source = "google" if mk == "global" else "baidu"
                for s in sugs[:10]:
                    key = s.strip().lower()
                    if not key or key == r["root"].lower() or key in seen:
                        continue
                    if not is_relevant(s, r["root"]):
                        continue
                    if root_n[r["root"]] >= max_per_root or len(terms) >= max_terms:
                        continue
                    root_n[r["root"]] += 1
                    seen.add(key)
                    grp = classify_term(s, kind)
                    st = s.strip()
                    qtext = to_question(st, group=grp, market=mk)
                    terms.append(
                        {
                            "term": st,
                            "root": r["root"],
                            "kind": kind,
                            "market": mk,
                            "question_group": grp,
                            "question": qtext,
                            "suggest_source": source,
                            "in_bank": qtext.strip().lower() in existing
                            or st.lower() in existing,
                        }
                    )

    return {
        "roots": roots,
        "calls": n_calls,
        "items": terms,
        "total": len(terms),
        "new_count": sum(1 for t in terms if not t["in_bank"]),
        "errors": errors[:12],
    }
