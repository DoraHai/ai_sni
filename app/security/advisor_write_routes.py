"""Exact, intentionally narrow GEO manual-content write policy."""
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.security.advisor_scope import deny


@dataclass(frozen=True)
class WriteRule:
    method: str
    template: str
    fields: frozenset[str]
    forbidden: frozenset[str]
    edit_all: tuple[str, ...]
    assignment: str


FORBIDDEN = frozenset({
    "status", "owner_user_id", "advisor_user_id", "project_id", "site_id",
    "verified", "public_use_allowed", "published", "published_url",
    "verified_translation", "verified_translations", "verification", "public_use",
    "enabled", "action", "use_llm", "run_async", "created_by", "deleted_at",
})
BRIEF_FIELDS = frozenset({
    "industry", "audience", "intent", "content_type", "cta", "banned_claims", "notes",
    "ai_question", "not_recommended_reasons", "info_gaps", "recommend_when",
    "competitors", "must_cover", "source_bar", "strategy_notes", "schema_version",
})
# Match business_profile.normalize_profile: scalar strings stay within its
# 500-character storage limit; list fields accept form text or string lists.
PROFILE_STRING_FIELDS = frozenset({
    "product_name", "website", "summary", "industry", "audience", "cta",
})
PROFILE_LIST_FIELDS = frozenset({
    "honors", "qualifications", "capabilities", "scenarios", "competitors",
    "recommend_reasons", "banned_claims",
})
PROFILE_STRING_MAX = 500
PROFILE_LIST_MAX = 20
PROFILE_ITEM_MAX = 500
PROFILE_LIST_TEXT_MAX = PROFILE_LIST_MAX * (PROFILE_ITEM_MAX + 1) - 1
WRITE_ROUTES: dict[tuple[str, str], WriteRule] = {}


def _register(method, suffix, fields):
    template = "/api/v1/geo" + suffix
    rule = WriteRule(method, template, frozenset(fields.split()), FORBIDDEN,
                     ("geo.assets", "geo.content"), "project")
    WRITE_ROUTES[(method, template)] = rule


_FACT = "title statement fact_type source_name source_url observed_at expires_at author_name trust_level"
_PROMPT = "question priority tags demand_note question_group market"
_BUSINESS = "name description sort_order"
_UNIT = "name keyword description sort_order"
_register("POST", "/facts", "tenant_id business_id " + _FACT)
_register("PATCH", "/facts/{fact_id}", _FACT)
_register("POST", "/prompts", "tenant_id unit_id language source " + _PROMPT)
_register("PATCH", "/prompts/{prompt_id}", _PROMPT)
_register("POST", "/optimization-businesses", "tenant_id " + _BUSINESS)
_register("PATCH", "/optimization-businesses/{business_id}", _BUSINESS + " profile")
_register("POST", "/optimization-units", "tenant_id business_id " + _UNIT)
_register("PATCH", "/optimization-units/{unit_id}", _UNIT)
_register("POST", "/content-tasks", "tenant_id prompt_id title target_channels fact_ids brief")
_register("POST", "/content-imports/create-task",
          "tenant_id prompt_id title body_markdown source_type source_url target_channels")
_register("PATCH", "/content-tasks/{task_id}", "title brief target_channels")
_register("PUT", "/content-tasks/{task_id}/facts", "fact_ids")
_register("PUT", "/content-tasks/{task_id}/article", "expected_article_id title body_markdown")
_register("PATCH", "/content-tasks/{task_id}/variants/{channel}", "title body_markdown")

# A single paid action, separate from the 13 manual-content rules. No client
# engine, prompt limit, scheduling or execution switches are admitted.
VISIBILITY_RUN_RULE = WriteRule(
    "POST", "/api/v1/geo/visibility-patrol/runs", frozenset({"tenant_id"}),
    FORBIDDEN, ("geo.assets", "geo.content"), "visibility",
)


def match_write_rule(request) -> WriteRule | None:
    # Never fall back to the URL or a prefix when route resolution is missing.
    key = (request.method, getattr(request.scope.get("route"), "path", None))
    if key == (VISIBILITY_RUN_RULE.method, VISIBILITY_RUN_RULE.template):
        return VISIBILITY_RUN_RULE
    return WRITE_ROUTES.get(key)


def check_write_fields(rule: WriteRule, body: dict) -> None:
    def forbidden():
        deny(403, "ADVISOR_WRITE_FIELD_FORBIDDEN", "此字段或操作未向顾问开放")

    if not isinstance(body, dict) or set(body) - rule.fields or set(body) & rule.forbidden:
        forbidden()
    if 'body_markdown' in body and isinstance(body['body_markdown'], str) and len(body['body_markdown']) > 500_000:
        deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '文章正文不能超过 50 万字，请拆分后保存')
    if "trust_level" in body and body["trust_level"] not in ("draft", "needs_review"):
        forbidden()
    if "source" in body and body["source"] != "manual":
        forbidden()
    if rule.template == "/api/v1/geo/content-imports/create-task" and body.get("source_type") not in ("paste", "file"):
        forbidden()
    if rule.template.endswith("/article") and "expected_article_id" not in body:
        forbidden()
    if "expected_article_id" in body and body["expected_article_id"] is not None:
        if type(body["expected_article_id"]) is not int or body["expected_article_id"] <= 0:
            forbidden()
    # Validate raw input before schema coercion or normalization can hide keys,
    # truncate strings/lists, or turn an object into display text.
    if "profile" in body:
        profile = body["profile"]
        def profile_forbidden(message):
            deny(403, "ADVISOR_WRITE_FIELD_FORBIDDEN", message)

        if not isinstance(profile, dict):
            profile_forbidden("品牌资料必须按字段填写，不能提交空值、列表或嵌套对象")
        if set(profile) - (PROFILE_STRING_FIELDS | PROFILE_LIST_FIELDS):
            profile_forbidden("品牌资料含未开放的字段，请只保存品牌名称、官网、简介等已开放资料")
        for key, value in profile.items():
            if key in PROFILE_STRING_FIELDS:
                if not isinstance(value, str) or len(value) > PROFILE_STRING_MAX:
                    profile_forbidden(f"品牌资料 {key} 必须是文字，最多 {PROFILE_STRING_MAX} 个字符")
                if key == 'website' and value.strip():
                    try:
                        url = urlsplit(value.strip())
                        valid = (url.scheme in {'http', 'https'} and bool(url.hostname)
                                 and url.username is None and url.password is None
                                 and not any(c.isspace() or ord(c) < 32 or c == '\\' for c in value.strip()))
                        url.port
                    except ValueError:
                        valid = False
                    if not valid:
                        profile_forbidden('官网请填写完整的 http:// 或 https:// 网址，不能含账号信息')
            else:
                if isinstance(value, str) and len(value) <= PROFILE_LIST_TEXT_MAX:
                    # Use the same separators as normalize_profile.
                    value = [p.strip() for p in value.replace("；", ",").replace("\n", ",").split(",") if p.strip()]
                if (not isinstance(value, list) or len(value) > PROFILE_LIST_MAX or
                        any(not isinstance(item, str) or len(item) > PROFILE_ITEM_MAX for item in value)):
                    profile_forbidden(f"品牌资料 {key} 请填写文字或文字列表，最多 {PROFILE_LIST_MAX} 条，每条最多 {PROFILE_ITEM_MAX} 个字符")
    # Other supported containers also have a defined shape; opaque metadata/
    # outline remain excluded instead of silently dropping their keys.
    brief = body.get("brief")
    if brief is not None:
        if not isinstance(brief, dict) or set(brief) - BRIEF_FIELDS:
            forbidden()
        for value in brief.values():
            if isinstance(value, dict) or (isinstance(value, list) and
                    any(not isinstance(item, str) for item in value)):
                forbidden()
    for key in ("tags", "target_channels"):
        if key in body and (not isinstance(body[key], list) or
                            any(not isinstance(item, str) for item in body[key])):
            forbidden()
    for key, value in body.items():
        if key not in {"brief", "profile"} and isinstance(value, dict):
            forbidden()
        if key not in {"tags", "target_channels", "fact_ids"} and isinstance(value, list):
            forbidden()
    if "fact_ids" in body and (not isinstance(body["fact_ids"], list) or
            len(body["fact_ids"]) > 50 or
            any(type(item) is not int or item <= 0 for item in body["fact_ids"])):
        forbidden()
