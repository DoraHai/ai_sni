"""Normal manual handoff closure; unknown requires a separate investigation."""
import hashlib
from uuid import uuid4
from app import distribution_control as core, distribution_execution as execution, distribution_scheduling as scheduling


async def adopt(db,credential,req):
    from app.distribution_execution_capabilities import authenticate
    await authenticate(db,credential,req.deviceId)
    r=req.receipt
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id::text=:id AND device_id=:device',id=r.taskId,device=req.deviceId)
    if not task:raise core.problem('receipt_scope_mismatch',403)
    scope={k:task[k] for k in ('module','tenant_id','scope_id')}
    await core.lock(db,'scope:'+core.canonical(scope))
    binding=await scheduling.binding(db,task['binding_id'],scope)
    await scheduling.account_lock(db,binding)
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=task['id'])
    expected={**core.target(task),'contentVersion':task['source_revision'],'contentDigest':task['content_digest'],'leaseId':str(task['lease_id'])}
    value=r.model_dump(mode='json')
    allowed={'HUMAN_HANDOFF_ACCEPTED':'succeeded','HUMAN_INTERVENTION_COMPLETED':'canceled','HUMAN_INVESTIGATED_FAILURE':'failed'}
    if task['action']!='handoff' or req.grantId!=str(task['grant_id']) or any(value[k]!=v for k,v in expected.items()) or r.code not in allowed or r.status!=allowed[r.code] or r.evidence!='human-reported' or r.publicUrl is not None or r.at>core.now_ms()+300000:
        raise core.problem('invalid_handoff_receipt',422)
    fp=hashlib.sha256(core.canonical(req.model_dump(mode='json')).encode()).hexdigest()
    prior=await core.one(db,'SELECT fingerprint FROM distribution_receipts WHERE receipt_id=:receipt OR (task_id=:id AND lease_id=:lease AND sequence=:sequence)',receipt=r.receiptId,id=task['id'],lease=task['lease_id'],sequence=r.sequence)
    result='HANDOFF_COMPLETE' if r.status=='succeeded' else 'HANDOFF_TERMINATED'
    response={'handoffVersion':1,'receiptAck':{k:value[k] for k in ('receiptId','taskId','leaseId','sequence','status','at')},'result':result,'publicationVerified':False}
    if prior:
        if prior['fingerprint']!=fp:raise core.problem('receipt_conflict')
        return response
    if task['status']=='unknown':raise core.problem('handoff_investigation_required')
    if task['status']!='awaiting-human' or r.sequence<=task['receipt_sequence']:raise core.problem('handoff_state_conflict')
    old_code=(task['receipt'] or {}).get('code')
    if r.code=='HUMAN_HANDOFF_ACCEPTED' and old_code!='HUMAN_REQUIRED' or r.code=='HUMAN_INTERVENTION_COMPLETED' and old_code not in ('LOGIN_REQUIRED','CAPTCHA'):
        raise core.problem('handoff_state_conflict')
    project=await core.one(db,'SELECT * FROM distribution_controls WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id',**scope)
    if task['revoked'] or min(task['grant_expires_at'],task['lease_expires_at'])<=core.now_ms() or not project or project['state']!='running' or project['owner_user_id']!=task['advisor_user_id'] or not await execution.task_valid(db,task):
        raise core.problem('handoff_authorization_changed',403)
    source,digest=await core.source(db,task['advisor_user_id'],scope,task['variant_id'],task['platform'])
    if source['source_revision']!=task['source_revision'] or digest!=task['content_digest']:raise core.problem('source_changed')
    await db.execute(core.text('INSERT INTO distribution_receipts VALUES(:receipt,:id,:lease,:sequence,:status,:at,:fp,CAST(:payload AS jsonb))'),{'receipt':r.receiptId,'id':task['id'],'lease':task['lease_id'],'sequence':r.sequence,'status':r.status,'at':r.at,'fp':fp,'payload':core.canonical(value)})
    await db.execute(core.text('UPDATE distribution_tasks SET status=:status,revoked=true,receipt_at=:at,receipt_sequence=:sequence,receipt=CAST(:payload AS jsonb) WHERE id=:id'),{'status':r.status,'at':r.at,'sequence':r.sequence,'payload':core.canonical(value),'id':task['id']})
    await execution.receipt_effect(db,task)
    await core.audit(db,'device:'+req.deviceId,'handoff_closed',scope,result,task['id'])
    return response


async def investigate(db,actor,req):
    """Fresh advisor authority to investigate a stopped old attempt, not replay it."""
    scope=req.model_dump(include={'module','tenant_id','scope_id'})
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=req.task_id)
    if not task or task['advisor_user_id']!=actor or task['action']!='handoff' or any(task[k]!=scope[k] for k in scope):raise core.problem('scope_forbidden',403)
    await core.lock(db,'device:'+task['device_id']);await core.lock(db,'scope:'+core.canonical(scope))
    binding=await core.one(db,'SELECT * FROM distribution_bindings WHERE id=:id',id=task['binding_id'])
    await scheduling.account_lock(db,binding)
    await core.authorize_scope(db,actor,scope)
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=req.task_id)
    if task['advisor_user_id']!=actor or task['action']!='handoff' or any(task[k]!=scope[k] for k in scope):raise core.problem('scope_forbidden',403)
    project=await core.one(db,'SELECT * FROM distribution_controls WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id',**scope)
    if not project or project['owner_user_id']!=actor:raise core.problem('scope_forbidden',403)
    fp,prior=await scheduling.request_prior(db,actor,req)
    if prior:return prior
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=req.task_id)
    if req.source_revision!=task['source_revision'] or req.content_digest!=task['content_digest']:raise core.problem('handoff_investigation_conflict')
    if task['status'] in ('leased','running','awaiting-human') and min(task['grant_expires_at'],task['lease_expires_at'])<=core.now_ms():
        await db.execute(core.text("UPDATE distribution_tasks SET status='unknown',revoked=true WHERE id=:id"),{'id':task['id']})
        task['status']='unknown'
        await core.audit(db,'system','handoff_expired_fenced',scope,'EXPOSED_RESULT_UNKNOWN',task['id'])
    if task['status']!='unknown':raise core.problem('handoff_investigation_conflict')
    at=core.now_ms()
    await db.execute(core.text('INSERT INTO distribution_handoff_resolutions VALUES(:id,:task,:actor,:source,:digest,:outcome,:at)'),{'id':uuid4(),'task':task['id'],'actor':actor,'source':task['source_revision'],'digest':task['content_digest'],'outcome':req.outcome,'at':at})
    await db.execute(core.text("UPDATE distribution_tasks SET status='failed',revoked=true WHERE id=:id"),{'id':task['id']})
    await execution.receipt_effect(db,task)
    response={'handoffVersion':1,'task_id':str(task['id']),'outcome':'not-published','checked_at':at,'evidence':'advisor-reported','result':'HANDOFF_NOT_PUBLISHED','publicationVerified':False}
    await scheduling.save_request(db,actor,req,fp,response)
    await core.audit(db,actor,'handoff_investigated',scope,'CONFIRMED_NOT_PUBLISHED',task['id'])
    return response


async def resolution_read(db,credential,req):
    """Read exact old negative evidence; no grant inferred or lane state written."""
    from app.distribution_execution_capabilities import authenticate
    await authenticate(db,credential,req.deviceId)
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id::text=:id AND device_id=:device',id=req.taskId,device=req.deviceId)
    if not task or task['action']!='handoff':raise core.problem('scope_forbidden',403)
    scope={k:task[k] for k in ('module','tenant_id','scope_id')}
    await core.lock(db,'scope:'+core.canonical(scope))
    binding=await scheduling.binding(db,task['binding_id'],scope)
    await scheduling.account_lock(db,binding)
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=task['id'])
    expected={**core.target(task),'grantId':str(task['grant_id']),'leaseId':str(task['lease_id']),'contentVersion':task['source_revision'],'contentDigest':task['content_digest']}
    value=req.model_dump(mode='json')
    if any(value[k]!=v for k,v in expected.items()) or binding['device_id']!=req.deviceId:raise core.problem('receipt_scope_mismatch',403)
    project=await core.one(db,'SELECT * FROM distribution_controls WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id',**scope)
    if not project or project['owner_user_id']!=task['advisor_user_id']:raise core.problem('scope_forbidden',403)
    await core.authorize_scope(db,task['advisor_user_id'],scope)
    resolution=await core.one(db,'SELECT * FROM distribution_handoff_resolutions WHERE task_id=:id',id=task['id'])
    proof=None
    if resolution:
        if resolution['source_revision']!=task['source_revision'] or resolution['content_digest']!=task['content_digest'] or resolution['outcome']!='not-published' or task['status']!='failed' or not task['revoked']:raise core.problem('handoff_resolution_conflict')
        proof={'id':str(resolution['id']),'outcome':'not-published','checkedAt':resolution['checked_at'],'evidence':'advisor-reported'}
    return {**value,'resolution':proof,'publicationVerified':False}
