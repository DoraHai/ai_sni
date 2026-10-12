"""Native upload/review router; explicitly mount in local integration app only."""
from uuid import UUID
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_session
from app.security.auth import require_auth
from app import seo_distribution_media as media
from app.seo_distribution_sources import authorize_scope, denied


class PrivateMediaRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request):
            try:
                if request.method=='POST':
                    chunks=[]; size=0
                    async for chunk in request.stream():
                        size+=len(chunk)
                        if size>media.MAX_TOTAL+65536:
                            return JSONResponse(status_code=413,content={'detail':{'code':'seo_distribution_asset_invalid'}},
                                headers={'Cache-Control':'no-store'})
                        chunks.append(chunk)
                    request._body=b''.join(chunks)
                result = await handler(request)
                result.headers['Cache-Control']='no-store'
                result.headers['X-Content-Type-Options']='nosniff'
                return result
            except RequestValidationError:
                return JSONResponse(status_code=422,content={'detail':{'code':'seo_distribution_asset_invalid'}},
                    headers={'Cache-Control':'no-store'})
            except HTTPException as exc:
                exc.headers={**(exc.headers or {}),'Cache-Control':'no-store'}
                raise
            except (SQLAlchemyError,OSError,TimeoutError):
                exc=denied('source_unavailable','素材存储暂不可用，请稍后核对',503)
                exc.headers={'Cache-Control':'no-store'}
                raise exc from None
        return guarded


router = APIRouter(prefix='/api/seo/distribution-media',route_class=PrivateMediaRoute)
UI_ROOT=Path(__file__).resolve().parents[1]/'static'/'seo-distribution-media'


@router.get('/workspace')
async def workspace():
    # Public static shell only. Every data request requires named authorization.
    return FileResponse(UI_ROOT/'index.html',headers={'Content-Security-Policy':
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})


@router.get('/ui/{name}')
async def ui_file(name:str):
    paths={'app.js':UI_ROOT/'app.js','style.css':UI_ROOT/'style.css',
        'session.js':Path(__file__).resolve().parents[2]/'frontend'/'src'/'store'/'sessionStorage.js'}
    if name not in paths: raise HTTPException(404)
    return FileResponse(paths[name],media_type='text/css' if name.endswith('.css') else 'text/javascript')


@router.get('/variants')
async def drafts(tenant_id:int=Query(gt=0),site_id:int=Query(gt=0),db=Depends(get_session),ctx=Depends(require_auth)):
    return {'items':await media.list_drafts(db,ctx.user_id,tenant_id,site_id)}


class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    tenant_id: int = Field(gt=0,strict=True)
    site_id: int = Field(gt=0,strict=True)
    set_id: UUID
    expected_token: str = Field(pattern='^[a-f0-9]{64}$')


@router.get('/variants/{variant_id}')
async def preview(variant_id:int,tenant_id:int=Query(gt=0),site_id:int=Query(gt=0),
                  db=Depends(get_session),ctx=Depends(require_auth)):
    return await media.preview(db,ctx.user_id,tenant_id,site_id,variant_id)


@router.post('/variants/{variant_id}/assets')
async def upload(variant_id:int,tenant_id:int=Form(gt=0),site_id:int=Form(gt=0),expected_token:str=Form(pattern='^[a-f0-9]{64}$'),
                 files:list[UploadFile]=File(...),db=Depends(get_session),ctx=Depends(require_auth)):
    await authorize_scope(db,ctx.user_id,tenant_id,site_id)
    if not 1<=len(files)<=media.MAX_IMAGES: raise denied('asset_invalid','须上传 1 至 9 张图片',422)
    images=[]
    for file in files:
        images.append(await file.read(media.MAX_IMAGE+1))
    result=await media.replace_assets(db,ctx.user_id,tenant_id,site_id,variant_id,expected_token,images)
    await db.commit()
    return result


@router.get('/variants/{variant_id}/assets/{asset_id}')
async def preview_asset(variant_id:int,asset_id:str,tenant_id:int=Query(gt=0),site_id:int=Query(gt=0),
                        db=Depends(get_session),ctx=Depends(require_auth)):
    data,kind=await media.preview_asset(db,ctx.user_id,tenant_id,site_id,variant_id,asset_id)
    return Response(data,media_type=kind)


@router.post('/variants/{variant_id}/review')
async def review(variant_id:int,request:Review,db=Depends(get_session),ctx=Depends(require_auth)):
    result=await media.review_assets(db,ctx.user_id,request.tenant_id,request.site_id,variant_id,
        request.expected_token,request.set_id)
    await db.commit()
    return result
