"""SEO advisor operation records. Never log request text or credentials."""
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("seo.advisor.operations")
logger.setLevel(logging.INFO)


def record(request, ctx, result, *, evidence=None):
    logger.info(json.dumps({
        "event": "seo_advisor_operation", "user_id": ctx.user_id,
        "tenant_id": ctx.tenant_id, "method": request.method,
        "path": request.url.path, "object_ids": dict(request.path_params),
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
        from app.security.seo_advisor_reviews import prepare_review_evidence
        await prepare_review_evidence(session, ctx, created + list(getattr(session, 'dirty', ())))
        await original()
        evidence = {**getattr(request.state, "seo_advisor_evidence", {}),
                    "created_objects": [{"table": row.__tablename__, "id": row.id}
                                        for row in created if hasattr(row, "__tablename__") and hasattr(row, "id")]}
        record(request, ctx, "committed", evidence=evidence)

    session.commit = commit
    session._seo_advisor_commit_guard = True
