"""Additive shared controls: explicit sources, typed steps, receipts and audit.

No module authorization or HTTP lives here. Adapters own transactions and must
validate live identity, source bindings, targets and capabilities at each gate.
"""
from copy import deepcopy
import hashlib
import json
import re
from datetime import datetime
from uuid import uuid5
import csv
import io

from sqlalchemy import text

from app import automation_projects as core
from app.automation_project_contract import (ConfigurationV2,parse_configuration,Target,SourceBinding,
    SourceVersion,Cycle,Limits,LimitsV2)

CALL_STATES={'succeeded','failed','unknown','stale','cancelled'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


async def schema_ready(db):
    if not await core.schema_ready(db): return False
    columns=set((await db.execute(text('''SELECT table_name,column_name FROM information_schema.columns
        WHERE table_schema=current_schema() AND ((table_name='automation_projects' AND column_name='ended_at')
        OR (table_name='automation_project_events' AND column_name='safe_changes'))'''))).all())
    return columns=={('automation_projects','ended_at'),('automation_project_events','safe_changes')}


async def require_schema(db):
    if not await schema_ready(db):
        raise core.problem('automation_schema_pending','项目 v2 结构或权限尚未审核就绪',503)


def typed_steps(config,run_id):
    parsed=ConfigurationV2.model_validate(config)
    result=[]
    for target in parsed.targets:
        value=target.model_dump(mode='json')
        task_id=target.object_id if target.operation=='onsite_ai' and target.object_type=='onsite_task' else None
        key=f'onsite_ai:{task_id}' if task_id else target.operation+':'+fingerprint(value)[:24]
        result.append({'step_key':key,'kind':target.operation,'operation':target.operation,'target':value,
            'task_id':task_id,'status':'pending','started_at':None,'finished_at':None,'waiting_for':'system',
            'blocker':None,'result_links':[],'error_code':None,'request_id':str(uuid5(run_id,key)),
            'evidence_refs':[],'fee_state':'not_called','dispatched_at':None,'calls':[]})
    if len({s['step_key'] for s in result})!=len(result):
        raise ValueError('ambiguous typed steps')
    return result


def audit_snapshot(project):
    if not project: return {}
    result={k:core.wire(project.get(k)) for k in ('state','version','generation','owner_user_id','cycle_enabled','ended_at')}
    config=project.get('configuration') or {}
    try:
        safe=parse_configuration(config).model_dump(mode='json')
    except (ValueError,TypeError):
        # Never expose malformed stored config as an audit value.
        result['configuration_fingerprint']=fingerprint(config)
        return result
    for key in ('task_ids','operations','targets','service_plan','source_bindings','cycle','limits','stop_condition','contract_version'):
        if key in safe: result['configuration.'+key]=safe[key]
    return result


def audit_changes(before,after):
    old,new=audit_snapshot(before),audit_snapshot(after)
    return [{'path':key,'before':old.get(key),'after':new.get(key)} for key in sorted(old.keys()|new.keys())
        if old.get(key)!=new.get(key)]


def validate_changes(changes):
    # This field is only populated from audit_changes, not client JSON.
    allowed={'state','version','generation','owner_user_id','cycle_enabled','ended_at','configuration_fingerprint'}
    allowed.update('configuration.'+k for k in ('task_ids','operations','targets','service_plan','source_bindings',
        'cycle','limits','stop_condition','contract_version'))
    if not isinstance(changes,list) or len(changes)>20 or any(
        not isinstance(row,dict) or set(row)!={'path','before','after'} or row['path'] not in allowed for row in changes):
        raise ValueError('unsafe audit changes')
    if len(json.dumps(changes,ensure_ascii=False))>24000:
        raise ValueError('audit changes exceed bound')
    for row in changes:
        for value in (row['before'],row['after']):
            if value is None: continue
            path=row['path']
            if path=='state':
                if value not in {'not_started','active','pausing','paused','taking_over','taken_over','ending','idle'}:
                    raise ValueError('unsafe state')
            elif path in {'version','generation','owner_user_id','configuration.contract_version'}:
                if type(value) is not int or value<0: raise ValueError('unsafe numeric audit value')
            elif path=='cycle_enabled':
                if type(value) is not bool: raise ValueError('unsafe cycle audit value')
            elif path=='ended_at':
                if not isinstance(value,str) or len(value)>40: raise ValueError('unsafe date')
                datetime.fromisoformat(value)
            elif path=='configuration_fingerprint':
                if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value): raise ValueError('unsafe digest')
            elif path=='configuration.task_ids':
                if not isinstance(value,list) or len(value)>20 or any(type(v) is not int or v<1 for v in value): raise ValueError('unsafe task IDs')
            elif path=='configuration.operations':
                if not isinstance(value,list) or len(value)>20 or any(not isinstance(v,str) or not re.fullmatch('[a-z][a-z0-9_]{0,39}',v) for v in value): raise ValueError('unsafe operations')
            elif path in {'configuration.targets','configuration.source_bindings'}:
                model=Target if path.endswith('targets') else SourceBinding
                if not isinstance(value,list) or len(value)>(20 if model is Target else 8): raise ValueError('unsafe targets')
                for item in value: model.model_validate(item)
            elif path=='configuration.service_plan': SourceVersion.model_validate(value)
            elif path=='configuration.cycle': Cycle.model_validate(value)
            elif path=='configuration.limits':
                (LimitsV2 if 'max_external_calls_per_run' in value else Limits).model_validate(value)
            elif path=='configuration.stop_condition' and value!='drafts_ready_or_blocked':
                raise ValueError('unsafe stop condition')


async def begin_call(db,token,call_key,*,kind='provider'):
    """Commit True before HTTP. False means already admitted: never resend."""
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_:.-]{0,79}',call_key) or kind not in {'provider','http'}:
        raise ValueError('invalid external call identity')
    await require_schema(db)
    _,run,step=await core.check_step(db,token)
    config=ConfigurationV2.model_validate(run['configuration'])
    if any(c['call_key']==call_key for c in step.get('calls',[])): return False
    if sum(len(s.get('calls',[])) for s in run['steps'])>=config.limits.max_external_calls_per_run:
        raise core.problem('automation_external_call_limit','本次外部调用准入额度已用完')
    steps=deepcopy(run['steps'])
    step=next(s for s in steps if s['request_id']==token['request_id'])
    stamp=core.now().isoformat()
    fee='unknown_charge' if kind=='provider' else 'not_called'
    step['dispatched_at']=step.get('dispatched_at') or stamp
    step['fee_state']=fee if kind=='provider' else step['fee_state']
    step.setdefault('calls',[]).append({'call_key':call_key,'kind':kind,'state':'admitted',
        'admitted_at':stamp,'finished_at':None,'fee_state':fee,'evidence_refs':[]})
    await db.execute(text('UPDATE automation_project_runs SET steps=CAST(:steps AS jsonb) WHERE id=CAST(:id AS uuid)'),
        {'id':token['run_id'],'steps':json.dumps(steps)})
    await core.append_event(db,core.scope(token['module'],token['tenant_id'],token['scope_id']),run_id=token['run_id'],
        step_key=token['step_key'],request_id=token['request_id'],code='external_call_admitted',fee_state=fee)
    return True


async def finish_call(db,token,call_key,*,state,fee_state,evidence_refs=()):
    """Receipt survives stop; this never authorizes adopting business results."""
    if state not in CALL_STATES or fee_state not in core.FEE_STATES: raise ValueError('invalid receipt')
    await require_schema(db)
    key=core.scope(token['module'],token['tenant_id'],token['scope_id'])
    await core.read_project(db,key,lock=True)
    run=await core.read_run(db,key,token['run_id'],lock=True)
    if not run: raise core.problem('automation_run_not_found','运行不存在',404)
    steps=deepcopy(run['steps'])
    step=next((s for s in steps if s['step_key']==token['step_key'] and s['request_id']==token['request_id']),None)
    call=next((c for c in step.get('calls',[]) if c['call_key']==call_key),None) if step else None
    if call is None: raise core.problem('automation_call_not_found','未找到本步骤的外呼准入',404)
    late=call['state']=='unknown'
    if call['state']!='admitted':
        if (call['state'],call['fee_state'],call['evidence_refs'])==(state,fee_state,list(evidence_refs)): return False
        if not late:
            raise core.problem('automation_receipt_conflict','已保存回执内容不一致，不能覆盖')
    call.update(state=state,fee_state=fee_state,evidence_refs=list(evidence_refs),finished_at=core.now().isoformat())
    paid=[c for c in step['calls'] if c['kind']=='provider']
    step['fee_state']=('not_called' if not paid else 'recorded' if all(c['fee_state']=='recorded' for c in paid) else 'unknown_charge')
    await core.append_event(db,key,run_id=token['run_id'],step_key=token['step_key'],request_id=token['request_id'],
        code='external_call_late_receipt' if late else 'external_call_'+state,fee_state=fee_state,evidence_refs=evidence_refs)
    await db.execute(text('UPDATE automation_project_runs SET steps=CAST(:steps AS jsonb) WHERE id=CAST(:id AS uuid)'),
        {'id':token['run_id'],'steps':json.dumps(steps)})
    return True


async def end_project(db,key,project):
    await require_schema(db)
    run=await core.read_run(db,key,project['current_run_id'],lock=True) if project['current_run_id'] else None
    await db.execute(text('''UPDATE automation_projects SET ended_at=CURRENT_TIMESTAMP,cycle_enabled=false,
        next_due_at=NULL,state=:state,version=version+1,generation=generation+1,updated_at=CURRENT_TIMESTAMP WHERE '''+core.SCOPE),
        {**key,'state':'ending' if run else 'idle'})
    if run:
        await db.execute(text("UPDATE automation_project_runs SET state='ending',stop_requested=true WHERE id=CAST(:id AS uuid)"),{'id':str(run['id'])})
        await core.finish_stop(db,key,await core.read_project(db,key),await core.read_run(db,key,run['id']))


async def ownership(db,key,operation):
    """Fail closed registry read; absent all tables is legacy, partial is not.

    Does not take locks: use before any business locks, then recheck under the
    project lock before write/admission. False means not explicitly adopted.
    """
    installed=await db.scalar(text('''SELECT EXISTS(SELECT 1 FROM information_schema.tables
        WHERE table_schema=current_schema() AND table_name=ANY(:tables))'''),{'tables':list(core.TABLES)})
    if not installed: return None
    await core.require_schema(db)
    project=await core.read_project(db,key)
    if not project or project['configuration'].get('contract_version')!=2: return None
    await require_schema(db)
    config=ConfigurationV2.model_validate(project['configuration'])
    return project if operation in config.operations else None


async def check_legacy(db,key,operation):
    """Legacy admission/result gate. Call BEFORE business locks, then commit.

    A managed operation never falls back to an old scheduler, even when paused
    or ended. Repeat this after external I/O in the result-write transaction.
    The advisory lock also fences first configuration while no project exists.
    """
    await core.lock_scope(db,key)
    if await ownership(db,key,operation) is not None:
        raise core.problem('automation_legacy_owned','该操作已由项目机制接管，旧调度器不得另行执行')


async def events_export_page(db,key,*,after_id=0,through_id=None,limit=100):
    core.scope(**key)
    if (type(limit) is not int or not 1<=limit<=500 or type(after_id) is not int or after_id<0
            or through_id is not None and (type(through_id) is not int or through_id<0)):
        raise core.problem('automation_invalid_cursor','导出分页参数无效',422)
    await core.require_schema(db)
    if through_id is None:
        through_id=int(await db.scalar(text('SELECT max(id) FROM automation_project_events WHERE '+core.SCOPE),key) or 0)
    rows=list((await db.execute(text('SELECT * FROM automation_project_events WHERE '+core.SCOPE+
        ' AND id>:after AND id<=:through ORDER BY id LIMIT :limit'),
        {**key,'after':after_id,'through':through_id,'limit':limit+1})).mappings())
    fields=('id','module','tenant_id','scope_id','run_id','actor_kind','actor_user_id','step_key','code',
        'request_id','evidence_refs','fee_state','safe_changes','created_at')
    return core.wire({'schema':1,**key,'snapshot_upper_id':through_id,
        'items':[{field:row.get(field,[] if field=='safe_changes' else None) for field in fields} for row in rows[:limit]],
        'next_after_id':rows[limit-1]['id'] if len(rows)>limit else None})


def csv_export(page):
    output=io.StringIO(newline='')
    fields=('id','module','tenant_id','scope_id','run_id','actor_kind','actor_user_id','step_key','code',
        'request_id','evidence_refs','fee_state','safe_changes','created_at')
    writer=csv.writer(output)
    writer.writerow(fields)
    for row in page['items']:
        values=[]
        for field in fields:
            value=row.get(field)
            cell='' if value is None else json.dumps(value,ensure_ascii=False) if isinstance(value,(list,dict)) else str(value)
            if cell.lstrip(' \t\r\n\ufeff').startswith(('=','+','-','@')): cell="'"+cell
            values.append(cell)
        writer.writerow(values)
    return output.getvalue()


async def health_snapshot(db,module,*,worker=None):
    core.scope(module,1,1)
    worker=worker or {'state':'unverified','verified':False,'last_tick_at':None,'evidence':None}
    result={'schema':1,'module':module,'scope':{'kind':'global','tenant_id':None},'as_of':core.now().isoformat(),
        'state':'schema_pending','contract_versions':[],
        'counts':dict.fromkeys(('projects','runs','pending_human','unknown_cost')),
        'rows':[],'truncated':False,'queue':{'state':'not_connected','queued':None,'running':None,'unknown':None},
        'worker':worker,'overall':'unverified','alerts':[]}
    if not await core.schema_ready(db):
        result['alerts']=[{'code':'automation_schema_pending','summary':'结构或权限未就绪，计数未知'}]
        return result
    result['state']='available'
    result['contract_versions']=[1,2] if await schema_ready(db) else [1]
    cte='''WITH costs AS (
        SELECT r.tenant_id,r.scope_id,count(*) AS unknown_cost
        FROM automation_project_runs r CROSS JOIN LATERAL jsonb_array_elements(r.steps) s(value)
        WHERE r.module=:module AND (
          (jsonb_array_length(COALESCE(s.value->'calls','[]'::jsonb))=0
             AND s.value->>'dispatched_at' IS NOT NULL AND s.value->>'fee_state' IN ('unknown_charge','unverified'))
          OR EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(s.value->'calls','[]'::jsonb)) c(value)
             WHERE c.value->>'kind'='provider' AND c.value->>'fee_state' IN ('unknown_charge','unverified')))
        GROUP BY r.tenant_id,r.scope_id),
      projects AS (
        SELECT p.tenant_id,p.scope_id,p.state AS project_state,r.state AS run_state,
          CASE WHEN r.state IN ('waiting_input','waiting_human','taken_over') THEN 1 ELSE 0 END AS pending_human,
          COALESCE(c.unknown_cost,0) AS unknown_cost,p.cycle_enabled,p.updated_at
        FROM automation_projects p LEFT JOIN automation_project_runs r
          ON r.id=p.current_run_id AND r.module=p.module AND r.tenant_id=p.tenant_id AND r.scope_id=p.scope_id
        LEFT JOIN costs c ON c.tenant_id=p.tenant_id AND c.scope_id=p.scope_id WHERE p.module=:module)
    '''
    counts=(await db.execute(text(cte+'''SELECT count(*) AS projects,
        (SELECT count(*) FROM automation_project_runs WHERE module=:module) AS runs,
        COALESCE(sum(pending_human),0) AS pending_human,COALESCE(sum(unknown_cost),0) AS unknown_cost FROM projects'''),
        {'module':module})).mappings().one()
    rows=list((await db.execute(text(cte+'SELECT * FROM projects ORDER BY tenant_id,scope_id LIMIT 51'),
        {'module':module})).mappings())
    result.update(counts={k:int(v) for k,v in counts.items()},rows=core.wire([dict(r) for r in rows[:50]]),truncated=len(rows)>50)
    if result['counts']['unknown_cost']:
        result['alerts'].append({'code':'automation_unknown_cost','summary':'存在费用尚未核实的已准入步骤'})
    if not worker['verified']:
        result['alerts'].append({'code':'automation_worker_unverified','summary':'尚无可核实的本进程工作心跳'})
    return result
