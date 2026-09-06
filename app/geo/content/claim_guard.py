"""Reject invented numbers / performance / case claims not present in bound facts."""

from __future__ import annotations

import re
from typing import Any

_NUM = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*(%|％|个|人|名|家|秒|分钟|小时|天|日|周|月|年|万|亿|倍)?"
)

_STAT_UNITS = {"%", "％", "个", "人", "名", "家", "秒", "分钟", "小时", "天", "日", "万", "亿", "倍"}

_PERF_TERMS = (
    "识别率",
    "准确率",
    "召回率",
    "满意度",
    "接通率",
    "解决率",
    "可用率",
    "SLA",
    "并发",
    "响应时间",
    "平均响应",
    "秒级响应",
    "毫秒",
)

_CASE_TERMS = (
    "成功案例",
    "客户案例",
    "标杆客户",
    "头部客户",
    "合作客户",
    "世界500强",
    "500强客户",
    "标杆项目",
    "落地案例",
)

# Qualitative assertions also need evidence. Match assertion spans, not a list
# of industries: a familiar product name is not proof of the added application
# or causal explanation. Conservative matching deliberately requires review of
# paraphrases/translations that cannot be established from the stored statement.
_QUALITATIVE = re.compile(
    r"(?:适用于|适合于|可用于|可覆盖|可成为|广泛用于|例如|比如|如[：:]|诸如)[^。！？!?；;\n]{2,100}"
    r"|(?:包括|例如|如)[^。！？!?；;\n]{2,60}(?:设备|机械|机)[^。！？!?；;\n]{0,40}"
    r"|[^。！？!?；;\n]{0,45}(?:导致|防止|直接影响|决定了|有效降低|延长|缩短)[^。！？!?；;\n]{2,100}"
)


def qualitative_claims(text: str, facts: list[dict[str, Any]]) -> list[dict[str, str]]:
    def compact(value: str) -> str:
        return re.sub(r"[\s*]+", "", value).casefold()

    # Titles and source labels are not verified statements.
    statements = [compact(str(f.get('statement') or '')) for f in facts or []]
    def supported(span: str) -> bool:
        needle = compact(span)
        for statement in statements:
            for found in re.finditer(re.escape(needle), statement):
                prefix = re.split(r'[。！？!?；;\n]', statement[:found.start()])[-1]
                suffix = statement[found.end():]
                # Do not drop a source's negation, restriction or trailing
                # condition and turn a qualified statement into a guarantee.
                if re.search(r'不|未|仅|只|限|假设|如果|可能', prefix):
                    continue
                if suffix and suffix[0] not in '。！？!?；;':
                    continue
                return True
        return False

    hits = []
    body = re.sub(r"[（(]来源[：:][^）)\n]*[）)]", "", text or '')
    for match in _QUALITATIVE.finditer(body):
        span = match.group().strip()
        if not supported(span):
            hits.append({'kind': 'qualitative', 'token': span, 'excerpt': span[:180]})
    return hits


def _norm_num(raw: str) -> str:
    return raw.replace("％", "%").strip()


def norm_stat_token(raw: str) -> str:
    """Collapse '48 小时' / '48小时' / '48％' into one comparable token."""
    s = _norm_num(raw).replace(",", "")
    return re.sub(r"\s+", "", s).lower()


def number_token_allowed(val: str, allowed: set[str]) -> bool:
    nv = norm_stat_token(val)
    if not nv:
        return False
    allowed_n = {norm_stat_token(x) for x in allowed if str(x).strip()}
    return nv in allowed_n


def _fact_blob(facts: list[dict[str, Any]]) -> str:
    return " ".join(
        f"{f.get('title') or ''} {f.get('statement') or ''} {f.get('source_name') or ''}"
        for f in facts or []
    )


def _is_calendar_token(num: str, unit: str) -> bool:
    """Years / calendar months are not performance stats."""
    try:
        nval = float(str(num).replace(",", ""))
    except ValueError:
        return False
    if unit == "年" and 1900 <= nval <= 2100:
        return True
    if unit == "月" and 1 <= nval <= 12:
        return True
    return False


def numbers_in_text(text: str) -> set[str]:
    out: set[str] = set()
    for m in _NUM.finditer(text or ""):
        token = _norm_num(m.group(0))
        if token in {"24", "7", "365"} and not m.group(2):
            continue
        compact = norm_stat_token(token)
        out.add(token)
        out.add(compact)
        out.add(_norm_num(m.group(1)))
    return out


def fact_number_allowlist(facts: list[dict[str, Any]]) -> set[str]:
    return numbers_in_text(_fact_blob(facts))


def invented_numbers(text: str, facts: list[dict[str, Any]]) -> list[str]:
    allowed = fact_number_allowlist(facts)
    found = numbers_in_text(text)
    hits: list[str] = []
    for t in found:
        if t in allowed:
            continue
        if t.isdigit() and int(t) < 2:
            continue
        hits.append(t)
    return sorted(set(hits))


def invented_stat_claims(text: str, facts: list[dict[str, Any]]) -> list[str]:
    """Concrete stats (percent / 坐席 / 秒 / 天 / 家) must appear in facts."""
    return [c["token"] for c in ungrounded_claims(text, facts) if c["kind"] == "number"]


def ungrounded_claims(text: str, facts: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Numbers, performance phrases, and case boasts not grounded in facts."""
    allowed = fact_number_allowlist(facts)
    blob = _fact_blob(facts)
    body = text or ""
    hits: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(kind: str, token: str, excerpt: str) -> None:
        key = (kind, token)
        if key in seen:
            return
        seen.add(key)
        hits.append({"kind": kind, "token": token, "excerpt": excerpt[:80]})

    allowed_n = {norm_stat_token(x) for x in allowed if str(x).strip()}
    for m in _NUM.finditer(body):
        unit = m.group(2) or ""
        token = _norm_num(m.group(0))
        num = _norm_num(m.group(1))
        compact = norm_stat_token(token)
        if unit not in _STAT_UNITS:
            continue
        if _is_calendar_token(num, unit):
            continue
        # Same number+unit, ignoring spaces: 48小时 == 48 小时.
        # Do not treat bare "48" as covering "48%" / "48小时".
        if compact in allowed_n or (not unit and num in allowed_n):
            continue
        start = max(0, m.start() - 12)
        _add("number", compact or token, body[start : m.end() + 12].replace("\n", " "))

    for term in _PERF_TERMS:
        if term in body and term not in blob:
            _add("performance", term, term)

    for term in _CASE_TERMS:
        if term in body and term not in blob:
            _add("case", term, term)

    hits.extend(qualitative_claims(body, facts))

    return hits


def format_ungrounded(claims: list[dict[str, str]], *, limit: int = 8) -> str:
    parts: list[str] = []
    labels = {"number": "数字", "performance": "性能表述", "case": "案例表述", "qualitative": "适用性或机理表述"}
    for c in claims[:limit]:
        parts.append(f"{labels.get(c['kind'], c['kind'])}「{c['token']}」")
    return "、".join(parts)
