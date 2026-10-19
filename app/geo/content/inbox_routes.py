"""Exact GEO business routes for external inbox labels and publications."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.exc import DBAPIError, IntegrityError
from starlette.responses import JSONResponse

from app.database import get_session
from app.distribution_inbox_protocol import (ProtocolError, fail, strict_json, validate_label,
    validate_revision, exact_object, clean_text, match_inbox_business_route)
from app.security.auth import require_auth
from app.geo.content import inbox as service

PREFIX = '/api/v1/geo/distribution/v2'


class SafeRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handle(request):
            try:
                response = await original(request)
            except ProtocolError as error:
                response = JSONResponse({'detail': error.detail}, status_code=error.status)
            except RequestValidationError:
                error = ProtocolError()
                response = JSONResponse({'detail': error.detail}, status_code=422)
            except HTTPException as error:
                response = JSONResponse({'detail': error.detail}, status_code=error.status_code)
            response.headers['Cache-Control'] = 'no-store'
            return response
        return handle


router = APIRouter(prefix=PREFIX, tags=['GEO 外部回传'], route_class=SafeRoute)


def request_scope(request):
    if (not match_inbox_business_route(request.method, request.url.path, 'geo')
            or request.scope.get('raw_path', b'') != request.url.path.encode('ascii')):
        fail('INBOX_FORBIDDEN', 403)
    allowed = {'tenant_id', 'scope_id'} if request.method == 'GET' else {'tenant_id'}
    if (len(request.query_params) != len(request.query_params.multi_items())
            or not set(request.query_params) <= allowed or 'tenant_id' not in request.query_params):
        fail()
    def positive(key):
        value = request.query_params.get(key)
        if value is None:
            return None
        if not re.fullmatch('[1-9][0-9]{0,17}', value):
            fail()
        return int(value)
    return positive('tenant_id'), positive('scope_id')


async def safe_session(session=Depends(get_session)):
    try:
        yield session
    except ProtocolError as error:
        await session.rollback()
        raise HTTPException(error.status, error.detail) from None
    except IntegrityError:
        await session.rollback()
        error = ProtocolError('DUPLICATE_LINK', 409)
        raise HTTPException(error.status, error.detail) from None
    except DBAPIError:
        await session.rollback()
        error = ProtocolError('INBOX_SCHEMA_NOT_READY', 503)
        raise HTTPException(error.status, error.detail) from None
    except BaseException:
        await session.rollback()
        raise


async def read_body(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16384:
            fail(status=413)
    return strict_json(bytes(raw))


def respond(value):
    return JSONResponse(value, headers={'Cache-Control': 'no-store'})


@router.post('/receipts/{receiptId}/label')
async def label(receiptId: str, request: Request, session=Depends(safe_session), ctx=Depends(require_auth)):
    tenant, _ = request_scope(request)
    data = validate_label(await read_body(request))
    if data['targetTenant'] != tenant:
        fail('INBOX_FORBIDDEN', 403)
    await service.schema_ready(session)
    result = await service.label(session, ctx, receiptId, tenant, data)
    await session.commit()
    return respond(result)


@router.post('/receipts/{receiptId}/unlabel')
async def unlabel(receiptId: str, request: Request, session=Depends(safe_session), ctx=Depends(require_auth)):
    tenant, _ = request_scope(request)
    data = exact_object(await read_body(request), ('expectedRevision', 'reason'))
    validate_revision(data['expectedRevision'])
    clean_text(data['reason'], 200, nullable=True)
    await service.schema_ready(session)
    result = await service.unlabel(session, ctx, receiptId, tenant, data)
    await session.commit()
    return respond(result)


@router.get('/publications')
async def publications(request: Request, session=Depends(safe_session), ctx=Depends(require_auth)):
    tenant, scope = request_scope(request)
    await service.schema_ready(session)
    result = await service.publications(session, ctx, tenant, scope)
    return respond(result)
