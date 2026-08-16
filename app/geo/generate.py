"""从诊断结果生成整改建议和基础 GEO 资产。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def deterministic_advice(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed = sorted(
        (item for item in findings if not item.get("passed")),
        key=lambda item: (PRIORITY_ORDER.get(item.get("severity"), 9), -item.get("deduction", 0)),
    )
    return [
        {
            "code": item["code"],
            "priority": item["severity"],
            "title": item["title"],
            "action": item["recommendation"],
            "expected_impact": "修复该项后可提升页面的机器可读性、可信度或被引用概率。",
            "acceptance": f"重新诊断后“{item['title']}”检查通过。",
        }
        for item in failed[:8]
    ]


async def ai_advice(
    *,
    tenant_name: str,
    url: str,
    score: int,
    title: str,
    description: str,
    findings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    # 延迟导入，纯规则与资产生成不应依赖应用数据库配置。
    from app.ai.deepseek import DeepSeekError, chat_json, is_enabled

    fallback = deterministic_advice(findings)
    if not is_enabled():
        return fallback, "rules"
    problems = [
        {
            "code": item["code"],
            "severity": item["severity"],
            "title": item["title"],
            "evidence": item["evidence"],
            "recommendation": item["recommendation"],
        }
        for item in findings
        if not item.get("passed")
    ]
    system = """你是严谨的 GEO（生成式引擎优化）顾问。根据规则诊断给出可执行整改项。
只返回 JSON 对象：{"recommendations":[...]}。每项必须包含 code、priority、title、action、
expected_impact、acceptance。不得承诺排名或模型收录，不得捏造网站事实，最多 8 项。"""
    user = (
        f"客户：{tenant_name}\n网址：{url}\n得分：{score}\n"
        f"标题：{title}\n描述：{description}\n问题：{problems}"
    )
    try:
        result = await chat_json(system, user, timeout=45)
        rows = result.get("recommendations") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            return fallback, "rules"
        clean = []
        valid_codes = {item["code"] for item in problems}
        for row in rows[:8]:
            if not isinstance(row, dict) or row.get("code") not in valid_codes:
                continue
            clean.append(
                {
                    "code": row["code"],
                    "priority": str(row.get("priority") or "medium"),
                    "title": str(row.get("title") or "整改建议"),
                    "action": str(row.get("action") or ""),
                    "expected_impact": str(row.get("expected_impact") or ""),
                    "acceptance": str(row.get("acceptance") or ""),
                }
            )
        return (clean or fallback), ("ai" if clean else "rules")
    except DeepSeekError:
        return fallback, "rules"


def generate_json_ld(
    *, tenant_name: str, url: str, title: str, description: str
) -> dict[str, Any]:
    origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    page_title = title or tenant_name
    page_description = description or f"{tenant_name}官方网站与业务信息。"
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"{origin}/#organization",
                "name": tenant_name,
                "url": origin,
            },
            {
                "@type": "WebSite",
                "@id": f"{origin}/#website",
                "url": origin,
                "name": tenant_name,
                "publisher": {"@id": f"{origin}/#organization"},
                "inLanguage": "zh-CN",
            },
            {
                "@type": "WebPage",
                "@id": f"{url}#webpage",
                "url": url,
                "name": page_title,
                "description": page_description,
                "isPartOf": {"@id": f"{origin}/#website"},
                "about": {"@id": f"{origin}/#organization"},
                "inLanguage": "zh-CN",
            },
        ],
    }


def generate_llms_text(
    *,
    tenant_name: str,
    url: str,
    title: str,
    description: str,
    snapshot: dict[str, Any],
) -> str:
    headings = [
        item.get("text", "").strip()
        for item in snapshot.get("headings", [])
        if item.get("level") in {1, 2} and item.get("text")
    ][:8]
    lines = [
        f"# {tenant_name}",
        "",
        f"> {description or title or f'{tenant_name}官方网站'}",
        "",
        "## Official site",
        "",
        f"- [{title or tenant_name}]({url}): 官方页面。",
    ]
    if headings:
        lines += ["", "## Page topics", ""]
        lines.extend(f"- {heading}" for heading in headings)
    lines += [
        "",
        "## Usage",
        "",
        "- 优先引用上述官方页面中的最新事实、产品说明和联系方式。",
        "- 涉及价格、参数、资质或时效信息时，请回到官方页面核验。",
        "",
    ]
    return "\n".join(lines)
