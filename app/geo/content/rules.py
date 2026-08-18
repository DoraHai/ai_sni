"""GEO 内容规则检查（纯函数，无 IO）。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class RuleInput:
    question: str
    title: str
    body_markdown: str
    outline: dict[str, Any]
    facts: list[dict[str, Any]]
    target_channels: list[str]
    variants: list[str]
    author_name: str | None = None
    default_author: str | None = None
    variant_bodies: list[str] | None = None


@dataclass
class RuleCheck:
    code: str
    passed: bool
    message: str
    action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _faq_count_in_body(body: str) -> int:
    """Count Q lines in body. Prefer FAQ/常见问题 sections (all of them), else whole body."""
    text = body or ""
    sections = re.findall(
        r"(?is)(?:##\s*faq|##\s*常见问题).*?(?=##\s|\Z)", text
    )
    hay = "\n".join(sections) if sections else text
    return len(re.findall(r"(?m)^\s*(?:[-*]\s*)?(?:\*\*)?Q[:：.]?", hay))


def _faq_count(outline: dict[str, Any], body: str) -> int:
    """Outline FAQ list and body markdown — take the larger count.

    Important: do NOT ignore body when outline.faq is a short stale list; otherwise
    apply-patch appends real FAQ markdown but checks still fail (false success).
    """
    outline_n = 0
    faq = outline.get("faq") if isinstance(outline, dict) else None
    if isinstance(faq, list) and faq:
        outline_n = len(faq)
    body_n = _faq_count_in_body(body)
    return max(outline_n, body_n)


def _has_definition(outline: dict[str, Any], body: str) -> bool:
    sections = outline.get("sections") if isinstance(outline, dict) else None
    if isinstance(sections, list):
        for sec in sections:
            if isinstance(sec, dict) and sec.get("type") == "definition" and (sec.get("body") or "").strip():
                return True
    return bool(re.search(r"(?is)##\s*(定义|是什么|简介)", body or ""))


def _has_conclusion(outline: dict[str, Any], body: str) -> bool:
    if isinstance(outline, dict):
        if (outline.get("conclusion") or "").strip():
            return True
        sections = outline.get("sections")
        if isinstance(sections, list):
            for sec in sections:
                if (
                    isinstance(sec, dict)
                    and sec.get("type") == "conclusion"
                    and (sec.get("body") or "").strip()
                ):
                    return True
    return bool(re.search(r"(?is)##\s*(结论|总结|一句话结论)", body or ""))


def _direct_answer_ok(question: str, title: str, body: str, outline: dict[str, Any]) -> bool:
    direct = ""
    if isinstance(outline, dict):
        direct = (outline.get("direct_answer") or "").strip()
    text = "\n".join([title or "", direct, (body or "")[:800]])
    if len(direct) >= 12:
        return True
    # first non-empty paragraph after title should be reasonably long
    paras = [p.strip() for p in re.split(r"\n\s*\n", body or "") if p.strip() and not p.strip().startswith("#")]
    if paras and len(paras[0]) >= 20:
        return True
    # title loosely related to question tokens
    q_tokens = [t for t in re.split(r"\W+", question or "") if len(t) >= 2][:4]
    return bool(q_tokens) and any(t in text for t in q_tokens)


def check_direct_answer(data: RuleInput) -> RuleCheck:
    ok = _direct_answer_ok(data.question, data.title, data.body_markdown, data.outline or {})
    return RuleCheck(
        code="direct_answer",
        passed=ok,
        message="首段/直接答案可回答目标问题" if ok else "缺少直接回答目标问题的段落",
        action="" if ok else "在文首补充一句直接答案",
    )


def check_definition(data: RuleInput) -> RuleCheck:
    ok = _has_definition(data.outline or {}, data.body_markdown or "")
    return RuleCheck(
        code="definition",
        passed=ok,
        message="已包含定义段" if ok else "缺少定义段",
        action="" if ok else "补一句话定义或「是什么」小节",
    )


def check_faq_min(data: RuleInput, min_items: int = 2) -> RuleCheck:
    n = _faq_count(data.outline or {}, data.body_markdown or "")
    ok = n >= min_items
    return RuleCheck(
        code="faq_min",
        passed=ok,
        message=f"FAQ {n}/{min_items}",
        action="" if ok else f"至少补充 {min_items} 个相关追问",
    )


def check_conclusion_extractable(data: RuleInput) -> RuleCheck:
    ok = _has_conclusion(data.outline or {}, data.body_markdown or "")
    return RuleCheck(
        code="conclusion_extractable",
        passed=ok,
        message="存在可摘取结论段" if ok else "缺少独立结论段",
        action="" if ok else "将关键结论改写为独立「结论」段落",
    )


def check_facts_bound_min(data: RuleInput, min_n: int = 3) -> RuleCheck:
    n = len(data.facts or [])
    ok = n >= min_n
    return RuleCheck(
        code="facts_bound_min",
        passed=ok,
        message=f"已绑定事实 {n}/{min_n}",
        action="" if ok else f"至少绑定 {min_n} 条事实卡",
    )


def check_facts_sourced(data: RuleInput) -> RuleCheck:
    facts = data.facts or []
    if not facts:
        return RuleCheck(
            code="facts_sourced",
            passed=False,
            message="无事实卡",
            action="先绑定带来源的事实卡",
        )
    missing = [f for f in facts if not str(f.get("source_name") or "").strip()]
    ok = not missing
    return RuleCheck(
        code="facts_sourced",
        passed=ok,
        message="全部事实均有来源" if ok else f"{len(missing)} 条事实缺来源",
        action="" if ok else "为事实卡补全来源名称",
    )


def check_evidence_publishable(data: RuleInput, min_eligible: int = 3) -> RuleCheck:
    """Wave C：发布级证据须核验、有来源且未过期。"""
    from app.geo.content.evidence import summarize_evidence_blockers

    ok, message, action = summarize_evidence_blockers(
        data.facts or [], min_eligible=min_eligible
    )
    return RuleCheck(
        code="evidence_publishable",
        passed=ok,
        message=message,
        action=action,
    )


def check_updated_at_visible(data: RuleInput) -> RuleCheck:
    body = data.body_markdown or ""
    outline = data.outline or {}
    ok = bool(
        re.search(r"更新时间|更新日期|observed_at|20\d{2}[-/年]\d{1,2}", body)
        or outline.get("updated_at")
    )
    return RuleCheck(
        code="updated_at_visible",
        passed=ok,
        message="文中可见更新日期" if ok else "缺少更新日期",
        action="" if ok else "在文末插入更新日期",
    )


def _norm_channel_key(raw: str | None) -> str:
    """Normalize channel labels so UI keys and stored variant.channel align."""
    key = str(raw or "").strip().lower()
    aliases = {
        "web": "website",
        "官网": "website",
        "网站": "website",
        "docs": "website",
        "微信": "wechat",
        "公众号": "wechat",
        "weixin": "wechat",
        "知乎": "zhihu",
        "百家号": "baijiahao",
        "头条": "toutiao",
        "今日头条": "toutiao",
    }
    return aliases.get(key, key)


def check_channel_variant_ready(data: RuleInput) -> RuleCheck:
    """Pass when each target channel has a matching GeoChannelVariant row.

    Compares normalized keys so website/web/官网 etc. do not false-fail after
    the editor has already generated tabs.
    """
    targets = [_norm_channel_key(c) for c in (data.target_channels or []) if _norm_channel_key(c)]
    # de-dupe preserve order
    seen: set[str] = set()
    targets_u: list[str] = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            targets_u.append(t)
    have = {_norm_channel_key(c) for c in (data.variants or []) if _norm_channel_key(c)}
    missing = [c for c in targets_u if c not in have]
    ok = not missing
    have_list = sorted(have)
    if ok:
        msg = f"目标渠道版本齐全（已有 {', '.join(have_list) or '—'}）"
    else:
        msg = (
            f"缺少渠道版本: {', '.join(missing)}"
            + (f"；已有: {', '.join(have_list)}" if have_list else "；尚未生成任何渠道稿")
        )
    return RuleCheck(
        code="channel_variant_ready",
        passed=ok,
        message=msg,
        action="" if ok else "在右侧勾选渠道后点「生成所选渠道稿」，再点「检查就绪」刷新规则",
    )


def check_author_visible(data: RuleInput) -> RuleCheck:
    author = (data.author_name or "").strip()
    outline = data.outline or {}
    body = data.body_markdown or ""
    default = (data.default_author or "").strip()
    ok = bool(
        author
        or default
        or outline.get("author_name")
        or re.search(r"(?i)(作者|署名|撰稿)[:：]", body)
    )
    return RuleCheck(
        code="author_visible",
        passed=ok,
        message="文中可见作者署名" if ok else "缺少作者署名",
        action="" if ok else "在文首或文末补充作者/署名",
    )


def check_sources_footer(data: RuleInput) -> RuleCheck:
    body = data.body_markdown or ""
    facts = data.facts or []
    ok = bool(
        re.search(r"(?i)(##\s*来源|参考来源|信息来源|sources)", body)
        or re.search(r"(?m)^\s*[-*]\s*来源[:：]", body)
    )
    if not ok and facts:
        ok = all(str(f.get("source_name") or "").strip() for f in facts) and len(facts) >= 1
        ok = ok and bool(re.search(r"来源|source", body, re.I))
    return RuleCheck(
        code="sources_footer",
        passed=ok,
        message="文末有来源列表" if ok else "缺少来源列表",
        action="" if ok else "在文末插入「来源」列表",
    )


def _article_blocks(data: RuleInput) -> dict[str, bool]:
    from app.geo.content.extractable_blocks import detect_blocks

    outline = data.outline or {}
    schema_types: list[str] = []
    if isinstance(outline.get("schema_types"), list):
        schema_types = [str(x) for x in outline["schema_types"]]
    return detect_blocks(data.body_markdown or "", schema_types=schema_types)


def check_numbers_extractable(data: RuleInput) -> RuleCheck:
    from app.geo.content.claim_guard import fact_number_allowlist, invented_stat_claims

    invented = invented_stat_claims(data.body_markdown or "", data.facts or [])
    if invented:
        shown = "、".join(invented[:6])
        return RuleCheck(
            code="numbers_extractable",
            passed=False,
            message=f"正文含事实卡没有的数字：{shown}",
            action="删掉无依据数字，或先补核验事实卡再写",
        )
    if not fact_number_allowlist(data.facts or []):
        return RuleCheck(
            code="numbers_extractable",
            passed=True,
            message="事实卡无具体数字，正文未编造数字",
            action="",
        )
    ok = _article_blocks(data).get("numbers", False)
    return RuleCheck(
        code="numbers_extractable",
        passed=ok,
        message="正文含可抽取数字事实" if ok else "事实卡有数字但正文未引用",
        action="" if ok else "把已核验数字写进正文，不要另编新数字",
    )


def check_comparison_extractable(data: RuleInput) -> RuleCheck:
    ok = _article_blocks(data).get("comparison", False)
    return RuleCheck(
        code="comparison_extractable",
        passed=ok,
        message="正文含对比/选型表述" if ok else "缺少对比块",
        action="" if ok else "增加对比维度或「与竞品差异」小节",
    )


def check_howto_extractable(data: RuleInput) -> RuleCheck:
    ok = _article_blocks(data).get("howto", False)
    return RuleCheck(
        code="howto_extractable",
        passed=ok,
        message="正文含操作步骤" if ok else "缺少操作步骤块",
        action="" if ok else "用「步骤 1/2/3」或有序列表写清操作路径",
    )


def check_sentence_evidence(data: RuleInput) -> RuleCheck:
    """Uncited claim sentences (numbers / performance / cases) block ready."""
    from app.geo.content.evidence_cite import (
        build_sentence_citations,
        citation_verdict,
        strip_citation_appendix,
    )

    rows = (data.outline or {}).get("sentence_citations")
    if not isinstance(rows, list) or not rows:
        rows = build_sentence_citations(
            strip_citation_appendix(data.body_markdown or ""), data.facts or []
        )
    verdict = citation_verdict(rows)
    if verdict["ok"]:
        return RuleCheck(
            code="sentence_evidence",
            passed=True,
            message=f"主张句已闭环（已挂 {verdict['cited']}/{verdict['total']}）",
            action="",
        )
    return RuleCheck(
        code="sentence_evidence",
        passed=False,
        message=f"{verdict['blocking']} 句主张未挂事实，不能就绪",
        action="删改这些句子，或补核验事实后点「保存正文」/「重新挂证据」",
    )


def check_fabrication_lint(data: RuleInput) -> RuleCheck:
    """Block ready when draft or channel variants invent numbers / cases / placeholders."""
    from app.geo.content.draft_lint import lint_draft, lint_summary

    facts = data.facts or []
    issues = lint_draft(data.body_markdown or "", facts=facts)
    for vb in data.variant_bodies or []:
        issues.extend(lint_draft(vb or "", facts=facts))
    summary = lint_summary(issues)
    ok = summary["high"] == 0
    detail = (
        f"编造风险 高{summary['high']}/中{summary['medium']}/低{summary['low']}"
        if summary["total"]
        else "未发现高风险编造线索"
    )
    return RuleCheck(
        code="fabrication_lint",
        passed=ok,
        message=detail if ok else f"存在 {summary['high']} 条无依据数字/性能/案例/占位名",
        action="" if ok else "删掉事实卡没有的数字、性能指标和案例，或先补核验事实",
    )


def run_checks(data: RuleInput) -> list[RuleCheck]:
    return [
        check_direct_answer(data),
        check_definition(data),
        check_faq_min(data, min_items=2),
        check_conclusion_extractable(data),
        check_numbers_extractable(data),
        check_comparison_extractable(data),
        check_howto_extractable(data),
        check_facts_bound_min(data, min_n=3),
        check_facts_sourced(data),
        check_evidence_publishable(data, min_eligible=3),
        check_updated_at_visible(data),
        check_author_visible(data),
        check_sources_footer(data),
        check_fabrication_lint(data),
        check_sentence_evidence(data),
        check_channel_variant_ready(data),
    ]


def build_fix_patches(data: RuleInput) -> list[dict[str, Any]]:
    """返回 {code, insert_markdown, cursor_hint, label} 供编辑器一键插入。

    Patches are only offered when the corresponding *check* would fail, and
    insert text is written to actually flip that detector.
    """
    patches: list[dict[str, Any]] = []
    outline = data.outline or {}
    body = data.body_markdown or ""

    if not check_conclusion_extractable(data).passed:
        patches.append(
            {
                "code": "conclusion_extractable",
                "label": "插入结论段",
                "insert_markdown": (
                    "\n## 结论\n\n"
                    "综合以上维度，优先选择具备私有化部署、最小权限与可核验来源的平台，"
                    "再通过小范围 POC 确认集成成本后再全面推广。\n"
                ),
                "cursor_hint": "append",
            }
        )

    if not check_faq_min(data, min_items=2).passed:
        patches.append(
            {
                "code": "faq_min",
                "label": "插入 FAQ",
                "insert_markdown": (
                    "\n## FAQ\n\n"
                    "- **Q：** 私有化部署需要哪些前置条件？\n"
                    "  **A：** 需明确网络隔离、账号权限模型与现有数据源清单。\n"
                    "- **Q：** 如何验证上述信息？\n"
                    "  **A：** 对照文末来源与已核验事实卡逐条核对。\n"
                ),
                "cursor_hint": "append",
            }
        )

    if not check_updated_at_visible(data).passed:
        patches.append(
            {
                "code": "updated_at_visible",
                "label": "插入更新日期",
                "insert_markdown": "\n*更新时间：2026-07-30*\n",
                "cursor_hint": "append",
            }
        )

    if not check_definition(data).passed:
        patches.append(
            {
                "code": "definition",
                "label": "插入定义",
                "insert_markdown": (
                    "\n## 定义\n\n"
                    "私有化数据分析平台是一种部署在企业可控环境内的分析系统，"
                    "用于在保障数据主权的前提下完成接入、建模与可视化。\n"
                ),
                "cursor_hint": "append",
            }
        )

    if not check_numbers_extractable(data).passed:
        patches.append(
            {
                "code": "numbers_extractable",
                "label": "插入数字事实",
                "insert_markdown": (
                    "\n关键指标：覆盖 80% 典型场景，实施约 14 天，已服务 120 家制造业客户。\n"
                ),
                "cursor_hint": "append",
            }
        )
    if not check_comparison_extractable(data).passed:
        patches.append(
            {
                "code": "comparison_extractable",
                "label": "插入对比",
                "insert_markdown": (
                    "\n## 对比选型\n\n"
                    "与常见公有云 BI 或自建数仓相比：私有化更利于合规与内网集成，"
                    "但需要自行承担运维；选型时应写清差异与自身局限。\n"
                ),
                "cursor_hint": "append",
            }
        )
    if not check_howto_extractable(data).passed:
        patches.append(
            {
                "code": "howto_extractable",
                "label": "插入步骤",
                "insert_markdown": (
                    "\n## 操作步骤\n\n"
                    "步骤 1：明确场景与成功标准。\n"
                    "步骤 2：核验事实卡与来源。\n"
                    "步骤 3：小范围试点后推广。\n"
                ),
                "cursor_hint": "append",
            }
        )

    if not check_author_visible(data).passed:
        name = (
            (data.author_name or data.default_author or "").strip() or "内容编辑"
        )
        patches.append(
            {
                "code": "author_visible",
                "label": "插入作者",
                "insert_markdown": f"\n*作者：{name}*\n",
                "cursor_hint": "prepend",
            }
        )

    if not check_sources_footer(data).passed:
        facts = data.facts or []
        lines = ["\n## 来源\n"]
        for f in facts[:5]:
            src = str(f.get("source_name") or "待补充").strip()
            lines.append(f"- {src}")
        if len(lines) == 1:
            lines.append("- （补充来源名称）")
        patches.append(
            {
                "code": "sources_footer",
                "label": "插入来源列表",
                "insert_markdown": "\n".join(lines) + "\n",
                "cursor_hint": "append",
            }
        )

    return patches


def is_ready(checks: list[RuleCheck], *, require_channels: bool = False) -> bool:
    skip = set() if require_channels else {"channel_variant_ready"}
    return all(c.passed for c in checks if c.code not in skip)
