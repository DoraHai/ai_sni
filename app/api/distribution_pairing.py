"""HTTPS-only bootstrap and device-scoped metadata; no browser credential getter."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from app.database import get_session
from app.security.auth import require_auth
from app import distribution_control as core
from app import distribution_pairing as pairing
from app.distribution_pairing_contract import PairingCreate, PairingClaim, PairingRevoke, DeviceBindingsRequest


class PairingRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def private(request):
            try:
                if request.url.scheme != 'https':
                    raise pairing.problem('PAIRING_HTTPS_REQUIRED', 426)
                if request.query_params:
                    raise pairing.problem('PAIRING_QUERY_FORBIDDEN', 400)
                pairing.require_enabled()
                if request.method != 'GET':
                    if request.headers.get('content-type') != 'application/json':
                        raise pairing.problem('PAIRING_INVALID_REQUEST', 422)
                    size, chunks = 0, []
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > 4096:
                            raise pairing.problem('PAIRING_REQUEST_TOO_LARGE', 413)
                        chunks.append(chunk)
                    request._body = b''.join(chunks)
                response = await handler(request)
            except (RequestValidationError, ValidationError):
                response = JSONResponse(status_code=422, content={'detail': {'code': 'PAIRING_INVALID_REQUEST'}})
            except HTTPException as exc:
                # Never expose native authorization messages or request values.
                detail = exc.detail if isinstance(exc.detail, dict) and str(exc.detail.get('code', '')).startswith('PAIRING_') else {'code': 'PAIRING_UNAUTHORIZED' if exc.status_code == 401 else 'PAIRING_FORBIDDEN' if exc.status_code == 403 else 'PAIRING_UNAVAILABLE'}
                response = JSONResponse(status_code=exc.status_code, content={'detail': detail})
            except (SQLAlchemyError, ImportError, OSError, KeyError, ValueError):
                response = JSONResponse(status_code=503, content={'detail': {'code': 'PAIRING_UNAVAILABLE'}})
            response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
            return response
        return private


router = APIRouter(prefix='/api/distribution/v1', tags=['一次性设备配对'], route_class=PairingRoute)


async def admin(db, ctx):
    from app.api.distribution import named
    return await named(db, ctx, admin=True)


@router.post('/device-pairings')
async def create(request: PairingCreate, db=Depends(get_session), ctx=Depends(require_auth)):
    actor = await admin(db, ctx)
    result = await pairing.create(db, actor.user_id, request)
    await db.commit()
    return result


@router.get('/device-pairings')
async def listing(db=Depends(get_session), ctx=Depends(require_auth)):
    await admin(db, ctx)
    rows = await core.rows(db, 'SELECT p.*,d.label FROM distribution_device_pairings p '
        'JOIN distribution_devices d ON d.id=p.device_id ORDER BY p.created_at DESC,p.id DESC LIMIT 20')
    return {'schema': 1, 'items': [pairing.view(row) for row in rows], 'as_of': core.now_ms()}


# Static claim path precedes the UUID resource paths.
@router.post('/device-pairings/claim')
async def claim(request: PairingClaim, http: Request, db=Depends(get_session)):
    if 'authorization' in http.headers or 'origin' in http.headers or any(key.startswith('sec-fetch-') for key in http.headers):
        raise pairing.problem('PAIRING_DEVICE_ONLY', 400)
    result = await pairing.claim(db, request)
    await db.commit()
    return result


@router.get('/device-pairings/{pairing_id}')
async def read(pairing_id: UUID, db=Depends(get_session), ctx=Depends(require_auth)):
    await admin(db, ctx)
    return {'schema': 1, 'pairing': pairing.view(await pairing.row_by_id(db, pairing_id))}


@router.post('/device-pairings/{pairing_id}/revoke')
async def revoke(pairing_id: UUID, request: PairingRevoke, db=Depends(get_session), ctx=Depends(require_auth)):
    actor = await admin(db, ctx)
    row = await pairing.row_by_id(db, pairing_id)
    await core.audit(db, actor.user_id, 'pairing_revoke_requested', {'pairing_id': str(pairing_id), 'request_id': str(request.request_id)}, 'REQUESTED')
    from app.api.distribution import revoke as revoke_device
    await revoke_device(row['device_id'], db, actor)
    result = {'schema': 1, 'pairing': pairing.view(await pairing.row_by_id(db, pairing_id))}
    await db.commit()
    return result


@router.post('/device/bindings')
async def bindings(request: DeviceBindingsRequest, http: Request, db=Depends(get_session)):
    from app.api.distribution import device_credential
    result = await pairing.device_bindings(db, device_credential(http), request.device_id)
    await db.commit()
    return result
