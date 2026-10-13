"""Persistent planning queue. Never creates execution grants or submits to a platform.

The native approved-source polling contract is available now; discovery of completed
unreviewed drafts requires a separate native, paginated metadata contract.
"""
from uuid import uuid4
import re
from fastapi import HTTPException
from app import distribution_control as core, distribution_scheduling as scheduling

# Server-owned ceilings: admin can disable these, never promote an unverified path.
# Adding a channel does not extend the frozen device-v1 Platform enum.
CATALOG = {
    'wechat-article': ('article', '公众号文章', 'manual'),
    'xiaohongshu-image': ('image-text', '小红书图文', 'manual'),
    'website-article': ('article', '官网文章', 'not-integrated'),
}


async def capability(db, platform, content_type, binding=None):
    entry = CATALOG.get(platform)
    permission = await core.one(db, 'SELECT * FROM distribution_channel_permissions '
        'WHERE platform=:platform AND content_type=:kind', platform=platform, kind=content_type)
    supported = bool(entry and entry[0] == content_type)
    enabled = bool(permission and permission['enabled'])
    reason = ('NOT_INTEGRATED' if not supported or entry[2] == 'not-integrated' else
              'NOT_AUTHORIZED' if not enabled else 'REAL_CHANNEL_NOT_ACCEPTED')
    if binding and (not binding['active'] or not binding['device_active']):
        reason = 'BINDING_UNAVAILABLE'
    return {'platform': platform, 'content_type': content_type,
        'label': entry[1] if entry else platform,
        'mode': entry[2] if supported else 'not-integrated',
        'enabled': enabled, 'revision': permission['revision'] if permission else 0,
        'executable': False, 'automated_publish': False, 'real_channel_verified': False,
        'automatic_steps': ['队列登记', '当前审核与版本复核', '账号节奏检查'] if supported and entry[2] == 'manual' else [],
        'manual_steps': ['平台登录与验证码处理', '填写正文与上传配图', '正式发布', '公开作品核验'] if supported and entry[2] == 'manual' else [],
        'reason': reason}


async def catalog(db):
    return [await capability(db, platform, value[0]) for platform, value in CATALOG.items()]


async def set_permission(db, actor, req):
    if req.platform not in CATALOG or CATALOG[req.platform][0] != req.content_type:
        raise core.problem('channel_unsupported', 422)
    await core.lock(db, 'channel:'+req.platform+':'+req.content_type)
    fp, prior = await scheduling.request_prior(db, actor, req)
    if prior: return prior
    current = await capability(db, req.platform, req.content_type)
    if current['revision'] != req.expected_revision: raise core.problem('version_conflict')
    if req.enabled and current['mode'] == 'not-integrated': raise core.problem('channel_unsupported', 422)
    await db.execute(core.text('INSERT INTO distribution_channel_permissions VALUES(:platform,:kind,:enabled,:revision,:actor,:at) '
        'ON CONFLICT(platform,content_type) DO UPDATE SET enabled=EXCLUDED.enabled,revision=EXCLUDED.revision,'
        'updated_by=EXCLUDED.updated_by,updated_at=EXCLUDED.updated_at'),
        {'platform':req.platform,'kind':req.content_type,'enabled':req.enabled,'revision':req.expected_revision+1,'actor':actor,'at':core.now_ms()})
    result = await capability(db, req.platform, req.content_type)
    await scheduling.save_request(db, actor, req, fp, result)
    await core.audit(db, actor, 'channel_permission', {'platform':req.platform,'content_type':req.content_type}, 'ENABLED' if req.enabled else 'DISABLED')
    return result


async def set_channel(db, actor, req):
    scope = req.model_dump(include={'module','tenant_id','scope_id'})
    await core.lock(db, 'scope:'+core.canonical(scope))
    b = await scheduling.binding(db, req.binding_id, scope)
    await scheduling.account_lock(db,b)
    await core.authorize_scope(db, actor, scope)
    if CATALOG[b['platform']][0] != req.content_type: raise core.problem('channel_unsupported', 422)
    project = await core.one(db, 'SELECT * FROM distribution_controls WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id', **scope)
    if project and (project['owner_user_id'] != actor or project['state'] == 'ended'): raise core.problem('scope_forbidden', 403)
    fp, prior = await scheduling.request_prior(db, actor, req)
    if prior: return prior
    params = {**scope, 'binding':req.binding_id}
    old = await core.one(db, 'SELECT * FROM distribution_project_channels WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND binding_id=:binding', **params)
    if old and old['owner_user_id'] != actor: raise core.problem('scope_forbidden', 403)
    if (old['revision'] if old else 0) != req.expected_revision: raise core.problem('version_conflict')
    if req.enabled:
        duplicate=await core.one(db,'SELECT c.binding_id FROM distribution_project_channels c JOIN distribution_bindings b ON b.id=c.binding_id '
            'JOIN distribution_devices d ON d.id=b.device_id '
            'WHERE c.tenant_id=:tenant_id AND c.module=:module AND c.scope_id=:scope_id AND c.enabled AND b.active AND d.active AND b.platform=:platform '
            'AND b.external_account_id=:external AND c.binding_id<>:binding LIMIT 1',
            **params,platform=b['platform'],external=b['external_account_id'])
        if duplicate: raise core.problem('duplicate_channel_account')
    await db.execute(core.text('INSERT INTO distribution_project_channels VALUES(:tenant_id,:module,:scope_id,:binding,:kind,:enabled,:actor,:revision) '
        'ON CONFLICT(tenant_id,module,scope_id,binding_id) DO UPDATE SET enabled=EXCLUDED.enabled,revision=EXCLUDED.revision'),
        {**params,'kind':req.content_type,'enabled':req.enabled,'actor':actor,'revision':req.expected_revision+1})
    result = {'binding_id':str(req.binding_id), 'enabled':req.enabled, 'revision':req.expected_revision+1}
    await scheduling.save_request(db, actor, req, fp, result)
    await core.audit(db, actor, 'project_channel', {**scope,'binding_id':str(req.binding_id)}, 'ENABLED' if req.enabled else 'DISABLED')
    return result


async def channels(db, actor, scope):
    await core.authorize_scope(db, actor, scope)
    records = await core.rows(db, 'SELECT b.*,d.active AS device_active,c.enabled AS selected,c.revision AS selection_revision '
        'FROM distribution_bindings b JOIN distribution_devices d ON d.id=b.device_id '
        'LEFT JOIN distribution_project_channels c ON c.binding_id=b.id AND c.tenant_id=b.tenant_id AND c.module=b.module AND c.scope_id=b.scope_id '
        'WHERE b.tenant_id=:tenant_id AND b.module=:module AND b.scope_id=:scope_id ORDER BY b.id LIMIT 100', **scope)
    return [{'binding_id':str(b['id']), 'account_id':b['account_id'], 'selected':bool(b['selected']),
             'revision':b['selection_revision'] or 0,
             'capability':await capability(db,b['platform'],CATALOG[b['platform']][0],b)} for b in records]


async def scan_channel(db, config):
    scope = {k:config[k] for k in ('module','tenant_id','scope_id')}
    actor = config['owner_user_id']; binding_id = config['binding_id']
    # Re-read after locking: stale worker snapshots cannot resurrect a revoked configuration.
    await core.lock(db, 'scope:'+core.canonical(scope))
    c = await core.one(db, 'SELECT * FROM distribution_project_channels WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND binding_id=:binding', **scope,binding=binding_id)
    b = await scheduling.binding(db,binding_id,scope)
    await scheduling.account_lock(db,b)
    # Native GEO authorization may lock tenant rows. Account precedes native
    # locks, matching enqueue/exchange and avoiding cross-project lock inversion.
    await core.authorize_scope(db, actor, scope)
    p = await core.one(db, 'SELECT * FROM distribution_controls WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id', **scope)
    cap = await capability(db,b['platform'],c['content_type'],b)
    prior = await core.one(db,'SELECT next_cursor,recheck_cursor FROM distribution_queue_scans WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND binding_id=:binding',**scope,binding=binding_id)
    recheck_cursor=prior['recheck_cursor'] if prior else None
    if not c['enabled']:
        existing=await core.rows(db,"SELECT * FROM distribution_queue WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND binding_id=:binding AND state<>'superseded' "
            'AND (CAST(:cursor AS uuid) IS NULL OR id>CAST(:cursor AS uuid)) ORDER BY id LIMIT 50',**scope,binding=binding_id,cursor=str(recheck_cursor) if recheck_cursor else None)
        for q in existing:
            await update_item(db,actor,q,'paused','CHANNEL_DISABLED',None)
        await save_scan(db,c,'CHANNEL_DISABLED',None,'unavailable',existing[-1]['id'] if len(existing)==50 else None)
        return None,'unavailable'
    # Discover while paused: queueing does not confer execution authority.
    native = core.adapter(scope['module'])
    intake = getattr(native,'list_intake_candidates',None)
    cursor = prior['next_cursor'] if prior else None
    if intake:
        page = await intake(db,actor,scope['tenant_id'],scope['scope_id'],b['platform'],after_variant_id=cursor,limit=50)
        candidates,next_cursor = validate_page(page,cursor)
        discovery = 'completed-draft-polling'
    else:
        candidates = await native.list_sources(db,actor,scope['tenant_id'],scope['scope_id'],b['platform'])
        if not isinstance(candidates,list) or len(candidates)>50: raise core.problem('distribution_unavailable',503)
        candidates = [{'variant_id':v['variant_id'],'source_revision':v['source_revision'],
            'draft_version':v['source_revision'],'readiness':'ready','reason':'APPROVED_SOURCE'} for v in candidates]
        next_cursor,discovery = None,'approved-source-polling'
    if not isinstance(candidates,list) or len(candidates)>50: raise core.problem('distribution_unavailable',503)
    for candidate in candidates:
        digest = None
        if candidate['readiness']=='ready':
            value,digest = await core.source(db,actor,scope,candidate['variant_id'],b['platform'])
            if value['source_revision'] != candidate['source_revision']: raise core.problem('source_changed')
        previous=await core.one(db,'SELECT * FROM distribution_queue WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND platform=:platform AND external_account_id=:external AND variant_id=:variant AND draft_version=:draft',
            **scope,platform=b['platform'],external=b['external_account_id'],variant=candidate['variant_id'],draft=candidate['draft_version'])
        ident=previous['id'] if previous else uuid4()
        initial_state='queued' if candidate['readiness']=='ready' else candidate['readiness']
        await db.execute(core.text('INSERT INTO distribution_queue(id,tenant_id,module,scope_id,platform,external_account_id,binding_id,variant_id,draft_version,source_revision,content_digest,state,reason,created_at,checked_at) '
            "VALUES(:id,:tenant_id,:module,:scope_id,:platform,:external,:binding,:variant,:draft,:revision,:digest,:state,:reason,:at,:at) "
            'ON CONFLICT(tenant_id,module,scope_id,platform,external_account_id,variant_id,draft_version) DO UPDATE SET '
            'source_revision=EXCLUDED.source_revision,content_digest=EXCLUDED.content_digest,binding_id=EXCLUDED.binding_id'),
            {**scope,'id':ident,'platform':b['platform'],'external':b['external_account_id'],'binding':binding_id,
             'variant':candidate['variant_id'],'draft':candidate['draft_version'],'revision':candidate['source_revision'],
             'digest':digest,'state':initial_state,
             'reason':candidate['reason'],'at':core.now_ms()})
        if not previous:
            await core.audit(db,actor,'queue_intake',{**scope,'binding_id':str(binding_id),'variant_id':candidate['variant_id']},candidate['reason'],ident)
        replaced=await core.rows(db,"SELECT * FROM distribution_queue "
            'WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND platform=:platform AND external_account_id=:external '
            "AND variant_id=:variant AND draft_version<>:draft AND state<>'superseded'",
            **scope,platform=b['platform'],external=b['external_account_id'],variant=candidate['variant_id'],draft=candidate['draft_version'])
        for old in replaced: await update_item(db,actor,old,'superseded','SOURCE_CHANGED',None)
    queue = await core.rows(db, 'SELECT * FROM distribution_queue WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND platform=:platform AND external_account_id=:external '
        "AND state<>'superseded' AND (CAST(:cursor AS uuid) IS NULL OR id>CAST(:cursor AS uuid)) ORDER BY id LIMIT 50", **scope,platform=b['platform'],external=b['external_account_id'],cursor=str(recheck_cursor) if recheck_cursor else None)
    sched = await scheduling.schedule(db,b)
    for q in queue:
        inspect=getattr(native,'load_intake_candidate',None)
        meta=None
        if inspect:
            meta=await inspect(db,actor,scope['tenant_id'],scope['scope_id'],q['variant_id'],b['platform'])
            if meta is None:
                await update_item(db,actor,q,'superseded','SOURCE_CHANGED',None);continue
        else:
            meta=next((v for v in candidates if v['variant_id']==q['variant_id'] and v['draft_version']==q['draft_version']),None)
        if meta:
            validate_page({'items':[meta],'next_cursor':None},None)
            if meta['variant_id']!=q['variant_id']: raise core.problem('distribution_unavailable',503)
            if meta['draft_version']!=q['draft_version']:
                await update_item(db,actor,q,'superseded','SOURCE_CHANGED',None);continue
            if meta['readiness']!='ready':
                await db.execute(core.text('UPDATE distribution_queue SET source_revision=NULL,content_digest=NULL WHERE id=:id'),{'id':q['id']})
                state,reason=meta['readiness'],meta['reason']
                if not p or p['state']!='running' or p['owner_user_id']!=actor: state,reason='paused','PROJECT_PAUSED'
                await update_item(db,actor,q,state,reason,None);continue
            verified,verified_digest=await core.source(db,actor,scope,q['variant_id'],b['platform'])
            if verified['source_revision']!=meta['source_revision']: raise core.problem('source_changed')
            # Approval changes may change source_revision; stable draft identity
            # still represents the same queue item and must not produce a retry.
            await db.execute(core.text('UPDATE distribution_queue SET source_revision=:revision,content_digest=:digest WHERE id=:id'),
                {'revision':verified['source_revision'],'digest':verified_digest,'id':q['id']})
            q=dict(q,source_revision=verified['source_revision'],content_digest=verified_digest)
        if q['source_revision'] is None:
            if not p or p['state']!='running' or p['owner_user_id']!=actor: await update_item(db,actor,q,'paused','PROJECT_PAUSED',None)
            continue
        state,reason,next_at = 'awaiting-adaptation',cap['reason'],None
        try:
            value,digest = await core.source(db,actor,scope,q['variant_id'],b['platform'])
            if value['source_revision']!=q['source_revision'] or digest!=q['content_digest']:
                state,reason = 'superseded','SOURCE_CHANGED'
        except HTTPException as exc:
            code=exc.detail.get('code') if isinstance(exc.detail,dict) else None
            if code in ('seo_distribution_source_not_found','seo_distribution_source_stale','geo_distribution_source_not_found','geo_distribution_variant_stale'):
                state,reason='superseded','SOURCE_CHANGED'
            elif exc.status_code in (404,409,422): state,reason = 'awaiting-review','SOURCE_REVIEW_REQUIRED'
            else: raise
        if state not in ('superseded','awaiting-review'):
            if not c['enabled'] or not p or p['state']!='running' or p['owner_user_id']!=actor:
                state,reason = 'paused','PROJECT_PAUSED' if c['enabled'] else 'CHANNEL_DISABLED'
            elif not cap['enabled']: state,reason = 'awaiting-authorization','NOT_AUTHORIZED'
            elif sched['reason'] in ('OUTCOME_UNKNOWN','ACCOUNT_BUSY','ACCOUNT_PAUSED','CAPTCHA','LOGIN_REQUIRED','RESULT_CONFLICT'):
                state,reason = 'awaiting-intervention',sched['reason']
            elif not sched['available']:
                state,reason,next_at = 'scheduled',sched['reason'],sched['next_allowed_at']
        # Never enqueue device tasks here: no real channel path has passed acceptance.
        await update_item(db,actor,q,state,reason,next_at)
    await save_scan(db,c,'SCANNED',next_cursor,discovery,queue[-1]['id'] if len(queue)==50 else None)
    return next_cursor,discovery


async def update_item(db,actor,q,state,reason,next_at):
    if (q['state'],q['reason'])!=(state,reason):
        await core.audit(db,actor,'queue_'+state,{**{k:q[k] for k in ('module','tenant_id','scope_id','variant_id')},
            'binding_id':str(q['binding_id']),'action':q['state']},reason,q['id'])
    await db.execute(core.text('UPDATE distribution_queue SET state=:state,reason=:reason,next_allowed_at=:next,checked_at=:at WHERE id=:id'),
        {'state':state,'reason':reason,'next':next_at,'at':core.now_ms(),'id':q['id']})


def validate_page(page, cursor):
    if not isinstance(page,dict) or set(page)!={'items','next_cursor'} or not isinstance(page['items'],list) or len(page['items'])>50:
        raise core.problem('distribution_unavailable',503)
    previous = cursor or 0
    for v in page['items']:
        if (not isinstance(v,dict) or set(v)!={'variant_id','draft_version','source_revision','readiness','reason'}
            or type(v['variant_id']) is not int or v['variant_id']<=previous
            or not isinstance(v['draft_version'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',v['draft_version'])
            or v['readiness'] not in ('ready','awaiting-review','awaiting-adaptation')
            or not isinstance(v['reason'],str) or not re.fullmatch(r'[a-zA-Z0-9_]{1,64}',v['reason'])
            or (v['readiness']=='ready' and (not isinstance(v['source_revision'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',v['source_revision'])))
            or (v['readiness']!='ready' and v['source_revision'] is not None)):
            raise core.problem('distribution_unavailable',503)
        previous=v['variant_id']
    next_cursor=page['next_cursor']
    if next_cursor is not None and (type(next_cursor) is not int or not page['items'] or next_cursor!=previous):
        raise core.problem('distribution_unavailable',503)
    return page['items'],next_cursor


async def run_once(sessions,*,module=None):
    """Restart-safe background entrance; one transaction per configured channel.

    Failed native reads roll back only that scan; a separate persisted scan failure
    tells the advisor why the last queue projection cannot be trusted.
    """
    async with sessions() as db:
        configs = [dict(c) for c in await core.rows(db,'SELECT c.* FROM distribution_project_channels c LEFT JOIN distribution_queue_scans s '
            'USING(tenant_id,module,scope_id,binding_id) WHERE (CAST(:module AS varchar) IS NULL OR c.module=:module) ORDER BY COALESCE(s.checked_at,0),c.binding_id LIMIT 50',module=module)]
    for c in configs:
        reason = 'SCANNED'
        next_cursor,discovery = None,'unavailable'
        try:
            async with sessions() as db:
                next_cursor,discovery = await scan_channel(db,c)
                await db.commit()
            continue
        except HTTPException as exc:
            reason = 'AUTHORIZATION_REVOKED' if exc.status_code==403 else 'BINDING_UNAVAILABLE' if isinstance(exc.detail,dict) and exc.detail.get('code')=='binding_unavailable' else 'SOURCE_UNAVAILABLE'
        except Exception:
            reason = 'SCAN_UNAVAILABLE'
        async with sessions() as db:
            await core.lock(db,'scope:'+core.canonical({k:c[k] for k in ('module','tenant_id','scope_id')}))
            await save_scan(db,c,reason,next_cursor,discovery)
            await db.commit()


async def save_scan(db,c,reason,cursor,discovery,recheck_cursor=None):
    previous=await core.one(db,'SELECT * FROM distribution_queue_scans WHERE tenant_id=:tenant_id AND module=:module AND scope_id=:scope_id AND binding_id=:binding',
        **{k:c[k] for k in ('module','tenant_id','scope_id')},binding=c['binding_id'])
    if not previous or previous['reason']!=reason:
        await core.audit(db,c['owner_user_id'],'queue_scan',{**{k:c[k] for k in ('module','tenant_id','scope_id')},'binding_id':str(c['binding_id'])},reason)
    await db.execute(core.text('INSERT INTO distribution_queue_scans VALUES(:tenant_id,:module,:scope_id,:binding_id,:state,:reason,:at,:cursor,:discovery,:recheck) '
        'ON CONFLICT(tenant_id,module,scope_id,binding_id) DO UPDATE SET state=EXCLUDED.state,reason=EXCLUDED.reason,checked_at=EXCLUDED.checked_at,'
        "next_cursor=CASE WHEN EXCLUDED.state='checked' THEN EXCLUDED.next_cursor ELSE distribution_queue_scans.next_cursor END,discovery=EXCLUDED.discovery,"
        "recheck_cursor=CASE WHEN EXCLUDED.reason IN ('SCANNED','CHANNEL_DISABLED') THEN EXCLUDED.recheck_cursor ELSE distribution_queue_scans.recheck_cursor END"),
        {**c,'state':'checked' if reason in ('SCANNED','CHANNEL_DISABLED') else 'unavailable','reason':reason,'at':core.now_ms(),'cursor':cursor,'discovery':discovery,'recheck':recheck_cursor})
