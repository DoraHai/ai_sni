"""Identity inbox, native device transport, and exact SEO business routes."""
from collections import OrderedDict, deque
from datetime import timedelta
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select, func, or_
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.database import get_session
from app.distribution_inbox_protocol import (PREFIX, ProtocolError, fail, strict_json, exact_object, identifier,
    validate_pairing, validate_claim, validate_ack_query, validate_revision, validate_label, clean_text, http_error_code)
from app import distribution_inbox_service as service
from app.models.distribution_inbox import DistributionInboxDevice as Device, DistributionInboxReceipt as Receipt
from app.security.distribution_inbox_auth import require_inbox_identity
from app.security.auth import require_scoped_auth


class SafeRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handle(request):
            try:
                response = await original(request)
            except ProtocolError as exc:
                response = JSONResponse({'detail': exc.detail}, status_code=exc.status)
            except IntegrityError:
                error = ProtocolError('DUPLICATE_LINK', 409)
                response = JSONResponse({'detail': error.detail}, status_code=409)
            except SQLAlchemyError:
                error = ProtocolError('INBOX_SCHEMA_NOT_READY', 503)
                response = JSONResponse({'detail': error.detail}, status_code=503)
            except HTTPException as exc:
                code = http_error_code(exc.status_code, exc.detail)
                response = JSONResponse({'detail': ProtocolError(code).detail}, status_code=exc.status_code)
            except (RequestValidationError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                response = JSONResponse({'detail': ProtocolError().detail}, status_code=422)
            response.headers['Cache-Control'] = 'private, no-store'
            if response.status_code == 429:
                response.headers['Retry-After'] = '60'
            return response
        return handle


router = APIRouter(route_class=SafeRoute)
_claim_rates = OrderedDict()


def claim_rate(key, maximum):
    stamp = service.now().timestamp()
    for k in list(_claim_rates):
        if not _claim_rates[k] or _claim_rates[k][-1] <= stamp-60:
            del _claim_rates[k]
    if key not in _claim_rates and len(_claim_rates) >= 4096:
        fail('RATE_LIMITED', 429)
    bucket = _claim_rates.setdefault(key, deque())
    while bucket and bucket[0] <= stamp-60:
        bucket.popleft()
    if len(bucket) >= maximum:
        fail('RATE_LIMITED', 429)
    bucket.append(stamp)


async def body_for(request):
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        fail()
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16384:
            fail(status=413)
    return bytes(raw), strict_json(bytes(raw))


async def ready(session):
    await service.schema_ready(session)


def device_shape(request, *, claim=False):
    if (request.scope.get('raw_path') != request.url.path.encode('ascii') or request.query_params
            or any(k.lower() in {'cookie','origin','x-api-key'} or k.lower().startswith('sec-fetch-') for k in request.headers)):
        fail('DEVICE_CREDENTIAL_INVALID', 401)
    authorization = request.headers.getlist('authorization')
    if claim:
        if authorization:
            fail('DEVICE_CREDENTIAL_INVALID', 401)
        return ''
    if len(authorization) != 1 or not authorization[0].startswith('Bearer '):
        fail('DEVICE_CREDENTIAL_INVALID', 401)
    return authorization[0][7:]


@router.post(PREFIX+'/pairings', status_code=201)
async def pairing(request: Request, ctx=Depends(require_inbox_identity), session=Depends(get_session)):
    await ready(session)
    _, body = await body_for(request)
    result = await service.create_pairing(session, ctx, validate_pairing(body))
    await session.commit()
    return result


@router.post(PREFIX+'/device-pairings/claim')
async def claim(request: Request, session=Depends(get_session)):
    device_shape(request, claim=True)
    await ready(session)
    _, body = await body_for(request)
    validate_claim(body)
    claim_rate(('global',), 3000)
    claim_rate(('ip', request.client.host if request.client else ''), 30)
    claim_rate(('code', service.sha(body['pairingCode'])), 10)
    # Known pending-code rate is durable under the same owner/device lock as claim.
    # A successful claim consumes it once; later attempts cannot issue credentials.
    try:
        result = await service.claim(session, body)
    except ProtocolError:
        if session.info.pop('inbox_claim_rate_changed', False):
            await session.commit()
        raise
    await session.commit()
    return result


@router.post(PREFIX+'/device/results')
async def receive(request: Request, session=Depends(get_session)):
    credential = device_shape(request)
    await ready(session)
    raw, body = await body_for(request)
    device = await service.authenticate_device(session, credential)
    # Reject malformed replays as well; only new-event clock checks are deferred.
    from app.distribution_inbox_protocol import EVENT_KEYS, payload_digest
    exact_object(body, (*EVENT_KEYS, 'payloadDigest'))
    if not identifier(body.get('eventId')) or not isinstance(body.get('payloadDigest'), str) or payload_digest(body) != body['payloadDigest']:
        fail('PAYLOAD_DIGEST_INVALID')
    result = await service.receive(session, device, body, len(raw))
    await session.commit()
    return result


@router.post(PREFIX+'/device/ack')
async def ack(request: Request, session=Depends(get_session)):
    credential = device_shape(request)
    await ready(session)
    _, body = await body_for(request)
    validate_ack_query(body)
    device = await service.authenticate_device(session, credential)
    result = await service.existing_ack(session, device, body)
    if result is None:
        fail('EVENT_NOT_FOUND', 404)
    return result


@router.post(PREFIX+'/pairings/{rid}/cancel')
@router.post(PREFIX+'/devices/{rid}/revoke')
async def revoke(rid: str, request: Request, ctx=Depends(require_inbox_identity), session=Depends(get_session)):
    await ready(session)
    _, body = await body_for(request)
    exact_object(body, ('expectedRevision',))
    result = await service.mutate_device(session, ctx, rid, validate_revision(body['expectedRevision']), cancel=request.url.path.endswith('/cancel'))
    await session.commit()
    return result


def positive_query(value, *, maximum=2**63-1, minimum=1):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) > 19:
        fail()
    result = int(value)
    if not minimum <= result <= maximum:
        fail()
    return result


async def filters(request, session, ctx):
    _, _, admin = await service.actor(session, ctx, identity=True)
    params = request.query_params
    owner = positive_query(params['ownerUserId']) if 'ownerUserId' in params and admin else ctx.user_id
    state = params.get('state', 'pending')
    if state not in {'pending','active','archived'}:
        fail()
    old = service.now()-timedelta(days=90)
    state_condition = (or_(Receipt.state == 'archived', (Receipt.state == 'pending') & (Receipt.received_at <= old)) if state == 'archived'
        else (Receipt.state == 'pending') & (Receipt.received_at > old) if state == 'pending' else Receipt.state == 'active')
    conditions = [Receipt.owner_user_id == owner, state_condition]
    if params.get('q'):
        q = clean_text(params['q'], 100)
        conditions.append(or_(Receipt.title.contains(q, autoescape=True), Receipt.platform.contains(q, autoescape=True),
            Receipt.reported_account.contains(q, autoescape=True), Receipt.public_url.contains(q, autoescape=True)))
    return owner, admin, conditions


@router.get(PREFIX+'/receipts/count')
async def count(request: Request, ctx=Depends(require_inbox_identity), session=Depends(get_session)):
    await ready(session)
    owner, _, conditions = await filters(request, session, ctx)
    usage = await service.usage(session, owner)
    return {'schema': 2, 'count': await session.scalar(select(func.count()).select_from(Receipt).where(*conditions)),
        'unlabeledCount': usage[0], 'unlabeledBytes': usage[1]}


@router.get(PREFIX+'/receipts')
async def receipts(request: Request, ctx=Depends(require_inbox_identity), session=Depends(get_session)):
    await ready(session)
    _, admin, conditions = await filters(request, session, ctx)
    limit = positive_query(request.query_params.get('limit', '50'), maximum=100)
    offset = positive_query(request.query_params.get('offset', '0'), maximum=5000, minimum=0)
    rows = list(await session.scalars(select(Receipt).where(*conditions).order_by(Receipt.received_at.desc(), Receipt.id).limit(limit).offset(offset)))
    return {'schema': 2, 'items': [await service.project(session, row, ctx, admin) for row in rows],
        'total': await session.scalar(select(func.count()).select_from(Receipt).where(*conditions))}


@router.get(PREFIX+'/receipts/{rid}')
async def receipt(rid: str, request: Request, ctx=Depends(require_inbox_identity), session=Depends(get_session)):
    await ready(session)
    _, _, admin = await service.actor(session, ctx, identity=True)
    row = await session.get(Receipt, rid)
    if row is None or row.owner_user_id != ctx.user_id and not admin:
        fail('RECEIPT_NOT_FOUND', 404)
    return await service.project(session, row, ctx, admin)


@router.get(PREFIX+'/devices')
async def devices(request: Request, ctx=Depends(require_inbox_identity), session=Depends(get_session)):
    await ready(session)
    _, _, admin = await service.actor(session, ctx, identity=True)
    owner = positive_query(request.query_params['ownerUserId']) if admin and 'ownerUserId' in request.query_params else ctx.user_id
    rows = list(await session.scalars(select(Device).where(Device.owner_user_id == owner).order_by(Device.created_at.desc())))
    stamp = service.now()
    return {'schema': 2, 'items': [{'id': d.id, 'label': d.label,
        'state': 'expired' if d.state in {'pending','active'} and (d.credential_expires_at or d.pairing_expires_at) <= stamp else d.state,
        'revision': d.revision, 'createdAt': service.iso(d.created_at), 'expiresAt': service.iso(d.credential_expires_at or d.pairing_expires_at)} for d in rows]}


@router.get(PREFIX+'/targets')
async def targets(request: Request, ctx=Depends(require_inbox_identity), session=Depends(get_session)):
    await ready(session)
    from app.models.tenant import Tenant
    from app.models.module_workspace import SeoSite
    from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
    user, _, admin = await service.actor(session, ctx, identity=True)
    conditions = []
    if not admin:
        conditions.append(Tenant.id.in_(select(Grant.tenant_id).where(Grant.user_id == ctx.user_id, Grant.revoked_at.is_(None))))
    elif user.tenant_id is not None:
        conditions.append(Tenant.id == user.tenant_id)
    items = []
    for tenant in await session.scalars(select(Tenant).where(*conditions).order_by(Tenant.id)):
        modules = [m for m in ('seo','geo') if await service.target_allowed(session, ctx.user_id, tenant.id, m, None)]
        if not modules:
            continue
        scopes = []
        if 'seo' in modules:
            for site in await session.scalars(select(SeoSite).where(SeoSite.tenant_id == tenant.id, SeoSite.status == 'active')):
                if await service.target_allowed(session, ctx.user_id, tenant.id, 'seo', site.id):
                    from app.models.seo import SeoContentAsset
                    from app.api.seo import _content_confirmation_hash, _require_active_content_confirmation, _content_confirmation_schema_ready
                    articles = []
                    if await _content_confirmation_schema_ready(session):
                        for article in await session.scalars(select(SeoContentAsset).where(SeoContentAsset.tenant_id == tenant.id,
                                SeoContentAsset.site_id == site.id, SeoContentAsset.status.in_(['ready','published'])).order_by(SeoContentAsset.id)):
                            try:
                                await _require_active_content_confirmation(session, article)
                            except HTTPException:
                                continue
                            articles.append({'id': article.id, 'title': article.title, 'version': article.version_count,
                                'digest': _content_confirmation_hash(article)})
                    scopes.append({'id': site.id, 'name': site.name, 'module': 'seo', 'articles': articles})
        if 'geo' in modules:
            from app.models.module_workspace import GeoProject
            for project in await session.scalars(select(GeoProject).where(GeoProject.tenant_id == tenant.id, GeoProject.status == 'active')):
                if await service.target_allowed(session, ctx.user_id, tenant.id, 'geo', project.id):
                    scopes.append({'id': project.id, 'name': project.name, 'module': 'geo',
                        'articles': await service.geo_article_options(session, tenant.id, project)})
        items.append({'tenantId': tenant.id, 'name': tenant.name, 'modules': modules, 'scopes': scopes})
    owners = []
    if admin:
        from app.models.user import User
        for owner in await session.scalars(select(User).where(User.id.in_(select(Device.owner_user_id))).order_by(User.id)):
            owners.append({'id': owner.id, 'displayName': owner.display_name or owner.username, 'active': owner.is_active})
    return {'schema': 2, 'items': items, 'owners': owners, 'inboxAdmin': admin}


@router.post(PREFIX+'/receipts/{rid}/archive')
@router.post(PREFIX+'/receipts/{rid}/delete')
async def clean(rid: str, request: Request, ctx=Depends(require_inbox_identity), session=Depends(get_session)):
    await ready(session)
    _, body = await body_for(request)
    exact_object(body, ('expectedRevision',))
    result = await service.clean_receipt(session, ctx, rid, validate_revision(body['expectedRevision']), request.url.path.rsplit('/',1)[1])
    await session.commit()
    return result


def business_query(request, *, listing=False):
    params = request.query_params
    allowed = {'tenant_id','scope_id','limit','offset'} if listing else {'tenant_id'}
    if (request.scope.get('raw_path') != request.url.path.encode('ascii') or set(params)-allowed
            or len(params.multi_items()) != len(params) or 'tenant_id' not in params):
        fail()
    return positive_query(params['tenant_id'])


@router.post('/api/v1/seo/distribution/v2/receipts/{rid}/label')
@router.post('/api/v1/seo/distribution/v2/receipts/{rid}/unlabel')
async def label(rid: str, request: Request, ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    await ready(session)
    if not identifier(rid):
        fail()
    tenant = business_query(request)
    ctx.ensure_tenant(tenant)
    _, body = await body_for(request)
    unlabel = request.url.path.endswith('/unlabel')
    if unlabel:
        exact_object(body, ('expectedRevision','reason'))
        validate_revision(body['expectedRevision'])
        clean_text(body['reason'], 200, nullable=True)
    else:
        validate_label(body)
        if body['targetTenant'] != tenant:
            fail('INBOX_FORBIDDEN', 403)
    result = await service.label(session, ctx, rid, body, tenant, unlabel=unlabel)
    await session.commit()
    return result


@router.get('/api/v1/seo/distribution/v2/publications')
async def publications(request: Request, ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    await ready(session)
    tenant = business_query(request, listing=True)
    ctx.ensure_tenant(tenant)
    _, _, admin = await service.actor(session, ctx)
    scope = positive_query(request.query_params['scope_id']) if 'scope_id' in request.query_params else None
    if not await service.target_allowed(session, ctx.user_id, tenant, 'seo', scope):
        fail('INBOX_FORBIDDEN', 403)
    conditions = [Receipt.tenant_id == tenant, Receipt.module == 'seo', Receipt.label_state == 'active', Receipt.scope_id == scope]
    if scope is None and not admin:
        conditions.append(Receipt.owner_user_id == ctx.user_id)
    limit = positive_query(request.query_params.get('limit','50'), maximum=100)
    offset = positive_query(request.query_params.get('offset','0'), maximum=5000, minimum=0)
    rows = list(await session.scalars(select(Receipt).where(*conditions).order_by(Receipt.received_at.desc(), Receipt.id).limit(limit).offset(offset)))
    return {'schema': 2, 'total': await session.scalar(select(func.count()).select_from(Receipt).where(*conditions)),
        'items': [service.publication_receipt(service.row_dict(row), actor_id=ctx.user_id,
            expected_tenant=tenant, expected_module='seo', target_visible=True, inbox_admin=admin) for row in rows]}
