"""Live authority at synchronous operational supplier boundaries."""
from contextvars import ContextVar
from functools import wraps
import inspect

current_operation = ContextVar('geo_advisor_operation', default=None)


async def recheck_current():
    binding = current_operation.get()
    if binding is not None:
        session, ctx = binding
        from app.security.advisor_write_commit import recheck_advisor_before_commit
        await recheck_advisor_before_commit(session, ctx)
        await session.commit()  # release authorization locks before remote work


def checked_call(function):
    @wraps(function)
    async def checked(*args, **kwargs):
        await recheck_current()
        result = await function(*args, **kwargs)
        await recheck_current()
        return result
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
