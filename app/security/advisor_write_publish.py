"""Exact publication contracts; credentials/configuration are never writable."""
PREFIX = "/api/v1/geo/content-tasks/{task_id}"
VARIANTS = PREFIX + "/variants"
PUSH_BATCH = PREFIX + "/push-batch"
FIELDS = {
    PREFIX + "/export": "expected_revision",
    PREFIX + "/publications": "tenant_id channel custom_channel_name source_variant_id published_url note",
    PREFIX + "/push": "tenant_id channel account_id mode create_publication published_url note",
    PUSH_BATCH: "tenant_id mode create_publication targets note",
    VARIANTS: "channels use_llm",
}


def rules():
    from app.security.advisor_write_routes import FORBIDDEN, WriteRule
    return {("POST", path): WriteRule("POST", path, frozenset(fields.split()),
             FORBIDDEN - {"published_url", "use_llm"}, ("geo.assets", "geo.content"), "project")
            for path, fields in FIELDS.items()}


async def recheck_external(session, result, **objects):
    """Recheck immediately before each connector attempt, including retries."""
    binding = getattr(session, "info", {}).get("advisor_scoped_write")
    if binding is None:
        return
    from app.security.advisor_write_commit import recheck_advisor_before_commit
    from app.security.advisor_write_audit import record
    if result == "external_returned":
        record(binding[1].scope, result, **objects)
    await recheck_advisor_before_commit(session, binding[0])
    if result == "external_returned":
        return
    record(binding[1].scope, result, **objects)


def check_fields(rule, body):
    from app.security.advisor_scope import deny
    if rule.template not in FIELDS:
        return
    def invalid():
        deny(403, "ADVISOR_WRITE_FIELD_FORBIDDEN", "请只填写本次发布操作支持的参数")
    for key in {"use_llm", "create_publication"} & body.keys():
        if type(body[key]) is not bool:
            invalid()
    if "mode" in body and body["mode"] not in {"draft", "publish"}:
        invalid()
    if body.get("targets") is not None:
        targets = body["targets"]
        if not isinstance(targets, list) or len(targets) > 100:
            invalid()
        for target in targets:
            if not isinstance(target, dict) or set(target) != {"account_id", "channel"}:
                invalid()
    if "channels" in body and (not isinstance(body["channels"], list) or not 1 <= len(body["channels"]) <= 20
            or any(not isinstance(c, str) for c in body["channels"])):
        invalid()
