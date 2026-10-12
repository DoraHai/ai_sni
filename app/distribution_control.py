"""Shared durable broker; native source adapters own business authorization."""
from __future__ import annotations

import hashlib
import importlib
import secrets
import time
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy import text
from app.distribution_contract import ApprovedContent, canonical, content_digest
from pydantic import ValidationError

TERMINAL = {'succeeded', 'failed', 'unknown', 'canceled'}
RECEIPT_CODES = {'ACCEPTED','DISPATCHED','PREFLIGHT_OK','HUMAN_REQUIRED','LOGIN_REQUIRED','CAPTCHA',
    'ASSET_REQUIRED','ASSET_UNAVAILABLE','ASSET_CHANGED','INVALID_ASSET','EXECUTION_RESULT_UNKNOWN',
    'AUTHORIZATION_CHANGED','AUTHORIZATION_OR_LEASE_INVALID','CRASH_RESULT_UNKNOWN',
    'HUMAN_PUBLISHED','HUMAN_UNKNOWN','HUMAN_FAILED'}


def now_ms(): return time.time_ns() // 1000000


def problem(code, status=409):
    return HTTPException(status, {'code':code, 'message':{
        'source_changed':'审核稿或权限已变化，请重新核对',
        'scope_forbidden':'当前账号不能操作该客户项目',
        'project_not_running':'请先启动当前项目的分发',
        'outcome_unknown':'执行结果待核查，不能重复派发',
        'version_conflict':'项目状态已变化，请重新读取',
        'binding_unavailable':'设备或平台账号绑定不可用',
        'distribution_unavailable':'分发接入尚未就绪',
    }.get(code,'分发请求未通过核验，请刷新后核对')}, headers={'Cache-Control':'no-store'})


async def rows(db, sql, **params):
    return (await db.execute(text(sql), params)).mappings().all()


async def one(db, sql, **params):
    result=await rows(db,sql,**params); return dict(result[0]) if result else None


async def lock(db, key):
    # Stable ordering is enforced by callers: device -> scope; no source writes.
    digest=int.from_bytes(hashlib.sha256(key.encode()).digest()[:8],'big',signed=True)
    await db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':digest})


async def audit(db, actor, action, target, result, task_id=None):
    await db.execute(text('INSERT INTO distribution_events(at,actor,action,task_id,target,result) '
        'VALUES(:at,:actor,:action,:task,CAST(:target AS jsonb),:result)'),
        {'at':now_ms(),'actor':str(actor),'action':action,'task':task_id,'target':canonical(target),'result':result})


def adapter(module):
    try: return importlib.import_module('app.seo_distribution_sources' if module=='seo' else 'app.geo.distribution_sources')
    except ImportError: raise problem('distribution_unavailable',503) from None


async def authorize_scope(db, actor_id, scope):
    if not actor_id: raise problem('scope_forbidden',403)
    await adapter(scope['module']).authorize_scope(db,actor_id,scope['tenant_id'],scope['scope_id'])


async def source(db, actor_id, scope, variant_id, platform):
    value=await adapter(scope['module']).load_source(db,actor_id,scope['tenant_id'],scope['scope_id'],variant_id,platform)
    if any(value.get(k)!=scope[k] for k in ('module','tenant_id','scope_id')) or value.get('variant_id')!=variant_id:
        raise problem('source_changed')
    try: content=ApprovedContent.model_validate(value['content']).model_dump()
    except ValidationError: raise problem('source_changed') from None
    value['content']=content
    if platform=='xiaohongshu-image' and not content['assets']: raise problem('source_changed')
    if content.get('version')!=value['source_revision']: raise problem('source_changed')
    return value,content_digest(content)


async def create_device(db, actor_id, label):
    device_id=str(uuid4()); credential=secrets.token_urlsafe(48)
    await db.execute(text('INSERT INTO distribution_devices(id,label,credential_hash,created_by,created_at) '
        'VALUES(:id,:label,:hash,:actor,:at)'),{'id':device_id,'label':label,
        'hash':hashlib.sha256(credential.encode()).hexdigest(),'actor':actor_id,'at':now_ms()})
    await audit(db,actor_id,'device_created',{'device_id':device_id},'CREATED')
    return {'id':device_id,'label':label,'credential':credential,'credential_once':True}


async def bind(db, actor_id, request):
    value=request.model_dump(); scope={k:value[k] for k in ('module','tenant_id','scope_id')}
    await lock(db,'device:'+value['device_id'])
    await lock(db,'account:'+value['platform']+':'+value['external_account_id'])
    device=await one(db,'SELECT id FROM distribution_devices WHERE id=:id AND active',id=value['device_id'])
    if not device: raise problem('binding_unavailable')
    table='seo_sites' if value['module']=='seo' else 'geo_projects'
    native_scope=await one(db,f'SELECT id FROM {table} WHERE id=:scope_id AND tenant_id=:tenant_id',**scope)
    if not native_scope: raise problem('binding_scope_mismatch',404)
    other=await one(db,'SELECT id FROM distribution_bindings WHERE platform=:platform '
        'AND external_account_id=:external_account_id AND tenant_id<>:tenant_id LIMIT 1',**value)
    if other: raise problem('account_customer_conflict')
    local=await one(db,'SELECT id FROM distribution_bindings WHERE device_id=:device_id AND account_id=:account_id '
        'AND active AND (tenant_id<>:tenant_id OR platform<>:platform OR external_account_id<>:external_account_id) LIMIT 1',**value)
    if local: raise problem('account_customer_conflict')
    previous=await one(db,'SELECT external_account_id FROM distribution_bindings WHERE device_id=:device_id AND account_id=:account_id '
        'AND module=:module AND tenant_id=:tenant_id AND scope_id=:scope_id AND platform=:platform',**value)
    if previous and previous['external_account_id']!=value['external_account_id']:
        raise problem('binding_identity_immutable')
    ident=str(uuid4())
    await db.execute(text('INSERT INTO distribution_bindings(id,tenant_id,module,scope_id,device_id,account_id,external_account_id,platform,created_by) '
        'VALUES(:id,:tenant_id,:module,:scope_id,:device_id,:account_id,:external_account_id,:platform,:actor) '
        'ON CONFLICT(device_id,account_id,module,tenant_id,scope_id,platform) DO UPDATE SET active=true '
        'RETURNING id'),{**value,'id':ident,'actor':actor_id})
    binding=await one(db,'SELECT id,tenant_id,module,scope_id,device_id,account_id,platform,active FROM distribution_bindings '
        'WHERE device_id=:device_id AND account_id=:account_id AND module=:module AND tenant_id=:tenant_id AND scope_id=:scope_id AND platform=:platform',**value)
    await audit(db,actor_id,'account_bound',{**scope,'binding_id':str(binding['id'])},'BOUND')
    return binding


async def control(db, actor_id, request):
    scope=request.model_dump(include={'module','tenant_id','scope_id'})
    await lock(db,'scope:'+canonical(scope))
    if request.action=='end':
        from app import distribution_execution as execution
        if await execution.installed(db):
            accounts=await rows(db,'SELECT DISTINCT b.platform,b.external_account_id FROM distribution_tasks t JOIN distribution_bindings b ON b.id=t.binding_id WHERE t.tenant_id=:tenant_id AND t.module=:module AND t.scope_id=:scope_id',**scope)
            for key in sorted(a['platform']+':'+a['external_account_id'] for a in accounts):await lock(db,'account:'+key)
    await authorize_scope(db,actor_id,scope)
    params=request.model_dump(mode='json'); fingerprint=hashlib.sha256(canonical(params).encode()).hexdigest()
    old=await one(db,'SELECT fingerprint,result FROM distribution_requests WHERE actor_id=:actor AND request_id=:id',actor=actor_id,id=request.request_id)
    if old:
        if old['fingerprint']!=fingerprint: raise problem('idempotency_conflict')
        return old['result']
    row=await one(db,'SELECT * FROM distribution_controls WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id',**scope)
    if row and row['owner_user_id']!=actor_id: raise problem('scope_forbidden',403)
    if (row['revision'] if row else 0)!=request.expected_revision: raise problem('version_conflict')
    transitions={'start':({'paused'},'running'),'pause':({'running'},'paused'),
        'resume':({'paused'},'running'),'end':({'running','paused'},'ended')}
    allowed,state=transitions[request.action]
    if (row['state'] if row else 'paused') not in allowed or not row and request.action!='start': raise problem('invalid_transition')
    revision=request.expected_revision+1
    await db.execute(text('INSERT INTO distribution_controls(tenant_id,module,scope_id,owner_user_id,state,revision) '
        'VALUES(:tenant_id,:module,:scope_id,:actor,:state,:revision) ON CONFLICT(tenant_id,module,scope_id) '
        'DO UPDATE SET state=EXCLUDED.state,revision=EXCLUDED.revision'),{**scope,'actor':actor_id,'state':state,'revision':revision})
    if state=='ended':
        await db.execute(text("UPDATE distribution_tasks SET revoked=true,status=CASE WHEN status='queued' THEN 'canceled' "
            "WHEN status IN ('leased','running','awaiting-human') THEN 'unknown' ELSE status END "
            'WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id'),scope)
        from app import distribution_execution as execution
        await execution.release_canceled(db,scope=scope)
    result={**scope,'state':state,'revision':revision,'owner_user_id':actor_id}
    await db.execute(text('INSERT INTO distribution_requests VALUES(:actor,:id,:fp,CAST(:result AS jsonb))'),
        {'actor':actor_id,'id':request.request_id,'fp':fingerprint,'result':canonical(result)})
    await audit(db,actor_id,'project_'+request.action,scope,state.upper())
    return result


async def enqueue(db, actor_id, request):
    scope=request.model_dump(include={'module','tenant_id','scope_id'})
    # Match exchange's lock order, then serialize the canonical account across devices.
    binding=await one(db,'SELECT * FROM distribution_bindings WHERE id=:id',id=request.binding_id)
    if not binding or any(binding[k]!=scope[k] for k in scope): raise problem('binding_unavailable')
    await lock(db,'device:'+binding['device_id']); await lock(db,'scope:'+canonical(scope))
    await lock(db,'account:'+binding['platform']+':'+binding['external_account_id'])
    binding=await one(db,'SELECT b.* FROM distribution_bindings b JOIN distribution_devices d ON d.id=b.device_id '
        'WHERE b.id=:id AND b.active AND d.active',id=request.binding_id)
    if not binding: raise problem('binding_unavailable')
    value,digest=await source(db,actor_id,scope,request.variant_id,binding['platform'])
    if (value['source_revision'],digest)!=(request.source_revision,request.expected_digest): raise problem('source_changed')
    if request.action=='publish' and not request.confirm_manual_publication: raise problem('publication_confirmation_required')
    project=await one(db,'SELECT * FROM distribution_controls WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id',**scope)
    if not project or project['state']!='running' or project['owner_user_id']!=actor_id: raise problem('project_not_running')
    fp=hashlib.sha256(canonical(request.model_dump(mode='json')).encode()).hexdigest()
    prior=await one(db,'SELECT * FROM distribution_tasks WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id '
        'AND advisor_user_id=:actor AND request_id=:req',**scope,actor=actor_id,req=request.request_id)
    if prior:
        if prior['request_fingerprint']!=fp: raise problem('idempotency_conflict')
        return task_view(prior)
    duplicate=await one(db,'SELECT t.status FROM distribution_tasks t JOIN distribution_bindings b ON b.id=t.binding_id '
        'WHERE t.tenant_id=:tenant_id AND t.module=:module AND t.scope_id=:scope_id AND t.variant_id=:variant '
        'AND t.source_revision=:revision AND t.action=:action AND b.platform=:platform AND b.external_account_id=:external '
        "AND t.status NOT IN ('failed','canceled') LIMIT 1",**scope,variant=request.variant_id,revision=value['source_revision'],
        action=request.action,platform=binding['platform'],external=binding['external_account_id'])
    if duplicate: raise problem('outcome_unknown' if duplicate['status']=='unknown' else 'duplicate_intent')
    capacity=await one(db,"SELECT count(*) AS total FROM distribution_tasks WHERE device_id=:id "
        "AND status NOT IN ('succeeded','failed','unknown','canceled')",id=binding['device_id'])
    if capacity['total']>=100: raise problem('device_capacity_reached')
    ident=str(uuid4()); expiry=now_ms()+request.expires_in_seconds*1000
    await db.execute(text('INSERT INTO distribution_tasks(id,tenant_id,module,scope_id,variant_id,binding_id,device_id,account_id,platform,'
        'advisor_user_id,source_revision,content,content_digest,action,grant_id,publication_grant_id,grant_expires_at,lease_id,lease_expires_at,created_at,request_id,request_fingerprint) '
        'VALUES(:id,:tenant_id,:module,:scope_id,:variant,:binding,:device,:account,:platform,:actor,:revision,CAST(:content AS jsonb),:digest,'
        ':action,:grant,:publication,:expiry,:lease,:expiry,:at,:req,:fp)'),{**scope,'id':ident,'variant':request.variant_id,'binding':request.binding_id,
        'device':binding['device_id'],'account':binding['account_id'],'platform':binding['platform'],'actor':actor_id,
        'revision':value['source_revision'],'content':canonical(value['content']),'digest':digest,'action':request.action,
        'grant':str(uuid4()),'publication':str(uuid4()) if request.action=='publish' else None,
        'expiry':expiry,'lease':str(uuid4()),'at':now_ms(),'req':request.request_id,'fp':fp})
    await audit(db,actor_id,'task_authorized',{**scope,'variant_id':request.variant_id,'binding_id':str(request.binding_id),'action':request.action},'AUTHORIZED',ident)
    return task_view(await one(db,'SELECT * FROM distribution_tasks WHERE id=:id',id=ident))


def task_view(row):
    return {k:str(row[k]) if k in {'id','binding_id'} else row[k] for k in (
        'id','tenant_id','module','scope_id','variant_id','binding_id','device_id','account_id','platform','source_revision',
        'action','status','created_at','grant_expires_at','revoked','receipt')}


def target(row):
    return {'customerId':str(row['tenant_id']),'projectId':row['module']+'-'+str(row['scope_id']),
        'deviceId':row['device_id'],'accountId':row['account_id'],'platform':row['platform']}


def public_url(platform, raw):
    if raw is None: return None
    import re
    parsed=urlsplit(raw)
    host='mp.weixin.qq.com' if platform=='wechat-article' else 'www.xiaohongshu.com'
    pattern=r'/s/[A-Za-z0-9_-]+' if platform=='wechat-article' else r'/explore/[a-f0-9]+'
    if parsed.scheme!='https' or parsed.netloc!=host or not re.fullmatch(pattern,parsed.path): raise problem('invalid_public_url',422)
    return urlunsplit(('https',host,parsed.path,'',''))


async def accept_receipt(db, device_id, receipt):
    row=await one(db,'SELECT * FROM distribution_tasks WHERE id::text=:id AND device_id=:device',id=receipt.taskId,device=device_id)
    if not row: raise problem('receipt_scope_mismatch',403)
    expected={**target(row),'contentVersion':row['source_revision'],'contentDigest':row['content_digest'],'leaseId':str(row['lease_id'])}
    value=receipt.model_dump(mode='json')
    if any(value[k]!=v for k,v in expected.items()) or receipt.code not in RECEIPT_CODES or receipt.at>now_ms()+300000:
        raise problem('receipt_scope_mismatch',403)
    url=public_url(row['platform'],receipt.publicUrl)
    if receipt.status=='succeeded':
        if row['action']=='publish':
            if (receipt.code,receipt.evidence)!=("HUMAN_PUBLISHED","human-reported") or not url: raise problem('invalid_publication_receipt',422)
        elif row['action']!='preflight' or receipt.code!='PREFLIGHT_OK' or receipt.evidence!='none' or url:
            raise problem('invalid_receipt',422)
    elif url is not None: raise problem('invalid_receipt',422)
    value['publicUrl']=url
    fp=hashlib.sha256(canonical(value).encode()).hexdigest()
    prior=await one(db,'SELECT receipt_id,fingerprint FROM distribution_receipts WHERE receipt_id=:receipt '
        'OR (task_id=:id AND lease_id=:lease AND sequence=:sequence)',receipt=receipt.receiptId,
        id=row['id'],lease=row['lease_id'],sequence=receipt.sequence)
    if prior and prior['fingerprint']!=fp: raise problem('receipt_conflict')
    if not prior:
        # Result adoption repeats business authorization before a terminal
        # receipt can remove this task from the dispatch-time freshness check.
        if row['status'] not in TERMINAL:
            scope={k:row[k] for k in ('module','tenant_id','scope_id')}
            current=await one(db,'SELECT c.state,c.owner_user_id,b.active FROM distribution_controls c '
                'JOIN distribution_bindings b ON b.id=:binding WHERE c.tenant_id=:tenant_id AND c.module=:module AND c.scope_id=:scope_id',
                **scope,binding=row['binding_id'])
            valid=not row['revoked'] and row['grant_expires_at']>now_ms() and row['lease_expires_at']>now_ms() and current 
            valid=valid and current['active'] and current['state']!='ended' and current['owner_user_id']==row['advisor_user_id']
            if valid:
                try:
                    native,digest=await source(db,row['advisor_user_id'],scope,row['variant_id'],row['platform'])
                    valid=native['source_revision']==row['source_revision'] and digest==row['content_digest']
                    if valid:
                        from app import distribution_execution as execution
                        valid=await execution.task_valid(db,row)
                    if valid and row['action']=='publish' and receipt.status=='succeeded':
                        from app import distribution_scheduling as scheduling
                        account=await one(db,'SELECT * FROM distribution_bindings WHERE id=:id',id=row['binding_id'])
                        valid=current['state']=='running' and (await scheduling.schedule(db,account,row['id']))['available']
                except HTTPException as exc:
                    if exc.status_code>=500: raise
                    valid=False
            if not valid:
                row['status']='unknown' if row['status']!='queued' else 'canceled'; row['revoked']=True
                await db.execute(text('UPDATE distribution_tasks SET status=:state,revoked=true WHERE id=:id'),{'state':row['status'],'id':row['id']})
                await audit(db,'system','task_fenced',scope,'AUTHORIZATION_OR_LEASE_INVALID',row['id'])
        await db.execute(text('INSERT INTO distribution_receipts VALUES(:receipt,:id,:lease,:sequence,:status,:at,:fp,CAST(:payload AS jsonb))'),
            {'receipt':receipt.receiptId,'id':row['id'],'lease':row['lease_id'],'sequence':receipt.sequence,
            'status':receipt.status,'at':receipt.at,'fp':fp,'payload':canonical(value)})
        rank={'queued':0,'leased':0,'running':1,'awaiting-human':2}
        forward=row['status'] not in TERMINAL and receipt.sequence>row['receipt_sequence'] and (
            receipt.status in TERMINAL or rank.get(receipt.status,-1)>=rank.get(row['status'],-1))
        if forward:
            await db.execute(text('UPDATE distribution_tasks SET status=:status,receipt_at=:at,receipt_sequence=:sequence,receipt=CAST(:payload AS jsonb) WHERE id=:id'),
                {'status':receipt.status,'at':receipt.at,'sequence':receipt.sequence,'payload':canonical(value),'id':row['id']})
        elif row['status'] in ('unknown','failed') and receipt.sequence>row['receipt_sequence'] and receipt.status=='succeeded' and receipt.evidence=='human-reported':
            # Preserve the reported publication fact without treating a late receipt
            # as proof that revoked/expired execution was authorized or verified.
            await db.execute(text('UPDATE distribution_tasks SET receipt_at=:at,receipt_sequence=:sequence,receipt=CAST(:payload AS jsonb) WHERE id=:id'),
                {'at':receipt.at,'sequence':receipt.sequence,'payload':canonical(value),'id':row['id']})
        await audit(db,'device:'+device_id,'receipt_recorded',
            {**expected,**{k:row[k] for k in ('module','tenant_id','scope_id')}},receipt.code,row['id'])
        from app import distribution_scheduling as scheduling
        await scheduling.receipt_effect(db,row,receipt)
    return {k:value[k] for k in ('receiptId','taskId','leaseId','sequence','status','at')}


async def exchange(db, credential, request):
    await lock(db,'device:'+request.deviceId)
    device=await one(db,'SELECT * FROM distribution_devices WHERE id=:id AND active',id=request.deviceId)
    if not device or not secrets.compare_digest(device['credential_hash'],hashlib.sha256(credential.encode()).hexdigest()):
        raise problem('device_unauthorized',401)
    pending_scopes=await rows(db,"SELECT DISTINCT tenant_id,module,scope_id FROM distribution_tasks WHERE device_id=:device "
        "AND (status NOT IN ('succeeded','failed','unknown','canceled') OR id::text=ANY(CAST(:ids AS text[])))",
        device=device['id'],ids=[r.taskId for r in request.receipts])
    for scope_key in sorted(canonical(dict(row)) for row in pending_scopes):
        await lock(db,'scope:'+scope_key)
    from app import distribution_scheduling as scheduling
    account_keys=await rows(db,'SELECT DISTINCT b.platform,b.external_account_id FROM distribution_tasks t '
        'JOIN distribution_bindings b ON b.id=t.binding_id WHERE t.device_id=:device '
        "AND (t.status NOT IN ('succeeded','failed','unknown','canceled') OR t.id::text=ANY(CAST(:ids AS text[])))",
        device=device['id'],ids=[r.taskId for r in request.receipts])
    for row in sorted(account_keys,key=lambda r:(r['platform'],r['external_account_id'])):
        await scheduling.account_lock(db,row)
    acks=[]
    for receipt in request.receipts: acks.append(await accept_receipt(db,device['id'],receipt))
    await db.execute(text('UPDATE distribution_devices SET last_seen_at=:at WHERE id=:id'),{'at':now_ms(),'id':device['id']})
    tasks=await rows(db,'SELECT t.*,b.active AS binding_active,b.external_account_id,c.state AS project_state FROM distribution_tasks t '
        'JOIN distribution_bindings b ON b.id=t.binding_id JOIN distribution_controls c ON '
        'c.tenant_id=t.tenant_id AND c.module=t.module AND c.scope_id=t.scope_id '
        "WHERE t.device_id=:device AND t.status NOT IN ('succeeded','failed','unknown','canceled') ORDER BY t.created_at,t.id LIMIT 100",
        device=device['id'])
    envelope={'contractVersion':1,'deviceAuthorized':True,'binding':[],'paused':False,'pausedTaskIds':[],'grants':[],'tasks':[],'receiptAcks':acks}
    seen=set()
    for item in tasks:
        row=dict(item); scope={k:row[k] for k in ('module','tenant_id','scope_id')}
        # Re-read after scope lock: a concurrent pause/end must fence this response.
        project=await one(db,'SELECT state,owner_user_id FROM distribution_controls WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id',**scope)
        valid=not row['revoked'] and row['binding_active'] and row['grant_expires_at']>now_ms() and row['lease_expires_at']>now_ms() and project['state']!='ended'
        if valid:
            try:
                current,digest=await source(db,row['advisor_user_id'],scope,row['variant_id'],row['platform'])
                valid=current['source_revision']==row['source_revision'] and digest==row['content_digest'] and project['owner_user_id']==row['advisor_user_id']
                if valid:
                    from app import distribution_execution as execution
                    valid=await execution.task_valid(db,row)
            except HTTPException as exc:
                if exc.status_code>=500: raise
                valid=False
        if not valid:
            state='canceled' if row['status']=='queued' else 'unknown'
            await db.execute(text('UPDATE distribution_tasks SET revoked=true,status=:state WHERE id=:id'),{'state':state,'id':row['id']})
            from app import distribution_execution as execution
            await execution.receipt_effect(db,row)
            await audit(db,'system','task_fenced',scope,'AUTHORIZATION_OR_LEASE_INVALID',row['id']); continue
        account={**row,'id':row['binding_id']}
        admission=await scheduling.schedule(db,account,row['id']) if row['action']=='publish' else None
        if row['status']=='queued' and admission and (project['state']!='running' or not admission['available']):
            continue
        sizes={name:len(envelope[name]) for name in ('binding','grants','pausedTaskIds','tasks')}
        tgt=target(row); key=canonical(tgt)
        if key not in seen: seen.add(key); envelope['binding'].append(tgt)
        grant={**tgt,'purpose':'task','id':str(row['grant_id']),'advisorId':str(row['advisor_user_id']),
            'contentVersion':row['source_revision'],'contentDigest':row['content_digest'],'actions':[row['action']],
            'expiresAt':row['grant_expires_at'],'revoked':False}
        envelope['grants'].append(grant)
        if row['publication_grant_id']:
            envelope['grants'].append({**grant,'id':str(row['publication_grant_id']),'purpose':'publication','actions':['publish']})
        if project['state']=='paused' or admission and not admission['available']: envelope['pausedTaskIds'].append(str(row['id']))
        if row['receipt_sequence']==0:
            # ACCEPTED is emitted only after the executor persists task+outbox.
            # Keep grants current without retransmitting the complete article.
            envelope['tasks'].append({**tgt,'contractVersion':1,'id':str(row['id']),'idempotencyKey':str(row['id']),
                'grantId':str(row['grant_id']),'publicationGrantId':str(row['publication_grant_id']) if row['publication_grant_id'] else None,
                'content':row['content'],'contentDigest':row['content_digest'],'action':row['action'],
                'leaseId':str(row['lease_id']),'leaseExpiresAt':row['lease_expires_at']})
        if len(canonical(envelope).encode('utf-8'))>900000:
            # Leave complete unleased tasks queued for a later exchange; the
            # executor rejects responses above 1 MiB. Never split a snapshot.
            for name,length in sizes.items(): del envelope[name][length:]
            break
        if row['status']=='queued' and project['state']=='running':
            if row['action']=='publish': await scheduling.reserve(db,account,row)
            await db.execute(text("UPDATE distribution_tasks SET status='leased' WHERE id=:id"),{'id':row['id']})
            await audit(db,'system','task_dispatched',scope,'LEASED',row['id'])
    return envelope
