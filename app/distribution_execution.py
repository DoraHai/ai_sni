"""Bounded queue-to-preflight/human-handoff dispatch. Never grants publication."""
from uuid import uuid4,uuid5,NAMESPACE_URL
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app import distribution_control as core,distribution_scheduling as scheduling
from app import distribution_execution_capabilities as capabilities
from app.distribution_contract import TaskCreate

async def installed(db):
    return bool((await core.one(db,"SELECT to_regclass(current_schema()||'.distribution_execution_intents') IS NOT NULL AS ready"))['ready'])

async def configure(db,actor,req):
    scope=req.model_dump(include={'module','tenant_id','scope_id'})
    b=await core.one(db,'SELECT * FROM distribution_bindings WHERE id=:id',id=req.binding_id)
    if not b or any(b[k]!=scope[k] for k in scope):raise core.problem('binding_unavailable')
    await core.lock(db,'device:'+b['device_id']);await core.lock(db,'scope:'+core.canonical(scope));await scheduling.account_lock(db,b)
    await core.authorize_scope(db,actor,scope)
    b=await scheduling.binding(db,req.binding_id,scope)
    project=await core.one(db,'SELECT * FROM distribution_controls WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id',**scope)
    if not project or project['owner_user_id']!=actor or project['state']=='ended':raise core.problem('scope_forbidden',403)
    fp,prior=await scheduling.request_prior(db,actor,req)
    if prior:return prior
    old=await core.one(db,'SELECT * FROM distribution_handoff_permissions WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND binding_id=:binding',**scope,binding=req.binding_id)
    if (old['revision'] if old else 0)!=req.expected_revision:raise core.problem('version_conflict')
    value={**scope,'binding':req.binding_id,'actor':actor,'enabled':req.enabled,'stage':req.stage,'revision':req.expected_revision+1,'at':core.now_ms()}
    await db.execute(core.text('INSERT INTO distribution_handoff_permissions VALUES(:tenant_id,:module,:scope_id,:binding,:actor,:enabled,:stage,:revision,:at) ON CONFLICT(tenant_id,module,scope_id,binding_id) DO UPDATE SET actor_id=EXCLUDED.actor_id,enabled=EXCLUDED.enabled,stage=EXCLUDED.stage,revision=EXCLUDED.revision,updated_at=EXCLUDED.updated_at'),value)
    result={'binding_id':str(req.binding_id),'enabled':req.enabled,'stage':req.stage,'revision':value['revision']}
    await scheduling.save_request(db,actor,req,fp,result);await core.audit(db,actor,'handoff_permission',{**scope,'binding_id':str(req.binding_id)},'ENABLED' if req.enabled else 'DISABLED')
    return result

async def eligible(db,q,plan,permission,b,*,capability_digest=None,for_task=False):
    scope={k:q[k] for k in ('tenant_id','module','scope_id')}
    project=await core.one(db,'SELECT * FROM distribution_controls WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id',**scope)
    if not project or project['state'] not in (('running','paused') if for_task else ('running',)) or not permission or not permission['enabled'] or project['owner_user_id']!=permission['actor_id']:return 'PROJECT_OR_HANDOFF_DISABLED'
    await core.authorize_scope(db,permission['actor_id'],scope)
    await scheduling.binding(db,q['binding_id'],scope)
    selected=await core.one(db,'SELECT * FROM distribution_project_channels WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND binding_id=:binding AND enabled',**scope,binding=q['binding_id'])
    global_permission=await core.one(db,'SELECT enabled FROM distribution_channel_permissions WHERE platform=:platform AND content_type=:kind',platform=q['platform'],kind=selected['content_type'] if selected else '')
    if not selected or selected['owner_user_id']!=permission['actor_id'] or not global_permission or not global_permission['enabled']:return 'CHANNEL_DISABLED'
    plan_keys=('tenant_id','module','scope_id','binding_id','platform','external_account_id','draft_version','source_revision','content_digest')
    if not plan or plan['queue_id']!=q['id'] or (not for_task and plan['state']!='planned') or any(q[k]!=plan[k] for k in plan_keys):return 'PLAN_OR_VERSION_CHANGED'
    if not await capabilities.current(db,b['device_id'],q['platform'],permission['stage'],capability_digest,binding_id=q['binding_id']):return 'CAPABILITY_UNAVAILABLE'
    value,digest=await core.source(db,permission['actor_id'],scope,q['variant_id'],q['platform'])
    if (value['source_revision'],digest)!=(q['source_revision'],q['content_digest']):return 'SOURCE_CHANGED'
    return None

async def dispatch_one(db,queue_id,*,attempt=1):
    q=await core.one(db,'SELECT * FROM distribution_queue WHERE id=:id',id=queue_id)
    if not q:return False
    b=await core.one(db,'SELECT * FROM distribution_bindings WHERE id=:id',id=q['binding_id'])
    if not b:return False
    scope={k:q[k] for k in ('tenant_id','module','scope_id')}
    # Matches core.exchange/enqueue. Never acquire a device lock after scope.
    await core.lock(db,'device:'+b['device_id']);await core.lock(db,'scope:'+core.canonical(scope));await scheduling.account_lock(db,b)
    q=await core.one(db,'SELECT * FROM distribution_queue WHERE id=:id',id=queue_id)
    if not q:return False
    if q['binding_id']!=b['id']:return 'BINDING_CHANGED_RETRY'
    permission=await core.one(db,'SELECT * FROM distribution_handoff_permissions WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND binding_id=:binding',**scope,binding=q['binding_id'])
    if not permission:return 'HANDOFF_NOT_AUTHORIZED'
    prior=await core.one(db,'SELECT id FROM distribution_execution_intents WHERE queue_id=:queue AND source_revision=:source AND content_digest=:digest AND stage=:stage AND attempt=:attempt',queue=q['id'],source=q['source_revision'],digest=q['content_digest'],stage=permission['stage'],attempt=attempt)
    if prior:return 'ALREADY_LINKED'
    plan=await core.one(db,"SELECT * FROM distribution_plans WHERE queue_id=:id AND state='planned'",id=q['id'])
    reason=await eligible(db,q,plan,permission,b)
    if reason:return reason
    at=core.now_ms()
    if plan['planned_at']>at:return 'PLANNED_FOR_LATER'
    schedule=await scheduling.schedule(db,{**b,'id':b['id']})
    if not schedule['available']:return schedule['reason']
    held=await core.one(db,"SELECT id FROM distribution_execution_intents e JOIN distribution_handoff_slots s ON s.intent_id=e.id WHERE s.platform=:platform AND s.external_account_id=:external AND s.state='held' LIMIT 1",platform=q['platform'],external=b['external_account_id'])
    if held:return 'ACCOUNT_BUSY'
    start,end=scheduling.day_bounds(at,ZoneInfo(schedule['policy']['timezone']))
    slots=await core.rows(db,"SELECT reserved_at,completed_at FROM distribution_handoff_slots WHERE platform=:platform AND external_account_id=:external AND state<>'released' AND (reserved_at>=:start OR completed_at>=:start)",platform=q['platform'],external=b['external_account_id'],start=start-86400000)
    used=[max(s['reserved_at'],s['completed_at'] or s['reserved_at']) for s in slots]
    if sum(start<=s<end for s in used)>=schedule['effective_daily_limit'] or used and at-max(used)<schedule['effective_interval_seconds']*1000:return 'HANDOFF_RATE_LIMIT'
    cap=await capabilities.current(db,b['device_id'],q['platform'],permission['stage'],binding_id=q['binding_id'])
    task=await core.enqueue(db,permission['actor_id'],TaskCreate(**scope,variant_id=q['variant_id'],binding_id=q['binding_id'],source_revision=q['source_revision'],expected_digest=q['content_digest'],action=permission['stage'],confirm_reviewed_content=True,request_id=uuid5(NAMESPACE_URL,'distribution-handoff:'+str(q['id'])+':'+q['source_revision']+':'+permission['stage']+':'+str(attempt))))
    ident=uuid4()
    await db.execute(core.text('INSERT INTO distribution_execution_intents VALUES(:id,:queue,:plan,:binding,:tenant_id,:module,:scope_id,:source,:draft,:digest,:platform,:external,:stage,:revision,:capability,:task,:at,:attempt)'),{**scope,'id':ident,'queue':q['id'],'plan':plan['id'],'binding':q['binding_id'],'source':q['source_revision'],'draft':q['draft_version'],'digest':q['content_digest'],'platform':q['platform'],'external':b['external_account_id'],'stage':permission['stage'],'revision':permission['revision'],'capability':cap['digest'],'task':task['id'],'at':at,'attempt':attempt})
    await db.execute(core.text("INSERT INTO distribution_handoff_slots VALUES(:id,:platform,:external,'held',:at,NULL)"),{'id':ident,'platform':q['platform'],'external':b['external_account_id'],'at':at})
    await core.audit(db,permission['actor_id'],'queue_handoff_authorized',{**scope,'binding_id':str(q['binding_id']),'variant_id':q['variant_id']},'HANDOFF_ONLY',task['id'])
    return True

async def retry(db,actor,req):
    scope=req.model_dump(include={'module','tenant_id','scope_id'})
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=req.task_id)
    if not task or task['action']!='handoff' or task['advisor_user_id']!=actor or any(task[k]!=scope[k] for k in scope):raise core.problem('scope_forbidden',403)
    await core.lock(db,'device:'+task['device_id']);await core.lock(db,'scope:'+core.canonical(scope))
    b=await scheduling.binding(db,task['binding_id'],scope);await scheduling.account_lock(db,b)
    await core.authorize_scope(db,actor,scope)
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=req.task_id)
    if task['advisor_user_id']!=actor or task['action']!='handoff' or any(task[k]!=scope[k] for k in scope):raise core.problem('scope_forbidden',403)
    fp,prior=await scheduling.request_prior(db,actor,req)
    if prior:return prior
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=req.task_id)
    old=await core.one(db,'SELECT * FROM distribution_execution_intents WHERE task_id=:id',id=task['id'])
    if task['status']=='unknown':raise core.problem('handoff_investigation_required')
    if not old or task['status'] not in ('canceled','failed') or req.source_revision!=task['source_revision'] or req.content_digest!=task['content_digest']:raise core.problem('handoff_retry_conflict')
    if old['attempt']>=3:raise core.problem('handoff_attempt_limit')
    q=await core.one(db,'SELECT * FROM distribution_queue WHERE id=:id',id=old['queue_id'])
    if not q or any(q[k]!=old[k] for k in ('binding_id','source_revision','content_digest','draft_version','tenant_id','module','scope_id','platform','external_account_id')):raise core.problem('handoff_retry_source_changed')
    if await core.one(db,'SELECT previous_intent_id FROM distribution_handoff_retry_links WHERE previous_intent_id=:id',id=old['id']):raise core.problem('handoff_retry_already_linked')
    project=await core.one(db,'SELECT * FROM distribution_controls WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id',**scope)
    permission=await core.one(db,'SELECT * FROM distribution_handoff_permissions WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND binding_id=:id',**scope,id=b['id'])
    if not project or project['owner_user_id']!=actor or not permission or permission['stage']!='handoff':raise core.problem('scope_forbidden',403)
    result=await dispatch_one(db,q['id'],attempt=old['attempt']+1)
    if result is not True:raise core.problem('handoff_retry_not_ready')
    new=await core.one(db,'SELECT * FROM distribution_execution_intents WHERE queue_id=:queue AND source_revision=:source AND content_digest=:digest AND stage=:stage AND attempt=:attempt',queue=q['id'],source=q['source_revision'],digest=q['content_digest'],stage=old['stage'],attempt=old['attempt']+1)
    await db.execute(core.text('INSERT INTO distribution_handoff_retry_links VALUES(:old,:new,:actor,:at)'),{'old':old['id'],'new':new['id'],'actor':actor,'at':core.now_ms()})
    response={'handoffVersion':1,'task_id':str(new['task_id']),'previous_task_id':str(task['id']),'attempt':new['attempt'],'result':'HANDOFF_REDISPATCHED','publicationVerified':False}
    await scheduling.save_request(db,actor,req,fp,response)
    await core.audit(db,actor,'handoff_retry_authorized',scope,'CONFIRMED_NO_PUBLICATION',new['task_id'])
    return response

async def task_valid(db,task):
    if not await installed(db):return True
    intent=await core.one(db,'SELECT * FROM distribution_execution_intents WHERE task_id=:id',id=task['id'])
    if not intent:return True
    q=await core.one(db,'SELECT * FROM distribution_queue WHERE id=:id',id=intent['queue_id'])
    plan=await core.one(db,'SELECT * FROM distribution_plans WHERE id=:id',id=intent['plan_id'])
    pinned=('tenant_id','module','scope_id','binding_id','platform','external_account_id','draft_version','source_revision','content_digest')
    if not q or not plan or plan['queue_id']!=intent['queue_id'] or any(q[k]!=intent[k] or plan[k]!=intent[k] for k in pinned):return False
    if any(task[k]!=intent[k] for k in ('tenant_id','module','scope_id','binding_id','platform','source_revision','content_digest')) or task['variant_id']!=q['variant_id'] or task['action']!=intent['stage']:return False
    scope={k:intent[k] for k in ('tenant_id','module','scope_id')}
    permission=await core.one(db,'SELECT * FROM distribution_handoff_permissions WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND binding_id=:binding',**scope,binding=intent['binding_id'])
    if not permission or permission['revision']!=intent['permission_revision'] or permission['stage']!=intent['stage']:return False
    b=await core.one(db,'SELECT * FROM distribution_bindings WHERE id=:id',id=intent['binding_id'])
    if not b or b['device_id']!=task['device_id'] or b['external_account_id']!=intent['external_account_id'] or b['platform']!=intent['platform']:return False
    account=await scheduling.schedule(db,b,task['id'])
    human_risk=task['status']=='awaiting-human' and account['reason'] in ('LOGIN_REQUIRED','CAPTCHA') and (task['receipt'] or {}).get('code')==account['reason']
    if not account['available'] and not human_risk:return False
    try:return await eligible(db,q,plan,permission,b,capability_digest=intent['capability_digest'],for_task=True) is None
    except HTTPException as exc:
        if exc.status_code>=500:raise
        return False

async def receipt_effect(db,task):
    if not await installed(db):return
    intent=await core.one(db,'SELECT id FROM distribution_execution_intents WHERE task_id=:id',id=task['id'])
    if not intent:return
    current=await core.one(db,'SELECT status FROM distribution_tasks WHERE id=:id',id=task['id'])
    state='consumed' if current['status']=='succeeded' else 'released' if current['status'] in ('failed','canceled') else 'held'
    await db.execute(core.text('UPDATE distribution_handoff_slots SET state=:state,completed_at=:at WHERE intent_id=:id'),{'id':intent['id'],'state':state,'at':core.now_ms() if state!='held' else None})

async def release_canceled(db,*,device_id=None,binding_id=None,scope=None):
    """Called inside revocation/end transactions; exposed attempts stay unknown."""
    if not await installed(db):return
    where='t.device_id=:device' if device_id else 't.binding_id=:binding' if binding_id else 't.tenant_id=:tenant_id AND t.module=:module AND t.scope_id=:scope_id'
    params={'device':device_id} if device_id else {'binding':binding_id} if binding_id else scope
    tasks=await core.rows(db,"SELECT t.*,b.external_account_id FROM distribution_tasks t JOIN distribution_bindings b ON b.id=t.binding_id JOIN distribution_execution_intents e ON e.task_id=t.id JOIN distribution_handoff_slots s ON s.intent_id=e.id WHERE s.state='held' AND t.status='canceled' AND "+where,**params)
    for account in sorted({t['platform']+':'+t['external_account_id'] for t in tasks}):
        await core.lock(db,'account:'+account)
    for task in tasks:
        await receipt_effect(db,task)
        await core.audit(db,'system','handoff_slot_released',{k:task[k] for k in ('module','tenant_id','scope_id')},'UNSTARTED_TASK_CANCELED',task['id'])

async def run_once(sessions,*,module=None):
    async with sessions() as db:
        if not await installed(db):return
        ids=[q['id'] for q in await core.rows(db,"SELECT q.id FROM distribution_queue q JOIN distribution_plans p ON p.queue_id=q.id AND p.state='planned' LEFT JOIN distribution_execution_intents e ON e.queue_id=q.id AND e.source_revision=q.source_revision AND e.content_digest=q.content_digest LEFT JOIN distribution_execution_scans s ON s.queue_id=q.id WHERE e.id IS NULL AND (CAST(:module AS varchar) IS NULL OR q.module=:module) ORDER BY COALESCE(s.checked_at,0),p.planned_at,q.id LIMIT 20",module=module)]
    for ident in ids:
        try:
            async with sessions() as db:
                result=await dispatch_one(db,ident)
                reason=result if isinstance(result,str) else 'DISPATCHED' if result else 'BINDING_UNAVAILABLE'
                await db.execute(core.text('INSERT INTO distribution_execution_scans VALUES(:id,:at,:reason) ON CONFLICT(queue_id) DO UPDATE SET checked_at=EXCLUDED.checked_at,reason=EXCLUDED.reason'),{'id':ident,'at':core.now_ms(),'reason':reason})
                await db.commit()
        except HTTPException as exc:
            async with sessions() as db:
                reason='AUTHORIZATION_REVOKED' if exc.status_code==403 else 'SOURCE_OR_BINDING_UNAVAILABLE'
                await db.execute(core.text('INSERT INTO distribution_execution_scans VALUES(:id,:at,:reason) ON CONFLICT(queue_id) DO UPDATE SET checked_at=EXCLUDED.checked_at,reason=EXCLUDED.reason'),{'id':ident,'at':core.now_ms(),'reason':reason});await db.commit()
