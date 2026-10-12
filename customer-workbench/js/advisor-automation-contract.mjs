const positive=n=>Number.isSafeInteger(n)&&n>0;
const nonnegative=n=>Number.isSafeInteger(n)&&n>=0;
export const automationUuid=value=>typeof value==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value);
export const automationActions=['start','pause','resume','takeover','end','end_project','disable_cycle'];
const projectStates=['schema_pending','not_started','active','pausing','paused','taking_over','taken_over','ending','idle'];
const runStates=['queued','running','waiting_input','waiting_human','pausing','paused','taking_over','taken_over','ending','ended','failed'];
const stepStates=['pending','running','succeeded','failed','unknown','stale','cancelled','blocked'];
const feeStates=['not_called','recorded','unknown_charge','unverified'];
const bad=()=>{throw Object.assign(Error('AUTOMATION_CONTRACT_MISMATCH'),{code:'AUTOMATION_CONTRACT_MISMATCH'});};
const time=value=>value===null||typeof value==='string'&&Number.isFinite(Date.parse(value));
const strings=(value,max=100)=>Array.isArray(value)&&value.length<=max&&value.every(v=>typeof v==='string'&&v.length<=500);
const identifier=value=>typeof value==='string'&&/^[a-z][a-z0-9_]{0,39}$/.test(value);
const hash=value=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
const exactKeys=(value,allowed)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).every(key=>allowed.includes(key));
export function validateAutomationTarget(value){
  if(!exactKeys(value,['operation','object_type','object_id','source_revision','source_hash','variant'])||!identifier(value.operation)||!identifier(value.object_type)||
    !positive(value.object_id)||!nonnegative(value.source_revision)||!hash(value.source_hash)||value.variant!=null&&!identifier(value.variant))bad();
  return structuredClone(value);
}
export const automationTargetKey=value=>JSON.stringify([value.operation,value.object_type,value.object_id,value.variant??null]);
const plan=value=>exactKeys(value,['revision','sha256'])&&nonnegative(value.revision)&&hash(value.sha256);
function bindings(value){
  if(!Array.isArray(value)||value.length>8)bad();
  for(const row of value)if(!exactKeys(row,['kind','object_id','revision','sha256'])||!identifier(row.kind)||!positive(row.object_id)||!nonnegative(row.revision)||!hash(row.sha256))bad();
  if(new Set(value.map(row=>JSON.stringify([row.kind,row.object_id]))).size!==value.length)bad();
}
export function validateAutomationChanges(value){
  if(!Array.isArray(value)||value.length>20||JSON.stringify(value).length>24000)bad();
  const allowed=['state','version','generation','owner_user_id','cycle_enabled','ended_at','configuration_fingerprint',
    'configuration.task_ids','configuration.operations','configuration.targets','configuration.service_plan','configuration.source_bindings',
    'configuration.cycle','configuration.limits','configuration.stop_condition','configuration.contract_version'];
  for(const row of value){
    if(!exactKeys(row,['path','before','after'])||!Object.hasOwn(row,'before')||!Object.hasOwn(row,'after')||!allowed.includes(row.path))bad();
    for(const item of [row.before,row.after]){
      if(item===null)continue;
      switch(row.path){
        case 'state':if(!projectStates.includes(item))bad();break;
        case 'version':case 'generation':case 'owner_user_id':case 'configuration.contract_version':if(!nonnegative(item))bad();break;
        case 'cycle_enabled':if(typeof item!=='boolean')bad();break;
        case 'ended_at':if(!time(item))bad();break;
        case 'configuration_fingerprint':if(!hash(item))bad();break;
        case 'configuration.task_ids':if(!Array.isArray(item)||item.length>20||!item.every(positive))bad();break;
        case 'configuration.operations':if(!Array.isArray(item)||item.length>20||!item.every(identifier))bad();break;
        case 'configuration.targets':if(!Array.isArray(item)||item.length>20)bad();item.forEach(validateAutomationTarget);break;
        case 'configuration.source_bindings':bindings(item);break;
        case 'configuration.service_plan':if(!plan(item))bad();break;
        case 'configuration.cycle':if(!exactKeys(item,['mode','enabled'])||!['once','daily','monthly'].includes(item.mode)||typeof item.enabled!=='boolean'||item.mode==='once'&&item.enabled)bad();break;
        case 'configuration.limits':if(!exactKeys(item,['max_dispatches_per_run','max_external_calls_per_run'])||!positive(item.max_dispatches_per_run)||item.max_dispatches_per_run>20||item.max_external_calls_per_run!==undefined&&(!positive(item.max_external_calls_per_run)||item.max_external_calls_per_run>100))bad();break;
        case 'configuration.stop_condition':if(item!=='drafts_ready_or_blocked')bad();break;
      }
    }
  }
  return structuredClone(value);
}
export function automationScope({module,tenantId,scopeId}){
  if(!['seo','geo'].includes(module)||!positive(tenantId)||!positive(scopeId))bad();
  return {module,tenantId,scopeId};
}
function match(data,scope){
  if(data?.schema!==1||data.module!==scope.module||data.tenant_id!==scope.tenantId||data.scope_id!==scope.scopeId)bad();
}
export function validateAutomationConfiguration(value){
  if(value?.contract_version===2){
    if(!exactKeys(value,['contract_version','operations','targets','service_plan','source_bindings','cycle','limits','stop_condition','owner_user_id'])||
      !Array.isArray(value.operations)||value.operations.length<1||value.operations.length>20||!value.operations.every(identifier)||new Set(value.operations).size!==value.operations.length||
      !Array.isArray(value.targets)||value.targets.length<1||value.targets.length>20||!plan(value.service_plan)||
      !exactKeys(value.cycle,['mode','enabled'])||!['once','daily','monthly'].includes(value.cycle.mode)||typeof value.cycle.enabled!=='boolean'||value.cycle.mode==='once'&&value.cycle.enabled||
      !exactKeys(value.limits,['max_dispatches_per_run','max_external_calls_per_run'])||!positive(value.limits.max_dispatches_per_run)||value.limits.max_dispatches_per_run>20||
      !positive(value.limits.max_external_calls_per_run)||value.limits.max_external_calls_per_run>100||value.stop_condition!=='drafts_ready_or_blocked'||!positive(value.owner_user_id))bad();
    const keys=new Set();
    for(const target of value.targets){validateAutomationTarget(target);const key=automationTargetKey(target);if(!value.operations.includes(target.operation)||keys.has(key))bad();keys.add(key);}
    if(value.operations.some(operation=>!value.targets.some(target=>target.operation===operation)))bad();
    bindings(value.source_bindings??[]);
    return structuredClone(value);
  }
  if(!value||Object.keys(value).some(k=>!['task_ids','operations','cycle','limits','stop_condition','owner_user_id'].includes(k))||
    !Array.isArray(value.task_ids)||value.task_ids.length<1||value.task_ids.length>20||!value.task_ids.every(positive)||new Set(value.task_ids).size!==value.task_ids.length||
    !Array.isArray(value.operations)||value.operations.length!==1||value.operations[0]!=='onsite_ai'||
    !value.cycle||Object.keys(value.cycle).some(k=>!['mode','enabled'].includes(k))||!['once','daily','monthly'].includes(value.cycle.mode)||typeof value.cycle.enabled!=='boolean'||value.cycle.mode==='once'&&value.cycle.enabled||
    !value.limits||Object.keys(value.limits).some(k=>k!=='max_dispatches_per_run')||!positive(value.limits.max_dispatches_per_run)||value.limits.max_dispatches_per_run>20||
    value.stop_condition!=='drafts_ready_or_blocked'||!positive(value.owner_user_id))bad();
  return structuredClone(value);
}
export function validateAutomationBasis(data,scope,{operation,beforeObjectId=null,limit=25}={}){
  match(data,scope);
  if(data.contract_version!==2||!['ready','schema_pending'].includes(data.state)||!strings(data.available_operations,20)||
    !data.available_operations.every(identifier)||new Set(data.available_operations).size!==data.available_operations.length||!Array.isArray(data.targets)||data.targets.length>limit*10)bad();
  bindings(data.source_bindings);
  if(data.state==='schema_pending'){
    if(data.service_plan!==null||data.targets.length||data.source_bindings.length||data.available_operations.length||data.next_before_object_id!==null)bad();
    return structuredClone(data);
  }
  if(!plan(data.service_plan)||!identifier(operation)||!data.available_operations.includes(operation))bad();
  const seen=new Set(),objects=new Map();let previous=beforeObjectId??Infinity;
  for(const row of data.targets){
    if(!exactKeys(row,['operation','object_type','object_id','source_revision','source_hash','variant','label'])||row.label!==undefined&&(typeof row.label!=='string'||row.label.length>500))bad();
    const {label,...target}=row;validateAutomationTarget(target);
    const key=automationTargetKey(target);if(target.operation!==operation||target.object_id>previous||beforeObjectId!==null&&target.object_id>=beforeObjectId||seen.has(key))bad();
    seen.add(key);objects.set(target.object_id,(objects.get(target.object_id)||0)+1);previous=target.object_id;
  }
  if(objects.size>limit||[...objects.values()].some(count=>count>10)||data.next_before_object_id!==null&&(!positive(data.next_before_object_id)||!data.targets.length||data.next_before_object_id!==previous))bad();
  return structuredClone(data);
}
export function validateAutomationProject(data,scope){
  match(data,scope);
  if(!nonnegative(data.version)||!nonnegative(data.generation)||!projectStates.includes(data.state)||typeof data.cycle_enabled!=='boolean'||!time(data.next_due_at)||
    !(data.current_run_id===null||automationUuid(data.current_run_id))||!data.capabilities||!['ready','pending','schema_pending'].includes(data.capabilities.schema_state)||
    typeof data.capabilities.can_configure!=='boolean'||typeof data.capabilities.can_control!=='boolean'||!strings(data.capabilities.available_operations,20)||
    !strings(data.coverage?.controlled,30)||!strings(data.coverage?.not_controlled,30)||!Array.isArray(data.allowed_actions)||
    data.allowed_actions.some(a=>!automationActions.includes(a))||new Set(data.allowed_actions).size!==data.allowed_actions.length)bad();
  if(data.configuration!==null)validateAutomationConfiguration(data.configuration);
  if(data.ended_at!==undefined&&!time(data.ended_at))bad();
  if(data.ended_at&&data.allowed_actions.some(action=>['start','resume'].includes(action)))bad();
  if((data.state==='schema_pending'||data.capabilities.schema_state!=='ready')&&(data.allowed_actions.length||data.capabilities.can_configure||data.capabilities.can_control))bad();
  return structuredClone(data);
}
export function validateAutomationProjects(data,module,{beforeScopeId=null,limit=25,tenantId=null}={}){
  if(data?.schema!==1||data.module!==module||!Array.isArray(data.items)||data.items.length>limit)bad();
  let previous=beforeScopeId??Infinity;
  for(const row of data.items){
    const scope=automationScope({module,tenantId:row.tenant_id,scopeId:row.scope_id});
    validateAutomationProject(row,scope);
    if(row.scope_id>=previous||tenantId!==null&&row.tenant_id!==tenantId)bad();previous=row.scope_id;
  }
  if(data.next_before_scope_id!==null&&(!positive(data.next_before_scope_id)||!data.items.length||data.next_before_scope_id!==data.items.at(-1).scope_id))bad();
  return structuredClone(data);
}
export function validateAutomationRun(data,scope,runId){
  match(data,scope);const run=data.run;
  if(!automationUuid(runId)||run?.id!==runId||!runStates.includes(run.state)||!nonnegative(run.generation)||typeof run.stop_requested!=='boolean'||
    !time(run.started_at)||!time(run.finished_at)||!nonnegative(run.dispatch_count)||!Array.isArray(run.steps)||run.steps.length>20||
    new Set(run.steps.map(s=>s.step_key)).size!==run.steps.length)bad();
  for(const step of run.steps){
    const typed=step.target!==undefined;
    if(typed){validateAutomationTarget(step.target);if(step.kind!==step.target.operation||step.operation!==step.target.operation||step.kind==='onsite_ai'&&step.task_id!==step.target.object_id||step.kind!=='onsite_ai'&&step.task_id!==null)bad();}
    if(typeof step.step_key!=='string'||step.step_key.length>150||!typed&&(step.kind!=='onsite_ai'||!positive(step.task_id))||!stepStates.includes(step.status)||
      !time(step.started_at)||!time(step.finished_at)||![null,'system','advisor'].includes(step.waiting_for)||
      !Array.isArray(step.result_links)||!strings(step.evidence_refs,30)||!feeStates.includes(step.fee_state)||
      !(step.request_id===null||automationUuid(step.request_id)))bad();
    if(typed||step.calls!==undefined){
      if(!Array.isArray(step.calls)||step.calls.length>100||new Set(step.calls.map(call=>call?.call_key)).size!==step.calls.length)bad();
      for(const call of step.calls)if(!call||typeof call.call_key!=='string'||!/^[a-zA-Z0-9][a-zA-Z0-9_:.-]{0,79}$/.test(call.call_key)||!['provider','http'].includes(call.kind)||
        !['admitted','succeeded','failed','unknown','stale','cancelled'].includes(call.state)||!time(call.admitted_at)||!time(call.finished_at)||!feeStates.includes(call.fee_state)||!strings(call.evidence_refs,30))bad();
    }
  }
  if(run.steps.reduce((sum,step)=>sum+(step.calls?.length||0),0)>100)bad();
  const progress=run.progress;
  if(!progress||progress.total_steps!==run.steps.length||!['total_steps','terminal_steps','running_steps','waiting_steps'].every(k=>nonnegative(progress[k])&&progress[k]<=progress.total_steps))bad();
  return structuredClone(data);
}
export function validateAutomationEvents(data,scope,runId,{afterId=0,limit=50}={}){
  match(data,scope);
  if(runId!==null&&(data.run_id!==runId||!automationUuid(runId))||!Array.isArray(data.items)||data.items.length>limit)bad();
  let previous=afterId;
  for(const event of data.items){
    if(!positive(event.id)||event.id<=previous||event.module!==scope.module||event.tenant_id!==scope.tenantId||event.scope_id!==scope.scopeId||runId!==null&&event.run_id!==runId||runId===null&&!(event.run_id===null||automationUuid(event.run_id))||!['human','system','ai'].includes(event.actor_kind)||
      !(event.actor_user_id===null||positive(event.actor_user_id))||typeof event.code!=='string'||event.code.length>150||!time(event.created_at)||
      !strings(event.evidence_refs,30)||!feeStates.includes(event.fee_state)||!(event.request_id===null||automationUuid(event.request_id)))bad();
    if(event.safe_changes!==undefined)validateAutomationChanges(event.safe_changes);
    previous=event.id;
  }
  if(data.next_after_id!==null&&(!positive(data.next_after_id)||!data.items.length||data.next_after_id!==previous))bad();
  return structuredClone(data);
}
export function validateAutomationExport(data,scope,{afterId=0,throughId=null,limit=500}={}){
  if(!nonnegative(data?.snapshot_upper_id)||throughId!==null&&data.snapshot_upper_id!==throughId)bad();
  const checked=validateAutomationEvents(data,scope,null,{afterId,limit});
  if(checked.items.some(row=>row.id>checked.snapshot_upper_id)||checked.next_after_id!==null&&checked.next_after_id>=checked.snapshot_upper_id)bad();
  return checked;
}
export function validateAutomationHistory(data,scope,{beforeRunId=null,limit=20}={}){
  match(data,scope);
  if(!Array.isArray(data.items)||data.items.length>limit||new Set(data.items.map(row=>row.id)).size!==data.items.length)bad();
  for(const row of data.items)if(!automationUuid(row.id)||row.id===beforeRunId||!runStates.includes(row.state)||!time(row.started_at)||!time(row.finished_at))bad();
  if(data.next_before_run_id!==null&&(!automationUuid(data.next_before_run_id)||!data.items.length||data.next_before_run_id!==data.items.at(-1).id))bad();
  return structuredClone(data);
}
