"""Structured advisor write records without request bodies or credentials."""
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import event

logger = logging.getLogger('uvicorn.error')
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
                logger.info('geo_advisor_write %s', json.dumps(result, ensure_ascii=True, sort_keys=True))
