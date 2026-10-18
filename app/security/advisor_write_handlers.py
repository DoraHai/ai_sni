"""Defense in depth for the admitted GEO handlers, including direct callers."""
from app.security.advisor_scope import deny
from app.security.advisor_write_routes import WRITE_ROUTES, check_write_fields


def check_handler_fields(ctx, method, suffix, req):
    if getattr(ctx, "advisor_scope", None) is not None:
        check_write_fields(WRITE_ROUTES[(method, "/api/v1/geo" + suffix)],
                           req.model_dump(exclude_unset=True))


async def lock_manual_task(session, ctx, task, *, already_locked=False):
    if getattr(ctx, "advisor_scope", None) is None:
        return
    if not already_locked:
        await session.refresh(task, with_for_update=True)
    # Actual GEO draft states; generating/review/ready/published/archived are
    # excluded so manual edits cannot race or invalidate customer decisions.
    if task.status not in {"draft", "facts_bound", "editing", "needs_fix", "failed"}:
        deny(403, "ADVISOR_WRITE_STATE_FORBIDDEN", "当前任务状态不允许顾问手工编辑")
