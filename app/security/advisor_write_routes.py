"""Exact, deliberately small admission contract for manual SEO advisor writes."""
from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True)
class WriteRule:
    method: str
    template: str
    fields: frozenset[str]
    forbidden: frozenset[str]
    edit_all: tuple[str, ...]
    assignment: str
    workflow: bool = False


_FORBIDDEN = frozenset({
    "owner_user_id", "advisor_user_id", "project_id", "verified", "verified_at",
    "verified_by", "public_use_allowed", "published", "published_at", "page_url",
    "archived", "archived_at", "deleted", "deleted_at", "action", "operation",
})
_FACT = frozenset({"tenant_id", "site_id", "title", "statement", "source_name", "source_url", "expires_at", "status"})
_CONTENT = frozenset({
    "title", "outline", "draft", "humanized_content", "source_text", "keyword_id",
    "keyword_ids", "source_page_id", "content_type", "target_platforms", "author", "status",
})


def _rule(method, template, fields, permission):
    return WriteRule(method, "/api/v1/seo" + template, fields,
                     _FORBIDDEN, (permission,), "site")


_RULES = (
    _rule("POST", "/qa/facts", _FACT, "seo.content"),
    # tenant/site here are required scope selectors in the existing FactEdit
    # schema; the handler never assigns them and B checks the object's scope.
    _rule("PATCH", "/qa/facts/{fact_id}", _FACT | {"version"}, "seo.content"),
    _rule("POST", "/rank-serp/brand-assets", frozenset({"tenant_id", "site_id", "asset_type", "name", "match_value", "platform"}), "seo.keywords"),
    _rule("PATCH", "/rank-serp/brand-assets/{asset_id}", frozenset({"name", "match_value", "platform", "status"}), "seo.keywords"),
    _rule("POST", "/content-assets", _CONTENT | {"tenant_id", "site_id"}, "seo.content"),
    _rule("PATCH", "/content-assets/{content_id}", _CONTENT | {"version_count"}, "seo.content"),
    _rule("PUT", "/content-assets/{content_id}/source-page", frozenset({"source_page_id", "version_count"}), "seo.content"),
)
WRITE_ROUTES: dict[tuple[str, str], WriteRule] = {(r.method, r.template): r for r in _RULES}

from app.security.seo_advisor_work import workflow_rules
WRITE_ROUTES.update({(r.method, r.template): r for r in workflow_rules(WriteRule)})
from app.security.seo_advisor_reviews import review_rules
WRITE_ROUTES.update({(r.method, r.template): r for r in review_rules(WriteRule)})
from app.security.seo_advisor_publishing import publishing_rules
WRITE_ROUTES.update({(r.method, r.template): r for r in publishing_rules(WriteRule)})


def match_write_rule(request) -> WriteRule | None:
    # Never fall back to a URL prefix or a caller-supplied route template.
    return WRITE_ROUTES.get((request.method, getattr(request.scope.get("route"), "path", None)))


def check_write_fields(rule: WriteRule, body: dict) -> None:
    if rule.workflow:
        from app.security.seo_advisor_work import check_workflow_fields
        return check_workflow_fields(rule, body)
    def forbidden():
        raise HTTPException(403, {"code": "ADVISOR_WRITE_FIELD_FORBIDDEN"})

    if not isinstance(body, dict) or set(body) - rule.fields or set(body) & rule.forbidden:
        forbidden()
    # These seven schemas contain no nested objects. Do not let Pydantic's
    # ignored extras or coercion conceal actions/IDs inside editable fields.
    for key, value in body.items():
        if key in {"keyword_ids", "target_platforms"} and value is not None:
            if not isinstance(value, list) or any(isinstance(v, (dict, list)) for v in value):
                forbidden()
        elif isinstance(value, (dict, list)):
            forbidden()
    if "status" in body:
        allowed = ({"active", "retired"} if "/qa/facts" in rule.template else
                   {"active", "archived"} if "/brand-assets" in rule.template else {"planned", "drafting", "archived"})
        if body["status"] not in allowed:
            forbidden()
        if rule.method == 'POST' and '/content-assets' in rule.template and body['status'] == 'archived':
            forbidden()
    version = "version" if "/qa/facts/" in rule.template else "version_count"
    if rule.method in {"PATCH", "PUT"} and version in rule.fields:
        if body.get(version) is None:
            raise HTTPException(422, {"code": "ADVISOR_WRITE_VERSION_REQUIRED"})
        if type(body[version]) is not int or body[version] < 1:
            raise HTTPException(422, {"code": "ADVISOR_INVALID_WRITE_VERSION"})


def check_advisor_handler(ctx, method, template, body, row=None):
    """Repeat field/status constraints on the freshly locked handler object."""
    if not getattr(ctx, "is_advisor", False):
        return
    rule = WRITE_ROUTES[(method, "/api/v1/seo" + template)]
    check_write_fields(rule, body)
    if rule.workflow:
        return
    if row is not None:
        if '/content-assets/' in template and row.status == 'archived' and (
            set(body) - {'status', 'version_count'} or body.get('status') not in {'planned', 'drafting'}
        ):
            raise HTTPException(403, {'code': 'ADVISOR_WRITE_STATE_FORBIDDEN'})
        allowed = ({"active", "retired"} if "/qa/facts" in template else
                   {"active", "archived"} if "/brand-assets" in template else {"planned", "drafting", "archived"})
        if row.status not in allowed:
            raise HTTPException(403, {"code": "ADVISOR_WRITE_STATE_FORBIDDEN"})
