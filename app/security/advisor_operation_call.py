"""Live authority at synchronous operational supplier boundaries."""
from contextvars import ContextVar
from functools import wraps
import inspect

current_operation = ContextVar('geo_advisor_operation', default=None)


async def recheck_current(*, release=False):
    binding = current_operation.get()
    if binding is not None:
        session, ctx = binding
        from app.security.advisor_scope import deny
        if session.info.get('advisor_operation_denied'):
            deny(403, 'ADVISOR_GRANT_REVOKED', '本次操作授权已变化，请重新发起')
        from app.security.advisor_write_commit import recheck_advisor_before_commit
        try:
            await recheck_advisor_before_commit(session, ctx)
            from app.security.advisor_read_scope import recheck_initial_scope
            await recheck_initial_scope(session, ctx)
            if release:
                await session.commit()  # no authorization row locks across remote I/O
        except BaseException:
            # A handler may catch a supplier error. It must still be unable to
            # dispatch another step or commit results after this denial.
            session.info['advisor_operation_denied'] = True
            await session.rollback()
            raise


def checked_call(function):
    @wraps(function)
    async def checked(*args, **kwargs):
        binding = current_operation.get()
        info = binding[0].info if binding else {}
        depth = info.get('advisor_operation_depth', 0)
        info['advisor_operation_depth'] = depth + 1
        try:
            await recheck_current(release=True)
            result = await function(*args, **kwargs)
            # A committed DELETE's missing target cannot be resolved again.
            # Delivery still freshly checks grant/role/project authority.
            if binding is None or not info.get('advisor_delete_committed'):
                await recheck_current()  # retain locks until business commit
            return result
        finally:
            info['advisor_operation_depth'] = depth
            if binding is not None and depth == 0:
                from app.security.advisor_quota import refund_unused_reservation
                await refund_unused_reservation(binding[0])
    original = inspect.unwrap(function)
    checked.__signature__ = inspect.signature(original, eval_str=True)
    checked.__annotations__ = inspect.get_annotations(original, eval_str=True)
    return checked


def background_call(function):
    @wraps(function)
    async def background(*args, **kwargs):
        token = current_operation.set(None)
        try:
            return await function(*args, **kwargs)
        finally:
            current_operation.reset(token)
    return background
