"""Bounded AI advice with durable claims and independently admitted account slots.

No device tasks, publication grants, native writebacks or platform actions.
"""
import asyncio
import hashlib
from uuid import uuid4
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app import distribution_control as core, distribution_scheduling as scheduling
from app.distribution_planning_gateway import suggest,GatewayFailure

MAX_ITEMS=10
MAX_CALLS=2
RETRY_SECONDS=300
HORIZON=7*86400000
MODEL_TIMEOUT_SECONDS=45


async def snapshot(db,scope,*,include_planned=False,queue_ids=None):
    await core.lock(db,'scope:'+core.canonical(scope))
    p=await core.one(db,'SELECT * FROM distribution_controls WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id',**scope)
    if not p or p['state']!='running': return None
    if not include_planned and await core.one(db,"SELECT id FROM distribution_plan_requests WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND state IN ('running','unknown') LIMIT 1",**scope):
        await db.execute(core.text('INSERT INTO distribution_planner_scans(tenant_id,module,scope_id,checked_at) VALUES(:tenant_id,:module,:scope_id,:at) ON CONFLICT(tenant_id,module,scope_id) DO UPDATE SET checked_at=EXCLUDED.checked_at'),{**scope,'at':core.now_ms()})
        return None
    scan=await core.one(db,'SELECT binding_cursor FROM distribution_planner_scans WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id',**scope)
    cursor=None if queue_ids else (scan or {}).get('binding_cursor')
    configs=await core.rows(db,'SELECT c.*,b.platform,b.external_account_id,b.account_id FROM distribution_project_channels c '
        'JOIN distribution_bindings b ON b.id=c.binding_id JOIN distribution_devices d ON d.id=b.device_id WHERE c.tenant_id=:tenant_id AND c.module=:module AND c.scope_id=:scope_id '
        'AND c.enabled AND b.active AND d.active AND (CAST(:cursor AS uuid) IS NULL OR c.binding_id>CAST(:cursor AS uuid)) '
        'AND (CAST(:ids AS uuid[]) IS NULL OR c.binding_id IN (SELECT binding_id FROM distribution_queue WHERE id=ANY(CAST(:ids AS uuid[])))) '
        'ORDER BY c.binding_id LIMIT 20',**scope,cursor=cursor,ids=queue_ids)
    if not queue_ids:
        await db.execute(core.text('INSERT INTO distribution_planner_scans VALUES(:tenant_id,:module,:scope_id,:at,:cursor) ON CONFLICT(tenant_id,module,scope_id) DO UPDATE SET checked_at=EXCLUDED.checked_at,binding_cursor=EXCLUDED.binding_cursor'),{**scope,'at':core.now_ms(),'cursor':configs[-1]['binding_id'] if len(configs)==20 else None})
    for c in sorted(configs,key=lambda c:(c['platform'],c['external_account_id'])): await scheduling.account_lock(db,c)
    actor=p['owner_user_id'];await core.authorize_scope(db,actor,scope)
    at=core.now_ms();items=[]
    for c in configs:
        if c['owner_user_id']!=actor: continue
        try:b=await scheduling.binding(db,c['binding_id'],scope)
        except HTTPException as exc:
            if exc.status_code>=500:raise
            continue
        permission=await core.one(db,'SELECT * FROM distribution_channel_permissions WHERE platform=:platform AND content_type=:kind',platform=b['platform'],kind=c['content_type'])
        if not permission or not permission['enabled']: continue
        sched=await scheduling.schedule(db,b)
        if sched['reason'] in ('POLICY_REQUIRED','POLICY_DISABLED','ACCOUNT_PAUSED','CAPTCHA','LOGIN_REQUIRED','RESULT_CONFLICT','OUTCOME_UNKNOWN','ACCOUNT_BUSY') or sched['next_allowed_at'] is None: continue
        candidates=await core.rows(db,'SELECT q.* FROM distribution_queue q WHERE q.tenant_id=:tenant_id AND q.module=:module AND q.scope_id=:scope_id '
            "AND q.binding_id=:binding AND q.source_revision IS NOT NULL AND q.state IN ('queued','scheduled','awaiting-adaptation') "
            'AND (CAST(:ids AS uuid[]) IS NULL OR q.id=ANY(CAST(:ids AS uuid[]))) '
            "AND (:include OR NOT EXISTS (SELECT 1 FROM distribution_plans p JOIN distribution_plan_requests r ON r.id=p.request_id WHERE p.queue_id=q.id AND p.state='planned' AND NOT (p.basis='rules' AND r.state='failed' AND r.attempts<3 AND r.retry_at<=:at))) "
            "AND NOT EXISTS (SELECT 1 FROM distribution_tasks t JOIN distribution_bindings existing_binding ON existing_binding.id=t.binding_id WHERE t.tenant_id=q.tenant_id AND t.module=q.module AND t.scope_id=q.scope_id AND t.variant_id=q.variant_id AND t.source_revision=q.source_revision AND t.action='publish' AND t.status NOT IN ('failed','canceled') AND existing_binding.platform=q.platform AND existing_binding.external_account_id=q.external_account_id) "
            'ORDER BY q.created_at,q.id LIMIT 10',**scope,binding=c['binding_id'],ids=queue_ids,include=include_planned,at=at)
        for q in candidates:
            live=await core.one(db,"SELECT p.*,r.state AS request_state,r.attempts,r.retry_at FROM distribution_plans p JOIN distribution_plan_requests r ON r.id=p.request_id WHERE p.queue_id=:id AND p.state='planned'",id=q['id'])
            if live and not include_planned and not (live['basis']=='rules' and live['request_state']=='failed' and live['attempts']<3 and live['retry_at'] is not None and live['retry_at']<=at): continue
            existing=await core.one(db,'SELECT t.id FROM distribution_tasks t JOIN distribution_bindings b ON b.id=t.binding_id '
                'WHERE t.tenant_id=:tenant_id AND t.module=:module AND t.scope_id=:scope_id AND t.variant_id=:variant '
                "AND t.source_revision=:revision AND t.action='publish' AND t.status NOT IN ('failed','canceled') AND b.platform=:platform AND b.external_account_id=:external LIMIT 1",
                **scope,variant=q['variant_id'],revision=q['source_revision'],platform=b['platform'],external=b['external_account_id'])
            if existing: continue
            value,digest=await core.source(db,actor,scope,q['variant_id'],b['platform'])
            if (value['source_revision'],digest)!=(q['source_revision'],q['content_digest']): continue
            items.append({'queue_id':str(q['id']),'binding_id':str(q['binding_id']),'variant_id':q['variant_id'],
                'platform':q['platform'],'account_id':b['account_id'],'external_account_id':b['external_account_id'],
                'draft_version':q['draft_version'],'source_revision':q['source_revision'],'content_digest':digest,
                'selection_revision':c['revision'],'permission_revision':permission['revision'],
                'policy':sched['policy'],'restriction':sched['restriction'],'earliest_at':max(at,sched['next_allowed_at']),
                'daily_limit':sched['effective_daily_limit'],'interval_seconds':sched['effective_interval_seconds']})
            if len(items)==MAX_ITEMS: break
        if len(items)==MAX_ITEMS: break
    if not items: return None
    return {**scope,'actor_id':actor,'control_revision':p['revision'],'items':items}


def fingerprint(value):
    stable={**value,'items':[{k:v for k,v in i.items() if k!='earliest_at'} for i in value['items']]}
    return hashlib.sha256(core.canonical(stable).encode()).hexdigest()


def validate_output(value,snap):
    ids={i['queue_id']:i for i in snap['items']}
    if not isinstance(value,dict) or set(value)!={'items'} or not isinstance(value['items'],list) or len(value['items'])!=len(ids): raise GatewayFailure('AI_INVALID_OUTPUT')
    seen=set();ordered=[]
    for item in value['items']:
        if (not isinstance(item,dict) or set(item)!={'queue_id','at'} or not isinstance(item['queue_id'],str)
            or item['queue_id'] not in ids or item['queue_id'] in seen or type(item['at']) is not int
            or not ids[item['queue_id']]['earliest_at']<=item['at']<=ids[item['queue_id']]['earliest_at']+HORIZON): raise GatewayFailure('AI_INVALID_OUTPUT')
        seen.add(item['queue_id']);ordered.append(item)
    return ordered


async def allocate(db,item,proposed,exclude):
    """Account-wide advisory slots, separate from actual publication reservations."""
    zone=ZoneInfo(item['policy']['timezone']);candidate=max(proposed,item['earliest_at']);end=item['earliest_at']+HORIZON
    start,_=scheduling.day_bounds(item['earliest_at'],zone)
    floor=start-86400000
    planned=await core.rows(db,"SELECT planned_at FROM distribution_plans WHERE platform=:platform AND external_account_id=:external AND state='planned' AND planned_at BETWEEN :floor AND :end AND queue_id::text<>ALL(CAST(:exclude AS text[]))",
        platform=item['platform'],external=item['external_account_id'],exclude=exclude,floor=floor,end=end+86400000)
    actual=await core.rows(db,"SELECT reserved_at,completed_at FROM distribution_publish_reservations WHERE platform=:platform AND external_account_id=:external AND state<>'released' AND GREATEST(reserved_at,COALESCE(completed_at,reserved_at)) BETWEEN :floor AND :end",
        platform=item['platform'],external=item['external_account_id'],floor=floor,end=end+86400000)
    used=[r['planned_at'] for r in planned]+[max(r['reserved_at'],r['completed_at'] or r['reserved_at']) for r in actual]
    interval=item['interval_seconds']*1000
    while candidate<=end:
        candidate=scheduling.next_window(candidate,zone,item['policy']['windows'])
        if candidate is None or candidate>end: break
        start,finish=scheduling.day_bounds(candidate,zone)
        if sum(start<=t<finish for t in used)>=item['daily_limit']:
            candidate=finish;continue
        conflict=next((t for t in sorted(used) if abs(t-candidate)<max(1,interval)),None)
        if conflict is not None: candidate=conflict+max(1,interval);continue
        return candidate
    return None


async def reconcile(sessions,*,module=None):
    from app import distribution_execution as execution
    async with sessions() as db:
        exclusion=" AND NOT EXISTS (SELECT 1 FROM distribution_execution_intents e JOIN distribution_tasks t ON t.id=e.task_id WHERE e.plan_id=p.id AND t.status IN ('queued','leased','running','awaiting-human','unknown'))" if await execution.installed(db) else ''
        plans=[dict(p) for p in await core.rows(db,"SELECT p.* FROM distribution_plans p WHERE p.state='planned' AND (CAST(:module AS varchar) IS NULL OR p.module=:module)"+exclusion+" ORDER BY p.checked_at,p.id LIMIT 50",module=module)]
    for plan in plans:
        scope={k:plan[k] for k in ('module','tenant_id','scope_id')};reason=None
        try:
            async with sessions() as db:
                snap=await snapshot(db,scope,include_planned=True,queue_ids=[plan['queue_id']])
                item=next((i for i in (snap or {}).get('items',[]) if i['queue_id']==str(plan['queue_id'])),None)
                if not item: reason='AUTHORIZATION_OR_SOURCE_CHANGED'
                elif (item['draft_version'],item['source_revision'],item['content_digest'])!=(plan['draft_version'],plan['source_revision'],plan['content_digest']): reason='SOURCE_CHANGED'
                else:
                    request=await core.one(db,'SELECT snapshot FROM distribution_plan_requests WHERE id=:id',id=plan['request_id'])
                    original=next((i for i in request['snapshot']['items'] if i['queue_id']==str(plan['queue_id'])),None)
                    if not original or {k:v for k,v in original.items() if k!='earliest_at'}!={k:v for k,v in item.items() if k!='earliest_at'} or request['snapshot']['control_revision']!=snap['control_revision']:
                        reason='PLANNING_RULES_CHANGED'
                    elif plan['planned_at']>=item['earliest_at'] and await allocate(db,item,plan['planned_at'],[str(plan['queue_id'])])!=plan['planned_at']:
                        reason='ACCOUNT_SLOT_CHANGED'
                if reason:
                    await db.execute(core.text("UPDATE distribution_plans SET state='blocked',reason=:reason,checked_at=:at WHERE id=:id AND state='planned'"),{'id':plan['id'],'reason':reason,'at':core.now_ms()})
                    await core.audit(db,(snap or {}).get('actor_id','planner'),'plan_blocked',scope,reason,plan['queue_id'])
                else: await db.execute(core.text('UPDATE distribution_plans SET checked_at=:at WHERE id=:id'),{'at':core.now_ms(),'id':plan['id']})
                await db.commit()
        except HTTPException:
            async with sessions() as db:
                await core.lock(db,'scope:'+core.canonical(scope))
                await db.execute(core.text("UPDATE distribution_plans SET state='blocked',reason='AUTHORIZATION_REVOKED',checked_at=:at WHERE id=:id AND state='planned'"),{'id':plan['id'],'at':core.now_ms()})
                await core.audit(db,'planner','plan_blocked',scope,'AUTHORIZATION_REVOKED',plan['queue_id'])
                await db.commit()


async def recover_claims(sessions,*,module=None):
    """Reclaim old claims independently of current batch eligibility/fingerprint."""
    cutoff=core.now_ms()-60000
    async with sessions() as db:
        claims=await core.rows(db,"SELECT id,tenant_id,module,scope_id FROM distribution_plan_requests WHERE state='running' AND updated_at<:cutoff AND (CAST(:module AS varchar) IS NULL OR module=:module) ORDER BY updated_at,id LIMIT 50",cutoff=cutoff,module=module)
    for claim in claims:
        scope={k:claim[k] for k in ('tenant_id','module','scope_id')}
        async with sessions() as db:
            await core.lock(db,'scope:'+core.canonical(scope))
            changed=await core.one(db,"UPDATE distribution_plan_requests SET state='unknown',reason='AI_ATTEMPT_UNKNOWN',updated_at=:at WHERE id=:id AND state='running' AND updated_at<:cutoff RETURNING id",id=claim['id'],at=core.now_ms(),cutoff=cutoff)
            if changed:await core.audit(db,'planner','plan_attempt_unknown',scope,'AI_ATTEMPT_UNKNOWN')
            await db.commit()


async def plan_scope(sessions,scope,model=suggest):
    async with sessions() as db:
        snap=await snapshot(db,scope)
        if not snap:
            await db.commit()
            return False
        fp=fingerprint(snap);at=core.now_ms()
        prior=await core.one(db,'SELECT * FROM distribution_plan_requests WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND fingerprint=:fp',**scope,fp=fp)
        if prior:
            if prior['state']=='running':
                if prior['updated_at']<at-60000:
                    await db.execute(core.text("UPDATE distribution_plan_requests SET state='unknown',reason='AI_ATTEMPT_UNKNOWN',updated_at=:at WHERE id=:id"),{'id':prior['id'],'at':at});await db.commit()
                await db.commit()
                return False
            if prior['state']=='unknown' or prior['attempts']>=3:
                await db.commit()
                return False
            due=prior['retry_at'] if prior['retry_at'] is not None else prior['updated_at']+RETRY_SECONDS*1000
            if due>at:
                await db.commit()
                return False
            ident=prior['id']
            await db.execute(core.text("UPDATE distribution_plan_requests SET state='running',attempts=attempts+1,snapshot=CAST(:snap AS jsonb),updated_at=:at WHERE id=:id"),{'id':ident,'snap':core.canonical(snap),'at':at})
        else:
            ident=uuid4()
            await db.execute(core.text("INSERT INTO distribution_plan_requests VALUES(:id,:tenant_id,:module,:scope_id,:fp,CAST(:snap AS jsonb),:actor,'running','AI_REQUESTED',1,:at,:at,NULL)"),{**scope,'id':ident,'fp':fp,'snap':core.canonical(snap),'actor':snap['actor_id'],'at':at})
        await core.audit(db,snap['actor_id'],'plan_requested',scope,'AI_REQUESTED')
        await db.commit()
    failure=None
    try:
        output=await asyncio.wait_for(model(snap,ident),MODEL_TIMEOUT_SECONDS)
        ordered=validate_output(output,snap)
    except Exception as exc:
        control_codes={'api_provider_disabled':'AI_PROVIDER_DISABLED','api_budget_exhausted':'AI_BUDGET_EXHAUSTED','api_concurrency_limit':'AI_CONCURRENCY_LIMIT','api_charge_unresolved':'AI_CHARGE_UNRESOLVED','api_budget_quote_unavailable':'AI_PRICE_REQUIRED'}
        failure=exc.code if isinstance(exc,GatewayFailure) else control_codes.get(getattr(exc,'code',None),'AI_ATTEMPT_UNKNOWN' if isinstance(exc,TimeoutError) else 'AI_FAILED')
        # Metering failures after an attempted provider call cannot be retried.
        if getattr(exc,'provider_attempted',False): failure='AI_ATTEMPT_UNKNOWN'
        ordered=[{'queue_id':i['queue_id'],'at':i['earliest_at']} for i in snap['items']]
    async with sessions() as db:
        try:
            fresh=await snapshot(db,scope,include_planned=True,queue_ids=[i['queue_id'] for i in snap['items']])
        except HTTPException:
            fresh=None
        request=await core.one(db,'SELECT state FROM distribution_plan_requests WHERE id=:id',id=ident)
        if request['state']!='running':
            await core.audit(db,snap['actor_id'],'plan_discarded',scope,'AI_ATTEMPT_UNKNOWN')
            await db.commit()
            return True
        selected={i['queue_id']:i for i in (fresh or {}).get('items',[])}
        matched={**(fresh or {}),'items':[selected[i['queue_id']] for i in snap['items'] if i['queue_id'] in selected]}
        if not fresh or len(matched['items'])!=len(snap['items']) or fingerprint(matched)!=fp:
            unknown=failure=='AI_ATTEMPT_UNKNOWN'
            reason='AI_ATTEMPT_UNKNOWN' if unknown else 'AUTHORIZATION_OR_SOURCE_CHANGED'
            await db.execute(core.text('UPDATE distribution_plan_requests SET state=:state,reason=:reason,updated_at=:at WHERE id=:id'),{'id':ident,'state':'unknown' if unknown else 'stale','reason':reason,'at':core.now_ms()})
            await core.audit(db,snap['actor_id'],'plan_discarded',scope,reason);await db.commit();return True
        admitted=0
        for suggestion in ordered:
            item=selected[suggestion['queue_id']]
            await db.execute(core.text("UPDATE distribution_plans SET state='superseded',reason='REPLANNED' WHERE queue_id=:id AND state='planned'"),{'id':item['queue_id']})
            time=await allocate(db,item,suggestion['at'],[item['queue_id']])
            if time is None: continue
            admitted+=1
            await db.execute(core.text("INSERT INTO distribution_plans VALUES(:id,:queue,:request,:tenant_id,:module,:scope_id,:platform,:external,:binding,:draft,:revision,:digest,:planned,:basis,'planned',:reason,:at,:at) "
                "ON CONFLICT(request_id,queue_id) DO UPDATE SET planned_at=EXCLUDED.planned_at,basis=EXCLUDED.basis,state='planned',reason=EXCLUDED.reason,checked_at=EXCLUDED.checked_at"),
                {**scope,'id':uuid4(),'queue':item['queue_id'],'request':ident,'platform':item['platform'],'external':item['external_account_id'],
                 'binding':item['binding_id'],'draft':item['draft_version'],'revision':item['source_revision'],'digest':item['content_digest'],
                 'planned':time,'basis':'rules' if failure else 'ai','reason':failure or 'AI_ADVICE_ADMITTED','at':core.now_ms()})
            await core.audit(db,snap['actor_id'],'plan_saved',{**scope,'binding_id':item['binding_id'],'variant_id':item['variant_id']},failure or 'AI_ADVICE_ADMITTED',item['queue_id'])
        if not admitted and not failure: failure='ACCOUNT_SLOT_UNAVAILABLE'
        state='unknown' if failure=='AI_ATTEMPT_UNKNOWN' else 'failed' if failure else 'succeeded'
        await db.execute(core.text('UPDATE distribution_plan_requests SET state=:state,reason=:reason,updated_at=:at,retry_at=:retry WHERE id=:id'),
            {'id':ident,'state':state,'reason':failure or 'AI_ADVICE_ADMITTED','at':core.now_ms(),'retry':core.now_ms()+RETRY_SECONDS*1000 if state=='failed' else None})
        await db.commit()
    return True


async def run_once(sessions,model=suggest,*,module=None):
    await recover_claims(sessions,module=module)
    await reconcile(sessions,module=module)
    async with sessions() as db:
        scopes=[dict(s) for s in await core.rows(db,"SELECT c.tenant_id,c.module,c.scope_id FROM distribution_controls c LEFT JOIN distribution_planner_scans s USING(tenant_id,module,scope_id) WHERE c.state='running' AND (CAST(:module AS varchar) IS NULL OR c.module=:module) ORDER BY COALESCE(s.checked_at,0),c.tenant_id,c.module,c.scope_id LIMIT 50",module=module)]
    calls=0
    for scope in scopes:
        try:
            if await plan_scope(sessions,scope,model): calls+=1
        except HTTPException:
            async with sessions() as db:
                await core.lock(db,'scope:'+core.canonical(scope))
                await db.execute(core.text('INSERT INTO distribution_planner_scans(tenant_id,module,scope_id,checked_at) VALUES(:tenant_id,:module,:scope_id,:at) ON CONFLICT(tenant_id,module,scope_id) DO UPDATE SET checked_at=EXCLUDED.checked_at'),{**scope,'at':core.now_ms()})
                await db.commit()
            continue
        if calls>=MAX_CALLS: break
