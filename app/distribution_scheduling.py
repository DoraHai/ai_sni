"""Canonical-account publication admission. Policy and reservations survive restarts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib

from app import distribution_control as core


async def binding(db, ident, scope=None):
    row=await core.one(db,'SELECT b.*,d.active AS device_active FROM distribution_bindings b '
        'JOIN distribution_devices d ON d.id=b.device_id WHERE b.id=:id',id=ident)
    if not row or not row['active'] or not row['device_active'] or scope and any(row[k]!=scope[k] for k in scope):
        raise core.problem('binding_unavailable')
    return row


async def account_lock(db, row):
    await core.lock(db,'account:'+row['platform']+':'+row['external_account_id'])


async def policy(db, row):
    return await core.one(db,'SELECT * FROM distribution_account_policies '
        'WHERE platform=:platform AND external_account_id=:external_account_id AND tenant_id=:tenant_id',**row)


async def request_prior(db, actor, request):
    await core.lock(db,'request:'+str(actor)+':'+str(request.request_id))
    fingerprint=hashlib.sha256(core.canonical(request.model_dump(mode='json')).encode()).hexdigest()
    prior=await core.one(db,'SELECT fingerprint,result FROM distribution_requests WHERE actor_id=:actor AND request_id=:id',
        actor=actor,id=request.request_id)
    if prior and prior['fingerprint']!=fingerprint: raise core.problem('idempotency_conflict')
    return fingerprint,prior['result'] if prior else None


async def save_request(db, actor, request, fingerprint, result):
    await db.execute(core.text('INSERT INTO distribution_requests VALUES(:actor,:id,:fp,CAST(:result AS jsonb))'),
        {'actor':actor,'id':request.request_id,'fp':fingerprint,'result':core.canonical(result)})


def day_bounds(at, zone):
    local=datetime.fromtimestamp(at/1000,timezone.utc).astimezone(zone)
    start=datetime.combine(local.date(),datetime.min.time(),tzinfo=zone)
    end=datetime.combine(local.date()+timedelta(days=1),datetime.min.time(),tzinfo=zone)
    return int(start.timestamp()*1000),int(end.timestamp()*1000)


def in_window(at, zone, windows):
    local=datetime.fromtimestamp(at/1000,timezone.utc).astimezone(zone)
    minute=local.hour*60+local.minute
    return any(w['start']<=minute<w['end'] for w in windows)


def next_window(at, zone, windows):
    if in_window(at,zone,windows): return at
    # Walk absolute minutes: DST gaps/folds cannot manufacture local execution times.
    candidate=((at+59999)//60000)*60000
    for _ in range(4320):
        if in_window(candidate,zone,windows): return candidate
        candidate+=60000
    return None


async def schedule(db, row, task_id=None, at=None):
    at=core.now_ms() if at is None else at
    existing=await core.one(db,'SELECT * FROM distribution_account_policies '
        'WHERE platform=:platform AND external_account_id=:external_account_id',**row)
    if existing and existing['tenant_id']!=row['tenant_id']: raise core.problem('account_tenant_conflict')
    p=existing
    restriction=await core.one(db,'SELECT * FROM distribution_account_restrictions WHERE binding_id=:id',id=row['id'])
    value={'binding_id':str(row['id']),'policy':None,'restriction':None,'as_of':at,
        'reason':'POLICY_REQUIRED','next_allowed_at':None,'available':False,'system_used_today':0,
        'system_remaining':None,'platform_remaining':None,'platform_quota_state':'unverified',
        'reservation_task_id':None,'effective_daily_limit':None,'effective_interval_seconds':None}
    if restriction:
        value['restriction']={k:restriction[k] for k in ('revision','min_interval_seconds','daily_limit')}
    if not p: return value
    from app import distribution_execution as execution
    if await execution.installed(db):
        handoff=await core.one(db,"SELECT t.status FROM distribution_handoff_slots s JOIN distribution_execution_intents e ON e.id=s.intent_id JOIN distribution_tasks t ON t.id=e.task_id WHERE s.platform=:platform AND s.external_account_id=:external_account_id AND s.state='held' AND t.id::text<>:task LIMIT 1",**row,task=str(task_id) if task_id else '')
        if handoff:
            value['policy']={k:p[k] for k in ('enabled','timezone','min_interval_seconds','daily_limit','windows','revision','paused_reason')}
            value.update(effective_daily_limit=min(p['daily_limit'],restriction['daily_limit']) if restriction else p['daily_limit'],effective_interval_seconds=max(p['min_interval_seconds'],restriction['min_interval_seconds']) if restriction else p['min_interval_seconds'])
            value['reason']='OUTCOME_UNKNOWN' if handoff['status']=='unknown' else 'ACCOUNT_BUSY'
            return value
    value['policy']={k:p[k] for k in ('enabled','timezone','min_interval_seconds','daily_limit','windows','revision','paused_reason')}
    limit=min(p['daily_limit'],restriction['daily_limit']) if restriction else p['daily_limit']
    interval=max(p['min_interval_seconds'],restriction['min_interval_seconds']) if restriction else p['min_interval_seconds']
    value.update(effective_daily_limit=limit,effective_interval_seconds=interval)
    zone=ZoneInfo(p['timezone']); start,end=day_bounds(at,zone)
    reservations=await core.rows(db,'SELECT r.*,t.status FROM distribution_publish_reservations r '
        'JOIN distribution_tasks t ON t.id=r.task_id WHERE r.platform=:platform AND r.external_account_id=:external_account_id '
        "AND (r.state='held' OR r.reserved_at>=:start OR r.completed_at>=:start)",**row,start=start)
    active=[r for r in reservations if r['state']=='held']
    used=sum(1 for r in reservations if r['state']!='released' and (
        start<=r['reserved_at']<end or r['completed_at'] is not None and start<=r['completed_at']<end))
    value.update(system_used_today=used,system_remaining=max(0,limit-used))
    own=next((r for r in active if str(r['task_id'])==str(task_id)),None)
    other=next((r for r in active if str(r['task_id'])!=str(task_id)),None)
    if other:
        value['reason']='OUTCOME_UNKNOWN' if other['status']=='unknown' else 'ACCOUNT_BUSY'
        # Do not disclose another project's task identity in a scoped account view.
        return value
    if own: value['reservation_task_id']=str(task_id)
    if not p['enabled']: value['reason']='POLICY_DISABLED'; return value
    if p['paused_reason']: value['reason']=p['paused_reason']; return value
    last=await core.one(db,'SELECT max(GREATEST(reserved_at,COALESCE(completed_at,reserved_at))) AS at '
        'FROM distribution_publish_reservations WHERE platform=:platform AND external_account_id=:external_account_id '
        'AND task_id::text<>:task',**row,task=str(task_id) if own else '')
    candidate=at if own else max(at,(last['at'] or 0)+interval*1000)
    if used>=limit and not own: candidate=max(candidate,end)
    allowed=next_window(candidate,zone,p['windows'])
    value['next_allowed_at']=allowed
    value['available']=allowed is not None and allowed<=at
    value['reason']='READY' if value['available'] else (
        'DAILY_LIMIT' if used>=limit and not own else 'MIN_INTERVAL' if candidate>at else 'OUTSIDE_WINDOW')
    return value


async def set_policy(db, actor, request):
    row=await binding(db,request.binding_id); await account_lock(db,row)
    fp,prior=await request_prior(db,actor,request)
    if prior: return prior
    p=await core.one(db,'SELECT * FROM distribution_account_policies '
        'WHERE platform=:platform AND external_account_id=:external_account_id',**row)
    if p and p['tenant_id']!=row['tenant_id']: raise core.problem('account_tenant_conflict')
    if (p['revision'] if p else 0)!=request.expected_revision: raise core.problem('version_conflict')
    await db.execute(core.text('INSERT INTO distribution_account_policies '
        '(platform,external_account_id,tenant_id,enabled,timezone,min_interval_seconds,daily_limit,windows,revision,updated_at) '
        'VALUES(:platform,:external_account_id,:tenant_id,:enabled,:zone,:interval,:limit,CAST(:windows AS jsonb),:rev,:at) '
        'ON CONFLICT(platform,external_account_id) DO UPDATE SET enabled=EXCLUDED.enabled,timezone=EXCLUDED.timezone,'
        'min_interval_seconds=EXCLUDED.min_interval_seconds,daily_limit=EXCLUDED.daily_limit,windows=EXCLUDED.windows,'
        'revision=EXCLUDED.revision,updated_at=EXCLUDED.updated_at'),{**row,'enabled':request.enabled,'zone':request.timezone,
        'interval':request.min_interval_seconds,'limit':request.daily_limit,'windows':core.canonical([w.model_dump() for w in request.windows]),
        'rev':request.expected_revision+1,'at':core.now_ms()})
    result=await schedule(db,row)
    await save_request(db,actor,request,fp,result)
    await core.audit(db,actor,'account_policy_saved',{'binding_id':str(row['id']),'tenant_id':row['tenant_id']},'POLICY_SAVED')
    return result


async def pause_account(db, actor, request):
    row=await binding(db,request.binding_id); await account_lock(db,row)
    fp,prior=await request_prior(db,actor,request)
    if prior: return prior
    p=await policy(db,row)
    if not p or p['revision']!=request.expected_revision: raise core.problem('version_conflict')
    await db.execute(core.text('UPDATE distribution_account_policies SET paused_reason=:reason,revision=revision+1,updated_at=:at '
        'WHERE platform=:platform AND external_account_id=:external_account_id'),
        {**row,'reason':'ACCOUNT_PAUSED' if request.action=='pause' else None,'at':core.now_ms()})
    result=await schedule(db,row); await save_request(db,actor,request,fp,result)
    await core.audit(db,actor,'account_'+request.action,{'binding_id':str(row['id']),'tenant_id':row['tenant_id']},request.action.upper())
    return result


async def set_restriction(db, actor, request):
    scope=request.model_dump(include={'module','tenant_id','scope_id'})
    await core.authorize_scope(db,actor,scope)
    row=await binding(db,request.binding_id,scope); await account_lock(db,row)
    fp,prior=await request_prior(db,actor,request)
    if prior: return prior
    p=await policy(db,row)
    if not p: raise core.problem('policy_required')
    if request.daily_limit>p['daily_limit'] or request.min_interval_seconds<p['min_interval_seconds']:
        raise core.problem('policy_cannot_expand',403)
    current=await core.one(db,'SELECT * FROM distribution_account_restrictions WHERE binding_id=:id',id=row['id'])
    if (current['revision'] if current else 0)!=request.expected_revision: raise core.problem('version_conflict')
    await db.execute(core.text('INSERT INTO distribution_account_restrictions VALUES(:id,:interval,:limit,:rev,:actor,:at) '
        'ON CONFLICT(binding_id) DO UPDATE SET min_interval_seconds=EXCLUDED.min_interval_seconds,'
        'daily_limit=EXCLUDED.daily_limit,revision=EXCLUDED.revision,updated_by=EXCLUDED.updated_by,updated_at=EXCLUDED.updated_at'),
        {'id':row['id'],'interval':request.min_interval_seconds,'limit':request.daily_limit,'rev':request.expected_revision+1,'actor':actor,'at':core.now_ms()})
    result=await schedule(db,row); await save_request(db,actor,request,fp,result)
    await core.audit(db,actor,'account_restricted',{**scope,'binding_id':str(row['id'])},'RESTRICTION_SAVED')
    return result


async def reserve(db, row, task):
    await db.execute(core.text('INSERT INTO distribution_publish_reservations '
        '(task_id,platform,external_account_id,tenant_id,reserved_at,policy_revision,state) '
        "VALUES(:task,:platform,:external_account_id,:tenant_id,:at,:revision,'held') ON CONFLICT(task_id) DO NOTHING"),
        {**row,'task':task['id'],'at':core.now_ms(),'revision':(await policy(db,row))['revision']})
    await core.audit(db,'system','publish_reserved',
        {k:task[k] for k in ('module','tenant_id','scope_id')},'ACCOUNT_RESERVED',task['id'])


async def receipt_effect(db, task, receipt):
    from app import distribution_execution as execution
    await execution.receipt_effect(db,task)
    row=await core.one(db,'SELECT * FROM distribution_bindings WHERE id=:id',id=task['binding_id'])
    if receipt.code in ('CAPTCHA','LOGIN_REQUIRED'): await risk_pause(db,row,receipt.code)
    if task['action']!='publish': return
    state=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=task['id'])
    r=await core.one(db,'SELECT * FROM distribution_publish_reservations WHERE task_id=:id',id=task['id'])
    if not r: return
    if receipt.code=='HUMAN_PUBLISHED':
        resolution=await core.one(db,'SELECT outcome FROM distribution_task_resolutions WHERE task_id=:id ORDER BY id DESC LIMIT 1',id=task['id'])
        if resolution and resolution['outcome']=='not-published':
            await db.execute(core.text("UPDATE distribution_tasks SET status='unknown',revoked=true WHERE id=:id"),{'id':task['id']})
            await db.execute(core.text("UPDATE distribution_publish_reservations SET state='held' WHERE task_id=:id"),{'id':task['id']})
            await db.execute(core.text("UPDATE distribution_tasks SET revoked=true,status=CASE WHEN status='queued' THEN 'canceled' ELSE 'unknown' END "
                "WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND binding_id IN "
                '(SELECT id FROM distribution_bindings WHERE platform=:platform AND external_account_id=:external_account_id) '
                "AND variant_id=:variant AND source_revision=:revision AND action='publish' "
                "AND id<>:id AND status IN ('queued','leased','running','awaiting-human')"),
                {**row,'variant':task['variant_id'],'revision':task['source_revision'],'id':task['id']})
            await risk_pause(db,row,'RESULT_CONFLICT')
        elif state['status']=='succeeded':
            await db.execute(core.text("UPDATE distribution_publish_reservations SET state='consumed',completed_at=:at WHERE task_id=:id"),
                {'at':core.now_ms(),'id':task['id']})
    elif state['status'] in ('failed','canceled') and receipt.code in ('ASSET_REQUIRED','ASSET_UNAVAILABLE','ASSET_CHANGED','INVALID_ASSET'):
        await db.execute(core.text("UPDATE distribution_publish_reservations SET state='released' WHERE task_id=:id"),{'id':task['id']})
    elif state['status'] in ('failed','canceled') and r['state']=='held':
        # A generic failure/late cancellation is not proof that nothing was posted.
        await db.execute(core.text("UPDATE distribution_tasks SET status='unknown',revoked=true WHERE id=:id"),{'id':task['id']})


async def risk_pause(db, row, reason):
    await db.execute(core.text('UPDATE distribution_account_policies SET paused_reason=:reason,revision=revision+1,updated_at=:at '
        'WHERE platform=:platform AND external_account_id=:external_account_id AND paused_reason IS DISTINCT FROM :reason'),
        {**row,'reason':reason,'at':core.now_ms()})
    await core.audit(db,'system','account_risk_paused',
        {k:row[k] for k in ('module','tenant_id','scope_id')},reason)


async def resolve(db, actor, request):
    scope=request.model_dump(include={'module','tenant_id','scope_id'})
    await core.authorize_scope(db,actor,scope)
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=request.task_id)
    if not task or any(task[k]!=scope[k] for k in scope) or task['advisor_user_id']!=actor: raise core.problem('scope_forbidden',403)
    await core.lock(db,'device:'+task['device_id']); await core.lock(db,'scope:'+core.canonical(scope))
    row=await core.one(db,'SELECT * FROM distribution_bindings WHERE id=:id',id=task['binding_id']); await account_lock(db,row)
    fp,prior=await request_prior(db,actor,request)
    if prior: return prior
    task=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=request.task_id)
    previous=await core.one(db,'SELECT * FROM distribution_task_resolutions WHERE task_id=:id ORDER BY id DESC LIMIT 1',id=task['id'])
    correction=previous and previous['outcome']=='not-published' and task['receipt'] and task['receipt'].get('code')=='HUMAN_PUBLISHED'
    if task['status']!='unknown' or task['action']!='publish' or previous and (not correction or request.outcome!='published'):
        raise core.problem('resolution_conflict')
    if request.outcome=='published' and not request.public_url: raise core.problem('publication_confirmation_required')
    if request.outcome=='not-published' and request.public_url: raise core.problem('invalid_public_url',422)
    url=core.public_url(task['platform'],request.public_url)
    await db.execute(core.text('INSERT INTO distribution_task_resolutions(task_id,outcome,actor_id,checked_at,public_url) VALUES(:id,:outcome,:actor,:at,:url)'),
        {'id':task['id'],'outcome':request.outcome,'actor':actor,'at':core.now_ms(),'url':url})
    await db.execute(core.text('UPDATE distribution_tasks SET status=:status,revoked=true WHERE id=:id'),
        {'id':task['id'],'status':'succeeded' if request.outcome=='published' else 'failed'})
    await db.execute(core.text('UPDATE distribution_publish_reservations SET state=:state,completed_at=:at WHERE task_id=:id'),
        {'id':task['id'],'state':'consumed' if request.outcome=='published' else 'released','at':core.now_ms()})
    result={'task_id':str(task['id']),'outcome':request.outcome,'checked_at':core.now_ms(),'public_url':url,'evidence':'advisor-reported'}
    await save_request(db,actor,request,fp,result)
    await core.audit(db,actor,'publish_result_checked',scope,request.outcome.upper().replace('-','_'),task['id'])
    return result
