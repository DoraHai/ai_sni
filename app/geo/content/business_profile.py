"""业务线画像：内容/策略/监测统一读取的上下文字段。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

PROFILE_LABELS = dict(zip(
    ('product_name', 'website', 'summary', 'honors', 'qualifications', 'capabilities',
     'audience', 'scenarios', 'geo_scope', 'industry', 'competitors',
     'recommend_reasons', 'banned_claims', 'cta'),
    ('品牌名称', '官网地址', '品牌简介', '品牌口号', '资质证书', '产品能力',
     '目标受众', '使用场景', '服务区域', '所属行业', '竞争对手',
     '推荐理由', '禁用说法', '行动引导'),
))
PROFILE_LIST_FIELDS = frozenset({'honors', 'qualifications', 'capabilities', 'scenarios',
                                  'competitors', 'recommend_reasons', 'banned_claims'})
PROFILE_STRING_MAX = 500
PROFILE_LIST_MAX = 20
PROFILE_ITEM_MAX = 500
PROFILE_LIST_TEXT_MAX = PROFILE_LIST_MAX * (PROFILE_ITEM_MAX + 1) - 1


def profile_items(value: str) -> list[str]:
    import re
    return [item.strip() for item in re.split(r'[,，；\n]', value) if item.strip()]


def validate_profile(raw: Any) -> dict:
    """Validate the entire submitted patch before any normalization or writes."""
    if not isinstance(raw, dict):
        raise ValueError('品牌资料必须按字段填写，不能提交空值、列表或嵌套对象')
    if set(raw) - PROFILE_LABELS.keys():
        raise ValueError('品牌资料含未开放的字段，请只保存品牌名称、官网、简介等已开放资料')
    for key, value in raw.items():
        label = PROFILE_LABELS[key]
        if key in PROFILE_LIST_FIELDS:
            if isinstance(value, str):
                if len(value) > PROFILE_LIST_TEXT_MAX:
                    raise ValueError(f'{label} 最多 {PROFILE_LIST_TEXT_MAX} 字，现在 {len(value)} 字')
                value = profile_items(value)
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValueError(f'{label} 请填写文字或文字列表')
            if len(value) > PROFILE_LIST_MAX:
                raise ValueError(f'{label} 最多 {PROFILE_LIST_MAX} 条，现在 {len(value)} 条')
            for item in value:
                if len(item) > PROFILE_ITEM_MAX:
                    raise ValueError(f'{label}每条最多 {PROFILE_ITEM_MAX} 字，现在 {len(item)} 字')
        else:
            if not isinstance(value, str):
                raise ValueError(f'{label} 必须是文字')
            if len(value) > PROFILE_STRING_MAX:
                raise ValueError(f'{label} 最多 {PROFILE_STRING_MAX} 字，现在 {len(value)} 字')
            if key == 'website' and value.strip():
                site = value.strip()
                try:
                    url = urlsplit(site)
                    valid = (site.lower().startswith(('http://', 'https://'))
                             and bool(url.hostname) and url.username is None and url.password is None
                             and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c == '\\' for c in site))
                    url.port
                except ValueError:
                    valid = False
                if not valid:
                    raise ValueError('官网地址要以 http:// 或 https:// 开头，请填写完整网址，不能含账号信息')
    return raw

PROFILE_KEYS = (
    "product_name",
    "website",
    "summary",
    "honors",
    "qualifications",
    "capabilities",
    "audience",
    "scenarios",
    "geo_scope",
    "industry",
    "competitors",
    "recommend_reasons",
    "banned_claims",
    "cta",
)


def normalize_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key in PROFILE_KEYS:
        val = data.get(key)
        if key in {
            "honors",
            "qualifications",
            "capabilities",
            "scenarios",
            "competitors",
            "recommend_reasons",
            "banned_claims",
        }:
            if isinstance(val, str):
                items = profile_items(val)
            elif isinstance(val, list):
                items = [str(x).strip() for x in val if str(x).strip()]
            else:
                items = []
            out[key] = items
        else:
            out[key] = str(val or "").strip()
    return out


def display_brand(profile: dict[str, Any] | None, *, fallback: str) -> str:
    p = normalize_profile(profile)
    return p.get("product_name") or fallback


def brand_names_for_profile(profile: dict[str, Any] | None, *, fallback: str) -> list[str]:
    """Probe / mention matching names. Prefer product, do not mix another brand."""
    product = display_brand(profile, fallback="")
    if product:
        return [product]
    fb = (fallback or "").strip()
    return [fb] if fb else []


def profile_brief_hints(profile: dict[str, Any] | None) -> dict[str, Any]:
    p = normalize_profile(profile)
    hints: dict[str, Any] = {}
    if p.get("industry"):
        hints["industry"] = p["industry"]
    if p.get("audience"):
        hints["audience"] = p["audience"]
    if p.get("cta"):
        hints["cta"] = p["cta"]
    if p.get("banned_claims"):
        hints["banned_claims"] = p["banned_claims"]
    if p.get("competitors"):
        hints["competitors"] = p["competitors"]
    must = list(p.get("capabilities") or []) + list(p.get("recommend_reasons") or [])
    if must:
        hints["must_cover"] = must[:8]
    if p.get("scenarios"):
        hints["recommend_when"] = "；".join(p["scenarios"][:3])
    return hints
