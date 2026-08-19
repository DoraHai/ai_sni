"""拓词 URL 爬取源：抓页面 → jieba 提词（自研，不调百度；流量回查在 sync 层做）。

首期只爬给定页面文本（原型推荐档），子链接 1-2 层二期再说。
单 URL 最多产出 30 个候选词（原型口径）。
"""
import ipaddress
import logging
import re
from urllib.parse import urlparse

import httpx
import jieba.analyse
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAX_WORDS_PER_URL = 30
FETCH_TIMEOUT = 15.0
MAX_CONTENT_BYTES = 2 * 1024 * 1024  # 2MB 上限，防大文件拖死
UA = "Mozilla/5.0 (compatible; SEM-Platform/1.0; +https://sem.snipers.com.cn)"

# getPvSearch 的 keywordName 上限 40 字节（中文 2 字节）→ 中文词最长 20 字
MAX_WORD_CHARS = 20

_CJK_RE = re.compile(r"[一-鿿]")
_TITLE_SPLIT_RE = re.compile(r"[丨|_\-–—,，;；/、:：>《》()（）\[\]【】]+")

# 通用词过滤（页面里高频但没有投放价值的词）
STOPWORDS = {
    "公司", "企业", "我们", "服务", "产品", "网站", "首页", "关于", "联系",
    "中国", "全国", "专业", "提供", "进行", "可以", "使用", "应用", "解决",
    "方案", "了解", "更多", "查看", "详情", "新闻", "动态", "版权", "所有",
}


class UrlFetchError(Exception):
    pass


def validate_url(url: str) -> str:
    """只允许 http/https 公网地址（基础 SSRF 防护）。返回规范化 URL。"""
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UrlFetchError(f"非法 URL（只支持 http/https）: {url}")
    host = parsed.hostname
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise UrlFetchError(f"禁止访问内网地址: {url}")
    except ValueError:
        if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
            raise UrlFetchError(f"禁止访问内网地址: {url}")
    return url


async def fetch_page_text(url: str) -> tuple[str, str]:
    """抓页面，返回 (title, 正文文本)。script/style/导航类标签剔除。"""
    url = validate_url(url)
    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT, follow_redirects=True, headers={"User-Agent": UA}
        ) as http:
            resp = await http.get(url)
    except httpx.HTTPError as e:
        raise UrlFetchError(f"抓取失败 {url}: {e}") from e
    if resp.status_code != 200:
        raise UrlFetchError(f"抓取失败 {url}: HTTP {resp.status_code}")
    content = resp.content[:MAX_CONTENT_BYTES]

    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "iframe"]):
        tag.decompose()

    title = (soup.title.get_text(strip=True) if soup.title else "") or ""
    meta_parts = []
    for name in ("keywords", "description"):
        m = soup.find("meta", attrs={"name": name})
        if m and m.get("content"):
            meta_parts.append(m["content"])
    headings = " ".join(h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"]))
    body = soup.get_text(" ", strip=True)
    # 标题/meta/小标题权重高：重复拼接放大词频
    text = " ".join([title] * 3 + meta_parts * 2 + [headings] * 2 + [body])
    return title, text


def _acceptable(word: str) -> bool:
    w = word.strip()
    if not (2 <= len(w) <= MAX_WORD_CHARS):
        return False
    if w in STOPWORDS:
        return False
    if w.isdigit():
        return False
    if _CJK_RE.search(w):
        return True
    # 纯英文/数字的产品型号词（HDPE、PVC 等）保留，但要 ≥3 位
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9\-]{2,}", w))


def extract_words(title: str, text: str, max_words: int = MAX_WORDS_PER_URL) -> list[str]:
    """jieba TF-IDF 提词 + 标题切段短语，去重保序，最多 max_words 个。"""
    phrases: list[str] = []
    for seg in _TITLE_SPLIT_RE.split(title):
        seg = re.sub(r"\s+", " ", seg).strip()
        if _CJK_RE.search(seg) and 2 <= len(seg) <= MAX_WORD_CHARS and seg not in STOPWORDS:
            phrases.append(seg)

    tags = jieba.analyse.extract_tags(text, topK=max_words * 3)
    words = [t for t in tags if _acceptable(t)]

    seen: set[str] = set()
    out: list[str] = []
    for w in phrases + words:
        key = w.lower()
        if key not in seen:
            seen.add(key)
            out.append(w)
        if len(out) >= max_words:
            break
    return out
