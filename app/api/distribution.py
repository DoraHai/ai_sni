"""Named advisor controls and separately authenticated device exchange."""
from __future__ import annotations
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_session
from app.models.role import Role
from app.models.user import User
from app.security.auth import AuthContext, require_auth
from app.distribution_contract import (Binding, DeviceCreate, Exchange, Module, Platform, ProjectControl, Scope, TaskCreate,
    AccountPolicy, AccountPause, AccountRestriction, TaskResolution, PublicationCheck, PublicationWriteback)
from app import distribution_control as core
from app import distribution_scheduling as scheduling
from app import distribution_publication_results as publications
from app import distribution_queue as queue
from app.distribution_contract import ChannelPermission, ProjectChannel
from app.distribution_contract import HandoffPermission
from app import distribution_execution as execution
from app import distribution_execution_capabilities as execution_capabilities


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def private(request):
            try:
                if request.method!='GET':
                    chunks=[]; size=0
                    async for chunk in request.stream():
                        size+=len(chunk)
                        if size>1048576:
                            return JSONResponse(status_code=413,content={'detail':{'code':'request_too_large'}},headers={'Cache-Control':'no-store'})
                        chunks.append(chunk)
                    request._body=b''.join(chunks)
                response=await handler(request)
            except RequestValidationError:
                return JSONResponse(status_code=422,content={'detail':{'code':'distribution_invalid_request'}},headers={'Cache-Control':'no-store'})
            except HTTPException as exc:
                exc.headers={**(exc.headers or {}),'Cache-Control':'no-store'}; raise
            except (SQLAlchemyError, ImportError, OSError, KeyError, ValueError):
                raise core.problem('distribution_unavailable',503) from None
            response.headers['Cache-Control']='no-store'
            return response
        return private


router=APIRouter(prefix='/api/distribution/v1',tags=['顾问分发接入'],route_class=PrivateRoute)


@router.get('/platform-directory')
async def platform_directory(module:Module,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx);scope={'module':module,'tenant_id':tenant_id,'scope_id':scope_id}
    await core.authorize_scope(db,fresh.user_id,scope)
    return {'schema':1,**scope,'items':execution_capabilities.directory()}


@router.post('/handoff-permission')
async def handoff_permission(req:HandoffPermission,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx);value=await execution.configure(db,fresh.user_id,req);await db.commit()
    return {'schema':1,'permission':value}


@router.get('/execution-progress')
async def execution_progress(module:Module,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx);scope={'module':module,'tenant_id':tenant_id,'scope_id':scope_id}
    await core.authorize_scope(db,fresh.user_id,scope)
    permissions=await core.rows(db,'SELECT binding_id,enabled,stage,revision FROM distribution_handoff_permissions WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id ORDER BY binding_id LIMIT 100',**scope)
    intents=await core.rows(db,'SELECT e.id,e.queue_id,e.plan_id,e.binding_id,e.task_id,e.draft_version,e.source_revision,e.content_digest,e.stage,e.capability_digest,t.status,t.revoked,t.receipt FROM distribution_execution_intents e JOIN distribution_tasks t ON t.id=e.task_id WHERE e.tenant_id=:tenant_id AND e.module=:module AND e.scope_id=:scope_id ORDER BY e.created_at DESC,e.id LIMIT 100',**scope)
    waits=await core.rows(db,'SELECT s.queue_id,s.checked_at,s.reason FROM distribution_execution_scans s JOIN distribution_queue q ON q.id=s.queue_id WHERE q.tenant_id=:tenant_id AND q.module=:module AND q.scope_id=:scope_id ORDER BY s.checked_at DESC,s.queue_id LIMIT 100',**scope)
    return {'schema':1,**scope,'waits':[dict(w) for w in waits],'permissions':[dict(p) for p in permissions],'items':[dict(i) for i in intents],'automatic_publish':False}


@router.get('/plans')
async def plans_view(module:Module,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx); scope={'module':module,'tenant_id':tenant_id,'scope_id':scope_id}
    await core.authorize_scope(db,fresh.user_id,scope)
    items=await core.rows(db,'SELECT p.id,p.queue_id,p.binding_id,p.draft_version,p.source_revision,p.planned_at,p.basis,p.state,p.reason,p.checked_at '
        'FROM distribution_plans p WHERE p.tenant_id=:tenant_id AND p.module=:module AND p.scope_id=:scope_id ORDER BY p.created_at DESC,p.id LIMIT 100',**scope)
    requests=await core.rows(db,'SELECT id,state,reason,attempts,retry_at,updated_at FROM distribution_plan_requests '
        'WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id ORDER BY updated_at DESC,id LIMIT 20',**scope)
    return {'schema':1,**scope,'items':[dict(p) for p in items],'requests':[dict(p) for p in requests],'automated_publish':False}


@router.get('/channel-catalog')
async def channel_catalog(db=Depends(get_session),ctx=Depends(require_auth)):
    await named(db,ctx,admin=True)
    return {'schema':1,'items':await queue.catalog(db)}


@router.post('/channel-permission')
async def channel_permission(req:ChannelPermission,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx,admin=True)
    result=await queue.set_permission(db,fresh.user_id,req)
    await db.commit(); return {'schema':1,'capability':result}


@router.get('/project-channels')
async def project_channels(module:Module,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx); scope={'module':module,'tenant_id':tenant_id,'scope_id':scope_id}
    return {'schema':1,**scope,'items':await queue.channels(db,fresh.user_id,scope)}


@router.post('/project-channel')
async def project_channel(req:ProjectChannel,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx)
    result=await queue.set_channel(db,fresh.user_id,req)
    await db.commit(); return {'schema':1,'selection':result}


@router.get('/queue')
async def queue_view(module:Module,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx); scope={'module':module,'tenant_id':tenant_id,'scope_id':scope_id}
    await core.authorize_scope(db,fresh.user_id,scope)
    items=await core.rows(db,'SELECT id,binding_id,variant_id,draft_version,source_revision,platform,state,reason,next_allowed_at,created_at,checked_at '
        'FROM distribution_queue WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id ORDER BY created_at DESC,id LIMIT 100',**scope)
    scans=await core.rows(db,'SELECT binding_id,state,reason,checked_at,discovery FROM distribution_queue_scans '
        'WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id ORDER BY binding_id LIMIT 100',**scope)
    return {'schema':1,**scope,'items':[dict(q) for q in items],'scans':[dict(q) for q in scans],
        'completed_draft_events_connected':False}


async def named(db, ctx, *, admin=False):
    if ctx.user_id is None: raise core.problem('scope_forbidden',403)
    user=await db.get(User,ctx.user_id,populate_existing=True,with_for_update={'read':True})
    role=await db.get(Role,user.role_id,populate_existing=True,with_for_update={'read':True}) if user else None
    if not user or not user.is_active or not role: raise core.problem('scope_forbidden',403)
    fresh=AuthContext(user.id,user.username,role.name,user.tenant_id,dict(role.permissions or {}))
    if admin and (fresh.tenant_id is not None or not all(fresh.can_edit(k) for k in ('settings.accounts','settings.customers'))):
        raise core.problem('scope_forbidden',403)
    return fresh


@router.post('/devices')
async def create_device(req:DeviceCreate,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx,admin=True)
    from app.distribution_pairing import enabled
    if enabled():raise core.problem('DEVICE_PAIRING_REQUIRED',409)
    result=await core.create_device(db,fresh.user_id,req.label)
    await db.commit(); return {'schema':1,'device':result}


@router.get('/devices')
async def devices(db=Depends(get_session),ctx=Depends(require_auth)):
    await named(db,ctx,admin=True)
    result=await core.rows(db,'SELECT id,label,active,last_seen_at,created_at FROM distribution_devices ORDER BY created_at DESC LIMIT 100')
    return {'schema':1,'items':[dict(row) for row in result],'as_of':core.now_ms()}


@router.post('/devices/{device_id}/revoke')
async def revoke(device_id:str,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx,admin=True); await core.lock(db,'device:'+device_id)
    device=await core.one(db,'SELECT id FROM distribution_devices WHERE id=:id',id=device_id)
    if not device: raise core.problem('binding_unavailable',404)
    from app.distribution_pairing import revoke_for_device
    await revoke_for_device(db,device_id,fresh.user_id)
    await db.execute(core.text('UPDATE distribution_devices SET active=false WHERE id=:id'),{'id':device_id})
    await db.execute(core.text("UPDATE distribution_tasks SET revoked=true,status=CASE WHEN status='queued' THEN 'canceled' "
        "WHEN status IN ('leased','running','awaiting-human') THEN 'unknown' ELSE status END WHERE device_id=:id"),{'id':device_id})
    await execution.release_canceled(db,device_id=device_id)
    await core.audit(db,fresh.user_id,'device_revoked',{'device_id':device_id},'REVOKED')
    await db.commit(); return {'schema':1,'id':device_id,'active':False}


@router.post('/bindings')
async def binding(req:Binding,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx,admin=True)
    result=await core.bind(db,fresh.user_id,req); await db.commit()
    return {'schema':1,'binding':result}


@router.get('/bindings')
async def bindings(db=Depends(get_session),ctx=Depends(require_auth)):
    await named(db,ctx,admin=True)
    result=await core.rows(db,'SELECT b.id,b.module,b.tenant_id,b.scope_id,b.device_id,b.account_id,'
        'b.external_account_id,b.platform,b.active,d.label AS device_label,d.active AS device_active '
        'FROM distribution_bindings b JOIN distribution_devices d ON d.id=b.device_id ORDER BY b.id LIMIT 100')
    return {'schema':1,'items':[dict(row) for row in result]}


@router.post('/bindings/{binding_id}/revoke')
async def revoke_binding(binding_id:UUID,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx,admin=True)
    binding=await core.one(db,'SELECT * FROM distribution_bindings WHERE id=:id',id=binding_id)
    if not binding: raise core.problem('binding_unavailable',404)
    scope={k:binding[k] for k in ('module','tenant_id','scope_id')}
    await core.lock(db,'device:'+binding['device_id']); await core.lock(db,'scope:'+core.canonical(scope))
    await db.execute(core.text('UPDATE distribution_bindings SET active=false WHERE id=:id'),{'id':binding_id})
    await db.execute(core.text("UPDATE distribution_tasks SET revoked=true,status=CASE WHEN status='queued' THEN 'canceled' "
        "WHEN status IN ('leased','running','awaiting-human') THEN 'unknown' ELSE status END WHERE binding_id=:id"),{'id':binding_id})
    await execution.release_canceled(db,binding_id=binding_id)
    await core.audit(db,fresh.user_id,'account_binding_revoked',{**scope,'binding_id':str(binding_id)},'REVOKED')
    await db.commit(); return {'schema':1,'id':str(binding_id),'active':False}


@router.get('/scope')
async def scope_view(module:Module,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx); scope=Scope(module=module,tenant_id=tenant_id,scope_id=scope_id).model_dump()
    await core.authorize_scope(db,fresh.user_id,scope)
    project=await core.one(db,'SELECT * FROM distribution_controls WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id',**scope)
    result=await core.rows(db,'SELECT b.id,b.device_id,b.account_id,b.platform,b.active,d.label AS device_label,d.last_seen_at '
        'FROM distribution_bindings b JOIN distribution_devices d ON d.id=b.device_id '
        'WHERE b.module=:module AND b.tenant_id=:tenant_id AND b.scope_id=:scope_id AND b.active AND d.active ORDER BY b.id LIMIT 100',**scope)
    return {'schema':1,**scope,'project':project or {**scope,'state':'paused','revision':0,'owner_user_id':None},
        'bindings':[dict(row) for row in result],'as_of':core.now_ms(),
        'capabilities':{'automated_publish':False,'human_handoff':True,'real_channel_verified':False}}


@router.post('/control')
async def control(req:ProjectControl,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx); value=await core.control(db,fresh.user_id,req)
    await db.commit(); return {'schema':1,'project':value}


@router.get('/source')
async def source(module:Module,platform:Platform,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),variant_id:int=Query(ge=1),
    db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx); scope={'module':module,'tenant_id':tenant_id,'scope_id':scope_id}
    value,digest=await core.source(db,fresh.user_id,scope,variant_id,platform)
    return {'schema':1,**value,'content_digest':digest,'platform':platform}


@router.get('/sources')
async def sources(module:Module,platform:Platform,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),
    db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx); scope={'module':module,'tenant_id':tenant_id,'scope_id':scope_id}
    candidates=await core.adapter(module).list_sources(db,fresh.user_id,tenant_id,scope_id,platform)
    if not isinstance(candidates,list) or len(candidates)>50: raise core.problem('distribution_unavailable',503)
    result=[]
    for candidate in candidates:
        try:
            value,_digest=await core.source(db,fresh.user_id,scope,candidate['variant_id'],platform)
        except HTTPException as exc:
            # Module drafts can exceed the executor contract. Only offer full,
            # currently valid snapshots; never truncate an approved article.
            if exc.status_code in (404,409,422): continue
            raise
        if value['source_revision']!=candidate['source_revision']: continue
        result.append({'variant_id':value['variant_id'],'source_revision':value['source_revision'],
            'title':value['content']['title'],'platform':platform})
    return {'schema':1,**scope,'platform':platform,'items':result}


@router.post('/tasks')
async def task(req:TaskCreate,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx); value=await core.enqueue(db,fresh.user_id,req)
    await db.commit(); return {'schema':1,'task':value}


@router.get('/tasks')
async def tasks(module:Module,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx); scope={'module':module,'tenant_id':tenant_id,'scope_id':scope_id}
    await core.authorize_scope(db,fresh.user_id,scope)
    result=await core.rows(db,'SELECT * FROM distribution_tasks WHERE tenant_id=:tenant_id AND module=:module '
        'AND scope_id=:scope_id AND advisor_user_id=:actor ORDER BY created_at DESC,id DESC LIMIT 100',**scope,actor=fresh.user_id)
    items=[]
    for row in result:
        item=core.task_view(dict(row))
        if row['action']=='handoff':
            item['content_digest']=row['content_digest']
            item['handoff_investigable']=row['status']=='unknown' or row['status'] in ('leased','running','awaiting-human') and min(row['grant_expires_at'],row['lease_expires_at'])<=core.now_ms()
            if await execution.installed(db):
                intent=await core.one(db,'SELECT attempt FROM distribution_execution_intents WHERE task_id=:id',id=row['id'])
                item['handoff_attempt']=intent['attempt'] if intent else None
            if (await core.one(db,"SELECT to_regclass(current_schema()||'.distribution_handoff_resolutions') IS NOT NULL AS ready"))['ready']:
                item['handoff_resolution']=await core.one(db,'SELECT outcome,checked_at FROM distribution_handoff_resolutions WHERE task_id=:id',id=row['id'])
        account=await core.one(db,'SELECT * FROM distribution_bindings WHERE id=:id',id=row['binding_id'])
        if row['action']=='publish': item['schedule']=await scheduling.schedule(db,account,row['id'])
        item['resolution']=await core.one(db,'SELECT outcome,checked_at,public_url FROM distribution_task_resolutions WHERE task_id=:id ORDER BY id DESC LIMIT 1',id=row['id'])
        item['publication']=await publications.view(db,row['id'])
        items.append(item)
    return {'schema':1,**scope,'items':items}


@router.post('/publication-check')
async def publication_check(req:PublicationCheck,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx)
    prepared,_fingerprint,prior=await publications.prepare_check(db,fresh.user_id,req)
    if prior: return prior
    # Public network I/O must never hold user locks or a DB transaction open.
    await db.rollback()
    observation=await publications.inspect(prepared,req)
    fresh=await named(db,ctx)
    result=await publications.finish_check(db,fresh.user_id,req,prepared,observation)
    await db.commit(); return result


@router.get('/publication-source')
async def publication_source(module:Module,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),task_id:UUID=Query(),
    db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx); scope={'module':module,'tenant_id':tenant_id,'scope_id':scope_id}
    task=await publications.task_for_actor(db,fresh.user_id,scope,task_id)
    await publications.reported(db,task)
    content=publications.frozen_content(task)
    account=await core.one(db,'SELECT external_account_id FROM distribution_bindings WHERE id=:id',id=task['binding_id'])
    if not account: raise core.problem('binding_unavailable')
    return {'schema':1,**scope,'task_id':str(task_id),'variant_id':task['variant_id'],'source_revision':task['source_revision'],
        'content_digest':task['content_digest'],'platform':task['platform'],'external_account_id':account['external_account_id'],'content':content}


@router.get('/publication-monitor')
async def publication_monitor(module:Module,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),task_id:UUID=Query(),
    db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx)
    return await publications.monitor_view(db,fresh.user_id,{'module':module,'tenant_id':tenant_id,'scope_id':scope_id},task_id)


@router.get('/publication-assets/{task_id}/{asset_id}')
async def publication_asset(task_id:UUID,asset_id:str,module:Module,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),
    db=Depends(get_session),ctx=Depends(require_auth)):
    import hashlib
    from io import BytesIO
    from PIL import Image, ImageFile
    fresh=await named(db,ctx); scope={'module':module,'tenant_id':tenant_id,'scope_id':scope_id}
    task=await publications.task_for_actor(db,fresh.user_id,scope,task_id)
    await publications.reported(db,task)
    asset=next((a for a in publications.frozen_content(task)['assets'] if a['id']==asset_id),None)
    if not asset: raise core.problem('scope_forbidden',403)
    # Historical images cannot be substituted by the latest draft's images.
    # Native load_asset repeats its current role/review gate and immutable IDs.
    loader=getattr(core.adapter(module),'load_asset',None)
    if not loader: raise core.problem('source_unavailable',503)
    data=await loader(db,fresh.user_id,tenant_id,scope_id,task['variant_id'],task['platform'],asset_id)
    if not isinstance(data,bytes) or len(data)!=asset['bytes'] or hashlib.sha256(data).hexdigest()!=asset['sha256']: raise core.problem('source_changed')
    if ImageFile.LOAD_TRUNCATED_IMAGES: raise core.problem('image_decoder_unavailable',503)
    try:
        with Image.open(BytesIO(data)) as picture:
            if picture.format!=('PNG' if asset['mediaType']=='image/png' else 'JPEG') or picture.width*picture.height>25000000 or getattr(picture,'n_frames',1)!=1: raise ValueError('Invalid image')
            picture.verify()
        with Image.open(BytesIO(data)) as picture: picture.load()
    except (ValueError,OSError,SyntaxError,Image.DecompressionBombError): raise core.problem('source_changed') from None
    return Response(data,media_type=asset['mediaType'],headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','ETag':'"'+asset['sha256']+'"'})


@router.post('/publication-writeback')
async def publication_writeback(req:PublicationWriteback,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx)
    result=await publications.retry_writeback(db,fresh.user_id,req)
    await db.commit(); return result


@router.get('/account-policies')
async def account_policies(db=Depends(get_session),ctx=Depends(require_auth)):
    await named(db,ctx,admin=True)
    bindings=await core.rows(db,'SELECT * FROM distribution_bindings WHERE active ORDER BY id LIMIT 100')
    return {'schema':1,'items':[await scheduling.schedule(db,dict(b)) for b in bindings]}


@router.get('/admin-events')
async def admin_events(db=Depends(get_session),ctx=Depends(require_auth)):
    await named(db,ctx,admin=True)
    values=await core.rows(db,'SELECT id,at,actor,action,task_id,result,target FROM distribution_events ORDER BY id DESC LIMIT 100')
    # Audit payloads are server-generated IDs/results, never credentials or content.
    allowed={'module','tenant_id','scope_id','binding_id','device_id','variant_id','action','platform','content_type'}
    return {'schema':1,'items':[{**dict(e),'target':{k:v for k,v in e['target'].items() if k in allowed}} for e in values]}


@router.post('/account-policy')
async def account_policy(req:AccountPolicy,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx,admin=True)
    result=await scheduling.set_policy(db,fresh.user_id,req); await db.commit()
    return {'schema':1,'schedule':result}


@router.post('/account-pause')
async def account_pause(req:AccountPause,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx,admin=True)
    result=await scheduling.pause_account(db,fresh.user_id,req); await db.commit()
    return {'schema':1,'schedule':result}


@router.get('/account-schedules')
async def account_schedules(module:Module,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx); scope={'module':module,'tenant_id':tenant_id,'scope_id':scope_id}
    await core.authorize_scope(db,fresh.user_id,scope)
    bindings=await core.rows(db,'SELECT * FROM distribution_bindings WHERE module=:module AND tenant_id=:tenant_id AND scope_id=:scope_id '
        'AND active ORDER BY id LIMIT 100',**scope)
    return {'schema':1,**scope,'items':[await scheduling.schedule(db,dict(b)) for b in bindings]}


@router.post('/account-restriction')
async def account_restriction(req:AccountRestriction,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx)
    result=await scheduling.set_restriction(db,fresh.user_id,req); await db.commit()
    return {'schema':1,'schedule':result}


@router.post('/task-resolution')
async def task_resolution(req:TaskResolution,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx)
    result=await scheduling.resolve(db,fresh.user_id,req); await db.commit()
    return {'schema':1,**result}


@router.get('/device/tasks/{task_id}/assets/{asset_id}')
async def device_asset(task_id:UUID,asset_id:str,request:Request,db=Depends(get_session)):
    import hashlib, secrets, re
    from io import BytesIO
    authorization=request.headers.get('authorization','')
    if not authorization.startswith('Bearer ') or not 40<=len(authorization)<=300 or request.query_params or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',asset_id):
        raise core.problem('device_unauthorized',401)
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=task_id)
    if not task: raise core.problem('scope_forbidden',403)
    await core.lock(db,'device:'+task['device_id'])
    scope={k:task[k] for k in ('module','tenant_id','scope_id')}; await core.lock(db,'scope:'+core.canonical(scope))
    device=await core.one(db,'SELECT * FROM distribution_devices WHERE id=:id AND active',id=task['device_id'])
    if not device or not secrets.compare_digest(device['credential_hash'],hashlib.sha256(authorization[7:].encode()).hexdigest()):
        raise core.problem('device_unauthorized',401)
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=task_id)
    account=await scheduling.binding(db,task['binding_id'],scope); await scheduling.account_lock(db,account)
    project=await core.one(db,'SELECT * FROM distribution_controls WHERE module=:module AND tenant_id=:tenant_id AND scope_id=:scope_id',**scope)
    if task['revoked'] or task['status'] not in ('leased','running','awaiting-human') or not project or project['state']!='running' or project['owner_user_id']!=task['advisor_user_id'] or min(task['grant_expires_at'],task['lease_expires_at'])<=core.now_ms():
        raise core.problem('scope_forbidden',403)
    if task['action']=='publish' and not (await scheduling.schedule(db,account,task['id']))['available']:
        raise core.problem('account_not_ready')
    if not await execution.task_valid(db,task):raise core.problem('scope_forbidden',403)
    source,digest=await core.source(db,task['advisor_user_id'],scope,task['variant_id'],task['platform'])
    if digest!=task['content_digest'] or source['source_revision']!=task['source_revision']: raise core.problem('source_changed')
    asset=next((a for a in source['content']['assets'] if a['id']==asset_id),None)
    if not asset: raise core.problem('scope_forbidden',403)
    loader=getattr(core.adapter(task['module']),'load_asset',None)
    if not loader: raise core.problem('source_unavailable',503)
    data=await loader(db,task['advisor_user_id'],task['tenant_id'],task['scope_id'],task['variant_id'],task['platform'],asset_id)
    if not isinstance(data,bytes) or len(data)!=asset['bytes'] or hashlib.sha256(data).hexdigest()!=asset['sha256']:
        raise core.problem('source_changed')
    from PIL import Image, ImageFile
    if ImageFile.LOAD_TRUNCATED_IMAGES: raise core.problem('image_decoder_unavailable',503)
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format!=('PNG' if asset['mediaType']=='image/png' else 'JPEG') or image.width*image.height>25000000 or getattr(image,'n_frames',1)!=1:
                raise ValueError('Invalid image')
            image.verify()
        with Image.open(BytesIO(data)) as image: image.load()
    except (ValueError,OSError,SyntaxError,Image.DecompressionBombError): raise core.problem('source_changed') from None
    return Response(data,media_type=asset['mediaType'],headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
        'ETag':'"'+asset['sha256']+'"'})


@router.get('/events')
async def events(module:Module,tenant_id:int=Query(ge=1),scope_id:int=Query(ge=1),db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx); scope={'module':module,'tenant_id':tenant_id,'scope_id':scope_id}
    await core.authorize_scope(db,fresh.user_id,scope)
    result=await core.rows(db,'SELECT id,at,actor,action,task_id,result FROM distribution_events '
        "WHERE target->>'module'=:module AND target->>'tenant_id'=:tenant AND target->>'scope_id'=:scope "
        'ORDER BY id DESC LIMIT 100',module=module,tenant=str(tenant_id),scope=str(scope_id))
    return {'schema':1,**scope,'items':[dict(row) for row in result]}


@router.post('/device/exchange')
async def exchange(req:Exchange,request:Request,db=Depends(get_session)):
    authorization=request.headers.get('authorization','')
    if not authorization.startswith('Bearer ') or not 40<=len(authorization)<=300 or request.query_params:
        raise core.problem('device_unauthorized',401)
    value=await core.exchange(db,authorization[7:],req)
    await db.commit(); return value


# A separate capability protocol: execution task/exchange/receipt v1 is unchanged.
from app.distribution_capability_contract import CapabilityRegistration, CapabilityRevocation, HandoffReceipt, HandoffInvestigation, HandoffRetry, HandoffResolutionRead
capability_router=APIRouter(prefix='/api/distribution/capabilities/v1',tags=['设备交接能力'],route_class=PrivateRoute)

def device_credential(request):
    authorization=request.headers.get('authorization','')
    if not authorization.startswith('Bearer ') or not 40<=len(authorization)<=300 or request.query_params:
        raise core.problem('device_unauthorized',401)
    return authorization[7:]

@capability_router.get('/device/{device_id}/status')
async def capability_status(device_id:str,request:Request,db=Depends(get_session)):
    if len(device_id)>100:raise core.problem('device_unauthorized',401)
    await execution_capabilities.authenticate(db,device_credential(request),device_id)
    row=await core.one(db,'SELECT * FROM distribution_device_capability_registrations WHERE device_id=:id',id=device_id)
    return {'capabilityVersion':1,'deviceId':device_id,'registration':execution_capabilities.registration_view(row) if row else None}

@capability_router.post('/device/register')
async def register_capability(req:CapabilityRegistration,request:Request,db=Depends(get_session)):
    value=await execution_capabilities.register(db,device_credential(request),req)
    await db.commit();return value

@capability_router.post('/device/revoke')
async def revoke_capability(req:CapabilityRevocation,request:Request,db=Depends(get_session)):
    value=await execution_capabilities.revoke(db,device_credential(request),req)
    await db.commit();return value

handoff_router=APIRouter(prefix='/api/distribution/handoff/v1',tags=['人工交接回执'],route_class=PrivateRoute)

@handoff_router.post('/device/receipt')
async def handoff_receipt(req:HandoffReceipt,request:Request,db=Depends(get_session)):
    from app import distribution_handoff_receipts
    value=await distribution_handoff_receipts.adopt(db,device_credential(request),req)
    await db.commit();return value

@handoff_router.post('/advisor/resolution')
async def handoff_investigation(req:HandoffInvestigation,db=Depends(get_session),ctx=Depends(require_auth)):
    from app import distribution_handoff_receipts
    fresh=await named(db,ctx)
    value=await distribution_handoff_receipts.investigate(db,fresh.user_id,req)
    await db.commit();return value

@handoff_router.post('/advisor/retry')
async def handoff_retry(req:HandoffRetry,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh=await named(db,ctx)
    value=await execution.retry(db,fresh.user_id,req)
    await db.commit();return value

@handoff_router.post('/device/resolution')
async def device_handoff_resolution(req:HandoffResolutionRead,request:Request,db=Depends(get_session)):
    from app import distribution_handoff_receipts
    return await distribution_handoff_receipts.resolution_read(db,device_credential(request),req)

legacy_router=router
router=APIRouter()
router.include_router(legacy_router)
router.include_router(capability_router)
router.include_router(handoff_router)
from app.api.distribution_remote import router as remote_router
router.include_router(remote_router)
from app.api.distribution_pairing import router as pairing_router
router.include_router(pairing_router)
