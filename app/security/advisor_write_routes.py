"""Exact, intentionally narrow GEO manual-content write policy."""
from dataclasses import dataclass

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
_register("PATCH", "/optimization-businesses/{business_id}", _BUSINESS)
_register("POST", "/optimization-units", "tenant_id business_id " + _UNIT)
_register("PATCH", "/optimization-units/{unit_id}", _UNIT)
_register("POST", "/content-tasks", "tenant_id prompt_id title target_channels fact_ids brief")
_register("PATCH", "/content-tasks/{task_id}", "title brief target_channels")
_register("PUT", "/content-tasks/{task_id}/facts", "fact_ids")
_register("PUT", "/content-tasks/{task_id}/article", "expected_article_id title body_markdown")
_register("PATCH", "/content-tasks/{task_id}/variants/{channel}", "title body_markdown")


def match_write_rule(request) -> WriteRule | None:
    # Never fall back to the URL or a prefix when route resolution is missing.
    return WRITE_ROUTES.get((request.method, getattr(request.scope.get("route"), "path", None)))


def check_write_fields(rule: WriteRule, body: dict) -> None:
    def forbidden():
        deny(403, "ADVISOR_WRITE_FIELD_FORBIDDEN", "此字段或操作未向顾问开放")

    if not isinstance(body, dict) or set(body) - rule.fields or set(body) & rule.forbidden:
        forbidden()
    if "trust_level" in body and body["trust_level"] not in ("draft", "needs_review"):
        forbidden()
    if "source" in body and body["source"] != "manual":
        forbidden()
    if rule.template.endswith("/article") and "expected_article_id" not in body:
        forbidden()
    if "expected_article_id" in body and body["expected_article_id"] is not None:
        if type(body["expected_article_id"]) is not int or body["expected_article_id"] <= 0:
            forbidden()
    # All supported containers have a defined shape; opaque metadata/profile/
    # outline are deliberately excluded instead of silently dropping their keys.
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
        if key != "brief" and isinstance(value, dict):
            forbidden()
        if key not in {"tags", "target_channels", "fact_ids"} and isinstance(value, list):
            forbidden()
    if "fact_ids" in body and (not isinstance(body["fact_ids"], list) or
            any(type(item) is not int or item <= 0 for item in body["fact_ids"])):
        forbidden()
