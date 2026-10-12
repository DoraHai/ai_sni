"""Authenticated account-window remote routes, mounted without main/auth edits."""
from uuid import UUID
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_session
from app.security.auth import require_auth
from app import distribution_execution_capabilities as capabilities
from app.distribution_remote import broker, error
from app.distribution_remote_contract import SessionCreate, SessionInput, SessionClose, DevicePoll, DeviceAck, FrameHeaders


class RemoteRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def private(request):
            try:
                if request.query_params:raise error('REMOTE_QUERY_FORBIDDEN',400)
                if request.method!='GET':
                    limit=2097152 if request.url.path.endswith('/device/frame') else 16384
                    parts=[];size=0
                    async for chunk in request.stream():
                        size+=len(chunk)
                        if size>limit:raise error('REMOTE_REQUEST_TOO_LARGE',413)
                        parts.append(chunk)
                    request._body=b''.join(parts)
                response=await handler(request)
            except (RequestValidationError,ValidationError):
                response=JSONResponse(status_code=422,content={'detail':{'code':'REMOTE_INVALID_REQUEST'}})
            except HTTPException as exc:
                exc.headers={**(exc.headers or {}),'Cache-Control':'no-store'};raise
            except (SQLAlchemyError,ImportError,OSError,KeyError,ValueError):
                raise error('REMOTE_UNAVAILABLE',503) from None
            response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
            return response
        return private


@asynccontextmanager
async def lifespan(app):
    from app.database import engine
    await broker.start(engine)
    try:yield
    finally:await broker.stop()


router=APIRouter(prefix='/api/distribution/v1/remote',tags=['顾问远程账号窗口'],route_class=RemoteRoute,lifespan=lifespan)


async def named(db,ctx):
    # Safe for both direct mounting and mounting from the legacy router.
    from app.api.distribution import named as current_named
    return await current_named(db,ctx)


def device_credential(request):
    from app.api.distribution import device_credential as current_credential
    return current_credential(request)


@router.post('/sessions')
async def create(req:SessionCreate,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx)
    async with broker.creation_guard:
        result=None
        try:
            result=await broker.create(db,fresh.user_id,req)
            await db.commit();return result
        except BaseException:
            if result:broker.forget(result['session']['id'])
            raise


@router.get('/sessions/{session_id}')
async def view(session_id:UUID,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx);row=await broker.checked(db,session_id,fresh.user_id,allow_closed=True)
    await db.commit();return {'schema':1,'session':broker.view(row)}


@router.get('/sessions/{session_id}/frame')
async def frame_read(session_id:UUID,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx);row,raw=await broker.frame_read(db,fresh.user_id,session_id)
    await db.commit()
    broker.note_read(row)
    return Response(raw,media_type='image/png',headers={'X-Frame-Seq':str(row['last_frame_seq']),
        'X-Control-Revision':str(row['control_revision']),'X-Viewport-Width':str(row['viewport_width']),
        'X-Viewport-Height':str(row['viewport_height']),'X-Remote-Session-Id':str(row['id']),
        'X-Remote-Device-Id':row['device_id'],'X-Frame-Captured-At':str(row['captured_at']),
        'Content-Security-Policy':"default-src 'none'; sandbox"})


@router.post('/sessions/{session_id}/input')
async def input(session_id:UUID,req:SessionInput,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx);result=await broker.input(db,fresh.user_id,session_id,req)
    await db.commit();return result


@router.post('/sessions/{session_id}/close')
async def close(session_id:UUID,req:SessionClose,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx);result=await broker.close(db,fresh.user_id,session_id,req)
    await db.commit();return result


@router.post('/device/poll')
async def poll(req:DevicePoll,request:Request,db=Depends(get_session)):
    await capabilities.authenticate(db,device_credential(request),req.device_id)
    result=await broker.poll(db,req.device_id);await db.commit();return result


@router.post('/device/frame')
async def frame_upload(request:Request,db=Depends(get_session)):
    if request.headers.get('content-type')!='image/png':raise error('REMOTE_INVALID_REQUEST',422)
    names={'device_id':'X-Remote-Device-Id','session_id':'X-Remote-Session-Id','frame_seq':'X-Frame-Seq',
        'control_revision':'X-Control-Revision','viewport_width':'X-Viewport-Width','viewport_height':'X-Viewport-Height',
        'captured_at':'X-Frame-Captured-At'}
    try:
        values={key:request.headers[name] for key,name in names.items()}
        for key in ('frame_seq','control_revision','viewport_width','viewport_height','captured_at'):
            if not values[key].isascii() or not values[key].isdigit():raise ValueError()
            values[key]=int(values[key])
        req=FrameHeaders.model_validate(values)
    except (KeyError,ValueError,ValidationError):raise error('REMOTE_INVALID_REQUEST',422) from None
    await capabilities.authenticate(db,device_credential(request),req.device_id)
    result=await broker.frame(db,req.device_id,req,await request.body());await db.commit();return result


@router.post('/device/ack')
async def ack(req:DeviceAck,request:Request,db=Depends(get_session)):
    await capabilities.authenticate(db,device_credential(request),req.device_id)
    result=await broker.ack(db,req.device_id,req);await db.commit();return result
