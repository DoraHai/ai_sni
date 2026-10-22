"""Fail-closed request admission; counters commit before supplier I/O."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert

from app.models.geo_visibility_patrol import GeoVisibilityPatrolDailyBudget as Budget

MAX_VISIBILITY_ATTEMPTS_PER_BJ_DAY = 36000


class VisibilityBudgetExhausted(RuntimeError):
    pass


class VisibilityBudgetUnavailable(RuntimeError):
    pass


async def claim_visibility_attempt(*, now=None, sessions=None):
    if sessions is None:
        from app.database import async_session_factory
        sessions = async_session_factory
    day = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Asia/Shanghai")).date()
    statement = insert(Budget).values(budget_day=day, attempts=1).on_conflict_do_update(
        index_elements=[Budget.budget_day],
        set_={"attempts": Budget.attempts + 1, "updated_at": func.now()},
        where=Budget.attempts < MAX_VISIBILITY_ATTEMPTS_PER_BJ_DAY,
    ).returning(Budget.attempts)
    try:
        async with sessions() as session:
            used = await session.scalar(statement)
            await session.commit()
    except SQLAlchemyError as exc:
        raise VisibilityBudgetUnavailable('daily_budget_unavailable') from exc
    if used is None:
        raise VisibilityBudgetExhausted("平台今日总额度已满")
    return used


def budgeted_chat(call, *, real=True, http_error=False):
    async def guarded(*args, **kwargs):
        if real:
            try:
                await claim_visibility_attempt()
            except (VisibilityBudgetExhausted, VisibilityBudgetUnavailable) as exc:
                if not http_error:
                    raise
                from fastapi import HTTPException
                exhausted = isinstance(exc, VisibilityBudgetExhausted)
                raise HTTPException(429 if exhausted else 503, {'code': 'DAILY_BUDGET_EXHAUSTED' if exhausted else 'DAILY_BUDGET_UNAVAILABLE',
                    'message': '平台今日总额度已满' if exhausted else '检测预算服务暂不可用'}) from exc
        return await call(*args, **kwargs)
    return guarded
