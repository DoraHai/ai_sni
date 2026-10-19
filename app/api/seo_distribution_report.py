"""SEO-only device endpoints, separate from JWT management dependencies."""
from collections import OrderedDict, deque
import json
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_session
from app.security.auth import require_scoped_auth
from app.seo_distribution_protocol import (PREFIX, deny, enabled, identifier, positive,
    registry, shape, validate_event)
from app import seo_distribution_report as service
from app.config import get_settings

_rates = OrderedDict()
_claim_rates = OrderedDict()


def limit(key, maximum, *, claim=False):
    now = service.now_ms()
    table = _claim_rates if claim else _rates
    bucket = table.setdefault(key, deque())
    table.move_to_end(key)
    while bucket and bucket[0] <= now - 60000:
        bucket.popleft()
    if len(bucket) >= maximum:
        deny('DEVICE_RATE_LIMITED', 429)
    if len(table) > 2048:
        # Reject new identities rather than evicting an active limit.
        old = next(iter(table))
        if table[old] and table[old][-1] > now - 60000:
            table.pop(key, None)
            deny('DEVICE_RATE_LIMITED', 429)
        table.popitem(last=False)
    bucket.append(now)


class SafeRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            try:
                response = await original(request)
            except (RequestValidationError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                response = JSONResponse({'detail': {'code': 'INVALID_SHAPE', 'message': '结果回传请求格式无效'}}, status_code=422)
            except HTTPException as exc:
                code = exc.detail.get('code') if isinstance(exc.detail, dict) else None
                if not isinstance(code, str) or not re.fullmatch('[A-Za-z0-9_]{1,80}', code):
                    code = 'REPORT_REQUEST_REJECTED'
                response = JSONResponse({'detail': {'code': code, 'message': '结果回传未获受理，请核对当前权限和任务'}}, status_code=exc.status_code)
                if exc.status_code == 429:
                    response.headers['Retry-After'] = '60'
            except SQLAlchemyError:
                response = JSONResponse({'detail': {'code': 'REPORT_STORAGE_UNAVAILABLE', 'message': '结果回传存储暂不可用'}}, status_code=503)
            response.headers['Cache-Control'] = 'private, no-store'
            return response
        return handle


router = APIRouter(prefix=PREFIX, tags=['SEO manual device reports'], route_class=SafeRoute)


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            deny('INVALID_SHAPE', 422)
        value[key] = item
    return value


async def body_for(request, fields):
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        deny('INVALID_SHAPE', 422)
    raw = await request.body()
    if len(raw) > 512 * 1024:
        deny('INVALID_SHAPE', 413)
    value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=lambda _: deny('INVALID_SHAPE', 422))
    shape(value, fields)
    return raw, value


def selectors(request):
    values = []
    for key in ('tenant_id', 'site_id'):
        candidates = request.query_params.getlist(key)
        if len(candidates) != 1 or not re.fullmatch('[1-9][0-9]{0,17}', candidates[0]):
            deny('SCOPE_FORBIDDEN', 403)
        values.append(int(candidates[0]))
    if set(request.query_params) != {'tenant_id', 'site_id'}:
        deny('INVALID_SHAPE', 422)
    return values


async def management(request, session, ctx, *, initialize=False):
    tenant_id, site_id = selectors(request)
    ctx.ensure_tenant(tenant_id)
    if ctx.user_id is None or not (ctx.is_advisor or ctx.can_edit('settings.accounts')):
        deny('SCOPE_FORBIDDEN', 403)
    if request.method != 'GET' and not ctx.can_edit('seo.content'):
        deny('SCOPE_FORBIDDEN', 403)
    await service.site_scope(session, tenant_id, site_id)
    module = await service.locked_module(session, tenant_id)
    if request.method != 'GET' and not ctx.is_advisor:
        # Human JWT admission is a snapshot. Hold fresh account/role locks for
        # administrators too, so an in-flight disable/permission revoke wins.
        await service.authorize_actor(session, service.proof_for(ctx), tenant_id, site_id)
    state = registry(module.module_settings, initialize=initialize)
    return module, state, site_id


@router.get('/settings')
async def settings(request: Request, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    module, state, site_id = await management(request, session, ctx, initialize=True)
    result = service.settings_payload(state, site_id)
    result['can_operate'] = ctx.can_edit('seo.content') and (not ctx.is_advisor or get_settings().advisor_scoped_content_writes_enabled)
    return result


@router.put('/settings')
async def update_settings(request: Request, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    _, body = await body_for(request, {'enabled', 'scope_enabled', 'expected_revision', 'expected_scope_revision'})
    if (type(body['enabled']) is not bool or type(body['scope_enabled']) is not bool
            or any(type(body[k]) is not int or body[k] < 0 for k in ('expected_revision', 'expected_scope_revision'))):
        deny('INVALID_SHAPE', 422)
    module, state, site_id = await management(request, session, ctx, initialize=True)
    result = await service.set_settings(session, module, state, site_id, body, ctx)
    await session.commit()
    return result


@router.post('/device-pairings', status_code=201)
async def pairing(request: Request, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    _, body = await body_for(request, {'label', 'platform', 'account_id', 'expected_revision'})
    if (not isinstance(body['label'], str) or not body['label'].strip() or len(body['label']) > 80
            or re.search(r'[\x00-\x1f\x7f]', body['label']) or body['platform'] != 'wechat-article'
            or type(body['expected_revision']) is not int):
        deny('INVALID_SHAPE', 422)
    module, state, site_id = await management(request, session, ctx, initialize=True)
    result = await service.create_pairing(session, module, state, site_id, body, ctx)
    await session.commit()
    return result


@router.post('/devices/{deviceId}/revoke')
async def revoke(deviceId: str, request: Request, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    _, body = await body_for(request, {'expected_revision'})
    module, state, site_id = await management(request, session, ctx)
    device = state['devices'].get(deviceId)
    if device is None or device['site_id'] != site_id:
        deny('SCOPE_FORBIDDEN', 403)
    if type(body['expected_revision']) is not int or body['expected_revision'] != state['revision']:
        deny('SOURCE_CHANGED')
    device['revoked'] = True
    state['revision'] += 1
    service.audit(state, 'device_revoked', actor=ctx.user_id, device=deviceId)
    service.store(module, state)
    await session.commit()
    return service.settings_payload(state, site_id)


@router.post('/tasks', status_code=201)
async def task(request: Request, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    _, body = await body_for(request, {'publication_id', 'source_version', 'payload_hash', 'device_id', 'request_id'})
    if (not positive(body['publication_id']) or not positive(body['source_version'])
            or not identifier(body['device_id']) or not identifier(body['request_id'])
            or not isinstance(body['payload_hash'], str) or not re.fullmatch('[a-f0-9]{64}', body['payload_hash'])):
        deny('INVALID_SHAPE', 422)
    module, state, site_id = await management(request, session, ctx)
    result = await service.admit_task(session, module, state, site_id, body, ctx)
    await session.commit()
    return result


@router.get('/tasks/{taskId}')
async def task_detail(taskId: str, request: Request, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    module, state, site_id = await management(request, session, ctx)
    task = state['tasks'].get(taskId)
    if task is None or task['site_id'] != site_id:
        deny('TASK_NOT_FOUND', 404)
    return service.task_payload(task)


def native_device_request(request):
    if any(h in request.headers for h in ('origin', 'cookie', 'sec-fetch-site', 'sec-fetch-mode', 'sec-fetch-dest')):
        deny('SCOPE_FORBIDDEN', 403)
    if request.query_params:
        deny('INVALID_SHAPE', 422)


def credential_for(request):
    native_device_request(request)
    auth = request.headers.get('authorization', '')
    if not auth.startswith('Bearer ') or len(auth) > 200:
        deny('DEVICE_CREDENTIAL_INVALID', 401)
    value = auth[7:]
    service.credential_locator(value)
    return value


async def authenticated_device(session, credential, **kwargs):
    result = await service.authenticate(session, credential, **kwargs)
    # Only a fully authenticated device can allocate or consume a credential
    # bucket. Anonymous claims and forged random credentials cannot fill it.
    limit(result[2]['id'], 120)
    return result


def replay_headers(request, device, raw, stream):
    try:
        seq_raw, sent_raw = request.headers['x-distribution-request-seq'], request.headers['x-distribution-sent-at']
        if not re.fullmatch('[1-9][0-9]{0,15}', seq_raw) or not re.fullmatch('[1-9][0-9]{0,15}', sent_raw):
            deny('INVALID_SHAPE', 422)
        return service.transport_request(device, request.method, request.url.path, raw,
            int(seq_raw), int(sent_raw), stream=stream)
    except KeyError:
        deny('INVALID_SHAPE', 422)


@router.post('/device-pairings/claim')
async def claim(request: Request, session=Depends(get_session)):
    native_device_request(request)
    # Use the ASGI peer identity, never caller-supplied forwarding headers.
    # Uvicorn resolves trusted proxy peers before constructing this Request.
    peer = request.client.host if request.client else 'unknown-peer'
    _, body = await body_for(request, {'pairing_code', 'request_id'})
    if (not isinstance(body['pairing_code'], str) or not re.fullmatch('[A-Za-z0-9_-]{32}', body['pairing_code'])
            or not isinstance(body['request_id'], str)
            or not re.fullmatch('[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}', body['request_id'])):
        deny('INVALID_SHAPE', 422)
    try:
        return await service.claim_pairing(session, body['pairing_code'])
    except HTTPException:
        await session.rollback()
        known = await service.record_claim_failure(session, body['pairing_code'])
        if not known:
            # Only unknown-code failures use process-local fallback. Successful
            # claims never consume, or get rejected by, another customer's IP
            # budget. Known-code limits survive worker/server restarts in JSONB.
            limit('claim-peer-' + service.sha(peer), 30, claim=True)
            limit('claim-code-' + service.sha(body['pairing_code']), 10, claim=True)
            limit('claim-global', 3000, claim=True)
        raise


@router.get('/device/profile')
async def profile(request: Request, session=Depends(get_session)):
    module, state, device = await authenticated_device(session, credential_for(request), require_enabled=False)
    return await service.device_profile(session, module, device)


@router.post('/device/bindings')
async def bindings(request: Request, session=Depends(get_session)):
    credential = credential_for(request)
    raw, body = await body_for(request, {'device_id'})
    module, state, device = await authenticated_device(session, credential, require_enabled=False)
    if body['device_id'] != device['id']:
        deny('SCOPE_FORBIDDEN', 403)
    replay_headers(request, device, raw, 'bindings')
    result = {'schema': 1, 'device_id': device['id'], 'as_of': service.now_ms(), 'automatic_submit': False,
        'items': [{'binding_id': device['binding_id'], 'device_id': device['id'], 'module': 'seo',
            'tenant_id': module.tenant_id, 'scope_id': device['site_id'], 'account_id': device['account_id'],
            'external_account_id': device['account_id'], 'platform': 'wechat-article', 'login_state': 'unverified'}]}
    service.store(module, state)
    await session.commit()
    return result


async def receive_events(request, session, background_tasks, stream):
    credential = credential_for(request)
    fields = {'contractVersion', 'deviceId', 'receipts'} if stream == 'receipt' else {'observationVersion', 'deviceId', 'items'}
    raw, body = await body_for(request, fields)
    version_key, events_key = ('contractVersion', 'receipts') if stream == 'receipt' else ('observationVersion', 'items')
    events = body[events_key]
    if type(body[version_key]) is not int or body[version_key] != 1 or type(events) is not list or len(events) > 100:
        deny('INVALID_SHAPE', 422)
    for event in events:
        validate_event(event, stream)
    module, state, device = await authenticated_device(session, credential)
    if body['deviceId'] != device['id']:
        deny('SCOPE_FORBIDDEN', 403)
    replay = replay_headers(request, device, raw, stream)
    # Re-run current task/actor authorization even for cached ACKs.
    acks = await service.apply_events(session, module, state, device, events, stream)
    if replay and acks != device['last_acks']:
        deny('REPLAY_REJECTED')
    device['last_acks'] = acks
    response = (await service.envelope(session, module, state, device, acks) if stream == 'receipt'
                else {'observationVersion': 1, 'acks': acks})
    service.store(module, state)
    await session.commit()
    if any(e['code'] == 'HUMAN_PUBLISHED' for e in events):
        from app.seo_distribution_verification import recover_report_verification
        background_tasks.add_task(recover_report_verification)
    return response


@router.post('/device/exchange')
async def exchange(request: Request, background_tasks: BackgroundTasks, session=Depends(get_session)):
    return await receive_events(request, session, background_tasks, 'receipt')


@router.post('/device/observations')
async def observations(request: Request, background_tasks: BackgroundTasks, session=Depends(get_session)):
    return await receive_events(request, session, background_tasks, 'observation')


@router.get('/device/tasks/{taskId}/verification')
async def verification(taskId: str, request: Request, session=Depends(get_session)):
    module, state, device = await authenticated_device(session, credential_for(request))
    task = state['tasks'].get(taskId)
    await service.live_task(session, module, device, task, success=False)
    return service.task_payload(task)


@router.post('/device/task-resolution')
async def resolution(request: Request, session=Depends(get_session)):
    fields = {'resolutionVersion', 'deviceId', 'taskId', 'grantId', 'publicationGrantId', 'leaseId',
              'customerId', 'projectId', 'accountId', 'platform', 'contentVersion', 'contentDigest'}
    credential = credential_for(request)
    raw, body = await body_for(request, fields)
    module, state, device = await authenticated_device(session, credential)
    task = state['tasks'].get(body['taskId'])
    await service.live_task(session, module, device, task)
    if (body['resolutionVersion'] != 1 or type(body['resolutionVersion']) is not int
            or any(body[k] != v for k, v in task['target'].items())
            or any(body[k] != task['wire'][k] for k in ('grantId', 'publicationGrantId', 'leaseId'))
            or body['contentVersion'] != task['content_version'] or body['contentDigest'] != task['content_digest']):
        deny('SCOPE_FORBIDDEN', 403)
    replay_headers(request, device, raw, 'resolution')
    service.store(module, state)
    await session.commit()
    return {**body, 'asOf': service.now_ms(), 'resolution': None,
            'publicationVerified': False, 'executionAuthorized': False}
