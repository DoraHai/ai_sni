"""Native device endpoints and exact human management routes, GEO only."""
import json
import time
from collections import OrderedDict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import DBAPIError
from starlette.responses import JSONResponse

from app.database import get_session
from app.geo.demo_runtime import require_geo_demo_safe_request
from app.security.auth import require_scoped_auth
from app.geo.content import distribution_protocol as p, distribution_report as s

router = APIRouter(prefix=p.PREFIX, tags=['GEO 多号通结果回传'],
                   dependencies=[Depends(require_geo_demo_safe_request)])
_claim_failures = OrderedDict()


def claim_failure_bucket(request, data):
    # A successful claim never consumes this budget. No IP-wide success limit.
    # Unknown codes have no tenant row; this bounded fallback is process-local.
    peer = request.client.host if request.client else 'unknown'
    code = data.get('pairing_code')
    key = s.sha(peer + '\0' + (code if isinstance(code, str) else 'invalid'))
    now = time.monotonic()
    bucket = _claim_failures.setdefault(key, deque(maxlen=s.PAIRING_FAILURE_LIMIT))
    while bucket and bucket[0] <= now - 60:
        bucket.popleft()
    _claim_failures.move_to_end(key)
    while len(_claim_failures) > 2048:
        _claim_failures.popitem(last=False)
    return bucket, now


async def safe_session(session=Depends(get_session)):
    # Sanitize DB errors before the general infrastructure handlers can log
    # statement parameters containing hashes or registry data.
    try:
        yield session
    except DBAPIError:
        await session.rollback()
        p.fail('REPORT_STORAGE_UNAVAILABLE', 503)
    except BaseException:
        await session.rollback()
        raise


async def body(request):
    raw = bytearray()
    if hasattr(request, '_body'):
        raw.extend(await request.body())
    else:
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > p.MAX_REQUEST:
                p.fail('INVALID_SHAPE', 422)
        request._body = bytes(raw)
    if len(raw) > p.MAX_REQUEST:
        p.fail('INVALID_SHAPE', 422)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                p.fail('INVALID_SHAPE', 422)
            result[key] = value
        return result
    try:
        value = json.loads(bytes(raw).decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=lambda _: p.fail('INVALID_SHAPE', 422))
        p.encode(value)
    except (ValueError, UnicodeError, RecursionError, TypeError):
        p.fail('INVALID_SHAPE', 422)
    if not isinstance(value, dict):
        p.fail('INVALID_SHAPE', 422)
    return value, bytes(raw)


def respond(value, status=200):
    return JSONResponse(value, status_code=status, headers={'Cache-Control': 'private, no-store'})


def scope(request):
    if (len(request.query_params.getlist('tenant_id')) != 1 or len(request.query_params.getlist('project_id')) != 1
            or set(request.query_params) != {'tenant_id', 'project_id'}):
        p.fail('INVALID_SHAPE', 422)
    try:
        tenant, project = (int(request.query_params[k]) for k in ('tenant_id', 'project_id'))
    except ValueError:
        p.fail('INVALID_SHAPE', 422)
    return p.integer(tenant), p.integer(project)


async def managed(request, session, ctx, *, write=False):
    tenant_id, project_id = scope(request)
    store = await s.management_store(session, ctx, tenant_id, project_id, write=write)
    return store, project_id


@router.get('/settings')
async def settings(request: Request, ctx=Depends(require_scoped_auth), session=Depends(safe_session)):
    store, project = await managed(request, session, ctx)
    result = s.settings_payload(store, project)
    result['can_manage'] = False
    try:
        await s.actor_authorized(store, project, s.actor_from_context(ctx))
        result['can_manage'] = True
    except HTTPException:
        pass
    return respond(result)


@router.put('/settings')
async def update_settings(request: Request, ctx=Depends(require_scoped_auth), session=Depends(safe_session)):
    store, project = await managed(request, session, ctx, write=True)
    data, _ = await body(request)
    result = await s.change_settings(store, project, s.actor_from_context(ctx), data)
    await session.commit()
    return respond(result)


@router.post('/device-pairings')
async def pair(request: Request, ctx=Depends(require_scoped_auth), session=Depends(safe_session)):
    store, project = await managed(request, session, ctx, write=True)
    data, _ = await body(request)
    result = await s.create_pairing(store, project, s.actor_from_context(ctx), data)
    await session.commit()
    return respond(result, 201)


@router.post('/devices/{deviceId}/revoke')
async def revoke(deviceId: str, request: Request, ctx=Depends(require_scoped_auth), session=Depends(safe_session)):
    store, project = await managed(request, session, ctx, write=True)
    data, _ = await body(request)
    p.exact(data, {'expected_revision'}); p.integer(data['expected_revision'], 0)
    device = store.book['devices'].get(deviceId)
    if device is None or device['scope_id'] != project:
        p.fail('TASK_NOT_FOUND', 404)
    if data['expected_revision'] != store.book['revision']:
        p.fail('SOURCE_CHANGED')
    device['revoked'] = True
    store.book['revision'] += 1
    store.audit('DEVICE_REVOKED', actor=ctx.user_id, device=deviceId)
    await store.save()
    await session.commit()
    return respond(s.settings_payload(store, project))


@router.post('/tasks')
async def dispatch(request: Request, ctx=Depends(require_scoped_auth), session=Depends(safe_session)):
    store, project = await managed(request, session, ctx, write=True)
    data, _ = await body(request)
    result = await s.create_task(store, project, s.actor_from_context(ctx), data)
    await session.commit()
    return respond(result, 201)


@router.get('/tasks/{taskId}')
async def task_status(taskId: str, request: Request, ctx=Depends(require_scoped_auth), session=Depends(safe_session)):
    store, project = await managed(request, session, ctx)
    task = store.book['tasks'].get(taskId)
    if task is None or task['scope_id'] != project:
        p.fail('TASK_NOT_FOUND', 404)
    await s.native_task(store, project, task['native_task_id'], task['variant_id'], task['article_id'], publish=False)
    return respond(await s.verification(store, task))


@router.post('/device-pairings/claim')
async def claim(request: Request, session=Depends(safe_session)):
    s.native_headers(request)
    data, _ = await body(request)
    bucket, now = claim_failure_bucket(request, data)
    if len(bucket) >= s.PAIRING_FAILURE_LIMIT:
        p.fail('DEVICE_RATE_LIMITED', 429)
    try:
        result = await s.claim(session, data)
    except s.PairingRejected:
        # Preserve only the failed known-code count despite an HTTP error.
        await session.commit()
        raise
    except HTTPException as error:
        # Known-code throttling is governed solely by its durable window.
        if error.detail.get('code') != 'DEVICE_RATE_LIMITED':
            bucket.append(now)
        raise
    await session.commit()
    return respond(result)


@router.get('/device/profile')
async def profile(request: Request, session=Depends(safe_session)):
    store, device = await s.authenticate(session, request, reporting=False)
    return respond(await s.device_profile(store, device))


@router.post('/device/bindings')
async def bindings(request: Request, session=Depends(safe_session)):
    store, device = await s.authenticate(session, request, reporting=False)
    data, raw = await body(request)
    p.exact(data, {'device_id'})
    if data['device_id'] != device['id']:
        p.fail('SCOPE_FORBIDDEN', 403)
    s.transport(device, request, raw)
    result = {'schema': 1, 'device_id': device['id'], 'as_of': s.now_ms(), 'automatic_submit': False,
        'items': [{'binding_id': device['binding_id'], 'device_id': device['id'], 'module': 'geo',
                   'tenant_id': store.tenant_id, 'scope_id': device['scope_id'],
                   'account_id': str(device['account_id']), 'external_account_id': f"unverified-account-{device['account_id']}",
                   'platform': 'wechat-article', 'login_state': 'unverified'}]}
    await store.save()
    await session.commit()
    return respond(result)


@router.post('/device/exchange')
async def exchange(request: Request, session=Depends(safe_session)):
    store, device = await s.authenticate(session, request, reporting=True)
    data, raw = await body(request)
    p.exact(data, {'contractVersion', 'deviceId', 'receipts'})
    if type(data['contractVersion']) is not int or data['contractVersion'] != 1 or data['deviceId'] != device['id']:
        p.fail('INVALID_SHAPE', 422)
    s.transport(device, request, raw)
    acks = await s.apply_events(store, device, data['receipts'], 'receipt')
    result = await s.envelope(store, device, acks)
    await store.save()
    await session.commit()
    # The existing ten-minute monitor batch recovers pending checks, including
    # a crash immediately after this transaction. No page fetch inside the ACK.
    return respond(result)


@router.post('/device/observations')
async def observations(request: Request, session=Depends(safe_session)):
    store, device = await s.authenticate(session, request, reporting=True)
    data, raw = await body(request)
    p.exact(data, {'observationVersion', 'deviceId', 'items'})
    if type(data['observationVersion']) is not int or data['observationVersion'] != 1 or data['deviceId'] != device['id']:
        p.fail('INVALID_SHAPE', 422)
    s.transport(device, request, raw)
    acks = await s.apply_events(store, device, data['items'], 'observation')
    await store.save()
    await session.commit()
    return respond({'observationVersion': 1, 'acks': acks})


@router.get('/device/tasks/{taskId}/verification')
async def verify(taskId: str, request: Request, session=Depends(safe_session)):
    store, device = await s.authenticate(session, request, reporting=True)
    task, _, _, _ = await s.task_authorized(store, device, taskId, publish=False)
    return respond(await s.verification(store, task))


@router.post('/device/task-resolution')
async def resolution(request: Request, session=Depends(safe_session)):
    store, device = await s.authenticate(session, request, reporting=True)
    data, raw = await body(request)
    keys = {'resolutionVersion', 'deviceId', 'taskId', 'grantId', 'publicationGrantId', *p.TARGET}
    p.exact(data, keys)
    if type(data['resolutionVersion']) is not int or data['resolutionVersion'] != 1 or data['deviceId'] != device['id']:
        p.fail('INVALID_SHAPE', 422)
    task, _, _, _ = await s.task_authorized(store, device, data['taskId'], publish=False)
    if (any(data[k] != task['target'][k] for k in p.TARGET)
            or any(data[k] != task['wire'][k] for k in ('grantId', 'publicationGrantId'))):
        p.fail('SCOPE_FORBIDDEN', 403)
    s.transport(device, request, raw)
    await store.save()
    await session.commit()
    return respond({**data, 'asOf': s.now_ms(), 'resolution': None,
                    'publicationVerified': False, 'executionAuthorized': False})
