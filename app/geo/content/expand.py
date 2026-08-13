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

# 泛公司词：不能当作「和本业相关」的上下文针
_GENERIC_CTX = STOP_BIGRAMS | {"科技", "公司", "股份", "集团", "有限", "企业"}

NAV_RX = re.compile(
    r"下载|官网|官方网站|安装|登录|注册|入口|客户端|手机版|破解|激活|会员|app\b|"
    r"download|install|login|sign ?in|sign ?up|app store",
    re.I,
)

# 与官网业务无关的下拉噪声。若页面上下文本身就含该主题则放行。
_OFFTOPIC_GROUPS: list[re.Pattern[str]] = [
    re.compile(r"招聘|校招|社招|简历|入职|外包公司"),
    re.compile(r"股票|股价|上市|概念股|股票代码"),
    re.compile(r"拼音|输入法|怎么读|如何读|读音"),
    re.compile(r"牙膏|牙科|拔牙|补牙|口腔医院|智齿痛|智齿炎|阻生智齿"),
]

_INTENT_FRAGMENT_RX = re.compile(
    r"怎么样|好用吗|好用|靠谱吗|靠谱|评测|测评|推荐|对比|比较|区别|"
    r"替代|价格|多少钱|哪个好|排行榜?|收费|免费|坑|缺点|值不值|值得买"
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


def _context_blob(context_tokens: list[str] | None) -> str:
    return " ".join(t.strip() for t in (context_tokens or []) if t and str(t).strip())


def _offtopic_without_context(term: str, context_blob: str) -> bool:
    for rx in _OFFTOPIC_GROUPS:
        if rx.search(term) and not rx.search(context_blob):
            return True
    return False


def _latin_glued_junk(term: str, root: str) -> bool:
    """zhichi → zhichiq：域名根词被百度补成无空格拉丁碎片。"""
    root_l = "".join(re.findall(r"[a-z]", root.lower()))
    if len(root_l) < 4:
        return False
    if re.search(r"[一-鿿]", term) or " " in term or "-" in term:
        return False
    term_l = "".join(re.findall(r"[a-z]", term.lower()))
    if not term_l.startswith(root_l) or term_l == root_l:
        return False
    extra = term_l[len(root_l) :]
    return 1 <= len(extra) <= 8


def _strict_relevance(root: str, kind: str) -> bool:
    """品牌词、两字中文根、纯拉丁根歧义多，需意图修饰或业务上下文。"""
    if kind == "brand":
        return True
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9\-]{2,}", root or ""):
        return True
    cjk_n = len(re.findall(r"[一-鿿]", root))
    return cjk_n == 2 and len(root) <= 4


def _context_needles(context_tokens: list[str] | None, root: str) -> set[str]:
    needles: set[str] = set()
    for raw in context_tokens or []:
        tok = str(raw or "").strip()
        if len(tok) < 2:
            continue
        needles.add(tok.lower())
        cjk = "".join(re.findall(r"[一-鿿]", tok))
        for n in (2, 3, 4):
            for i in range(0, max(0, len(cjk) - n + 1)):
                needles.add(cjk[i : i + n])
    root_l = (root or "").lower()
    out: set[str] = set()
    for n in needles:
        if n in _GENERIC_CTX or n == root_l or n in root_l or root_l in n:
            continue
        if len(n) >= 2:
            out.add(n)
    return out


def _intent_or_context(term: str, root: str, context_tokens: list[str] | None) -> bool:
    tl = term.lower().replace(" ", "")
    rl = root.lower().replace(" ", "")
    rem = tl.replace(rl, "", 1) if rl and rl in tl else tl
    rem = re.sub(r"[的了吗呢啊呀？?，,。.、\s]", "", rem)
    if not rem or _INTENT_FRAGMENT_RX.fullmatch(rem):
        return True
    if _INTENT_FRAGMENT_RX.sub("", rem) == "":
        return True
    low = term.lower()
    return any(n in low for n in _context_needles(context_tokens, root))


def is_relevant(
    term: str,
    root: str,
    *,
    kind: str = "category",
    context_tokens: list[str] | None = None,
) -> bool:
    if NAV_RX.search(term):
        return False
    blob = _context_blob(context_tokens)
    if _offtopic_without_context(term, blob):
        return False
    if _latin_glued_junk(term, root):
        return False
    tl = term.lower().replace(" ", "")
    latin = re.findall(r"[A-Za-z]{4,}", root.lower())
    if latin:
        if not any(w in tl for w in latin):
            return False
    else:
        rb = {b for b in _bigrams(root) if re.match(r"[一-鿿]", b)}
        if not rb:
            return False
        tb = _bigrams(term)
        if len(rb & tb) * 2 < len(rb):
            return False
    if _strict_relevance(root, kind):
        return _intent_or_context(term, root, context_tokens)
    return True


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
        # 品类/产品优先：品牌短词（智齿、泉衡）的下拉同音噪声多，后扩以免占满配额
        add(industry, "category", mk)
        for p in (products or [])[:4]:
            add(p, "category", mk)
        names = [n for n in (brand_names or []) if str(n).strip()]
        if names:
            add(names[0], "brand", mk)
            for al in names[1:3]:
                add(al, "brand", mk)
        for c in (competitors or [])[:6]:
            add(c, "competitor", mk)

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


def _expand_jobs(roots: list[dict[str, str]]) -> list[tuple[dict[str, str], str, str, str]]:
    """(root, market, kind, query) 按修饰词下标轮询，避免首个品牌根占满配额。"""
    prepared: list[tuple[dict[str, str], str, str, list[str]]] = []
    for r in roots:
        kind = r.get("kind") or "category"
        base_mk = r.get("market") or "cn"
        markets = ["cn", "global"] if base_mk == "both" else [base_mk]
        for mk in markets:
            mods = MODS.get(mk, MODS["cn"]).get(kind, MODS["cn"]["category"])
            prepared.append((r, mk, kind, mods))
    max_len = max((len(mods) for *_, mods in prepared), default=0)
    jobs: list[tuple[dict[str, str], str, str, str]] = []
    for i in range(max_len):
        for r, mk, kind, mods in prepared:
            if i < len(mods):
                jobs.append((r, mk, kind, r["root"] + mods[i]))
    return jobs


async def expand_candidates(
    *,
    roots: list[dict[str, str]],
    existing_questions: set[str] | None = None,
    suggest: SuggestFn | None = None,
    max_terms: int = 200,
    max_per_root: int = 25,
    throttle_s: float = 0.05,
    context_tokens: list[str] | None = None,
) -> dict[str, Any]:
    """Run suggest × mods → classify → template questions. Never writes prompts."""
    suggest_fn = suggest or default_suggest
    existing = {q.strip().lower() for q in (existing_questions or set()) if q}
    ctx = [str(t).strip() for t in (context_tokens or []) if t and str(t).strip()]
    seen: set[str] = set()
    terms: list[dict[str, Any]] = []
    root_n: dict[str, int] = {r["root"]: 0 for r in roots}
    n_calls = 0
    errors: list[str] = []

    for r, mk, kind, q in _expand_jobs(roots):
        if len(terms) >= max_terms:
            break
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
            if not is_relevant(s, r["root"], kind=kind, context_tokens=ctx):
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


def candidate_term_key(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    return str(item.get("term") or item.get("question") or "").strip().lower()


def annotate_vs_last_run(
    items: list[dict[str, Any]],
    previous_keys: set[str] | None,
) -> dict[str, Any]:
    """Attach vs_last_run badges. No previous run → leave field null."""
    prev = previous_keys if previous_keys is not None else None
    annotated: list[dict[str, Any]] = []
    new_vs_last = 0
    for raw in items:
        item = dict(raw)
        key = candidate_term_key(item)
        if prev is None:
            item["vs_last_run"] = None
        elif key and key not in prev:
            item["vs_last_run"] = "new"
            new_vs_last += 1
        else:
            item["vs_last_run"] = "still"
        annotated.append(item)
    return {
        "items": annotated,
        "new_vs_last_count": new_vs_last if prev is not None else None,
    }
