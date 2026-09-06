"""基于事实卡生成 GEO 母稿。"""

from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo
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


# Internal section type → Chinese H2 for publishable-looking drafts
SECTION_HEADINGS_ZH: dict[str, str] = {
    "definition": "定义与背景",
    "comparison": "关键对比与考量",
    "faq": "常见问题",
    "conclusion": "结论与建议",
    "body": "正文",
}


def _human_heading(stype: str, raw: str | None) -> str:
    """Prefer Chinese headings; never leak English type keys like ``definition``."""
    st = str(stype or "body").strip().lower()
    default = SECTION_HEADINGS_ZH.get(st, "正文")
    h = str(raw or "").strip()
    if not h:
        return default
    # Model sometimes echoes the type key as heading
    if h.lower() in SECTION_HEADINGS_ZH or h.lower() == st:
        return default
    return h


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
        {
            "type": "definition",
            "heading": SECTION_HEADINGS_ZH["definition"],
            "body": definition,
        },
        {
            "type": "comparison",
            "heading": SECTION_HEADINGS_ZH["comparison"],
            "body": "\n".join(fact_lines) if fact_lines else "（暂无事实）",
        },
        {
            "type": "faq",
            "heading": SECTION_HEADINGS_ZH["faq"],
            "items": faq_items[:4],
        },
        {
            "type": "conclusion",
            "heading": SECTION_HEADINGS_ZH["conclusion"],
            "body": conclusion,
        },
    ]
    return {
        "title": question if len(question) <= 80 else question[:77] + "…",
        "direct_answer": direct,
        "sections": sections,
        "used_fact_ids": [f["id"] for f in facts if f.get("id") is not None],
        "disclaimer": (
            "【草案】基于客户提供资料自动生成，仅供内部改稿；"
            "须人工润色与核验后方可发布。不承诺被 AI 引用或排名。"
        ),
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

    clean_sections: list[dict[str, Any]] = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        stype = str(sec.get("type") or "body")
        if stype not in {"definition", "comparison", "faq", "conclusion", "body"}:
            stype = "body"
        entry: dict[str, Any] = {
            "type": stype,
            "heading": _human_heading(stype, sec.get("heading")),
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

    default_disclaimer = (
        "【草案】基于客户提供资料自动生成，仅供内部改稿；"
        "须人工润色与核验后方可发布。不承诺被 AI 引用或排名。"
    )
    disclaimer = str(data.get("disclaimer") or default_disclaimer).strip()
    if "草案" not in disclaimer and "人工" not in disclaimer:
        disclaimer = f"{disclaimer}\n\n{default_disclaimer}".strip()

    return {
        "title": title,
        "direct_answer": direct,
        "sections": clean_sections,
        "used_fact_ids": used,
        "disclaimer": disclaimer,
        "updated_at": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        "_source": data.get("_source") or "ai",
    }


def to_markdown(payload: dict[str, Any]) -> str:
    parts: list[str] = [
        f"# {payload['title']}",
        "",
        "> **草案提示**：以下为自动生成母稿，请人工润色后再发布；勿直接对外使用。",
        "",
        payload["direct_answer"],
        "",
    ]
    faq_items: list[dict[str, str]] = []
    conclusion = ""
    for sec in payload.get("sections") or []:
        stype = sec.get("type")
        heading = _human_heading(str(stype or "body"), sec.get("heading"))
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
        parts.append(f"## {SECTION_HEADINGS_ZH['faq']}")
        parts.append("")
        for item in faq_items:
            parts.append(f"- **问：** {item.get('q', '')}")
            parts.append(f"  **答：** {item.get('a', '')}")
        parts.append("")
    if conclusion:
        parts.append(f"## {SECTION_HEADINGS_ZH['conclusion']}")
        parts.append("")
        parts.append(conclusion)
        parts.append("")
    parts.append(f"*草稿生成日期：{payload.get('updated_at') or date.today().isoformat()}（非来源更新日期）*")
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

    from app.geo.content.brand_geo import payload_brand_issues

    brand = (tenant_name or "").strip()
    system = (
        "你是严谨的 GEO 内容写作者。只使用提供的事实卡，禁止编造数据、客户名、排名或收录承诺。"
        "输出是「内部改稿用母稿草案」，不是可直接发布的成稿：语气完整可读，但 disclaimer 须标明需人工润色。"
        "必须遵守 brief 中的行业、受众、意图、内容类型与 CTA；禁用表述不得出现。"
        "【数字禁令】禁止编造百分比、坐席数、时长、识别率、并发、满意度等具体数字；"
        "禁止写成功案例、头部客户、标杆项目，除非该名称或案例原文出现在事实卡。"
        "事实卡里没有出现的数字、案例名、性能指标、竞品能力一律不得写入。"
        "行业适用性、设备举例、故障机理、寿命与选型结论也必须有事实原文支撑；不得用行业常识补写。"
        "brief 是写作需求，不是事实证据；资料不足时缩短正文，不得为了篇幅补充推断。"
        "不要把 Brief、行业画像、策略说明或内部指令复印到正文或免责声明；品牌主体以已核验事实为准，"
        "Brief 与事实主体不一致时不得混用同名企业资料。"
        "事实卡只有泛化官网介绍时，正文只能复述这些介绍，不得补行业常见数据。"
        "【GEO 品牌硬标准】user.brand 是本品品牌名：direct_answer（开篇直接答案）与 conclusion 结论段"
        "必须自然点名该品牌（至少各出现 1 次）；全文禁止写成无品牌的纯品类科普——"
        "否则无法被生成式引擎在回答中推荐/引用。禁止只写「某厂商」「行业方案」代替品牌名。"
        "若提供策略层：须针对 ai_question 回答「在什么场景可被考虑/推荐」并落到品牌；"
        "用事实回应 not_recommended_reasons 与 info_gaps（禁止编造填补）；"
        "competitors 非空时 comparison 段须有可核验对比维度；"
        "must_cover 实体须出现在 direct_answer 或 definition/conclusion 中。"
        "只返回 JSON 对象，字段：title, direct_answer, sections, used_fact_ids, disclaimer, updated_at。"
        "sections 为数组，每项 type 仅限 definition|comparison|faq|conclusion|body；"
        "每项必须有中文 heading（如「定义与背景」「关键对比与考量」「常见问题」「结论与建议」），"
        "禁止把 type 英文名（definition/comparison 等）当作 heading。"
        "faq 使用 items:[{q,a}]，其他类型使用 body。"
        "正文与问答中禁止写「(事实卡7)」「事实卡#5」等内部编号；依据用自然语言表述，来源写在语句中或文末。"
        "used_fact_ids 只放在 JSON 字段里，不要写进正文。"
        "FAQ 至少 2 条；必须有 definition 与 conclusion；updated_at 用 YYYY-MM-DD。"
        "文末结论或直接答案中自然呼应 CTA，不要硬塞广告口号。"
    )
    if section_hint:
        system += "建议章节顺序：" + " → ".join(section_hint) + "。"
    base_user: dict[str, Any] = {
        "brand": brand,
        "geo_goal": "brand_mention_for_generative_engine_recommendation",
        "require_brand_in_direct_answer": True,
        "require_brand_in_conclusion": True,
        "question": question,
        "facts": compact,
        "brief": brief_norm,
        "brief_text": brief_block,
        "strategy_text": strategy_block,
        "preferred_sections": section_hint,
    }
    try:
        kwargs: dict[str, Any] = {"timeout": 90}
        if llm:
            kwargs.update(
                {
                    "api_key": llm.get("api_key"),
                    "base_url": llm.get("base_url"),
                    "model": llm.get("model"),
                }
            )
        data = await chat_json(
            system, json.dumps(base_user, ensure_ascii=False), **kwargs
        )
        data["_source"] = "ai"
        payload = normalize_article_payload(data, compact)
        brand_issues = payload_brand_issues(payload, brand)
        if brand_issues:
            fix_user = {
                **base_user,
                "rewrite_mode": True,
                "quality_issues": brand_issues,
                "previous_direct_answer": payload.get("direct_answer"),
                "instruction": (
                    f"上一版未满足 GEO 品牌可见度。请整篇重写 JSON："
                    f"direct_answer 与 conclusion 必须明确写出品牌「{brand}」，"
                    "说明在何种场景可被考虑/选用；禁止无品牌品类空文。"
                ),
            }
            try:
                data2 = await chat_json(
                    system, json.dumps(fix_user, ensure_ascii=False), **kwargs
                )
                data2["_source"] = "ai"
                payload = normalize_article_payload(data2, compact)
                brand_issues = payload_brand_issues(payload, brand)
            except DeepSeekError:
                pass
        if brand_issues:
            raise GeoContentError(
                "母稿未满足 GEO 品牌提及硬标准：" + "；".join(brand_issues[:4])
            )
        from app.geo.content.claim_guard import format_ungrounded, ungrounded_claims

        invented = ungrounded_claims(to_markdown(payload), compact)
        if invented:
            try:
                fix_claims = {
                    **base_user,
                    "rewrite_mode": True,
                    "quality_issues": [format_ungrounded(invented)],
                    "previous_direct_answer": payload.get("direct_answer"),
                    "instruction": (
                        "上一版包含事实卡未能支撑的数字、性能、案例、适用性或机理。请整篇重写 JSON："
                        "只复述事实卡原文能支撑的内容；删掉所有无依据数字、识别率/满意度/并发、"
                        "成功案例/头部客户、行业适用性、设备示例及故障机理。资料不足就缩短正文，不能用免责声明保留无依据结论。"
                    ),
                }
                data3 = await chat_json(
                    system, json.dumps(fix_claims, ensure_ascii=False), **kwargs
                )
                data3["_source"] = "ai"
                payload = normalize_article_payload(data3, compact)
                invented = ungrounded_claims(to_markdown(payload), compact)
            except DeepSeekError:
                pass
        if invented:
            raise GeoContentError(
                "母稿存在事实卡未能支撑的表述，已拦截："
                + format_ungrounded(invented)
            )
        final_brand_issues = payload_brand_issues(payload, brand)
        if final_brand_issues:
            raise GeoContentError("母稿改写后未满足品牌标准：" + "；".join(final_brand_issues[:4]))
        payload["_evidence"] = evidence_meta
        payload["_brief"] = brief_norm
        payload["_strategy_richness"] = strategy_richness(brief_norm)
        payload["_brand"] = brand
        payload["_brand_mentioned"] = True
        return _stamp_brief_meta(payload)
    except GeoContentError:
        raise
    except DeepSeekError:
        # 可演示降级，与诊断 advice 一致（规则稿自带品牌名）
        payload = normalize_article_payload(
            deterministic_article(
                tenant_name=tenant_name, question=question, facts=compact
            ),
            compact,
        )
        return _stamp_brief_meta(payload)
