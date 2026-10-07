// UI-04: exact SEO local contract 8ec3dbf0. Host supplies ordinary session transport.
// This client is not enabled in the standalone demo and never falls back to mock success.
import {validateCycles} from './seo-cycle-config.mjs';
export function createSeoWorkflowClient({transport,getContext} = {}) {
  const deliveries=new Map(); let plan=null;
  const fail=(code,status,detail)=>{const e=Error(code);e.code=code;e.status=status;e.detail=detail;throw e;};
  const positive=n=>Number.isSafeInteger(n)&&n>0;
  function context() {
    const c=getContext?.();
    if(typeof transport!=='function'||!c?.connected||!positive(c.tenantId)||!positive(c.siteId)||!positive(c.userId)||c.revision==null) fail('NOT_CONNECTED');
    return {...c};
  }
  function same(c) {
    const n=context();
    if(n.tenantId!==c.tenantId||n.siteId!==c.siteId||n.userId!==c.userId||n.revision!==c.revision){deliveries.clear();plan=null;fail('CONTEXT_CHANGED');}
  }
  function invalidate(){deliveries.clear();plan=null;}
  async function request(path,method,c,body) {
    same(c);
    let response;
    try {response=await transport(path,{method,cache:'no-store',...(body?{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});}
    catch(e){invalidate();fail(method==='GET'?'READ_TRANSPORT_FAILED':'WRITE_OUTCOME_UNKNOWN',undefined,{message:e.message});}
    same(c);
    let data;try{data=await response.json();}catch{invalidate();fail(response.ok?'CONTRACT_MISMATCH':'HTTP_ERROR',response.status);}
    same(c);
    if(!response.ok){invalidate();fail(data?.detail?.code||(response.status===401?'AUTH_EXPIRED':response.status===403?'PERMISSION_DENIED':'HTTP_ERROR'),response.status,data?.detail);}
    return data;
  }
  function delivery(data,c,id) {
    const v=data?.content;
    if(!v||v.id!==id||v.tenant_id!==c.tenantId||v.site_id!==c.siteId||!positive(v.version_count)||!/^[a-f0-9]{64}$/i.test(v.payload_hash)||!data.allowed_actions||typeof data.allowed_actions!=='object'||data.confirmation?.approval_is_publication!==false) {invalidate();fail('CONTRACT_MISMATCH');}
    // Retain the server snapshot; no client-provided role or hash replacement.
    deliveries.set(id,{context:c,data:structuredClone(data)});return data;
  }
  function current(id,action){const row=deliveries.get(id);if(!row)fail('DELIVERY_REQUIRED');same(row.context);if((row.data.confirmation.status==='unavailable'||row.data.workflow_status==='confirmation_unavailable')&&/^(confirm_|reject_|start_publication)/.test(action))fail('CONFIRMATION_UNAVAILABLE');if(row.data.allowed_actions[action]!==true)fail('ACTION_NOT_ALLOWED');return row;}
  function planPayload(data,c){if(data?.tenant_id!==c.tenantId||data.site_id!==c.siteId||!Number.isSafeInteger(data.revision)||data.revision<0||!['active','paused'].includes(data.status)){invalidate();fail('CONTRACT_MISMATCH');}plan={context:c,data:structuredClone(data)};return data;}
  return {
    invalidate,
    async delivery(id){if(!positive(id))fail('INVALID_CONTENT_ID');const c=context();deliveries.delete(id);return delivery(await request(`/api/v1/seo/workbench/content-assets/${id}/delivery?tenant_id=${c.tenantId}&site_id=${c.siteId}`,'GET',c),c,id);},
    async confirm(id,{decision='approve',actorMode='customer_direct',note=null}={}) {
      if(!['approve','reject'].includes(decision)||!['customer_direct','advisor_proxy'].includes(actorMode))fail('INVALID_DECISION');
      if(decision==='reject'&&(!note||!note.trim()))fail('REJECTION_NOTE_REQUIRED');
      const key=`${decision==='approve'?'confirm':'reject'}_as_${actorMode==='advisor_proxy'?'advisor_proxy':'customer'}`;
      const row=current(id,key),c=row.context,v=row.data.content;
      const result=await request(`/api/v1/seo/workbench/content-assets/${id}/confirmations?tenant_id=${c.tenantId}`,'POST',c,{version_count:v.version_count,payload_hash:v.payload_hash,decision,actor_mode:actorMode,note});
      return delivery(result,c,id);
    },
    async review(id,{decision,note=null}) {
      if(!['approve','reject'].includes(decision))fail('INVALID_DECISION');if(decision==='reject'&&(!note||!note.trim()))fail('REJECTION_NOTE_REQUIRED');
      const row=current(id,'review'),c=row.context;
      const result=await request(`/api/v1/seo/content-assets/${id}/review?tenant_id=${c.tenantId}`,'POST',c,{version_count:row.data.content.version_count,decision,note});
      deliveries.delete(id);return result; // Existing endpoint returns content asset, not delivery.
    },
    async servicePlan(){const c=context();plan=null;return planPayload(await request(`/api/v1/seo/workbench/service-plan?tenant_id=${c.tenantId}&site_id=${c.siteId}`,'GET',c),c);},
    async saveServicePlan({optimizationDirections,contentTopics=[],serviceNote=null,status='active',cycles}) {
      if(!plan)fail('SERVICE_PLAN_REQUIRED');const c=plan.context;same(c);
      if(plan.data.allowed_actions?.update_service_plan!==true)fail('PLAN_UPDATE_NOT_ALLOWED',undefined,plan.data.permission_basis?.update_denial_reason??null);
      if(!Array.isArray(optimizationDirections)||!optimizationDirections.length||optimizationDirections.some(x=>typeof x!=='string'||!x.trim())||!Array.isArray(contentTopics)||contentTopics.some(x=>typeof x!=='string'||!x.trim())||!['active','paused'].includes(status))fail('INVALID_SERVICE_PLAN');
      const expectedRevision=plan.data.revision;
      const cyclePatch=cycles===undefined?{}:validateCycles(cycles);
      const result=await request('/api/v1/seo/workbench/service-plan','PUT',c,{
        tenant_id:c.tenantId,site_id:c.siteId,expected_revision:expectedRevision,
        optimization_directions:optimizationDirections,content_topics:contentTopics,service_note:serviceNote,status,...cyclePatch,
      });
      // A success message requires a validated server revision, never an optimistic local update.
      if(result?.revision!==expectedRevision+1||result.updated_by!==c.userId||typeof result.updated_at!=='string'||!Number.isFinite(Date.parse(result.updated_at))){invalidate();fail('CONTRACT_MISMATCH');}
      if(Object.entries(cyclePatch).some(([key,value])=>result[key]!==value)){invalidate();fail('CONTRACT_MISMATCH');}
      const saved=planPayload(result,c);
      plan=null; // PUT has no allowed_actions. Re-read GET before another write.
      return saved;
    },
    async serviceStatus(){const c=context();const result=await request(`/api/v1/seo/workbench/service-status?tenant_id=${c.tenantId}&site_id=${c.siteId}`,'GET',c);
      if(result?.tenant_id!==c.tenantId||result.site_id!==c.siteId||result.read_only!==true||!result.phases||typeof result.phases!=='object')fail('CONTRACT_MISMATCH');
      for(const p of Object.values(result.phases))if(!['ready','needs_attention','not_ready','no_data'].includes(p.state)||!Array.isArray(p.blockers)||!p.facts)fail('CONTRACT_MISMATCH');
      return result; // ready means facts ready, never synthesize workflow completion.
    },
  };
}
