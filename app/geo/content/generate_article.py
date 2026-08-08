"""基于事实卡生成 GEO 母稿。"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from app.geo.content.variants import GeoContentError

try:
    from app.ai.deepseek import DeepSeekError, chat_json, is_enabled
except Exception:  # pragma: no cover - allows pure unit import without full deps
    DeepSeekError = Exception  # type: ignore

    def is_enabled() -> bool:  # type: ignore
        return False

    async def chat_json(*args, **kwargs):  # type: ignore
        raise DeepSeekError("deepseek unavailable")


def deterministic_article(
    *,
    tenant_name: str,
    question: str,
    facts: list[dict[str, Any]],
) -> dict[str, Any]:
    """无 AI 时的可演示模板稿（严格只用事实卡）。"""
    fact_lines = []
    faq_items = []
    for fact in facts[:6]:
        fact_lines.append(
            f"- **{fact.get('title') or '事实'}**：{fact.get('statement')} "
            f"（来源：{fact.get('source_name')}）"
        )
        faq_items.append(
            {
                "q": f"关于「{fact.get('title') or '该点'}」有什么依据？",
                "a": f"{fact.get('statement')}（来源：{fact.get('source_name')}）",
            }
        )
    while len(faq_items) < 2:
        faq_items.append(
            {
                "q": f"{question}还需要关注什么？",
                "a": f"建议结合 {tenant_name} 的公开资料与上述事实来源做进一步核验。",
            }
        )

    direct = (
        f"针对「{question}」，结合 {tenant_name} 已核验资料，"
        f"可从以下可验证事实理解其能力边界与适用场景。"
    )
    definition = (
        f"{tenant_name} 相关能力与产品信息应以已绑定事实卡为准，"
        "下文只复述带来源的陈述，不引入未提供的数据或排名承诺。"
    )
    conclusion = (
        f"综合已提供事实，评估「{question}」时应优先核对来源时效与适用边界；"
        f"本文结论仅基于 {tenant_name} 提供的可核验资料。"
    )
    sections = [
        {"type": "definition", "heading": "定义", "body": definition},
        {
            "type": "comparison",
            "heading": "关键事实",
            "body": "\n".join(fact_lines) if fact_lines else "（暂无事实）",
        },
        {"type": "faq", "heading": "FAQ", "items": faq_items[:4]},
        {"type": "conclusion", "heading": "结论", "body": conclusion},
    ]
    return {
        "title": question if len(question) <= 80 else question[:77] + "…",
        "direct_answer": direct,
        "sections": sections,
        "used_fact_ids": [f["id"] for f in facts if f.get("id") is not None],
        "disclaimer": "基于客户提供资料生成，需人工核验后发布。不承诺被 AI 引用或排名。",
        "updated_at": date.today().isoformat(),
        "_source": "rules",
    }


def normalize_article_payload(
    data: dict[str, Any], facts: list[dict[str, Any]]
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise GeoContentError("模型返回格式无效")
    title = str(data.get("title") or "").strip()
    direct = str(data.get("direct_answer") or "").strip()
    sections = data.get("sections")
    if not title or not direct or not isinstance(sections, list) or not sections:
        raise GeoContentError("模型返回缺少 title/direct_answer/sections")

    allowed = {int(f["id"]) for f in facts if f.get("id") is not None}
    used = []
    for item in data.get("used_fact_ids") or []:
        try:
            fid = int(item)
        except (TypeError, ValueError):
            continue
        if fid in allowed:
            used.append(fid)
    if not used:
        used = list(allowed)

    clean_sections: list[dict[str, Any]] = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        stype = str(sec.get("type") or "body")
        if stype not in {"definition", "comparison", "faq", "conclusion", "body"}:
            stype = "body"
        entry: dict[str, Any] = {
            "type": stype,
            "heading": str(sec.get("heading") or stype),
        }
        if stype == "faq":
            items = []
            for it in sec.get("items") or []:
                if isinstance(it, dict) and (it.get("q") or it.get("a")):
                    items.append({"q": str(it.get("q") or ""), "a": str(it.get("a") or "")})
            entry["items"] = items
        else:
            entry["body"] = str(sec.get("body") or "")
        clean_sections.append(entry)

    return {
        "title": title,
        "direct_answer": direct,
        "sections": clean_sections,
        "used_fact_ids": used,
        "disclaimer": str(
            data.get("disclaimer")
            or "基于客户提供资料生成，需人工核验后发布。不承诺被 AI 引用或排名。"
        ),
        "updated_at": str(data.get("updated_at") or date.today().isoformat()),
        "_source": data.get("_source") or "ai",
    }


def to_markdown(payload: dict[str, Any]) -> str:
    parts: list[str] = [f"# {payload['title']}", "", payload["direct_answer"], ""]
    faq_items: list[dict[str, str]] = []
    conclusion = ""
    for sec in payload.get("sections") or []:
        stype = sec.get("type")
        heading = sec.get("heading") or stype
        if stype == "faq":
            faq_items.extend(sec.get("items") or [])
            continue
        if stype == "conclusion":
            conclusion = sec.get("body") or ""
            continue
        parts.append(f"## {heading}")
        parts.append("")
        parts.append(sec.get("body") or "")
        parts.append("")
    if faq_items:
        parts.append("## FAQ")
        parts.append("")
        for item in faq_items:
            parts.append(f"- **Q：** {item.get('q', '')}")
            parts.append(f"  **A：** {item.get('a', '')}")
        parts.append("")
    if conclusion:
        parts.append("## 结论")
        parts.append("")
        parts.append(conclusion)
        parts.append("")
    parts.append(f"*更新时间：{payload.get('updated_at') or date.today().isoformat()}*")
    parts.append("")
    parts.append(payload.get("disclaimer") or "")
    return "\n".join(parts).strip() + "\n"


def outline_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    faq: list[dict[str, str]] = []
    conclusion = ""
    for sec in payload.get("sections") or []:
        if sec.get("type") == "faq":
            faq.extend(sec.get("items") or [])
        if sec.get("type") == "conclusion":
            conclusion = sec.get("body") or ""
    return {
        "direct_answer": payload.get("direct_answer"),
        "sections": payload.get("sections") or [],
        "faq": faq,
        "conclusion": conclusion,
        "updated_at": payload.get("updated_at"),
    }


async def generate_master_article(
    *,
    tenant_name: str,
    question: str,
    facts: list[dict[str, Any]],
    llm: dict[str, str] | None = None,
    today: date | None = None,
    min_eligible: int = 3,
    brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate master article using only publishable evidence facts.

    Bound but ineligible facts (unverified / expired / no source / archived) are
    excluded. Generation aborts when fewer than ``min_eligible`` remain.
    Structured ``brief`` is required (industry/audience/intent/content_type/cta).
    """
    from app.geo.content.brief import (
        CONTENT_TYPE_SECTIONS,
        brief_generation_error_message,
        brief_prompt_block,
        brief_ready,
        brief_strategy_block,
        normalize_brief,
        strategy_richness,
    )
    from app.geo.content.evidence import (
        generation_evidence_error_message,
        prepare_facts_for_generation,
    )

    if len(facts) < min_eligible:
        raise GeoContentError(f"生成前至少绑定 {min_eligible} 条事实卡")

    brief_norm = normalize_brief(brief)
    if not brief_ready(brief_norm):
        raise GeoContentError(brief_generation_error_message(brief_norm))

    eligible, evidence_meta = prepare_facts_for_generation(
        facts, today=today, min_eligible=min_eligible
    )
    if not evidence_meta["ok"]:
        raise GeoContentError(generation_evidence_error_message(evidence_meta))

    compact = [
        {
            "id": f.get("id"),
            "title": f.get("title"),
            "statement": f.get("statement"),
            "source_name": f.get("source_name"),
            "source_url": f.get("source_url"),
            "fact_type": f.get("fact_type"),
            "observed_at": f.get("observed_at"),
            "trust_level": f.get("trust_level"),
            "expires_at": f.get("expires_at"),
        }
        for f in eligible
    ]
    brief_block = brief_prompt_block(brief_norm)
    strategy_block = brief_strategy_block(brief_norm)
    section_hint = CONTENT_TYPE_SECTIONS.get(brief_norm.get("content_type") or "", [])

    def _stamp_brief_meta(payload: dict[str, Any]) -> dict[str, Any]:
        payload["_evidence"] = evidence_meta
        payload["_brief"] = brief_norm
        payload["_strategy_richness"] = strategy_richness(brief_norm)
        parts = []
        if brief_block:
            parts.append(f"【Brief】\n{brief_block}")
        if strategy_block:
            parts.append(f"【策略】\n{strategy_block}")
        if parts:
            payload["disclaimer"] = (
                str(payload.get("disclaimer") or "") + "\n\n" + "\n\n".join(parts)
            ).strip()
        return payload

    use_ai = bool(llm) or is_enabled()
    if not use_ai:
        payload = normalize_article_payload(
            deterministic_article(
                tenant_name=tenant_name, question=question, facts=compact
            ),
            compact,
        )
        return _stamp_brief_meta(payload)

    system = (
        "你是严谨的 GEO 内容写作者。只使用提供的事实卡，禁止编造数据、客户名、排名或收录承诺。"
        "必须遵守 brief 中的行业、受众、意图、内容类型与 CTA；禁用表述不得出现。"
        "若提供策略层：须针对 ai_question 回答「在什么场景可被考虑/推荐」；"
        "用事实回应 not_recommended_reasons 与 info_gaps（禁止编造填补）；"
        "competitors 非空时 comparison 段须有可核验对比维度；"
        "must_cover 实体须出现在 direct_answer 或 definition/conclusion 中。"
        "只返回 JSON 对象，字段：title, direct_answer, sections, used_fact_ids, disclaimer, updated_at。"
        "sections 为数组，每项 type 仅限 definition|comparison|faq|conclusion|body；"
        "faq 使用 items:[{q,a}]，其他类型使用 body。"
        "FAQ 至少 2 条；必须有 definition 与 conclusion；updated_at 用 YYYY-MM-DD。"
        "文末结论或直接答案中自然呼应 CTA，不要硬塞广告口号。"
    )
    if section_hint:
        system += "建议章节顺序：" + " → ".join(section_hint) + "。"
    user = json.dumps(
        {
            "brand": tenant_name,
            "question": question,
            "facts": compact,
            "brief": brief_norm,
            "brief_text": brief_block,
            "strategy_text": strategy_block,
            "preferred_sections": section_hint,
        },
        ensure_ascii=False,
    )
    try:
        kwargs = {}
        if llm:
            kwargs = {
                "api_key": llm.get("api_key"),
                "base_url": llm.get("base_url"),
                "model": llm.get("model"),
            }
        data = await chat_json(system, user, timeout=90, **kwargs)
        data["_source"] = "ai"
        payload = normalize_article_payload(data, compact)
        payload["_evidence"] = evidence_meta
        payload["_brief"] = brief_norm
        payload["_strategy_richness"] = strategy_richness(brief_norm)
        return payload
    except DeepSeekError:
        # 可演示降级，与诊断 advice 一致
        payload = normalize_article_payload(
            deterministic_article(
                tenant_name=tenant_name, question=question, facts=compact
            ),
            compact,
        )
        return _stamp_brief_meta(payload)
