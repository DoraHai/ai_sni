// SEO-08/09 f9a22877 projection; never follows arbitrary links or replays writes.
export function createSeoExecutionClient({transport,getContext}) {
  const snapshots=new Map(),publicationChoices=new Map();
  const fail=(code,status)=>{snapshots.clear();const e=Error(code);e.code=code;e.status=status;throw e;};
  const positive=n=>Number.isSafeInteger(n)&&n>0;
  const kinds=['content_delivery','site_diagnosis','ranking_followup','monthly_report'];
  function context(){const c=getContext();if(!c?.connected)fail('NOT_CONNECTED');return {...c};}
  function same(c){const n=context();if(['tenantId','siteId','userId','revision'].some(k=>n[k]!==c[k])){snapshots.clear();fail('CONTEXT_CHANGED');}}
  const scope=c=>new URLSearchParams({tenant_id:c.tenantId,site_id:c.siteId}).toString();
  const stem=id=>`/api/v1/seo/workbench/executions/${id}`;
  async function request(path,method,c,body){
    same(c);let response;
    try{response=await transport(path,{method,...(body?{body:JSON.stringify(body)}:{})});}catch(e){snapshots.clear();if(['AUTH_EXPIRED','PERMISSION_DENIED','CONTEXT_CHANGED'].includes(e.code))throw e;fail(method==='GET'?'READ_FAILED':'WRITE_OUTCOME_UNKNOWN');}
    same(c);
    if(!response.ok){let data;try{data=await response.json();}catch{}same(c);snapshots.clear();fail(data?.detail?.code||'HTTP_ERROR',response.status);}
    return response;
  }
  async function json(path,method,c,body){const r=await request(path,method,c,body);let data;try{data=await r.json();}catch(e){snapshots.clear();if(e.code==='CONTEXT_CHANGED')throw e;fail('CONTRACT_MISMATCH');}same(c);return data;}
  function validate(data,c,id){
    if(!data||!positive(data.id)||(id&&data.id!==id)||data.read_only!==true||data.module!=='seo'||!kinds.includes(data.action_type)||!['open','in_progress','done','cancelled'].includes(data.status)||!data.params||!data.allowed_actions||typeof data.effective_pause!=='boolean'||data.links?.detail!==`${stem(data.id)}?${scope(c)}`)fail('CONTRACT_MISMATCH');
    const expected=data.action_type==='content_delivery'?`/api/v1/seo/workbench/content-workflows/${data.id}/advance`:`${stem(data.id)}/advance`;
    if(data.links.advance!==expected||data.links.cancel!==stem(data.id)||(data.links.report!=null&&data.links.report!==`${stem(data.id)}/report?${scope(c)}`))fail('CONTRACT_MISMATCH');
    if(data.params.report?.html!==undefined)fail('CONTRACT_MISMATCH');
    snapshots.set(data.id,{context:c,data:structuredClone(data)});return data;
  }
  function current(id,action){const row=snapshots.get(id);if(!row)fail('EXECUTION_REQUIRED');same(row.context);const t=row.data;if(action&&(t.allowed_actions[action]!==true||['done','cancelled'].includes(t.status)||(action!=='cancel'&&t.effective_pause)))fail('ACTION_NOT_ALLOWED');return row;}
  return {
    invalidate(){snapshots.clear();publicationChoices.clear();},
    async list({page=1,pageSize=20}={}){
      if(!positive(page)||page>10000||!positive(pageSize)||pageSize>100)fail('INVALID_PAGINATION');
      const c=context();snapshots.clear();const result=await json(`/api/v1/seo/workbench/executions?${scope(c)}&page=${page}&page_size=${pageSize}`,'GET',c);
      if(result.read_only!==true||result.page!==page||result.page_size!==pageSize||!Number.isSafeInteger(result.total)||result.total<0||!Array.isArray(result.items)||result.items.length>pageSize||!result.cycles)fail('CONTRACT_MISMATCH');
      result.items.forEach(t=>validate(t,c));return result;
    },
    async detail(id){if(!positive(id))fail('INVALID_TASK_ID');const c=context();snapshots.delete(id);publicationChoices.delete(id);return validate(await json(`${stem(id)}?${scope(c)}`,'GET',c),c,id);},
    async publicationOptions(id){
      const row=current(id),c=row.context,contentId=row.data.params.content_id;publicationChoices.delete(id);
      if(row.data.action_type!=='content_delivery'||!positive(contentId))fail('INVALID_CONTENT_ID');
      const data=await json(`/api/v1/seo/content-distribution/publications?${scope(c)}&content_id=${contentId}`,'GET',c);
      if(!Array.isArray(data?.items)||data.items.some(v=>!positive(v?.id)||v.tenant_id!==c.tenantId||v.content_id!==contentId||!positive(v.source_version)))fail('CONTRACT_MISMATCH');
      publicationChoices.set(id,{context:c,items:data.items});return data.items;
    },
    async act(id,action,input={}){
      const row=current(id,['retry','retry_analytics'].includes(action)?'advance':action==='incomplete_report'?'prepare_incomplete_report':action==='explain'?'explain_report':action),c=row.context,t=row.data;
      const body={tenant_id:c.tenantId,site_id:c.siteId};let method='POST',path=t.action_type==='content_delivery'?`/api/v1/seo/workbench/content-workflows/${id}/advance`:`${stem(id)}/advance`;
      if(action==='cancel'){method='DELETE';path=`${stem(id)}?${scope(c)}`;}
      else if(action==='retry'){if(t.action_type!=='site_diagnosis'||!positive(input.pageId)||!t.allowed_actions.retry_page_ids?.includes(input.pageId))fail('ACTION_NOT_ALLOWED');body.retry_page_id=input.pageId;}
      else if(action==='retry_analytics'){if(t.action_type!=='monthly_report'||t.params.report||!['baidu_tongji','ga4'].includes(input.source)||!t.allowed_actions.retry_analytics_sources?.includes(input.source))fail('ACTION_NOT_ALLOWED');body.retry_analytics_source=input.source;}
      else if(action==='incomplete_report'){if(t.action_type!=='monthly_report'||t.params.report)fail('ACTION_NOT_ALLOWED');body.allow_incomplete_analytics=true;}
      else if(action==='explain'){if(t.action_type!=='monthly_report'||!input.explanation?.trim()||input.explanation.length>4000||!/^[0-9a-f]{64}$/.test(t.params.report?.sha256))fail('INVALID_REPORT_EXPLANATION');body.explanation=input.explanation.trim();body.report_sha256=t.params.report.sha256;}
      else if(action==='advance'){if(input.publicationId!=null){const choices=publicationChoices.get(id);if(t.action_type!=='content_delivery'||!positive(input.publicationId)||!choices?.items.some(v=>v.id===input.publicationId))fail('PUBLICATION_SELECTION_REQUIRED');same(choices.context);body.publication_id=input.publicationId;}}
      else fail('ACTION_NOT_ALLOWED');
      snapshots.delete(id);await json(path,method,c,method==='DELETE'?undefined:body);
      // Content advance returns a raw task without fresh allowed_actions. Always re-read.
      same(c);return this.detail(id);
    },
    async readNotification(taskId,eventId){
      const row=current(taskId),c=row.context;
      if(typeof eventId!=='string'||!/^[0-9a-f-]{36}$/.test(eventId)||!row.data.notifications?.some(e=>e.id===eventId&&e.task_id===taskId))fail('NOTIFICATION_REQUIRED');
      snapshots.delete(taskId);
      const result=await json('/api/v1/seo/workbench/notifications/read','POST',c,{tenant_id:c.tenantId,site_id:c.siteId,task_id:taskId,event_id:eventId});
      if(result.event_id!==eventId||result.read!==true)fail('CONTRACT_MISMATCH');
      return result;
    },
    async report(id){
      const row=current(id),c=row.context,meta=row.data.params.report;
      if(row.data.action_type!=='monthly_report'||!row.data.links.report||!/^[0-9a-f]{64}$/.test(meta?.sha256)||meta.pdf_generated!==false)fail('REPORT_NOT_AVAILABLE');
      const response=await request(`${stem(id)}/report?${scope(c)}`,'GET',c);
      if(!response.headers.get('content-type')?.startsWith('text/html')||response.headers.get('etag')!==`"${meta.sha256}"`)fail('REPORT_VERSION_MISMATCH');
      const bytes=await response.arrayBuffer();same(c);
      const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');same(c);
      if(hash!==meta.sha256)fail('REPORT_VERSION_MISMATCH');
      return {bytes,filename:`seo-report-${id}.html`,sha256:hash};
    },
  };
}
