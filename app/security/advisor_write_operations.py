"""Explicit daily GEO actions; shared by the route and object guards."""
from app.security.advisor_scope import deny

DAILY = {
    ("POST", "/content-tasks/{task_id}/submit-review"): "expected_article_id expected_updated_at note",
    ("POST", "/content-tasks/{task_id}/review"): "expected_article_id expected_updated_at decision note",
    ("PATCH", "/projects/{project_id}"): "name brand_name domain description",
    ("POST", "/facts/{fact_id}/verify"): "excerpt excerpt_locator source_url note expected_source_statement expected_source_name expected_source_url",
    ("POST", "/content-tasks/{task_id}/check"): "",
    ("POST", "/content-tasks/{task_id}/lint"): "",
    ("POST", "/content-tasks/{task_id}/retrieve-facts/apply"): "fact_ids",
}


def rules():
    from app.security.advisor_write_routes import FORBIDDEN, WriteRule
    return {(method, "/api/v1/geo" + path): WriteRule(
        method, "/api/v1/geo" + path, frozenset(fields.split()), FORBIDDEN,
        ("geo.assets", "geo.content"), "project")
        for (method, path), fields in DAILY.items()}


def task_templates():
    return {path for _, path in rules() if "{task_id}" in path}


async def read_contract(request, rule):
    """Allow an absent body only on actions whose contract has no fields."""
    import json
    query = {"tenant_id"}
    if rule.template == "/api/v1/geo/content-tasks/{task_id}/check":
        query.add("require_channels")
    seen = set()
    for key, value in request.query_params.multi_items():
        if key in seen or key not in query or (key == "require_channels" and value not in {"true", "false"}):
            deny(403, "ADVISOR_WRITE_FIELD_FORBIDDEN", "请只提交这个操作支持的参数")
        seen.add(key)
    raw = await request.body()
    if not raw.strip() and not rule.fields:
        return {}
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                deny(403, "ADVISOR_WRITE_FIELD_FORBIDDEN", "参数不能重复")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        deny(403, "ADVISOR_WRITE_FIELD_FORBIDDEN", "请提交有效的操作参数")
