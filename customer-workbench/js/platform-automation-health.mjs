export const automationHealthPaths=Object.freeze({
  seo:'/api/v1/seo/workbench/automation-health',
  geo:'/api/v1/geo/workbench/automation-health',
});
const invalid=()=>{throw Object.assign(Error('CONSOLE_INVALID_AUTOMATION_HEALTH'),{code:'CONSOLE_INVALID_AUTOMATION_HEALTH'});};
const count=n=>n===null||Number.isSafeInteger(n)&&n>=0;
const positive=n=>Number.isSafeInteger(n)&&n>0;
const stamp=s=>typeof s==='string'&&/^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(s)&&Number.isFinite(Date.parse(s));

// Only a global, explicitly identified module snapshot can reach the platform view.
export function validateAutomationHealth(data,module){
  if(!Object.hasOwn(automationHealthPaths,module)||data?.schema!==1||data.module!==module||
    data.scope?.kind!=='global'||data.scope.tenant_id!==null||!stamp(data.as_of)||
    !['available','schema_pending','unavailable'].includes(data.state))invalid();
  if(data.state!=='available')return {schema:1,module,scope:{kind:'global',tenant_id:null},as_of:data.as_of,state:data.state};
  if(!data.counts||!['projects','runs','pending_human','unknown_cost'].every(k=>count(data.counts[k]))||
    !Array.isArray(data.rows)||data.rows.length>50||typeof data.truncated!=='boolean')invalid();
  const keys=new Set();
  const rows=data.rows.map(r=>{
    if(!positive(r?.tenant_id)||!positive(r.scope_id)||keys.has(r.tenant_id+':'+r.scope_id)||
      typeof r.project_state!=='string'||r.run_state!==null&&typeof r.run_state!=='string'||
      !count(r.pending_human)||!count(r.unknown_cost))invalid();
    keys.add(r.tenant_id+':'+r.scope_id);
    return {tenant_id:r.tenant_id,scope_id:r.scope_id,project_state:r.project_state,run_state:r.run_state,
      pending_human:r.pending_human,unknown_cost:r.unknown_cost,
      cycle_enabled:typeof r.cycle_enabled==='boolean'?r.cycle_enabled:null,
      updated_at:stamp(r.updated_at)?r.updated_at:null};
  });
  const q=data.queue,w=data.worker;
  return {schema:1,module,scope:{kind:'global',tenant_id:null},as_of:data.as_of,state:'available',
    counts:Object.fromEntries(['projects','runs','pending_human','unknown_cost'].map(k=>[k,data.counts[k]])),rows,truncated:data.truncated,
    queue:q?.state==='available'&&['queued','running','unknown'].every(k=>count(q[k]))?
      {state:'available',queued:q.queued,running:q.running,unknown:q.unknown}:{state:'unknown'},
    worker:{state:w?.state,verified:w?.verified===true,last_tick_at:stamp(w?.last_tick_at)?w.last_tick_at:null,
      evidence:w?.evidence?.kind==='local_tick'&&w.evidence.scope==='this_process'?{kind:'local_tick',scope:'this_process'}:null}};
}

export function automationReadState(error){
  if(error?.code==='CONSOLE_AUTOMATION_NOT_LAUNCHED')return 'not_launched';
  if(error?.status===404)return 'not_deployed';
  if(error?.status===401)return 'unauthorized';
  if(error?.status===403)return 'forbidden';
  if(error?.code==='CONSOLE_INVALID_AUTOMATION_HEALTH')return 'invalid';
  if(['TimeoutError','AbortError'].includes(error?.name))return 'timeout';
  return 'unavailable';
}
