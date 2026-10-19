"""SEO advisor operation records. Never log request text or credentials."""
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("seo.advisor.operations")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())


def record(request, ctx, result, *, evidence=None):
    path, object_ids = request.url.path, dict(request.path_params)
    if path.startswith('/api/v1/seo/distribution/v1/'):
        path = getattr(request.scope.get('route'), 'path', '/api/v1/seo/distribution/v1')
        object_ids = {}  # Registry UUIDs already have safe business-ledger audit.
    logger.info(json.dumps({
        "event": "seo_advisor_operation", "user_id": ctx.user_id,
        "tenant_id": ctx.tenant_id, "method": request.method,
        "path": path, "object_ids": object_ids,
        "result": result, "time": datetime.now(timezone.utc).isoformat(),
        **(evidence or {}),
    }, ensure_ascii=False, sort_keys=True))


async def operation_audit(request, call_next):
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        ctx = getattr(request.state, "seo_advisor_actor", None)
        if ctx is not None:
            record(request, ctx, status, evidence=getattr(request.state, "seo_advisor_evidence", None))


def install_commit_guard(session, ctx, request):
    """All commits on this request session repeat grant/assignment validation.

    The session belongs to this request; background/global session factories are
    not changed. Explicit handler checks remain in place as well.
    """
    if getattr(session, "_seo_advisor_commit_guard", False):
        return
    original = session.commit

    async def commit():
        from app.security.advisor_write_commit import recheck_advisor_before_commit
        await recheck_advisor_before_commit(session, ctx)
        created = list(getattr(session, "new", ()))
        changed = created + list(getattr(session, 'dirty', ())) + list(getattr(session, 'deleted', ()))
        from app.security.seo_advisor_reviews import prepare_review_evidence
        await prepare_review_evidence(session, ctx, created + list(getattr(session, 'dirty', ())))
        await original()
        evidence = {**getattr(request.state, "seo_advisor_evidence", {}),
                    'changed_objects': [{'table': row.__tablename__, 'id': row.id}
                                        for row in changed if hasattr(row, '__tablename__') and hasattr(row, 'id')],
                    "created_objects": [{"table": row.__tablename__, "id": row.id}
                                        for row in created if hasattr(row, "__tablename__") and hasattr(row, "id")]}
        record(request, ctx, "committed", evidence=evidence)

    session.commit = commit
    session._seo_advisor_commit_guard = True
    session._seo_advisor_context = ctx
    session._seo_advisor_request = request
