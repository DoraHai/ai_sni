"""Sentence-level fact citations. Appendix is metadata; claims without a fact block ready."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from app.geo.content.fact_retrieve import tokenize

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")
_APPENDIX = re.compile(r"\n+## 逐句证据\s*\n[\s\S]*\Z")
_GENERIC_HEADING = re.compile(
    r"^(?:定义(?:与背景)?|背景|概述|简介|对比(?:选型|与考量)?|操作步骤|"
    r"常见问题|FAQ|结论(?:与建议)?|来源|参考资料)$",
    re.I,
)
_METADATA = re.compile(
    r"^(?:\*(?:更新时间|发布日期)[：:]\d{4}-\d{2}-\d{2}\*|"
    r"\*草稿生成日期[：:]\d{4}-\d{2}-\d{2}（非来源更新日期）\*)$"
)
_SYSTEM_PRESENTATION = re.compile(
    r"^(?:> \*\*草案提示\*\*[：:]以下为自动生成母稿，请人工润色后再发布[；;]|"
    r"勿直接对外使用[。.]|"
    r"【草案】基于客户提供资料自动生成，仅供内部改稿[；;]|"
    r"须人工润色与核验后方可发布[。.]|"
    r"不承诺被 AI 引用或排名[。.])$"
)
_PURE_TRANSITION = re.compile(
    r"^(?:以下|下面|接下来)(?:将|按|从)?(?:依据|围绕|按照|基于)?(?:已核验)?(?:事实|资料|来源)?"
    r"(?:逐项|分别)?(?:说明|介绍|分析|展开|讨论)[。.!！]?$|"
    r"^基于(?:以上|上述)(?:已核验)?(?:事实|资料|来源)[，,]?(?:下文)?(?:逐项)?(?:说明|展开)[。.!！]?$",
)
_NEUTRAL_QUESTION = re.compile(
    r"^(?:需要关注什么|如何(?:验证|核验|检查|选择|比较|操作|开始|处理|评估|改进)|"
    r"如何为具体设备进行选型|"
    r"怎么(?:验证|核验|检查|选择|比较|操作|开始|处理)|"
    r"有哪些(?:步骤|注意事项|需要关注的事项))[?？]$"
)
_EVIDENCE_NOTICE = re.compile(
    r"^(?:(?:目前)?(?:暂无|尚未提供)[^。！？]*(?:案例|事实|资料|原文)|"
    r"(?:请|建议)(?:提供|补充|核验)[^。！？]*(?:案例|事实|资料|原文)[^。！？]*|"
    r"暂无[^。！？]*[，,](?:请|建议)(?:提供|补充|核验)[^。！？]*)[。.!！]?$"
)
_CTA = re.compile(
    r"^(?:如果您正在为具体设备进行选型[，,]建议预约诊断或咨询专业选型服务[，,]以获取针对性的方案|"
    r"如需了解设备选型[，,]请联系专业团队|如有设备选型问题[，,]请向专业团队咨询|"
    r"建议咨询专业团队)[。.!！]?$"
)
_PROCESS_INSTRUCTION = re.compile(
    r"^(?:步骤\s*\d+|第[一二三四五六七八九十]+步)[：:]\s*"
    r"(?:明确|核对|核验|验证|检查|完成|开展|进行|试点)[^。！？]*[。.!！]?$"
)
_GUIDANCE = re.compile(
    r"^(?:应结合场景与可核验事实选择[^，,。！？]{0,20}|"
    r"建议核验来源与时效|建议核对应?事实卡|优先核验|优先核验来源后再决策)[。.!！]?$"
)
_SOURCE_REFERENCE = re.compile(
    r"^(?:白皮书|文档|报告|官网|标准|手册|案例集|案例)$",
    re.I,
)
_SOURCE_METADATA_NAME = re.compile(
    r"^\*{0,2}来源[：:]\s*(?:白皮书|文档|报告|官网|标准|手册|案例集|案例)\*{0,2}$",
    re.I,
)
_SOURCE_PREFIX = re.compile(r"^\*{0,2}来源[：:]\s*", re.I)
_URL_DISALLOWED = re.compile(r"[\s，。；！？、*]")


def split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    for line in (text or "").splitlines():
        value = line.strip()
        if not value:
            continue
        # Query delimiters inside a standalone URL are URL syntax, not prose.
        if _is_standalone_url_reference(value):
            parts.append(value)
            continue
        parts.extend(
            p.strip() for p in _SENT_SPLIT.split(value) if p and p.strip()
        )
    return [p for p in parts if re.search(r"[A-Za-z0-9\u4e00-\u9fff]", p)]


def strip_citation_appendix(markdown: str) -> str:
    """Remove a previously appended citation section so repeated saves do not stack it."""
    return _APPENDIX.sub("", markdown or "").rstrip()


def _is_standalone_url_reference(value: str) -> bool:
    candidate = value.strip()
    for marker in ("**", "*"):
        if candidate.startswith(marker) and candidate.endswith(marker):
            candidate = candidate[len(marker) : -len(marker)].strip()
            break
    candidate = _SOURCE_PREFIX.sub("", candidate).strip()
    if _URL_DISALLOWED.search(candidate):
        return False
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return False
    return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)


def is_presentation_sentence(sentence: str) -> bool:
    value = str(sentence or "").strip()
    if not value:
        return True
    if (
        _METADATA.fullmatch(value)
        or _SYSTEM_PRESENTATION.fullmatch(value)
    ):
        return True
    if _PURE_TRANSITION.fullmatch(value):
        return True
    if re.match(r"^#{1,6}\s*", value):
        return True
    if value.endswith(("?", "？")):
        return True
    return False


def is_evidence_exempt(sentence: str) -> bool:
    """Return true only for syntax that does not assert a product/world fact."""
    value = str(sentence or "").strip()
    if (
        not value
        or _METADATA.fullmatch(value)
        or _SYSTEM_PRESENTATION.fullmatch(value)
        or _SOURCE_METADATA_NAME.fullmatch(value)
        or _is_standalone_url_reference(value)
        or _PURE_TRANSITION.fullmatch(value)
    ):
        return True
    heading = re.match(r"^#{1,6}\s*(.*?)\s*$", value)
    if heading:
        return bool(_GENERIC_HEADING.fullmatch(heading.group(1)))
    plain = re.sub(r"^\*{0,2}(?:直接回答|答|A)[：:]\*{0,2}\s*", "", value, flags=re.I)
    plain = re.sub(r"^(?:[-*+]\s*|\d+[.)、]\s*)", "", plain)
    if plain.endswith(("?", "？")):
        question = re.sub(r"^\*{0,2}(?:问|Q)[：:]\*{0,2}\s*", "", plain, flags=re.I)
        return bool(_NEUTRAL_QUESTION.fullmatch(question))
    return bool(
        _EVIDENCE_NOTICE.fullmatch(plain)
        or _CTA.fullmatch(plain)
        or _PROCESS_INSTRUCTION.fullmatch(plain)
        or _GUIDANCE.fullmatch(plain)
        or (
            bool(re.match(r"^(?:[-*+]\s*|\d+[.)、]\s*)", value))
            and bool(_SOURCE_REFERENCE.fullmatch(plain))
        )
    )


def _score(sentence: str, fact: dict[str, Any]) -> float:
    q = set(tokenize(sentence))
    from app.geo.content.cross_language import verified_translation_texts

    blob = " ".join(
        [
            str(fact.get("title") or ""),
            str(fact.get("statement") or ""),
            *verified_translation_texts(fact),
        ]
    )
    ftok = set(tokenize(blob))
    if not q or not ftok:
        return 0.0
    hit = q & ftok
    return len(hit) / max(3, len(q))


def _support_basis(sentence: str, fact: dict[str, Any]) -> str | None:
    """Accept only a complete source statement or explicitly verified translation."""
    from app.geo.content.cross_language import verified_translation_texts

    def canonical(value: str) -> str:
        text = re.sub(r"[（(]来源[：:][^）)\n]*[）)]\s*$", "", value or "")
        text = re.sub(r"^\s*(?:#{1,6}|[-*+])\s*", "", text)
        return re.sub(r"[\s*#`]+", "", text).strip("。.!！?？；;").casefold()

    source_values = [str(fact.get("statement") or ""), *verified_translation_texts(fact)]
    sent = canonical(sentence)
    for value in source_values:
        statement = canonical(value)
        if len(statement) >= 4 and statement == sent:
            return "exact_statement"
    return None


def _sentence_is_claim(sentence: str, facts: list[dict[str, Any]]) -> bool:
    from app.geo.content.claim_guard import ungrounded_claims

    return bool(ungrounded_claims(sentence, facts))


def build_sentence_citations(
    markdown: str,
    facts: list[dict[str, Any]],
    *,
    min_score: float = 0.22,
) -> list[dict[str, Any]]:
    """Match sentences to facts without inventing facts or rewriting the body."""
    facts = [f for f in facts or [] if f.get("id") is not None]
    body = strip_citation_appendix(markdown)
    rows: list[dict[str, Any]] = []
    if not body.strip():
        return rows
    for sent in split_sentences(body):
        cited = False
        fact: dict[str, Any] | None = None
        score = 0.0
        if facts:
            ranked = []
            for candidate in facts:
                candidate_score = _score(sent, candidate)
                candidate_basis = _support_basis(sent, candidate)
                ranked.append((candidate_basis is not None, candidate_score, candidate, candidate_basis))
            _supported, score, fact, support_basis = sorted(
                ranked, key=lambda item: (not item[0], -item[1])
            )[0]
            cited = (
                not is_presentation_sentence(sent)
                and score >= min_score
                and support_basis is not None
            )
        else:
            support_basis = None
        is_claim = _sentence_is_claim(sent, facts) or bool(
            not is_evidence_exempt(sent)
            and support_basis is None
        )
        # Similarity is only a retrieval hint. It cannot override a known
        # unsupported assertion, even when the rest repeats a fact verbatim.
        if is_claim:
            cited = False
        from app.geo.content.cross_language import evidence_candidates
        candidates = evidence_candidates(sent, facts) if is_claim else []
        rows.append(
            {
                "sentence": sent[:180],
                "fact_id": fact.get("id") if cited and fact else None,
                "fact_title": fact.get("title") if cited and fact else None,
                "source_name": fact.get("source_name") if cited and fact else None,
                "score": round(score, 3),
                "support_basis": support_basis if cited else None,
                "cited": cited,
                "is_claim": is_claim,
                "needs_fact": is_claim,
                "review_status": "needs_review" if is_claim else "not_required",
                "review_reason": "cross_language_unverified" if candidates else ("unsupported_claim" if is_claim else None),
                "evidence_candidates": candidates,
            }
        )
    return rows


def format_citation_appendix(rows: list[dict[str, Any]]) -> str:
    cited_n = sum(1 for r in rows if r["cited"])
    blocking_n = sum(1 for r in rows if r.get("needs_fact"))
    appendix = [
        "",
        "## 逐句证据",
        "",
        f"已挂事实 {cited_n}/{len(rows)} 句；主张未挂 {blocking_n} 句（须删改或补核验事实）。",
        "",
    ]
    for i, r in enumerate(rows, 1):
        if r["cited"]:
            appendix.append(
                f"{i}. {r['sentence'][:80]}… → 事实卡 #{r['fact_id']}「{r['fact_title']}」"
                f"（{r.get('source_name') or '来源未填'}）"
            )
        elif r.get("needs_fact"):
            appendix.append(f"{i}. {r['sentence'][:80]}… → **主张未挂事实，阻断就绪**")
        else:
            appendix.append(f"{i}. {r['sentence'][:80]}… → 叙述句，可不挂")
    appendix.append("")
    return "\n".join(appendix)


def attach_sentence_citations(
    markdown: str,
    facts: list[dict[str, Any]],
    *,
    min_score: float = 0.22,
) -> tuple[str, list[dict[str, Any]]]:
    """Return a de-duplicated body and its structured citation metadata."""
    body = strip_citation_appendix(markdown)
    return body, build_sentence_citations(body, facts, min_score=min_score)


def citation_verdict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    blocking = [row for row in rows if row.get("needs_fact")]
    cited = sum(1 for row in rows if row.get("cited"))
    return {
        "total": len(rows),
        "cited": cited,
        "blocking": len(blocking),
        "ok": not blocking,
    }
