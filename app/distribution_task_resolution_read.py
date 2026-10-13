"""Fresh device-scoped SELECT of an old publish outcome; no state mutation."""
from app import distribution_control as core, distribution_scheduling as scheduling
from app.distribution_execution_capabilities import authenticate
from app.distribution_task_resolution_contract import TaskResolutionReadView


def exact_task(req, task):
    expected = {**core.target(task), 'taskId':str(task['id']), 'grantId':str(task['grant_id']),
        'publicationGrantId':str(task['publication_grant_id']), 'leaseId':str(task['lease_id']),
        'contentVersion':task['source_revision'], 'contentDigest':task['content_digest']}
    if task['action'] != 'publish' or any(getattr(req, key) != value for key, value in expected.items()):
        raise core.problem('receipt_scope_mismatch',403)


def exact_binding(task, binding):
    if str(binding['id']) != str(task['binding_id']) or any(binding[key] != task[key]
            for key in ('tenant_id','module','scope_id','device_id','account_id','platform')):
        raise core.problem('receipt_scope_mismatch',403)


async def read(db, credential, req):
    # Same device -> scope -> canonical platform-account ordering as exchange.
    # Historical grant expiry/revocation is not execution permission or denial of
    # history. Current device, binding and native advisor scope must still live.
    await authenticate(db,credential,req.deviceId)
    task = await core.one(db,'SELECT * FROM distribution_tasks WHERE id::text=:id AND device_id=:device',
                          id=req.taskId,device=req.deviceId)
    if not task: raise core.problem('scope_forbidden',403)
    # SEO-only pilot. GEO current authorization locks Tenant before device in
    # its existing resolver; this device-first reader must never enter it.
    if task['module'] != 'seo': raise core.problem('scope_forbidden',403)
    exact_task(req,task)
    scope = {key:task[key] for key in ('module','tenant_id','scope_id')}
    await core.lock(db,'scope:'+core.canonical(scope))
    binding = await scheduling.binding(db,task['binding_id'],scope)
    exact_binding(task,binding)
    account_key = (str(binding['id']),binding['platform'],binding['external_account_id'])
    await scheduling.account_lock(db,binding)
    # Re-read after all locks; a stale first binding/task cannot lend authority.
    task = await core.one(db,'SELECT * FROM distribution_tasks WHERE id::text=:id AND device_id=:device',
                          id=req.taskId,device=req.deviceId)
    if not task or any(task[key] != scope[key] for key in scope): raise core.problem('scope_forbidden',403)
    exact_task(req,task)
    binding = await scheduling.binding(db,task['binding_id'],scope)
    exact_binding(task,binding)
    if (str(binding['id']),binding['platform'],binding['external_account_id']) != account_key:
        raise core.problem('receipt_scope_mismatch',403)
    project = await core.one(db,'SELECT * FROM distribution_controls WHERE tenant_id=:tenant_id '
                            'AND module=:module AND scope_id=:scope_id',**scope)
    if (not project or project['state'] not in {'paused','running'}
            or project['owner_user_id'] != task['advisor_user_id']):
        raise core.problem('scope_forbidden',403)
    await core.authorize_scope(db,task['advisor_user_id'],scope)
    resolution = await core.one(db,'SELECT * FROM distribution_task_resolutions WHERE task_id=:id '
                               'ORDER BY id DESC LIMIT 1',id=task['id'])
    at = core.now_ms()
    proof = None
    if resolution is not None:
        if (resolution['outcome'] != 'not-published' or resolution['public_url'] is not None
                or resolution['actor_id'] != task['advisor_user_id'] or task['status'] != 'failed'
                or task['revoked'] is not True or type(resolution['checked_at']) is not int
                or not 946684800000 <= resolution['checked_at'] <= at):
            raise core.problem('resolution_conflict')
        proof = {'id':resolution['id'],'outcome':'not-published','checkedAt':resolution['checked_at'],
                 'evidence':'advisor-reported'}
    response = {**req.model_dump(),'asOf':at,'resolution':proof,
                'publicationVerified':False,'executionAuthorized':False}
    return TaskResolutionReadView.model_validate(response).model_dump()
