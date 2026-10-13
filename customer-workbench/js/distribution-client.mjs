const base='/api/distribution/v1';
const handoffResolution='/api/distribution/handoff/v1/advisor/resolution';
const nordPreparationPath='/api/distribution/nord/v1/preparation';
const handoffRetry='/api/distribution/handoff/v1/advisor/retry';
const positive=n=>Number.isSafeInteger(n)&&n>0;
const uuid=s=>typeof s==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(s);
const id=s=>typeof s==='string'&&/^[a-zA-Z0-9_-]{1,100}$/.test(s);
const digest=s=>typeof s==='string'&&/^[a-f0-9]{64}$/.test(s);
const fault=(code,status)=>Object.assign(Error(code),{code,status});
const fail=()=>{throw fault('CONTRACT_MISMATCH');};
const modules=['seo','geo'],platforms=['wechat-article','xiaohongshu-image'];
const states=['queued','leased','running','awaiting-human','succeeded','failed','unknown','canceled'];
const scheduleReasons=['READY','POLICY_REQUIRED','POLICY_DISABLED','ACCOUNT_PAUSED','ACCOUNT_BUSY','OUTCOME_UNKNOWN',
  'CAPTCHA','LOGIN_REQUIRED','RESULT_CONFLICT','DAILY_LIMIT','MIN_INTERVAL','OUTSIDE_WINDOW'];
const nonnegative=n=>Number.isSafeInteger(n)&&n>=0;
export function validateDistributionPlans(value,scope){
  match(value,scope);
  if(value.automated_publish!==false||!Array.isArray(value.items)||value.items.length>100||!Array.isArray(value.requests)||value.requests.length>20)fail();
  for(const p of value.items)if(!uuid(p.id)||!uuid(p.queue_id)||!uuid(p.binding_id)||!id(p.draft_version)||!id(p.source_revision)||!nonnegative(p.planned_at)||!nonnegative(p.checked_at)||!['ai','rules'].includes(p.basis)||!['planned','blocked','superseded'].includes(p.state)||typeof p.reason!=='string'||!/^[A-Z_]{1,64}$/.test(p.reason))fail();
  for(const r of value.requests)if(!uuid(r.id)||!['running','failed','succeeded','stale','unknown'].includes(r.state)||!positive(r.attempts)||r.attempts>3||!nonnegative(r.updated_at)||!(r.retry_at===null||nonnegative(r.retry_at))||typeof r.reason!=='string'||!/^[A-Z_]{1,64}$/.test(r.reason))fail();
  return structuredClone(value);
}
export function validateChannelCapability(c){
  if(!c||!id(c.platform)||!['article','image-text'].includes(c.content_type)||typeof c.label!=='string'||
    !['manual','not-integrated'].includes(c.mode)||typeof c.enabled!=='boolean'||!nonnegative(c.revision)||
    c.executable!==false||c.automated_publish!==false||c.real_channel_verified!==false||
    !['NOT_INTEGRATED','NOT_AUTHORIZED','REAL_CHANNEL_NOT_ACCEPTED','BINDING_UNAVAILABLE'].includes(c.reason)||
    !Array.isArray(c.automatic_steps)||!Array.isArray(c.manual_steps)||[...c.automatic_steps,...c.manual_steps].some(s=>typeof s!=='string'||s.length>120))fail();
  return structuredClone(c);
}
export function validateDistributionQueue(value,scope){
  match(value,scope);
  if(value.completed_draft_events_connected!==false||!Array.isArray(value.items)||value.items.length>100||!Array.isArray(value.scans)||value.scans.length>100)fail();
  for(const q of value.items)if(!uuid(q.id)||!uuid(q.binding_id)||!positive(q.variant_id)||!id(q.draft_version)||
    !(q.source_revision===null||id(q.source_revision))||!platforms.includes(q.platform)||
    !['queued','awaiting-review','awaiting-adaptation','awaiting-authorization','paused','scheduled','awaiting-intervention','superseded'].includes(q.state)||
    typeof q.reason!=='string'||!/^[A-Za-z0-9_]{1,64}$/.test(q.reason)||!nonnegative(q.created_at)||!nonnegative(q.checked_at)||
    !(q.next_allowed_at===null||nonnegative(q.next_allowed_at)))fail();
  for(const s of value.scans)if(!uuid(s.binding_id)||!['checked','unavailable'].includes(s.state)||!nonnegative(s.checked_at)||
    !['approved-source-polling','completed-draft-polling','unavailable'].includes(s.discovery)||typeof s.reason!=='string'||!/^[A-Za-z0-9_]{1,64}$/.test(s.reason))fail();
  return structuredClone(value);
}
function limits(v){return v&&positive(v.daily_limit)&&v.daily_limit<=1000&&nonnegative(v.min_interval_seconds)&&v.min_interval_seconds<=86400;}
export function validateDistributionSchedule(v){
  if(!v||!uuid(v.binding_id)||!nonnegative(v.as_of)||!scheduleReasons.includes(v.reason)||typeof v.available!=='boolean'||
    !nonnegative(v.system_used_today)||!(v.system_remaining===null||nonnegative(v.system_remaining))||v.platform_remaining!==null||
    v.platform_quota_state!=='unverified'||!(v.next_allowed_at===null||nonnegative(v.next_allowed_at))||
    !(v.reservation_task_id===null||uuid(v.reservation_task_id))||
    !(v.effective_daily_limit===null||positive(v.effective_daily_limit)&&v.effective_daily_limit<=1000)||
    !(v.effective_interval_seconds===null||nonnegative(v.effective_interval_seconds)&&v.effective_interval_seconds<=86400))fail();
  if(v.policy){const p=v.policy;if(!limits(p)||!positive(p.revision)||typeof p.enabled!=='boolean'||typeof p.timezone!=='string'||p.timezone.length>60||
    !(p.paused_reason===null||['ACCOUNT_PAUSED','CAPTCHA','LOGIN_REQUIRED','RESULT_CONFLICT'].includes(p.paused_reason))||
    !Array.isArray(p.windows)||!p.windows.length||p.windows.length>8||p.windows.some((w,i)=>!nonnegative(w.start)||!positive(w.end)||
      w.start>=w.end||w.end>1440||i>0&&p.windows[i-1].end>w.start))fail();}
  else if(v.available||v.reason!=='POLICY_REQUIRED')fail();
  if(v.restriction&&(!limits(v.restriction)||!positive(v.restriction.revision)))fail();
  return structuredClone(v);
}
export function distributionScope(scope){
  if(!scope||!modules.includes(scope.module)||!positive(scope.tenant_id)||!positive(scope.scope_id))fail();
  return {module:scope.module,tenant_id:scope.tenant_id,scope_id:scope.scope_id};
}
function match(value,scope){if(value?.schema!==1||Object.keys(scope).some(k=>value[k]!==scope[k]))fail();}
export async function distributionContentDigest(content){
  const bytes=new TextEncoder().encode(JSON.stringify([content.version,content.title,content.body,
    content.assets.map(a=>[a.id,a.sha256,a.mediaType,a.bytes])]));
  return [...new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');
}
export function validateDistributionScope(value,scope){
  match(value,scope);const p=value.project;
  if(!p||Object.keys(scope).some(k=>p[k]!==scope[k])||!['running','paused','ended'].includes(p.state)||
    !Number.isSafeInteger(p.revision)||p.revision<0||!(p.owner_user_id===null||positive(p.owner_user_id))||
    !Array.isArray(value.bindings)||value.bindings.length>100||new Set(value.bindings.map(b=>b.id)).size!==value.bindings.length||
    !value.capabilities||value.capabilities.automated_publish!==false||value.capabilities.human_handoff!==true||
    value.capabilities.real_channel_verified!==false)fail();
  for(const b of value.bindings)if(!uuid(b.id)||!id(b.device_id)||!id(b.account_id)||!platforms.includes(b.platform)||b.active!==true||
    typeof b.device_label!=='string'||!(b.last_seen_at===null||Number.isSafeInteger(b.last_seen_at)&&b.last_seen_at>=0))fail();
  return structuredClone(value);
}
export function validateDistributionTasks(value,scope){
  match(value,scope);if(!Array.isArray(value.items)||value.items.length>100||new Set(value.items.map(t=>t.id)).size!==value.items.length)fail();
  for(const t of value.items){
    if(Object.keys(scope).some(k=>t[k]!==scope[k])||!uuid(t.id)||!uuid(t.binding_id)||!positive(t.variant_id)||
      !id(t.device_id)||!id(t.account_id)||!platforms.includes(t.platform)||!id(t.source_revision)||
      !['preflight','handoff','publish'].includes(t.action)||!states.includes(t.status)||
      typeof t.revoked!=='boolean'||!Number.isSafeInteger(t.created_at)||!Number.isSafeInteger(t.grant_expires_at))fail();
    if(t.receipt){const r=t.receipt;
      if(r.contractVersion!==1||r.taskId!==t.id||r.customerId!==String(t.tenant_id)||r.projectId!==t.module+'-'+t.scope_id||
        r.deviceId!==t.device_id||r.accountId!==t.account_id||r.platform!==t.platform||r.contentVersion!==t.source_revision||!digest(r.contentDigest)||
        !uuid(r.receiptId)||!positive(r.sequence)||!uuid(r.leaseId)||!states.includes(r.status)||!Number.isSafeInteger(r.at)||!['none','simulation','human-reported'].includes(r.evidence)||
        !(r.publicUrl===null||safeDistributionUrl(t.platform,r.publicUrl)))fail();
    }
    if(t.schedule&&validateDistributionSchedule(t.schedule).binding_id!==t.binding_id)fail();
    if(t.resolution&&(!['published','not-published'].includes(t.resolution.outcome)||!nonnegative(t.resolution.checked_at)||
      !(t.resolution.public_url===null||safeDistributionUrl(t.platform,t.resolution.public_url))))fail();
    if(t.publication)validateDistributionPublication(t.publication,t.id,t.platform,scope.module);
    if(t.content_digest!==undefined&&!digest(t.content_digest))fail();
    if(t.handoff_attempt!==undefined&&t.handoff_attempt!==null&&(![1,2,3].includes(t.handoff_attempt)||t.action!=='handoff'))fail();
    if(t.handoff_investigable!==undefined&&(typeof t.handoff_investigable!=='boolean'||t.action!=='handoff'||t.handoff_investigable&&!['unknown','leased','running','awaiting-human'].includes(t.status)))fail();
    if(t.handoff_resolution&&(t.action!=='handoff'||t.handoff_resolution.outcome!=='not-published'||!nonnegative(t.handoff_resolution.checked_at)))fail();
  }
  return structuredClone(value);
}
export function validateDistributionPublication(value,taskId,platform,module){
  if(!value||!Object.hasOwn(value,'check')||!Object.hasOwn(value,'writeback'))fail();
  const c=value.check,w=value.writeback;
  if(c&&(!uuid(c.id)||c.task_id!==taskId||!positive(c.actor_id)||!['machine','human'].includes(c.mode)||
    !safeDistributionUrl(platform,c.public_url)||!nonnegative(c.reported_at)||!nonnegative(c.checked_at)||
    !['verified','needs-human'].includes(c.status)||!['ADVISOR_CONFIRMED_PUBLIC_CONTENT','PUBLIC_TEXT_AND_ACCOUNT_MATCHED',
      'PAGE_UNAVAILABLE','CHANNEL_REQUIRES_HUMAN','PAGE_LAYOUT_UNVERIFIED','CONTENT_MISMATCH','ACCOUNT_UNVERIFIED','ASSETS_REQUIRE_HUMAN'].includes(c.code)||
    (c.status==='verified'?c.verification!==({human:'human-verified',machine:'machine-verified'})[c.mode]:c.verification!==null)))fail();
  if(w&&(!uuid(w.event_id)||!['pending','written','blocked'].includes(w.state)||!nonnegative(w.attempts)||!nonnegative(w.updated_at)||
    typeof w.code!=='string'||!/^[A-Za-z0-9_]{1,64}$/.test(w.code)))fail();
  if(w?.result){const r=w.result;if(r.module!==module||!positive(r.publication_id)||typeof r.idempotent!=='boolean'||
    !['human-verified','machine-verified'].includes(r.verification)||typeof r.monitor_state!=='string'||!/^[A-Za-z0-9_-]{1,40}$/.test(r.monitor_state)||
    r.placement_id!==undefined&&!positive(r.placement_id))fail();}
  if(w&&((w.state==='written')!==Boolean(w.result)))fail();
  if(value.monitor){if(w?.state!=='written')fail();validateDistributionMonitor(value.monitor,module,w.result.publication_id);}
  return structuredClone(value);
}
export function validateDistributionMonitor(value,module,publicationId){
  const fields=['module','publication_id','basis','state','evidence_source','observed_at','next_check_at','evidence_id','code'];
  const timestamp=n=>n===null||nonnegative(n)&&n<=4102444800000;
  if(!value||Object.keys(value).length!==fields.length||fields.some(k=>!Object.hasOwn(value,k))||
    value.module!==module||value.publication_id!==publicationId||!positive(publicationId)||
    value.basis!==({seo:'page-capture',geo:'public-text'})[module]||
    !['not_queued','pending','running','captured','observed','failed','unreachable','mismatch','version_changed','unavailable'].includes(value.state)||
    !['auto','manual','none'].includes(value.evidence_source)||!timestamp(value.observed_at)||!timestamp(value.next_check_at)||
    !(value.evidence_id===null||positive(value.evidence_id))||typeof value.code!=='string'||!/^[A-Za-z0-9_]{1,64}$/.test(value.code)||
    value.state==='captured'&&module!=='seo'||value.state==='observed'&&module!=='geo'||
    ['captured','observed'].includes(value.state)&&value.observed_at===null)fail();
  return structuredClone(value);
}
export function safeDistributionUrl(platform,raw){
  try{const u=new URL(raw),host=platform==='wechat-article'?'mp.weixin.qq.com':'www.xiaohongshu.com';
    return u.protocol==='https:'&&u.hostname===host&&!u.username&&!u.password&&!u.port&&!u.search&&!u.hash&&
      (platform==='wechat-article'?/^\/s\/[\w-]+$/:/^\/explore\/[a-f0-9]+$/).test(u.pathname);
  }catch{return false;}
}
export function validateDistributionSource(value,scope,variant,platform){
  match(value,scope);const c=value.content;
  if(value.variant_id!==variant||value.platform!==platform||!id(value.source_revision)||!digest(value.content_digest)||
    !c||c.version!==value.source_revision||typeof c.title!=='string'||c.title.length>200||typeof c.body!=='string'||!c.body||
    c.body.length>100000||!Array.isArray(c.assets)||c.assets.length>20||c.assets.some(a=>!id(a.id)||!digest(a.sha256)||
      !['image/png','image/jpeg'].includes(a.mediaType)||!positive(a.bytes)||a.bytes>20000000))fail();
  return structuredClone(value);
}
export function createDistributionClient({session,fetchImpl=fetch,subscribeSession=()=>()=>{}}){
  let epoch=0;const controllers=new Set(),listeners=new Set();
  const key=()=>JSON.stringify([session.token,session.user?.id,session.user?.tenant_id,session.authRevision,session.user?.permissions,session.modules]);
  let context=key();
  const invalidate=()=>{epoch++;for(const c of controllers)c.abort();controllers.clear();for(const fn of listeners)fn();};
  const sync=()=>{const next=key();if(next!==context){context=next;invalidate();}};
  const stop=subscribeSession(sync);
  async function request(path,{method='GET',body,binary=false}={}){
    sync();const stamp=epoch,k=key();
    if(!session.token||!positive(session.user?.id)||/\s/.test(session.token))throw fault('NOT_AUTHENTICATED',401);
    const u=new URL(path,'https://same-origin.invalid');
    if(u.origin!=='https://same-origin.invalid'||/[\\#\s]/.test(path)||u.pathname!==path.split('?')[0]||
      !['/scope','/source','/sources','/tasks','/events','/control','/devices','/bindings','/account-policies','/account-schedules',
        '/account-policy','/account-pause','/account-restriction','/task-resolution','/admin-events','/publication-check','/publication-writeback','/publication-source','/publication-monitor','/project-channels','/queue','/plans','/platform-directory','/execution-progress','/channel-catalog','/project-channel','/channel-permission','/handoff-permission'].some(p=>u.pathname===base+p)&&![handoffResolution,handoffRetry,nordPreparationPath].includes(u.pathname)&&
      !new RegExp('^'+base+'/(devices|bindings)/[a-f0-9-]{36}/revoke$').test(u.pathname)&&
      !new RegExp('^'+base+'/publication-assets/[a-f0-9-]{36}/[a-zA-Z0-9_-]{1,100}$').test(u.pathname)||
      !['GET','POST'].includes(method)||method==='GET'&&!['/scope','/source','/sources','/tasks','/events','/devices','/bindings','/account-policies','/account-schedules','/admin-events','/publication-source','/publication-monitor','/project-channels','/queue','/plans','/platform-directory','/execution-progress','/channel-catalog'].some(p=>u.pathname===base+p)&&u.pathname!==nordPreparationPath&&!u.pathname.startsWith(base+'/publication-assets/')||
      method==='POST'&&!['/control','/tasks','/devices','/bindings','/account-policy','/account-pause','/account-restriction','/task-resolution','/publication-check','/publication-writeback','/project-channel','/channel-permission','/handoff-permission'].some(p=>u.pathname===base+p)&&![handoffResolution,handoffRetry,nordPreparationPath].includes(u.pathname)&&!u.pathname.endsWith('/revoke'))throw fault('ROUTE_DENIED');
    const allowedQuery=u.pathname===nordPreparationPath?['device_id','external_account_id']:['/publication-source','/publication-monitor'].some(p=>u.pathname===base+p)?['module','tenant_id','scope_id','task_id']:u.pathname===base+'/source'?['module','tenant_id','scope_id','variant_id','platform']:
      u.pathname===base+'/sources'?['module','tenant_id','scope_id','platform']:['module','tenant_id','scope_id'];
    for(const name of u.searchParams.keys())if(!allowedQuery.includes(name)||u.searchParams.getAll(name).length!==1)throw fault('ROUTE_DENIED');
    const adminRoute=u.pathname===nordPreparationPath||['/devices','/bindings','/account-policies','/account-policy','/account-pause','/admin-events','/channel-catalog','/channel-permission'].some(p=>u.pathname===base+p)||u.pathname.endsWith('/revoke');
    if(adminRoute){if(session.user.tenant_id!==null||!['settings.accounts','settings.customers'].every(k=>session.user.permissions?.[k]==='edit'))throw fault('PERMISSION_DENIED',403);}
    else {const module=body?.module??u.searchParams.get('module'),tenant=body?.tenant_id??Number(u.searchParams.get('tenant_id'));
      const permitted=module==='seo'?['seo.site','seo.content'].every(k=>session.user.permissions?.[k]==='edit'):
        module==='geo'&&['geo.assets','geo.content'].every(k=>session.user.permissions?.[k]==='edit');
      if(!permitted||session.user.tenant_id!==null&&session.user.tenant_id!==tenant)throw fault('PERMISSION_DENIED',403);}
    const c=new AbortController();controllers.add(c);let sent=false;
    try{
      sent=true;const response=await fetchImpl(path,{method,headers:{Authorization:`Bearer ${session.token}`,Accept:'application/json',
        ...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined,credentials:'omit',cache:'no-store',
        redirect:'error',signal:AbortSignal.any([c.signal,AbortSignal.timeout(20000)])});
      sync();if(stamp!==epoch||k!==key())throw fault(method==='POST'?'WRITE_OUTCOME_UNKNOWN':'CONTEXT_CHANGED');
      if(response.status===401||response.status===403){invalidate();if(response.status===401)session.logout();throw fault('PERMISSION_DENIED',response.status);}
      if(!response.ok)throw fault(method==='POST'&&response.status>=500?'WRITE_OUTCOME_UNKNOWN':
        [404,405,501,503].includes(response.status)?'NOT_INTEGRATED':response.status===409?'CONFLICT':'REQUEST_FAILED',response.status);
      let value;
      if(binary){
        const mediaType=response.headers.get('content-type')?.split(';')[0];
        if(!['image/png','image/jpeg'].includes(mediaType))fail();
        const reader=response.body?.getReader();if(!reader)fail();const chunks=[];let size=0;
        try{for(;;){const next=await reader.read();if(next.done)break;size+=next.value.byteLength;if(size>20000000)fail();chunks.push(next.value);}}
        finally{await reader.cancel().catch(()=>{});}
        value={bytes:await new Blob(chunks).arrayBuffer(),mediaType};
      }else value=await response.json();
      sync();if(stamp!==epoch||k!==key())throw fault(method==='POST'?'WRITE_OUTCOME_UNKNOWN':'CONTEXT_CHANGED');
      return value;
    }catch(error){
      if(method==='POST'&&sent&&!['PERMISSION_DENIED','CONFLICT','REQUEST_FAILED'].includes(error.code))throw fault('WRITE_OUTCOME_UNKNOWN',error.status);
      throw error.code?error:fault('READ_FAILED');
    }finally{controllers.delete(c);}
  }
  const params=(scope,extra={})=>new URLSearchParams({...distributionScope(scope),...extra});
  return {
    async channelCatalog(){const v=await request(base+'/channel-catalog');if(v.schema!==1||!Array.isArray(v.items)||v.items.length>100)fail();
      return {...v,items:v.items.map(validateChannelCapability)};},
    async saveChannelPermission(value){if(!id(value.platform)||!['article','image-text'].includes(value.content_type)||typeof value.enabled!=='boolean'||!nonnegative(value.expected_revision)||!uuid(value.request_id))fail();
      const v=await request(base+'/channel-permission',{method:'POST',body:value});
      try{if(v.schema!==1||validateChannelCapability(v.capability).platform!==value.platform||v.capability.content_type!==value.content_type||v.capability.revision!==value.expected_revision+1||v.capability.enabled!==value.enabled)fail();}
      catch{throw fault('WRITE_OUTCOME_UNKNOWN');}return v;},
    async projectChannels(scope){const v=await request(base+'/project-channels?'+params(scope));match(v,scope);
      if(!Array.isArray(v.items)||v.items.length>100||v.items.some(c=>!uuid(c.binding_id)||!id(c.account_id)||typeof c.selected!=='boolean'||!nonnegative(c.revision)))fail();
      for(const c of v.items)validateChannelCapability(c.capability);return structuredClone(v);},
    async selectChannel(scope,c){if(!uuid(c.binding_id)||!['article','image-text'].includes(c.content_type)||typeof c.enabled!=='boolean'||!nonnegative(c.expected_revision)||!uuid(c.request_id))fail();
      const v=await request(base+'/project-channel',{method:'POST',body:{...c,...distributionScope(scope)}});
      if(v.schema!==1||v.selection?.binding_id!==c.binding_id||v.selection.enabled!==c.enabled||v.selection.revision!==c.expected_revision+1)throw fault('WRITE_OUTCOME_UNKNOWN');return v;},
    async queue(scope){return validateDistributionQueue(await request(base+'/queue?'+params(scope)),scope);},
    async plans(scope){return validateDistributionPlans(await request(base+'/plans?'+params(scope)),scope);},
    async platformDirectory(scope){const v=await request(base+'/platform-directory?'+params(scope));match(v,scope);
      const allowed=['wechat-official','wechat-channels','xiaohongshu','zhihu','bilibili','douyin','weibo','linkedin','toutiao','baijiahao','kuaishou','website','news-source','backlink'];
      if(!Array.isArray(v.items)||v.items.length>14||new Set(v.items.map(p=>p.platform_id)).size!==v.items.length)fail();
      for(const p of v.items)if(['news-source','backlink'].includes(p.platform_id)&&(p.execution_type!=='server-api'||p.configured!==false||p.adapter_verified!==false||p.native_intake!==false||p.v1_platform!==null))fail();
      for(const p of v.items)if(!allowed.includes(p.platform_id)||typeof p.label!=='string'||!Array.isArray(p.content_types)||p.content_types.some(t=>!['article','image-text','image-note','post','video','answer'].includes(t))||!Array.isArray(p.missing)||p.missing.some(t=>typeof t!=='string'||t.length>100)||!['manual-handoff-candidate','not-integrated','reserved'].includes(p.status)||p.automatic_publish!==false||p.real_channel_verified!==false||typeof p.native_intake!=='boolean'||!(p.v1_platform===null||platforms.includes(p.v1_platform)))fail();return structuredClone(v);},
    async executionProgress(scope){const v=await request(base+'/execution-progress?'+params(scope));match(v,scope);
      if(v.automatic_publish!==false||!['items','permissions','waits'].every(k=>Array.isArray(v[k])&&v[k].length<=100))fail();
      for(const p of v.permissions)if(!uuid(p.binding_id)||typeof p.enabled!=='boolean'||!positive(p.revision)||!['preflight','handoff'].includes(p.stage))fail();
      for(const i of v.items)if(!['id','queue_id','plan_id','binding_id','task_id'].every(k=>uuid(i[k]))||!id(i.draft_version)||!id(i.source_revision)||!digest(i.content_digest)||!digest(i.capability_digest)||!['preflight','handoff'].includes(i.stage)||!states.includes(i.status)||typeof i.revoked!=='boolean')fail();
      for(const w of v.waits)if(!uuid(w.queue_id)||!nonnegative(w.checked_at)||typeof w.reason!=='string'||!/^[A-Z_]{1,64}$/.test(w.reason))fail();return structuredClone(v);},
    async configureHandoff(scope,v){if(!uuid(v.binding_id)||typeof v.enabled!=='boolean'||!['preflight','handoff'].includes(v.stage)||v.confirm_reviewed_handoff!==true||!nonnegative(v.expected_revision)||!uuid(v.request_id))fail();
      const r=await request(base+'/handoff-permission',{method:'POST',body:{...v,...distributionScope(scope)}});
      if(r.schema!==1||r.permission?.binding_id!==v.binding_id||r.permission.enabled!==v.enabled||r.permission.stage!==v.stage||r.permission.revision!==v.expected_revision+1)throw fault('WRITE_OUTCOME_UNKNOWN');return r;},
    async publicationMonitor(scope,task){
      if(!uuid(task.id)||task.publication?.writeback?.state!=='written')fail();
      validateDistributionPublication(task.publication,task.id,task.platform,scope.module);
      const value=await request(base+'/publication-monitor?'+params(scope,{task_id:task.id}));
      match(value,scope);if(value.task_id!==task.id||!nonnegative(value.as_of))fail();
      validateDistributionMonitor(value.monitor,scope.module,task.publication.writeback.result.publication_id);
      return structuredClone(value);
    },
    async publicationSource(scope,task){
      if(!uuid(task.id))fail();sync();const stamp=epoch,k=key();const value=await request(base+'/publication-source?'+params(scope,{task_id:task.id}));
      validateDistributionSource(value,scope,task.variant_id,task.platform);
      if(value.task_id!==task.id||value.source_revision!==task.source_revision||!id(value.external_account_id)||
        await distributionContentDigest(value.content)!==value.content_digest)fail();
      sync();if(stamp!==epoch||k!==key())throw fault('CONTEXT_CHANGED');return value;
    },
    async publicationAsset(scope,task,asset){
      if(!uuid(task.id)||!id(asset.id)||!digest(asset.sha256)||!positive(asset.bytes)||asset.bytes>20000000)fail();
      sync();const stamp=epoch,k=key();
      const value=await request(base+'/publication-assets/'+task.id+'/'+asset.id+'?'+params(scope),{binary:true});
      const actual=[...new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256',value.bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');
      if(value.mediaType!==asset.mediaType||value.bytes.byteLength!==asset.bytes||actual!==asset.sha256)fail();
      sync();if(stamp!==epoch||k!==key())throw fault('CONTEXT_CHANGED');return new Blob([value.bytes],{type:value.mediaType});
    },
    async checkPublication(scope,{task,mode,preview,confirmPublic=false,confirmAccount=false,confirmContent=false,requestId}){
      const url=task.resolution?.outcome==='published'?task.resolution.public_url:task.receipt?.publicUrl;
      if(!uuid(task.id)||task.action!=='publish'||task.status!=='succeeded'||!safeDistributionUrl(task.platform,url)||!uuid(requestId)||
        !['machine','human'].includes(mode)||mode==='human'&&![confirmPublic,confirmAccount,confirmContent].every(v=>v===true))fail();
      if(mode==='human'){
        if(!preview||preview.task_id!==task.id||preview.source_revision!==task.source_revision)fail();
        validateDistributionSource(preview,scope,task.variant_id,task.platform);
        sync();const stamp=epoch,k=key();
        if(await distributionContentDigest(preview.content)!==preview.content_digest)fail();
        sync();if(stamp!==epoch||k!==key())throw fault('CONTEXT_CHANGED');
      }
      const value=await request(base+'/publication-check',{method:'POST',body:{...distributionScope(scope),task_id:task.id,
        mode,expected_public_url:url,confirm_public_access:confirmPublic,confirm_target_account:confirmAccount,
        confirm_approved_content:confirmContent,request_id:requestId}});
      try{match(value,scope);if(value.task_id!==task.id)fail();validateDistributionPublication(value.publication,task.id,task.platform,scope.module);}
      catch{throw fault('WRITE_OUTCOME_UNKNOWN');}return value;
    },
    async retryPublicationWriteback(scope,task,requestId){
      if(!uuid(task.id)||!uuid(task.publication?.writeback?.event_id)||!uuid(requestId))fail();
      const value=await request(base+'/publication-writeback',{method:'POST',body:{...distributionScope(scope),task_id:task.id,
        event_id:task.publication.writeback.event_id,request_id:requestId}});
      try{match(value,scope);if(value.task_id!==task.id)fail();validateDistributionPublication(value.publication,task.id,task.platform,scope.module);}
      catch{throw fault('WRITE_OUTCOME_UNKNOWN');}return value;
    },
    async scope(scope){return validateDistributionScope(await request(base+'/scope?'+params(scope)),scope);},
    async tasks(scope){return validateDistributionTasks(await request(base+'/tasks?'+params(scope)),scope);},
    async events(scope){const data=await request(base+'/events?'+params(scope));match(data,scope);
      if(!Array.isArray(data.items)||data.items.length>100||data.items.some(e=>!positive(e.id)||!Number.isSafeInteger(e.at)||
        typeof e.action!=='string'||typeof e.result!=='string'||e.task_id!==null&&!uuid(e.task_id)))fail();return structuredClone(data);},
    async sources(scope,platform){if(!platforms.includes(platform))fail();const data=await request(base+'/sources?'+params(scope,{platform}));match(data,scope);
      if(data.platform!==platform||!Array.isArray(data.items)||data.items.length>50||new Set(data.items.map(v=>v.variant_id)).size!==data.items.length||
        data.items.some(v=>!positive(v.variant_id)||!id(v.source_revision)||v.platform!==platform||typeof v.title!=='string'))fail();return structuredClone(data);},
    async preview(scope,variant,platform){if(!positive(variant)||!platforms.includes(platform))fail();
      sync();const stamp=epoch,k=key();
      const value=validateDistributionSource(await request(base+'/source?'+params(scope,{variant_id:variant,platform})),scope,variant,platform);
      if(await distributionContentDigest(value.content)!==value.content_digest)fail();
      sync();if(stamp!==epoch||k!==key())throw fault('CONTEXT_CHANGED');return value;},
    async control(scope,action,revision,requestId){if(!['start','pause','resume','end'].includes(action)||!Number.isSafeInteger(revision)||revision<0||!uuid(requestId))fail();
      const data=await request(base+'/control',{method:'POST',body:{...distributionScope(scope),action,expected_revision:revision,request_id:requestId}});
      if(data.schema!==1||!data.project||Object.keys(scope).some(k=>data.project[k]!==scope[k])||data.project.revision!==revision+1||
        data.project.owner_user_id!==session.user.id||data.project.state!==({start:'running',resume:'running',pause:'paused',end:'ended'})[action])throw fault('WRITE_OUTCOME_UNKNOWN');return data;},
    async enqueue(scope,{bindingId,preview,action,confirmManual=false,requestId}){
      sync();const stamp=epoch,k=key();
      validateDistributionSource(preview,scope,preview.variant_id,preview.platform);
      if(await distributionContentDigest(preview.content)!==preview.content_digest)fail();
      sync();if(stamp!==epoch||k!==key())throw fault('CONTEXT_CHANGED');
      if(!uuid(bindingId)||!uuid(requestId)||!['preflight','handoff','publish'].includes(action)||action==='publish'&&confirmManual!==true)fail();
      const value=await request(base+'/tasks',{method:'POST',body:{...distributionScope(scope),binding_id:bindingId,variant_id:preview.variant_id,
        source_revision:preview.source_revision,expected_digest:preview.content_digest,action,confirm_reviewed_content:true,
        confirm_manual_publication:confirmManual,request_id:requestId}});
      try{validateDistributionTasks({schema:1,...scope,items:[value.task]},scope);
        if(value.task.variant_id!==preview.variant_id||value.task.binding_id!==bindingId||value.task.platform!==preview.platform||
          value.task.source_revision!==preview.source_revision||value.task.action!==action)fail();}catch{throw fault('WRITE_OUTCOME_UNKNOWN');}return value;
    },
    async devices(){const value=await request(base+'/devices');if(value.schema!==1||!Array.isArray(value.items)||value.items.length>100||
      value.items.some(d=>!uuid(d.id)||typeof d.label!=='string'||typeof d.active!=='boolean'||'credential' in d||'credential_hash' in d))fail();return value;},
    async createDevice(){throw fault('DEVICE_PAIRING_REQUIRED');},
    async nordPreparation(identity,{confirm=false}={}){
      if(!uuid(identity.device_id)||!/^gh_[a-f0-9]{12}$/.test(identity.external_account_id))fail();
      const path='/api/distribution/nord/v1/preparation';
      const v=await request(confirm?path:path+'?'+new URLSearchParams({device_id:identity.device_id,external_account_id:identity.external_account_id}),confirm?{method:'POST',body:{device_id:identity.device_id,external_account_id:identity.external_account_id,confirm_account_ownership:true,confirm_current_advisor:true}}:{});
      if(v.schema!==1||v.module!=='seo'||v.tenant_id!==1||v.scope_id!==1||v.external_account_id!==identity.external_account_id||!positive(v.advisor_user_id)||typeof v.advisor_assigned!=='boolean'||v.connection_id!==null&&!positive(v.connection_id)||v.automatic_publish!==false||v.publication_verified!==false)throw fault(confirm?'WRITE_OUTCOME_UNKNOWN':'CONTRACT_MISMATCH');
      return v;
    },
    async bindings(){const value=await request(base+'/bindings');if(value.schema!==1||!Array.isArray(value.items)||value.items.length>100||
      value.items.some(b=>!uuid(b.id)||!modules.includes(b.module)||!positive(b.tenant_id)||!positive(b.scope_id)||!uuid(b.device_id)||
        !id(b.account_id)||!id(b.external_account_id)||!platforms.includes(b.platform)||typeof b.active!=='boolean'||
        typeof b.device_active!=='boolean'||typeof b.device_label!=='string'))fail();return structuredClone(value);},
    async schedules(scope){const v=await request(base+'/account-schedules?'+params(scope));match(v,scope);
      if(!Array.isArray(v.items)||v.items.length>100||new Set(v.items.map(s=>s.binding_id)).size!==v.items.length)fail();
      return {...v,items:v.items.map(validateDistributionSchedule)};},
    async accountPolicies(){const v=await request(base+'/account-policies');if(v.schema!==1||!Array.isArray(v.items)||v.items.length>100||
      new Set(v.items.map(s=>s.binding_id)).size!==v.items.length)fail();return {...v,items:v.items.map(validateDistributionSchedule)};},
    async adminEvents(){const v=await request(base+'/admin-events');if(v.schema!==1||!Array.isArray(v.items)||v.items.length>100||
      v.items.some(e=>!positive(e.id)||!nonnegative(e.at)||typeof e.actor!=='string'||typeof e.action!=='string'||typeof e.result!=='string'||
        !(e.task_id===null||uuid(e.task_id))||!e.target||Object.keys(e.target).some(k=>!['module','tenant_id','scope_id','binding_id','device_id','variant_id','action','platform','content_type'].includes(k))))fail();return structuredClone(v);},
    async savePolicy(value){if(!uuid(value.binding_id)||!uuid(value.request_id)||!nonnegative(value.expected_revision)||!limits(value))fail();
      const v=await request(base+'/account-policy',{method:'POST',body:value});
      try{if(v.schema!==1||validateDistributionSchedule(v.schedule).binding_id!==value.binding_id||v.schedule.policy?.revision!==value.expected_revision+1)fail();}
      catch{throw fault('WRITE_OUTCOME_UNKNOWN');}return v;},
    async pauseAccount(bindingId,revision,action,requestId){if(!uuid(bindingId)||!positive(revision)||!['pause','resume'].includes(action)||!uuid(requestId))fail();
      const v=await request(base+'/account-pause',{method:'POST',body:{binding_id:bindingId,expected_revision:revision,action,request_id:requestId}});
      try{if(v.schema!==1||validateDistributionSchedule(v.schedule).binding_id!==bindingId||v.schedule.policy?.revision!==revision+1)fail();}
      catch{throw fault('WRITE_OUTCOME_UNKNOWN');}return v;},
    async restrictAccount(scope,value){distributionScope(scope);if(!uuid(value.binding_id)||!uuid(value.request_id)||!nonnegative(value.expected_revision)||!limits(value))fail();
      const v=await request(base+'/account-restriction',{method:'POST',body:{...value,...scope}});
      try{if(v.schema!==1||validateDistributionSchedule(v.schedule).binding_id!==value.binding_id||v.schedule.restriction?.revision!==value.expected_revision+1)fail();}
      catch{throw fault('WRITE_OUTCOME_UNKNOWN');}return v;},
    async resolveHandoff(scope,value){distributionScope(scope);if(!uuid(value.task_id)||!uuid(value.request_id)||!id(value.source_revision)||!digest(value.content_digest)||value.outcome!=='not-published'||value.confirm_platform_checked!==true||value.confirm_executor_stopped!==true||value.confirm_no_publication!==true)fail();
      const v=await request(handoffResolution,{method:'POST',body:{...value,...distributionScope(scope)}});
      if(v.handoffVersion!==1||v.task_id!==value.task_id||v.outcome!=='not-published'||v.result!=='HANDOFF_NOT_PUBLISHED'||v.publicationVerified!==false||v.evidence!=='advisor-reported'||!nonnegative(v.checked_at))throw fault('WRITE_OUTCOME_UNKNOWN');return v;},
    async retryHandoff(scope,value){distributionScope(scope);if(!uuid(value.task_id)||!uuid(value.request_id)||!id(value.source_revision)||!digest(value.content_digest)||value.confirm_executor_stopped!==true||value.confirm_no_publication!==true)fail();
      const v=await request(handoffRetry,{method:'POST',body:{...value,...distributionScope(scope)}});
      if(v.handoffVersion!==1||!uuid(v.task_id)||v.task_id===value.task_id||v.previous_task_id!==value.task_id||![2,3].includes(v.attempt)||v.result!=='HANDOFF_REDISPATCHED'||v.publicationVerified!==false)throw fault('WRITE_OUTCOME_UNKNOWN');return v;},
    async resolveTask(scope,value){distributionScope(scope);if(!uuid(value.task_id)||!uuid(value.request_id)||!['published','not-published'].includes(value.outcome)||
      value.confirm_platform_checked!==true||value.confirm_executor_stopped!==true)fail();
      const v=await request(base+'/task-resolution',{method:'POST',body:{...value,...scope}});
      if(v.schema!==1||v.task_id!==value.task_id||v.outcome!==value.outcome||v.evidence!=='advisor-reported'||!nonnegative(v.checked_at)||
        v.public_url!==(value.public_url??null))throw fault('WRITE_OUTCOME_UNKNOWN');return v;},
    async revokeBinding(bindingId){if(!uuid(bindingId))fail();const value=await request(base+`/bindings/${bindingId}/revoke`,{method:'POST',body:{}});
      if(value.schema!==1||value.id!==bindingId||value.active!==false)throw fault('WRITE_OUTCOME_UNKNOWN');return value;},
    async bind(value){distributionScope(value);if(!uuid(value.device_id)||!id(value.account_id)||!id(value.external_account_id)||
      !platforms.includes(value.platform)||value.confirm_account_ownership!==true)fail();const data=await request(base+'/bindings',{method:'POST',body:value});
      if(data.schema!==1||!uuid(data.binding?.id)||['module','tenant_id','scope_id','device_id','account_id','platform'].some(k=>data.binding[k]!==value[k]))throw fault('WRITE_OUTCOME_UNKNOWN');return data;},
    async revoke(deviceId){if(!uuid(deviceId))fail();const value=await request(base+`/devices/${deviceId}/revoke`,{method:'POST',body:{}});
      if(value.schema!==1||value.id!==deviceId||value.active!==false)throw fault('WRITE_OUTCOME_UNKNOWN');return value;},
    subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn);},invalidate,
    dispose(){stop();listeners.clear();invalidate();},
  };
}
