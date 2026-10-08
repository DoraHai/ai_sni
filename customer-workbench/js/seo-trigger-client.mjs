const kinds={content:'content_delivery',website:'site_diagnosis',monitoring:'ranking_followup',report:'monthly_report'};
export function createSeoTriggerClient({transport,getContext,uuid=()=>crypto.randomUUID()}){
  let snapshot=null;const pending=new Map();
  const fail=(code,status)=>{snapshot=null;const e=Error(code);e.code=code;e.status=status;throw e;};
  const scope=c=>`${c.userId}/${c.tenantId}/${c.siteId}`;
  function context(){const c=getContext();if(!c?.connected)fail('NOT_CONNECTED');return {...c};}
  function same(c){const n=context();if(scope(n)!==scope(c)||n.revision!==c.revision)fail('CONTEXT_CHANGED');}
  return {
    invalidate(){snapshot=null;},
    async load(expectedRevision){const c=context();snapshot=null;let r;try{r=await transport(`/api/v1/seo/workbench/service-plan?tenant_id=${c.tenantId}&site_id=${c.siteId}`,{method:'GET'});}catch(e){fail(e.code||'READ_FAILED',e.status);}same(c);const data=await r.json();same(c);if(!r.ok)fail(data.detail?.code||'HTTP_ERROR',r.status);if(data.tenant_id!==c.tenantId||data.site_id!==c.siteId)fail('CONTRACT_MISMATCH');if(expectedRevision!==undefined&&data.revision!==expectedRevision)fail('service_plan_version_conflict',409);snapshot={context:c,data};return data.trigger_actions??{};},
    pending(){const c=context();return Object.fromEntries([...pending].filter(([k])=>k.startsWith(scope(c)+'/')).map(([k,v])=>[k.split('/').at(-1),v]));},
    async trigger(kind){
      if(!snapshot||!kinds[kind])fail('TRIGGER_READ_REQUIRED');const {context:c,data}=snapshot;same(c);
      const key=scope(c)+'/'+kind;if(pending.has(key))fail('TRIGGER_OUTCOME_UNRESOLVED');
      const action=data.trigger_actions?.[kind],endpoint='/api/v1/seo/workbench/'+(kind==='content'?'service-plan/run':'service-cycles/run');
      if(action?.allowed!==true)fail('ACTION_NOT_ALLOWED');
      if(action.endpoint!==endpoint||action.method!=='POST'||action.kind!==(kind==='content'?null:kind)||action.meaning!=='new_execution_only'||action.request_id_format!=='uuid'||action.expected_revision!==data.revision||!Number.isSafeInteger(data.revision)||data.revision<1)fail('CONTRACT_MISMATCH');
      const requestId=uuid();if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(requestId))fail('INVALID_REQUEST_ID');
      const body={tenant_id:c.tenantId,site_id:c.siteId,expected_revision:action.expected_revision,request_id:requestId,...(kind==='content'?{}:{kind})};
      pending.set(key,requestId);snapshot=null;let response,dataOut;
      try{response=await transport(endpoint,{method:'POST',body:JSON.stringify(body)});}catch(e){fail(['AUTH_EXPIRED','PERMISSION_DENIED','CONTEXT_CHANGED'].includes(e.code)?e.code:'WRITE_OUTCOME_UNKNOWN',e.status);}
      same(c);try{dataOut=await response.json();}catch{fail('WRITE_OUTCOME_UNKNOWN');}same(c);
      if(!response.ok){if(response.status<500)pending.delete(key);fail(dataOut.detail?.code||'HTTP_ERROR',response.status);}
      const task=dataOut.task;
      if(typeof dataOut.created!=='boolean'||!Number.isSafeInteger(task?.id)||task.id<1||task.module!=='seo'||task.action_type!==kinds[kind]||task.params?.request_key!==`request:${requestId}`)fail('WRITE_OUTCOME_UNKNOWN');
      pending.delete(key);return {id:task.id,requestId,created:dataOut.created};
    },
    reconcile(items){const c=context();for(const [key,id] of pending){if(!key.startsWith(scope(c)+'/'))continue;const kind=key.split('/').at(-1);if(items.some(t=>t.action_type===kinds[kind]&&t.params?.request_key===`request:${id}`))pending.delete(key);}},
  };
}
