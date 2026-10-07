// UI-04: exact SEO local contract 8ec3dbf0. Host supplies ordinary session transport.
// This client is not enabled in the standalone demo and never falls back to mock success.
import {validateCycles} from './seo-cycle-config.mjs';
export function createSeoWorkflowClient({transport,getContext} = {}) {
  const deliveries=new Map(),editors=new Map(),publications=new Map(); let plan=null;
  const fail=(code,status,detail)=>{const e=Error(code);e.code=code;e.status=status;e.detail=detail;throw e;};
  const positive=n=>Number.isSafeInteger(n)&&n>0;
  function context() {
    const c=getContext?.();
    if(typeof transport!=='function'||!c?.connected||!positive(c.tenantId)||!positive(c.siteId)||!positive(c.userId)||c.revision==null) fail('NOT_CONNECTED');
    return {...c};
  }
  function same(c) {
    const n=context();
    if(n.tenantId!==c.tenantId||n.siteId!==c.siteId||n.userId!==c.userId||n.revision!==c.revision){invalidate();fail('CONTEXT_CHANGED');}
  }
  function invalidate(){deliveries.clear();editors.clear();publications.clear();plan=null;}
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
  function advisor(id,action){const row=current(id,action);if(row.data.permission_basis?.active_site_advisor_assignment!==true)fail('ADVISOR_REQUIRED');return row;}
  function asset(data,c,id,version){if(data?.id!==id||data.tenant_id!==c.tenantId||data.site_id!==c.siteId||!positive(data.version_count)||(version!==undefined&&data.version_count!==version)){invalidate();fail('CONTENT_VERSION_OR_SCOPE_MISMATCH');}return data;}
  function planPayload(data,c){if(data?.tenant_id!==c.tenantId||data.site_id!==c.siteId||!Number.isSafeInteger(data.revision)||data.revision<0||!['active','paused'].includes(data.status)){invalidate();fail('CONTRACT_MISMATCH');}plan={context:c,data:structuredClone(data)};return data;}
  return {
    invalidate,
    async delivery(id){if(!positive(id))fail('INVALID_CONTENT_ID');const c=context();deliveries.delete(id);editors.delete(id);publications.delete(id);return delivery(await request(`/api/v1/seo/workbench/content-assets/${id}/delivery?tenant_id=${c.tenantId}&site_id=${c.siteId}`,'GET',c),c,id);},
    async editor(id){
      editors.delete(id);const row=advisor(id,'edit_content'),c=row.context;
      if(!['planned','drafting'].includes(row.data.content.status))fail('CONTENT_PROTECTED');
      const result=await request(`/api/v1/seo/content-assets?tenant_id=${c.tenantId}&site_id=${c.siteId}&content_id=${id}&page=1&page_size=50`,'GET',c);
      if(result?.total!==1||result.items?.length!==1){invalidate();fail('CONTRACT_MISMATCH');}
      const v=asset(result.items[0],c,id,row.data.content.version_count);
      if(v.status!==row.data.content.status||typeof v.title!=='string'||![v.outline,v.draft,v.humanized_content].every(x=>x==null||typeof x==='string')||!Array.isArray(v.keyword_ids)||v.keyword_ids.some(x=>!positive(x))){invalidate();fail('CONTRACT_MISMATCH');}
      const field=v.humanized_content?'humanized_content':'draft';
      if((v[field]||'')!==row.data.content.body){invalidate();fail('CONTENT_VERSION_OR_SCOPE_MISMATCH');}
      editors.set(id,{context:c,version:v.version_count,field});
      return {id,version:v.version_count,title:v.title,outline:v.outline||'',body:v[field]||'',field,keywordIds:v.keyword_ids||[]};
    },
    async saveContent(id,{title,outline,body}){
      const row=advisor(id,'edit_content'),edit=editors.get(id);if(!edit)fail('EDITOR_REQUIRED');same(edit.context);
      if(!['planned','drafting'].includes(row.data.content.status)||edit.version!==row.data.content.version_count)fail('CONTENT_PROTECTED');
      if(typeof title!=='string'||!title.trim()||title.length>300||typeof outline!=='string'||typeof body!=='string')fail('INVALID_CONTENT');
      editors.delete(id);
      const result=await request(`/api/v1/seo/content-assets/${id}?tenant_id=${edit.context.tenantId}`,'PATCH',edit.context,{version_count:edit.version,title,outline,[edit.field]:body});
      asset(result,edit.context,id);deliveries.delete(id);
      if(![edit.version,edit.version+1].includes(result.version_count)){invalidate();fail('CONTRACT_MISMATCH');}
      return result;
    },
    async submitReview(id,{note=null}={}){
      const row=advisor(id,'submit_review'),c=row.context;
      if(!['planned','drafting'].includes(row.data.content.status))fail('CONTENT_PROTECTED');
      if(note!==null&&(typeof note!=='string'||note.length>2000))fail('INVALID_NOTE');
      const result=await request(`/api/v1/seo/content-assets/${id}/submit-review?tenant_id=${c.tenantId}`,'POST',c,{version_count:row.data.content.version_count,note});
      asset(result,c,id,row.data.content.version_count);deliveries.delete(id);editors.delete(id);
      if(result.status!=='review')fail('CONTRACT_MISMATCH');return result;
    },
    async publications(id){
      const row=deliveries.get(id);if(!row)fail('DELIVERY_REQUIRED');same(row.context);const c=row.context;publications.delete(id);
      const result=await request(`/api/v1/seo/content-distribution/publications?tenant_id=${c.tenantId}&site_id=${c.siteId}&content_id=${id}`,'GET',c);
      if(!Array.isArray(result?.items)||result.items.some(v=>!positive(v.id)||v.tenant_id!==c.tenantId||v.content_id!==id||!positive(v.source_version))){invalidate();fail('CONTRACT_MISMATCH');}
      publications.set(id,{context:c,items:structuredClone(result.items)});return result;
    },
    async publicationAttempts(id,publicationId){
      const list=publications.get(id);if(!list||!list.items.some(v=>v.id===publicationId))fail('PUBLICATIONS_REQUIRED');same(list.context);const c=list.context;
      const result=await request(`/api/v1/seo/content-distribution/publications/${publicationId}/attempts?tenant_id=${c.tenantId}&site_id=${c.siteId}`,'GET',c);
      if(!Array.isArray(result?.items))fail('CONTRACT_MISMATCH');return result;
    },
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
      const row=advisor(id,'review'),c=row.context;
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
