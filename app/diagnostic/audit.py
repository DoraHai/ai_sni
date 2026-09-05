"""安全抓取网页并执行可解释的 GEO 基础诊断。"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

MAX_HTML_BYTES = 3 * 1024 * 1024
MAX_REDIRECTS = 5
FETCH_TIMEOUT = 18.0
USER_AGENT = "Mozilla/5.0 (compatible; GrowthSniper-GEO/1.0)"
RULE_VERSION = "1.1.0"

# Keep the established score contract for callers that aggregate multi-page audits.
RULE_WEIGHTS = {
    "https": 8,
    "title": 8,
    "description": 5,
    "canonical": 4,
    "indexable": 15,
    "h1": 7,
    "heading_depth": 5,
    "substantial": 8,
    "schema": 8,
    "entity_schema": 7,
    "faq": 5,
    "citations": 7,
    "freshness": 5,
    "language": 2,
    "robots": 3,
    "llms": 3,
    "block_definition": 6,
    "block_numbers": 6,
    "block_comparison": 5,
    "block_howto": 5,
    "block_faq": 3,
    "ai_crawlers": 6,
}

RULE_CRITERIA = {
    "https": "最终访问地址必须使用 HTTPS。",
    "title": "页面必须有唯一标题，标题长度为 12–70 个字符。",
    "description": "页面必须有 Meta Description，描述长度为 40–180 个字符。",
    "canonical": "页面必须声明指向首选地址的 Canonical URL。",
    "indexable": "页面不得通过 robots meta 声明 noindex。",
    "h1": "页面必须且只能包含 1 个 H1 主标题。",
    "heading_depth": "页面至少包含 3 个可识别的 H1–H6 标题节点。",
    "substantial": "页面可读正文须达到至少 500 个中英文内容单元。",
    "schema": "页面至少包含 1 种可解析的 JSON-LD Schema 类型。",
    "entity_schema": "JSON-LD 至少包含 Organization、LocalBusiness、Corporation 或 Brand 之一。",
    "faq": "页面包含 FAQPage Schema，或至少有 2 个可识别的问答式标题。",
    "citations": "页面至少包含 2 个指向其他域名的外部证据或来源链接。",
    "freshness": "页面必须同时提供可识别的作者信息和发布日期/更新时间。",
    "language": "HTML 根元素必须声明非空的 lang 页面语言。",
    "robots": "站点根目录的 robots.txt 必须可访问且内容非空。",
    "llms": "站点根目录的 llms.txt 必须可访问且内容非空。",
    "block_definition": "正文必须包含可独立摘取的定义性内容。",
    "block_numbers": "正文必须包含至少 3 项可核验的数字事实。",
    "block_comparison": "正文必须包含可识别的对比、差异或选型内容。",
    "block_howto": "正文必须包含可识别的步骤或操作流程。",
    "block_faq": "正文必须包含 FAQ、常见问题或问答式内容。",
    "ai_crawlers": "主流 AI 爬虫不得被 robots.txt 整站拦截。",
}

# Common AI crawler user-agents to audit in robots.txt
AI_CRAWLER_AGENTS = (
    "GPTBot",
    "ChatGPT-User",
    "ClaudeBot",
    "anthropic-ai",
    "Google-Extended",
    "Bytespider",
    "CCBot",
    "PerplexityBot",
)


def parse_robots_ai_agents(robots_text: str) -> dict[str, Any]:
    """Parse robots.txt for allow/disallow of known AI crawler UAs.

    status: allowed | blocked | unspecified
    """
    text = robots_text or ""
    blocks: list[dict[str, Any]] = []
    current_uas: list[str] = []
    current_rules: list[tuple[str, str]] = []

    def flush() -> None:
        nonlocal current_uas, current_rules
        if current_uas:
            blocks.append({"uas": list(current_uas), "rules": list(current_rules)})
        current_uas = []
        current_rules = []

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key_l = key.strip().lower()
        val = val.strip()
        if key_l == "user-agent":
            if current_rules:
                flush()
            elif current_uas and not current_rules:
                # consecutive User-agent lines share rules later
                pass
            current_uas.append(val)
        elif key_l in {"disallow", "allow"}:
            if not current_uas:
                current_uas = ["*"]
            current_rules.append((key_l, val))
    flush()

    def status_for(ua: str) -> tuple[str, list[str]]:
        ua_l = ua.lower()
        matched: list[tuple[str, str]] = []
        star: list[tuple[str, str]] = []
        for block in blocks:
            uas_l = [u.lower() for u in block["uas"]]
            if ua_l in uas_l:
                matched.extend(block["rules"])
            if "*" in uas_l:
                star.extend(block["rules"])
        rules = matched if matched else star
        disallows = [path for kind, path in rules if kind == "disallow" and path]
        if any(path.strip() == "/" for path in disallows):
            return "blocked", disallows
        if matched:
            return ("blocked" if disallows else "allowed"), disallows
        return "unspecified", disallows

    agents = []
    allowed = blocked = unspecified = 0
    for ua in AI_CRAWLER_AGENTS:
        st, disallows = status_for(ua)
        agents.append({"ua": ua, "status": st, "disallows": disallows[:8]})
        if st == "allowed":
            allowed += 1
        elif st == "blocked":
            blocked += 1
        else:
            unspecified += 1
    return {
        "agents": agents,
        "allowed_count": allowed,
        "blocked_count": blocked,
        "unspecified_count": unspecified,
    }


class GeoAuditError(Exception):
    pass


@dataclass
class PageDocument:
    requested_url: str
    final_url: str
    html: str
    content_type: str


def normalize_url(value: str) -> str:
    url = value.strip()
    explicit_scheme = re.match(r"^([a-z][a-z0-9+.-]*):/{2}", url, re.I)
    if explicit_scheme and explicit_scheme.group(1).lower() not in {"http", "https"}:
        raise GeoAuditError("请输入有效的 HTTP/HTTPS 网站地址")
    if not re.match(r"^https?://", url, re.I):
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise GeoAuditError("请输入有效的 HTTP/HTTPS 网站地址")
    if parsed.username or parsed.password:
        raise GeoAuditError("网址不能包含用户名或密码")
    return url


async def _ensure_public_host(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise GeoAuditError("网址缺少主机名")
    if host.lower() == "localhost" or host.lower().endswith((".local", ".internal")):
        raise GeoAuditError("禁止诊断本机或内网地址")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise GeoAuditError(f"域名解析失败：{host}") from exc
        addresses = list({ipaddress.ip_address(info[4][0]) for info in infos})
    if not addresses or any(not address.is_global for address in addresses):
        raise GeoAuditError("禁止诊断本机、内网或保留地址")


async def safe_fetch(
    url: str, *, allow_text: bool = False, allow_xml: bool = False
) -> PageDocument:
    """逐跳校验重定向目标，阻止 SSRF，并限制响应类型和体积。"""
    current = normalize_url(url)
    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT,
        follow_redirects=False,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xml,text/xml;q=0.9,text/plain;q=0.8",
        },
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await _ensure_public_host(current)
            try:
                async with client.stream("GET", current) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise GeoAuditError("网站返回了无目标地址的重定向")
                        current = urljoin(current, location)
                        continue
                    if response.status_code >= 400:
                        raise GeoAuditError(f"网站访问失败：HTTP {response.status_code}")
                    content_type = response.headers.get("content-type", "").lower()
                    accepted = "text/html" in content_type or (
                        allow_text and "text/plain" in content_type
                    ) or (
                        allow_xml and "xml" in content_type
                    )
                    if not accepted:
                        raise GeoAuditError(f"不支持的页面类型：{content_type or '未知'}")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_HTML_BYTES:
                            raise GeoAuditError("页面超过 3MB，已停止抓取")
                        chunks.append(chunk)
                    encoding = response.encoding or "utf-8"
                    return PageDocument(
                        requested_url=url,
                        final_url=str(response.url),
                        html=b"".join(chunks).decode(encoding, errors="replace"),
                        content_type=content_type,
                    )
            except httpx.HTTPError as exc:
                raise GeoAuditError(f"网站连接失败：{exc}") from exc
    raise GeoAuditError("网站重定向次数过多")


async def _optional_text(url: str) -> tuple[bool, str]:
    try:
        document = await safe_fetch(url, allow_text=True)
        return True, document.html[:20_000]
    except GeoAuditError:
        return False, ""


def _json_ld_items(soup: BeautifulSoup) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            parsed = json.loads(node.get_text(strip=True))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            items.append(parsed)
        elif isinstance(parsed, list):
            items.extend(item for item in parsed if isinstance(item, dict))
    return items


def _schema_types(items: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    queue: list[Any] = list(items)
    while queue:
        item = queue.pop()
        if isinstance(item, dict):
            kind = item.get("@type")
            if isinstance(kind, str):
                found.add(kind)
            elif isinstance(kind, list):
                found.update(str(value) for value in kind)
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)
    return found


def _finding(
    code: str,
    title: str,
    category: str,
    severity: str,
    passed: bool,
    evidence: str,
    recommendation: str,
    deduction: int,
    automatable: bool = False,
) -> dict[str, Any]:
    weight = RULE_WEIGHTS.get(code, deduction)
    return {
        "code": code,
        "title": title,
        "criterion": RULE_CRITERIA.get(code, recommendation),
        "category": category,
        "severity": severity,
        "passed": passed,
        "evidence": evidence,
        "reason": "" if passed else f"未满足“{title}”规则：{evidence}",
        "recommendation": recommendation,
        "weight": weight,
        "deduction": 0 if passed else weight,
        "automatable": automatable,
    }


async def audit_url(url: str) -> dict[str, Any]:
    document = await safe_fetch(url)
    soup = BeautifulSoup(document.html, "html.parser")
    for node in soup(["script", "style", "noscript", "template", "svg"]):
        node.decompose()

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description_node = soup.select_one('meta[name="description" i]')
    description = (
        str(description_node.get("content", "")).strip() if description_node else ""
    )
    canonical_node = soup.select_one('link[rel~="canonical" i]')
    canonical = str(canonical_node.get("href", "")).strip() if canonical_node else ""
    h1s = [node.get_text(" ", strip=True) for node in soup.find_all("h1")]
    headings = [
        {"level": int(node.name[1]), "text": node.get_text(" ", strip=True)[:180]}
        for node in soup.find_all(re.compile(r"^h[1-6]$"))
        if node.get_text(" ", strip=True)
    ]
    body_text = soup.get_text(" ", strip=True)
    compact_text = re.sub(r"\s+", " ", body_text)
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", compact_text))
    latin_words = len(re.findall(r"\b[\w'-]+\b", compact_text))
    content_units = cjk_count + latin_words
    json_ld_items = _json_ld_items(BeautifulSoup(document.html, "html.parser"))
    schema_types = _schema_types(json_ld_items)
    external_links = {
        href
        for node in soup.select("a[href]")
        if (href := str(node.get("href", ""))).startswith(("http://", "https://"))
        and urlparse(href).hostname != urlparse(document.final_url).hostname
    }
    question_headings = [
        heading["text"]
        for heading in headings
        if re.search(
            r"[?？]$|^(什么|如何|为什么|是否|怎么|哪|谁)|^(When|What|How|Why)\b",
            heading["text"],
            re.I,
        )
    ]
    has_author = bool(
        soup.select_one('[rel="author"], [itemprop="author"], meta[name="author" i]')
    )
    has_date = bool(
        soup.select_one(
            "time[datetime], [itemprop='datePublished'], meta[property='article:published_time']"
        )
    )
    robots_url = urljoin(document.final_url, "/robots.txt")
    llms_url = urljoin(document.final_url, "/llms.txt")
    (robots_ok, robots_text), (llms_ok, llms_text) = await asyncio.gather(
        _optional_text(robots_url), _optional_text(llms_url)
    )
    robots_meta = soup.select_one('meta[name="robots" i]')
    noindex = bool(robots_meta and "noindex" in str(robots_meta.get("content", "")).lower())
    language = str(soup.html.get("lang", "")).strip() if soup.html else ""

    from app.diagnostic.extractable_blocks import block_findings, blocks_payload

    table_count = len(soup.find_all("table"))
    li_count = len(soup.find_all("li"))
    block_info = blocks_payload(
        compact_text,
        li_count=li_count,
        table_count=table_count,
        schema_types=schema_types,
    )
    block_checks = block_findings(block_info["blocks"])

    robots_ai = parse_robots_ai_agents(robots_text if robots_ok else "")
    ai_ok = robots_ok and robots_ai["blocked_count"] == 0
    ai_detail = (
        f"允许 {robots_ai['allowed_count']} · "
        f"拦截 {robots_ai['blocked_count']} · "
        f"未声明 {robots_ai['unspecified_count']}"
        if robots_ok
        else "robots.txt 不可读，无法审计 AI 爬虫 UA"
    )

    checks = [
        _finding("https", "HTTPS 安全访问", "技术基础", "high", document.final_url.startswith("https://"), document.final_url, "启用 HTTPS 并统一跳转到安全版本。", 8),
        _finding("title", "页面标题清晰完整", "页面语义", "high", 12 <= len(title) <= 70, f"当前标题：{title or '缺失'}", "补充包含品牌、主题和用户意图的唯一标题，建议 12–70 字。", 8, True),
        _finding("description", "Meta 描述可摘要", "页面语义", "medium", 40 <= len(description) <= 180, f"当前长度：{len(description)}", "编写能独立说明页面价值的 Meta Description，建议 40–180 字。", 5, True),
        _finding("canonical", "Canonical 地址明确", "技术基础", "medium", bool(canonical), canonical or "未发现 canonical", "设置指向首选页面的 canonical URL，减少实体和内容信号分散。", 4, True),
        _finding("indexable", "页面允许索引", "技术基础", "critical", not noindex, "发现 noindex" if noindex else "未发现 noindex", "如果页面需要公开获客，请移除 noindex；若为私有页面则保持现状。", 15),
        _finding("h1", "主标题结构唯一", "内容结构", "high", len(h1s) == 1, f"发现 {len(h1s)} 个 H1", "保留一个描述页面核心主题的 H1，其余标题按 H2/H3 组织。", 7, True),
        _finding("heading_depth", "内容具备分层标题", "内容结构", "medium", len(headings) >= 3, f"发现 {len(headings)} 个标题节点", "用 H2/H3 把定义、方案、证据和 FAQ 分成可独立引用的内容块。", 5, True),
        _finding("substantial", "正文信息量充足", "内容质量", "high", content_units >= 500, f"可读内容约 {content_units} 个中英文单元", "扩充事实、步骤、适用条件、案例和限制，避免只有营销口号。", 8, True),
        _finding("schema", "存在有效 JSON-LD", "结构化数据", "high", bool(schema_types), f"识别类型：{', '.join(sorted(schema_types)) or '无'}", "至少增加 Organization、WebSite 和 WebPage JSON-LD。", 8, True),
        _finding("entity_schema", "品牌实体 Schema 完整", "结构化数据", "high", bool(schema_types & {"Organization", "LocalBusiness", "Corporation", "Brand"}), f"识别类型：{', '.join(sorted(schema_types)) or '无'}", "用 Organization/Brand 描述品牌名称、官网和可验证的官方资料。", 7, True),
        _finding("faq", "包含问答式内容", "AI 可引用性", "medium", "FAQPage" in schema_types or len(question_headings) >= 2, f"问答标题 {len(question_headings)} 个", "增加真实用户问题及简洁答案；符合条件时添加 FAQPage 标记。", 5, True),
        _finding("citations", "存在外部证据或引用", "可信度", "high", len(external_links) >= 2, f"发现 {len(external_links)} 个外部来源链接", "为关键数字和结论增加权威来源、发布日期与链接。", 7),
        _finding("freshness", "作者与更新时间可识别", "可信度", "medium", has_author and has_date, f"作者：{'有' if has_author else '无'}；日期：{'有' if has_date else '无'}", "展示作者/审核人和最近更新时间，并使用结构化字段标记。", 5, True),
        _finding("language", "页面语言已声明", "技术基础", "low", bool(language), f"lang={language or '未设置'}", "在 html 元素设置准确的 lang 属性。", 2, True),
        _finding("robots", "robots.txt 可访问", "技术基础", "medium", robots_ok and bool(robots_text.strip()), robots_url, "发布 robots.txt，明确允许公开页面被合规抓取。", 3),
        _finding(
            "ai_crawlers",
            "主流 AI 爬虫未被整站拦截",
            "AI 可访问性",
            "high",
            ai_ok,
            ai_detail,
            "在 robots.txt 中为 GPTBot / ClaudeBot / Google-Extended 等声明 Allow，避免 Disallow: /。",
            6,
            True,
        ),
        _finding("llms", "提供 llms.txt 导览", "AI 可访问性", "low", llms_ok and bool(llms_text.strip()), llms_url, "生成 llms.txt，向 AI 工具提供站点定位和关键页面导览。", 3, True),
    ]
    # D2: five extractable blocks (definition / numbers / comparison / howto / FAQ)
    for item in block_checks:
        checks.append(
            _finding(
                item["code"],
                item["title"],
                item["category"],
                item["severity"],
                item["passed"],
                item["evidence"],
                item["recommendation"],
                item["deduction"],
                item.get("automatable", True),
            )
        )
    score = max(0, 100 - sum(item["deduction"] for item in checks))
    return {
        "rule_version": RULE_VERSION,
        "url": normalize_url(url),
        "final_url": document.final_url,
        "score": score,
        "title": title,
        "description": description,
        "checks": checks,
        "blocks": block_info,
        "snapshot": {
            "canonical": canonical,
            "language": language,
            "h1": h1s[:5],
            "headings": headings[:40],
            "schema_types": sorted(schema_types),
            "content_units": content_units,
            "external_link_count": len(external_links),
            "external_links": sorted(external_links)[:100],
            "question_headings": question_headings[:12],
            "robots_url": robots_url,
            "llms_url": llms_url,
            "ai_crawlers": robots_ai,
            "blocks": block_info["blocks"],
            "block_issue_codes": block_info["issue_codes"],
            "passed": sum(1 for item in checks if item["passed"]),
            "total": len(checks),
        },
    }
