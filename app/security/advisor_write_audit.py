"""No schema change: operation, commit and background records.

Only declared identifiers and review fingerprints are logged. Never bodies,
headers, credentials, URLs supplied by a customer, or exception text.
"""
from datetime import datetime, timezone
import json
import logging
from uuid import uuid4

from sqlalchemy import event

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


write_logger = logging.getLogger('uvicorn.error')
KEY = 'geo_advisor_write_audit'


def bind_write_audit(request, user_id, tenant_id):
    if (request is None or request.method in {'GET', 'HEAD', 'OPTIONS'}
            or not request.url.path.startswith('/api/v1/geo/')):
        return
    request.scope.setdefault(KEY, {
        'request_id': uuid4().hex, 'user_id': user_id,
        'tenant_id': tenant_id if type(tenant_id) is int and tenant_id > 0 else None,
        'objects': {}, 'committed': False,
    })


def bind_write_changes(session, request):
    record = request.scope.get(KEY)
    if record is None or session.info.get('advisor_audit_hook'):
        return

    def after_flush(sync_session, _context):
        for row in list(sync_session.new) + list(sync_session.dirty):
            table = getattr(row, '__tablename__', '')
            ident = getattr(row, 'id', None)
            if table.startswith('geo_') and type(ident) is int:
                ids = record['objects'].setdefault(table, [])
                if ident not in ids and len(ids) < 50:
                    ids.append(ident)

    def after_commit(_session):
        # SAVEPOINT release also fires after_commit; the outer write may still
        # be rejected and rolled back by the authority recheck.
        if not _session.in_nested_transaction():
            record['committed'] = True

    event.listen(session.sync_session, 'after_flush', after_flush)
    event.listen(session.sync_session, 'after_commit', after_commit)
    session.info['advisor_audit_hook'] = True


class AdvisorWriteAuditMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        status, failed = 500, False

        async def audit_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            await send(message)

        try:
            await self.app(scope, receive, audit_send)
        except BaseException:
            failed = True
            raise
        finally:
            record = scope.get(KEY)
            if record is not None:
                route = getattr(scope.get('route'), 'path', scope.get('path', ''))
                path_ids = {}
                for key, value in scope.get('path_params', {}).items():
                    if key.endswith('_id') and str(value).isascii() and str(value).isdecimal():
                        path_ids[key] = str(value)[:19]
                result = {**record, 'at': datetime.now(timezone.utc).isoformat(),
                    'method': scope.get('method'), 'path': route[:500], 'path_ids': path_ids,
                    'status': status, 'response_failed': failed,
                    'result': 'committed' if record['committed'] else
                              'rejected' if status >= 400 or failed else 'completed'}
                write_logger.info('geo_advisor_write %s', json.dumps(result, ensure_ascii=True, sort_keys=True))
