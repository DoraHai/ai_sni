"""Shared durable SEO/GEO controls. Callers own transactions and authorization.

No provider, module model, implicit commit, task creation or acceptance lives
here. Module adapters must validate live scope before claims and business writes.
"""
import calendar
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import UUID, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import text

from app.automation_project_contract import parse_configuration

TABLES = {
    'automation_projects': {'module','tenant_id','scope_id','version','generation','state','owner_user_id',
        'configuration','cycle_enabled','next_due_at','current_run_id','created_at','updated_at'},
    'automation_project_runs': {'id','module','tenant_id','scope_id','generation','state','stop_requested',
        'dispatch_count','configuration','steps','created_at','started_at','finished_at'},
    'automation_project_commands': {'module','tenant_id','scope_id','request_id','actor_user_id','payload_hash',
        'action','applied_version','run_id','created_at'},
    'automation_project_events': {'id','module','tenant_id','scope_id','run_id','actor_kind','actor_user_id',
        'step_key','code','request_id','evidence_refs','fee_state','created_at'},
}
SCOPE = 'module=:module AND tenant_id=:tenant_id AND scope_id=:scope_id'
TERMINAL_STEPS = {'succeeded','failed','unknown','stale','cancelled','blocked'}
STOP_TARGET = {'pausing': 'paused', 'taking_over': 'taken_over', 'ending': 'idle'}
FEE_STATES = {'not_called','recorded','unknown_charge','unverified'}


def now():
    return datetime.now(timezone.utc)


def problem(code, message, status=409):
    return HTTPException(status, {'code':code,'message':message}, headers={'Cache-Control':'no-store'})


def scope(module, tenant_id, scope_id):
    if module not in {'seo','geo'} or type(tenant_id) is not int or type(scope_id) is not int or min(tenant_id,scope_id) < 1:
        raise ValueError('invalid automation scope')
    return {'module':module,'tenant_id':tenant_id,'scope_id':scope_id}


def wire(value):
    if isinstance(value, dict): return {k:wire(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [wire(v) for v in value]
    if isinstance(value, (datetime,UUID)): return value.isoformat() if isinstance(value,datetime) else str(value)
    return value


async def schema_ready(db):
    rows = (await db.execute(text('''SELECT table_name,column_name FROM information_schema.columns
        WHERE table_schema=current_schema() AND table_name=ANY(:tables)'''), {'tables':list(TABLES)})).all()
    actual = {name:{col for table,col in rows if table == name} for name in TABLES}
    if any(not cols <= actual[name] for name,cols in TABLES.items()):
        return False
    triggers = set((await db.execute(text('''SELECT t.tgname,c.relname,t.tgtype,p.proname FROM pg_trigger t
        JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_proc p ON p.oid=t.tgfoid AND p.pronamespace=n.oid
        WHERE n.nspname=current_schema() AND t.tgenabled IN ('O','A') AND t.tgname=ANY(:names)'''),
        {'names':['automation_events_immutable','automation_commands_immutable',
                  'automation_events_no_truncate','automation_commands_no_truncate']})).all())
    expected = {
        ('automation_events_immutable','automation_project_events',27,'automation_project_immutable'),
        ('automation_commands_immutable','automation_project_commands',27,'automation_project_immutable'),
        ('automation_events_no_truncate','automation_project_events',34,'automation_project_immutable'),
        ('automation_commands_no_truncate','automation_project_commands',34,'automation_project_immutable'),
    }
    if triggers != expected: return False
    for table in TABLES:
        privileges = ['SELECT','INSERT'] + (['UPDATE'] if table in {'automation_projects','automation_project_runs'} else [])
        for privilege in privileges:
            if not await db.scalar(text('SELECT has_table_privilege(quote_ident(current_schema()) || :table,:privilege)'),
                    {'table':'.'+table,'privilege':privilege}): return False
    return bool(await db.scalar(text("SELECT has_sequence_privilege(quote_ident(current_schema()) || '.automation_project_events_id_seq','USAGE')")))


async def require_schema(db):
    if not await schema_ready(db):
        raise problem('automation_schema_pending','自动执行结构或权限尚未就绪，暂不可操作',503)


async def read_project(db, key, *, lock=False):
    return (await db.execute(text('SELECT * FROM automation_projects WHERE '+SCOPE+(' FOR UPDATE' if lock else '')),key)).mappings().first()


async def read_run(db, key, run_id, *, lock=False):
    return (await db.execute(text('SELECT * FROM automation_project_runs WHERE '+SCOPE+
        ' AND id=CAST(:run_id AS uuid)'+(' FOR UPDATE' if lock else '')), {**key,'run_id':str(run_id)})).mappings().first()


async def append_event(db, key, *, code, actor_kind='system', actor_user_id=None, run_id=None,
                       step_key=None, request_id=None, evidence_refs=(), fee_state='not_called',safe_changes=None):
    # Fixed references only. Never accept a message, prompt or arbitrary result body.
    import re
    refs = list(evidence_refs)
    if (actor_kind not in {'human','system','ai'} or fee_state not in FEE_STATES
            or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}',code)
            or len(refs)>30 or any(not re.fullmatch(r'(seo|geo|api)_[a-z_]{1,40}:[0-9a-fA-F-]{1,40}',r) for r in refs)
            or step_key is not None and (len(step_key)>80 or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}:[a-zA-Z0-9_-]{1,40}',step_key))):
        raise ValueError('unsafe automation event')
    extra_column=extra_value=''
    if safe_changes is not None:
        from app import automation_project_v2 as v2
        await v2.require_schema(db)
        v2.validate_changes(safe_changes)
        extra_column=',safe_changes'
        extra_value=',CAST(:changes AS jsonb)'
    await db.execute(text(f'''INSERT INTO automation_project_events
        (module,tenant_id,scope_id,run_id,actor_kind,actor_user_id,step_key,code,request_id,evidence_refs,fee_state{extra_column})
        VALUES(:module,:tenant_id,:scope_id,CAST(:run_id AS uuid),:actor_kind,:actor_user_id,:step_key,:code,
            CAST(:request_id AS uuid),CAST(:refs AS jsonb),:fee_state{extra_value})'''),
        {**key,'run_id':str(run_id) if run_id else None,'actor_kind':actor_kind,'actor_user_id':actor_user_id,
         'step_key':step_key,'code':code,'request_id':str(request_id) if request_id else None,
         'refs':json.dumps(refs),'fee_state':fee_state,'changes':json.dumps(safe_changes)})


def actions(project):
    if project is None: return []
    if project.get('ended_at') is not None: return []
    result = {'not_started':['start'],'idle':['start'],'active':['pause','takeover','end'],
        'paused':['resume','takeover','end'],'taken_over':['resume','end'],
        'pausing':['takeover','end'],'taking_over':['end'],'ending':[]}[project['state']]
    return result + (['disable_cycle'] if project['cycle_enabled'] else []) + (['end_project'] if 'ended_at' in project else [])


def project_view(key, project, *, ready=True, coverage=None):
    mutable = ready and (project is None or project['state'] in {'not_started','idle'})
    return wire({'schema':1,**key,'version':project['version'] if project else 0,
        'generation':project['generation'] if project else 0,
        'state':project['state'] if ready and project else 'not_started' if ready else 'schema_pending',
        'configuration':project['configuration'] if project else None,
        'cycle_enabled':bool(project and project['cycle_enabled']),
        'next_due_at':project['next_due_at'] if project else None,
        'current_run_id':project['current_run_id'] if project else None,
        'ended_at':project.get('ended_at') if project else None,
        'capabilities':{'schema_state':'ready' if ready else 'pending','can_configure':mutable,
            'can_control':ready,'available_operations':['onsite_ai'] if ready else []},
        'coverage':coverage or {'controlled':['configured_onsite_ai'],'not_controlled':[]},
        'allowed_actions':actions(project) if ready else [],
        'blocker':None if ready else 'automation_schema_pending',
        'updated_at':project['updated_at'] if project else None})


async def command_begin(db, key, request, actor_id):
    scope(**key)
    if request.tenant_id != key['tenant_id']:
        raise problem('automation_scope_mismatch','请求与授权客户范围不一致',403)
    await require_schema(db)
    digest = hashlib.sha256(json.dumps(request.model_dump(mode='json'),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    await lock_scope(db,key)
    project = await read_project(db,key,lock=True)
    prior = (await db.execute(text('SELECT * FROM automation_project_commands WHERE '+SCOPE+
        ' AND request_id=CAST(:request_id AS uuid)'),{**key,'request_id':str(request.request_id)})).mappings().first()
    if prior:
        if prior['payload_hash'] != digest or prior['actor_user_id'] != actor_id:
            raise problem('automation_request_conflict','请求编号已用于不同内容或操作人')
        return project,digest,prior['applied_version']
    if request.expected_version != (project['version'] if project else 0):
        raise problem('automation_version_conflict','项目版本已变化，请重新读取后核对')
    return project,digest,None


async def lock_scope(db,key):
    """Serialize scope creation/ownership even before a project row exists."""
    scope(**key)
    lock_key=int.from_bytes(hashlib.sha256(('automation:'+json.dumps(key,sort_keys=True)).encode()).digest()[:8],'big',signed=True)
    await db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':lock_key})


async def command_end(db,key,request,actor_id,digest,action,*,before=None):
    project = await read_project(db,key)
    await db.execute(text('''INSERT INTO automation_project_commands
        (module,tenant_id,scope_id,request_id,actor_user_id,payload_hash,action,applied_version,run_id)
        VALUES(:module,:tenant_id,:scope_id,CAST(:request_id AS uuid),:actor,:hash,:action,:version,CAST(:run_id AS uuid))'''),
        {**key,'request_id':str(request.request_id),'actor':actor_id,'hash':digest,'action':action,
         'version':project['version'],'run_id':str(project['current_run_id']) if project['current_run_id'] else None})
    changes=None
    if 'ended_at' in project:
        from app.automation_project_v2 import audit_changes
        changes=audit_changes(before,project)
    await append_event(db,key,code='project_'+action,actor_kind='human',actor_user_id=actor_id,
        run_id=project['current_run_id'],request_id=request.request_id,safe_changes=changes)
    return project,False,project['version']


async def configure_project(db,key,request,actor_id):
    project,digest,prior = await command_begin(db,key,request,actor_id)
    if prior is not None: return project,True,prior
    if request.configuration.owner_user_id != actor_id:
        raise problem('automation_owner_mismatch','负责人必须为当前已分配实名顾问',403)
    if project and project['state'] not in {'not_started','idle'}:
        raise problem('automation_run_active','请先结束本次运行，再修改范围和配置')
    if getattr(request.configuration,'contract_version',1)==2:
        from app.automation_project_v2 import require_schema as require_v2
        await require_v2(db)
        if project and project['configuration'].get('contract_version')==2 and not set(
                project['configuration']['operations']) <= set(request.configuration.operations):
            raise problem('automation_operation_release_requires_review','不能通过移除操作隐式恢复旧调度器；请结束项目')
    elif project and project['configuration'].get('contract_version')==2:
        raise problem('automation_contract_downgrade','已接管项目不能隐式退回旧配置')
    params = {**key,'owner':actor_id,'configuration':request.configuration.model_dump_json(),
        'cycle':request.configuration.cycle.enabled}
    if project:
        reset_end=',ended_at=NULL' if 'ended_at' in project else ''
        await db.execute(text('''UPDATE automation_projects SET configuration=CAST(:configuration AS jsonb),
            owner_user_id=:owner,cycle_enabled=:cycle,next_due_at=NULL,version=version+1,generation=generation+1,
            state='not_started',updated_at=CURRENT_TIMESTAMP'''+reset_end+' WHERE '+SCOPE),params)
    else:
        await db.execute(text('''INSERT INTO automation_projects(module,tenant_id,scope_id,owner_user_id,configuration,cycle_enabled)
            VALUES(:module,:tenant_id,:scope_id,:owner,CAST(:configuration AS jsonb),:cycle)'''),params)
    return await command_end(db,key,request,actor_id,digest,'configure',before=project)


def next_due(configuration,stamp):
    mode = configuration['cycle']['mode']
    if mode == 'once': return None
    if mode == 'daily': return stamp+timedelta(days=1)
    year,month = (stamp.year+1,1) if stamp.month == 12 else (stamp.year,stamp.month+1)
    return stamp.replace(year=year,month=month,day=min(stamp.day,calendar.monthrange(year,month)[1]))


async def start_run(db,key,project, *, actor_kind='human',actor_id=None):
    # Also protect scheduler callers from a stale snapshot or concurrent start.
    await require_schema(db)
    current = await read_project(db,key,lock=True)
    if (not current or current.get('ended_at') is not None or current['version'] != project['version']
            or current['state'] not in {'not_started','idle'}):
        raise problem('automation_run_active','项目已变化或已有运行')
    project = current
    run_id,generation = uuid4(),project['generation']+1
    config = parse_configuration(project['configuration']).model_dump(mode='json')
    if config.get('contract_version')==2:
        from app.automation_project_v2 import typed_steps,require_schema as require_v2
        await require_v2(db)
        steps=typed_steps(config,run_id)
    else:
        steps = [{'step_key':f'onsite_ai:{ident}','kind':'onsite_ai','task_id':ident,'status':'pending',
        'started_at':None,'finished_at':None,'waiting_for':'system','blocker':None,'result_links':[],
        'error_code':None,'request_id':str(uuid5(run_id,f'onsite_ai:{ident}')),'evidence_refs':[],
        'fee_state':'not_called','dispatched_at':None} for ident in config['task_ids']]
    await db.execute(text('''INSERT INTO automation_project_runs(id,module,tenant_id,scope_id,generation,state,configuration,steps)
        VALUES(CAST(:id AS uuid),:module,:tenant_id,:scope_id,:generation,'queued',CAST(:configuration AS jsonb),CAST(:steps AS jsonb))'''),
        {**key,'id':str(run_id),'generation':generation,'configuration':json.dumps(config),'steps':json.dumps(steps)})
    await db.execute(text('''UPDATE automation_projects SET current_run_id=CAST(:id AS uuid),state='active',
        version=version+1,generation=:generation,next_due_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE '''+SCOPE),
        {**key,'id':str(run_id),'generation':generation})
    await append_event(db,key,run_id=run_id,code='run_queued',actor_kind=actor_kind,actor_user_id=actor_id)
    return run_id


async def finish_stop(db,key,project,run):
    if project['state'] not in STOP_TARGET or any(s['status']=='running' for s in run['steps']): return
    target = STOP_TARGET[project['state']]
    steps = deepcopy(run['steps'])
    if target == 'idle':
        for step in steps:
            if step['status'] == 'pending':
                step.update(status='cancelled',waiting_for=None,finished_at=now().isoformat(),blocker='run_ended')
    due = next_due(project['configuration'],now()) if target == 'idle' and project['cycle_enabled'] else None
    await db.execute(text('''UPDATE automation_projects SET state=:state,next_due_at=:due,
        version=version+1,updated_at=CURRENT_TIMESTAMP WHERE '''+SCOPE),{**key,'state':target,'due':due})
    await db.execute(text('''UPDATE automation_project_runs SET state=:state,steps=CAST(:steps AS jsonb),
        finished_at=CASE WHEN CAST(:state AS varchar)='ended' THEN CURRENT_TIMESTAMP ELSE finished_at END
        WHERE '''+SCOPE+' AND id=CAST(:id AS uuid)'),{**key,'id':str(run['id']),
            'steps':json.dumps(steps),'state':'ended' if target=='idle' else target})
    await append_event(db,key,run_id=run['id'],code='run_'+('ended' if target=='idle' else target))


async def control_project(db,key,request,actor_id):
    project,digest,prior = await command_begin(db,key,request,actor_id)
    if prior is not None: return project,True,prior
    if not project: raise problem('automation_configuration_required','请先保存明确的范围、周期、额度与负责人')
    if project['owner_user_id'] != actor_id:
        raise problem('automation_owner_mismatch','仅当前项目负责人可控制；顾问变更需重新配置',403)
    if request.action=='end_project':
        from app.automation_project_v2 import require_schema as require_v2
        await require_v2(db)
    if request.action not in actions(project):
        raise problem('automation_run_active' if request.action=='start' else 'automation_action_conflict','当前运行阶段不允许该动作')
    if request.action=='end_project':
        from app.automation_project_v2 import end_project
        await end_project(db,key,project)
    elif request.action == 'start':
        await start_run(db,key,project,actor_id=actor_id)
    elif request.action == 'disable_cycle':
        await db.execute(text('''UPDATE automation_projects SET cycle_enabled=false,next_due_at=NULL,
            version=version+1,updated_at=CURRENT_TIMESTAMP WHERE '''+SCOPE),key)
    else:
        run = await read_run(db,key,project['current_run_id'],lock=True)
        state = {'pause':'pausing','takeover':'taking_over','end':'ending','resume':'active'}[request.action]
        generation = project['generation']+1
        await db.execute(text('''UPDATE automation_projects SET state=:state,generation=:generation,
            version=version+1,updated_at=CURRENT_TIMESTAMP WHERE '''+SCOPE),{**key,'state':state,'generation':generation})
        await db.execute(text('''UPDATE automation_project_runs SET state=:state,generation=:generation,stop_requested=:stop
            WHERE '''+SCOPE+' AND id=CAST(:id AS uuid)'),{**key,'id':str(run['id']),'generation':generation,
                'state':('queued' if any(s['status']=='pending' for s in run['steps']) else 'waiting_human')
                    if state=='active' else state,'stop':state!='active'})
        if request.action != 'resume':
            await finish_stop(db,key,await read_project(db,key),await read_run(db,key,run['id']))
    return await command_end(db,key,request,actor_id,digest,request.action,before=project)


async def check_step(db, token, *, lock=True):
    key = scope(token['module'],token['tenant_id'],token['scope_id'])
    await require_schema(db)
    project = await read_project(db,key,lock=lock)
    if (not project or project['state']!='active' or project['generation']!=token['generation']
            or project['owner_user_id']!=token['owner_user_id'] or str(project['current_run_id'])!=token['run_id']):
        raise problem('automation_generation_stale','自动运行已暂停、接管、结束或变更；结果不得自动应用')
    run = await read_run(db,key,token['run_id'],lock=lock)
    step = next((s for s in run['steps'] if s['step_key']==token['step_key']),None) if run else None
    if (not run or run['stop_requested'] or not step or step['status']!='running'
            or step['request_id']!=token['request_id'] or step['task_id']!=token['task_id']):
        raise problem('automation_step_stale','自动步骤已变更；不会重复调用')
    if run['configuration'].get('contract_version')==2:
        from app.automation_project_v2 import require_schema as require_v2
        await require_v2(db)
        if token.get('target')!=step['target'] or token.get('operation')!=step['operation']:
            raise problem('automation_step_stale','自动步骤目标绑定已变化')
    return project,run,step


async def begin_dispatch(db, token):
    """One durable outbound admission. Commit before calling; never replay True.

    Adapter must recheck live actor/entitlement/limits before this function in
    the same transaction. A process loss after commit is an uncertain call,
    not permission to send again. No database can recall an admitted HTTP call.
    """
    _,run,step = await check_step(db,token)
    if run['configuration'].get('contract_version')==2:
        from app.automation_project_v2 import begin_call
        return await begin_call(db,token,'primary',kind='provider')
    if step.get('dispatched_at') is not None:
        return False
    steps = deepcopy(run['steps'])
    marked = next(s for s in steps if s['step_key']==token['step_key'])
    marked.update(dispatched_at=now().isoformat(),fee_state='unknown_charge')
    await db.execute(text('UPDATE automation_project_runs SET steps=CAST(:steps AS jsonb) WHERE id=CAST(:id AS uuid)'),
        {'id':token['run_id'],'steps':json.dumps(steps)})
    await append_event(db,scope(token['module'],token['tenant_id'],token['scope_id']),
        run_id=token['run_id'],code='dispatch_admitted',step_key=token['step_key'],
        request_id=token['request_id'],fee_state='unknown_charge')
    return True


async def claim_step(db,key):
    await require_schema(db)
    project = await read_project(db,key,lock=True)
    if not project or project['state']!='active': return None
    run = await read_run(db,key,project['current_run_id'],lock=True)
    if not run or run['stop_requested'] or any(s['status']=='running' for s in run['steps']): return None
    steps = deepcopy(run['steps'])
    step = next((s for s in steps if s['status']=='pending'),None)
    if not step: return None
    if run['dispatch_count'] >= run['configuration']['limits']['max_dispatches_per_run']:
        for pending in steps:
            if pending['status']=='pending': pending.update(status='blocked',waiting_for='advisor',blocker='dispatch_limit',finished_at=now().isoformat())
        await db.execute(text("UPDATE automation_project_runs SET state='waiting_human',steps=CAST(:steps AS jsonb) WHERE id=CAST(:id AS uuid)"),
            {'id':str(run['id']),'steps':json.dumps(steps)})
        await append_event(db,key,run_id=run['id'],code='dispatch_limit')
        return None
    step.update(status='running',started_at=now().isoformat(),fee_state='unverified')
    await db.execute(text("UPDATE automation_project_runs SET state='running',dispatch_count=dispatch_count+1,steps=CAST(:steps AS jsonb) WHERE id=CAST(:id AS uuid)"),
        {'id':str(run['id']),'steps':json.dumps(steps)})
    await append_event(db,key,run_id=run['id'],code='step_claimed',step_key=step['step_key'],request_id=step['request_id'],fee_state='unverified')
    token={**key,'run_id':str(run['id']),'generation':project['generation'],'step_key':step['step_key'],
        'task_id':step['task_id'],'request_id':step['request_id'],'owner_user_id':project['owner_user_id']}
    if run['configuration'].get('contract_version')==2:
        token.update(operation=step['operation'],target=deepcopy(step['target']))
    return token


async def settle_step(db,token,*,status,error_code=None,evidence_refs=(),result_links=(),fee_state='unverified',success_actor_kind=None):
    if status not in TERMINAL_STEPS or fee_state not in FEE_STATES: raise ValueError('invalid step result')
    if success_actor_kind not in {None,'system','ai'}: raise ValueError('invalid success actor')
    key = scope(token['module'],token['tenant_id'],token['scope_id'])
    await require_schema(db)
    project = await read_project(db,key,lock=True)
    run = await read_run(db,key,token['run_id'],lock=True)
    if not project or not run: raise problem('automation_run_not_found','运行不存在',404)
    steps = deepcopy(run['steps'])
    step = next((s for s in steps if s['step_key']==token['step_key'] and s['request_id']==token['request_id']),None)
    if not step or step['status']!='running': return False
    current = (project['state']=='active' and project['generation']==token['generation']
               and str(project['current_run_id'])==token['run_id'] and not run['stop_requested'])
    if not current and status=='succeeded': status,error_code,result_links = 'stale','automation_generation_stale',()
    # Only bounded module-relative read links, never user URLs or arbitrary error strings.
    prefix = '/api/v1/'+key['module']+'/'
    if any(not link.startswith(prefix) or len(link)>500 or any(c in link for c in '\r\n') for link in result_links):
        raise ValueError('invalid result link')
    if error_code is not None:
        import re
        if not re.fullmatch('[a-z][a-z0-9_]{0,79}',error_code): raise ValueError('unsafe error code')
    step.update(status=status,finished_at=now().isoformat(),waiting_for='advisor',blocker=error_code,
        error_code=error_code,evidence_refs=list(evidence_refs),result_links=list(result_links),fee_state=fee_state)
    state = run['state']
    if current:
        state = 'queued' if any(s['status']=='pending' for s in steps) else (
            'waiting_input' if all(s['status']=='blocked' for s in steps) else 'waiting_human')
    await db.execute(text('UPDATE automation_project_runs SET state=:state,steps=CAST(:steps AS jsonb) WHERE id=CAST(:id AS uuid)'),
        {'id':str(run['id']),'state':state,'steps':json.dumps(steps)})
    # Use the durable operation, never the caller's mutable token. Other module
    # adapters may explicitly classify their successful work as system or AI.
    success_actor = success_actor_kind or ('ai' if run['configuration'].get('contract_version')!=2
        or step.get('operation') in {'onsite_ai','content_draft'} else 'system')
    await append_event(db,key,run_id=run['id'],code='step_'+status,step_key=step['step_key'],
        actor_kind=success_actor if status=='succeeded' else 'system',request_id=step['request_id'],
        evidence_refs=evidence_refs,fee_state=fee_state)
    await finish_stop(db,key,project,await read_run(db,key,run['id']))
    return True


def run_view(key,run):
    if run is None: raise problem('automation_run_not_found','当前范围的运行不存在',404)
    steps = run['steps']
    return wire({'schema':1,**key,'run':{k:run[k] for k in
        ('id','state','generation','stop_requested','started_at','finished_at','dispatch_count','steps')} | {
        'progress':{'total_steps':len(steps),'terminal_steps':sum(s['status'] in TERMINAL_STEPS for s in steps),
            'running_steps':sum(s['status']=='running' for s in steps),'waiting_steps':sum(s['status']=='pending' for s in steps)},
        'completion_evidence':None}})


async def events_page(db,key,run_id,after_id=0,limit=50):
    if type(limit) is not int or not 1 <= limit <= 100 or type(after_id) is not int or after_id < 0:
        raise problem('automation_invalid_cursor','分页参数无效',422)
    if not await read_run(db,key,run_id): raise problem('automation_run_not_found','当前范围的运行不存在',404)
    rows = list((await db.execute(text('SELECT * FROM automation_project_events WHERE '+SCOPE+
        ' AND run_id=CAST(:run_id AS uuid) AND id>:after ORDER BY id LIMIT :limit'),
        {**key,'run_id':str(run_id),'after':after_id,'limit':limit+1})).mappings())
    return wire({'schema':1,**key,'run_id':str(run_id),'items':[dict(r) for r in rows[:limit]],
        'next_after_id':rows[limit-1]['id'] if len(rows)>limit else None})


async def project_events_page(db,key,after_id=0,limit=50):
    """All scope events, including configuration before the first run.

    Adapter verifies the live scope even when no project has been configured.
    The numeric cursor is a scoped lower bound, never a global event lookup.
    """
    scope(**key)
    if type(limit) is not int or not 1 <= limit <= 100 or type(after_id) is not int or after_id < 0:
        raise problem('automation_invalid_cursor','分页参数无效',422)
    rows = list((await db.execute(text('SELECT * FROM automation_project_events WHERE '+SCOPE+
        ' AND id>:after ORDER BY id LIMIT :limit'),
        {**key,'after':after_id,'limit':limit+1})).mappings())
    return wire({'schema':1,**key,'items':[dict(row) for row in rows[:limit]],
        'next_after_id':rows[limit-1]['id'] if len(rows)>limit else None})


async def runs_page(db,key,before_run_id=None,limit=20):
    """Pure scoped history; a foreign cursor is never looked up globally."""
    if type(limit) is not int or not 1 <= limit <= 50:
        raise problem('automation_invalid_cursor','分页参数无效',422)
    params = {**key,'limit':limit+1}
    cursor_sql = ''
    if before_run_id is not None:
        try:
            ident = str(UUID(str(before_run_id)))
        except ValueError:
            raise problem('automation_invalid_cursor','分页参数无效',422) from None
        cursor = await read_run(db,key,ident)
        if not cursor:
            raise problem('automation_run_not_found','当前范围的运行不存在',404)
        params.update(stamp=cursor['created_at'],cursor=ident)
        cursor_sql = ' AND (created_at,id)<(:stamp,CAST(:cursor AS uuid))'
    rows = list((await db.execute(text('SELECT id,state,started_at,finished_at FROM automation_project_runs WHERE '+
        SCOPE+cursor_sql+' ORDER BY created_at DESC,id DESC LIMIT :limit'),params)).mappings())
    return wire({'schema':1,**key,'items':[dict(row) for row in rows[:limit]],
        'next_before_run_id':rows[limit-1]['id'] if len(rows)>limit else None})
