"""No schema change: one structured event per advisor HTTP operation/commit.

Only declared identifiers and review fingerprints are logged. Never bodies,
headers, credentials, URLs supplied by a customer, or exception text.
"""
from datetime import datetime, timezone
import json
import logging

logger = logging.getLogger("geo.advisor.operations")
logger.setLevel(logging.INFO)
if not logger.handlers:
    # Uvicorn need not configure the root logger. Always emit the audit JSON
    # to the service's captured stderr even when root defaults to WARNING.
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def record(scope, result, **extra):
    actor = scope.get("geo_advisor_actor")
    if not actor:
        return
    user_id, tenant_id = actor
    objects = {key: value for key, value in scope.get("path_params", {}).items()
               if key.endswith("_id") and str(value).isascii() and str(value).isdecimal()}
    for table, ids in scope.get("geo_advisor_created_ids", {}).items():
        objects[table] = sorted(ids)
    event = {"event": "geo_advisor_operation", "advisor_user_id": user_id,
             "tenant_id": tenant_id, "method": scope["method"], "path": scope["path"],
             "object_ids": objects, "result": result,
             "time": datetime.now(timezone.utc).isoformat(), **extra}
    if scope.get("geo_advisor_review"):
        event["review"] = scope["geo_advisor_review"]
    logger.info(json.dumps(event, ensure_ascii=False, sort_keys=True))
