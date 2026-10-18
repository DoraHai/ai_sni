"""Opt-in records for deployed GEO configuration and receipt writes."""
import inspect
import json
import logging
from datetime import datetime, timezone
from functools import wraps

from fastapi import HTTPException

logger = logging.getLogger('uvicorn.error')


def audit_geo_operation(method, path, *, success_status=200):
    def decorate(func):
        signature = inspect.signature(func, eval_str=True)

        @wraps(func)
        async def audited(*args, **kwargs):
            values = signature.bind(*args, **kwargs).arguments
            ctx = values.get('ctx')
            status, result = 500, None
            try:
                result = await func(*args, **kwargs)
                status = success_status
                return result
            except HTTPException as exc:
                status = exc.status_code
                raise
            finally:
                if ctx is not None:
                    record = {'at': datetime.now(timezone.utc).isoformat(),
                        'user_id': getattr(ctx, 'user_id', None),
                        'tenant_id': values.get('tenant_id', getattr(values.get('req'), 'tenant_id', None)),
                        'method': method, 'path': path, 'status': status,
                        'objects': {k: values[k] for k in ('task_id', 'project_id') if k in values},
                        'result': 'completed' if status < 400 else 'failed' if status >= 500 else 'rejected'}
                    if isinstance(result, dict):
                        for key in ('dry_run', 'committed', 'changed', 'total', 'can_confirm'):
                            if key in result and type(result[key]) in (bool, int):
                                record[key] = result[key]
                        job = result.get('job')
                        if isinstance(job, dict) and type(job.get('id')) is int:
                            record['objects']['job_id'] = job['id']
                    logger.info('geo_operation %s', json.dumps(record, ensure_ascii=True, sort_keys=True))

        audited.__signature__ = signature
        return audited
    return decorate
