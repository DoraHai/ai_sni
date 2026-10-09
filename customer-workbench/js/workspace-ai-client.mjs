const fail=(code,status)=>Object.assign(Error(code),{code,status});
const scope=ctx=>JSON.stringify([ctx?.tenantId,ctx?.siteId,ctx?.userId,ctx?.revision]);
export function createWorkspaceAiClient({host,newId=()=>crypto.randomUUID()}){
 let generation=0;
 function context(){const c=host.getContext();if(!c?.connected)throw fail('NOT_CONNECTED');return c;}
 return {
  clear(){generation++;},
  prepare(message,history,contentId=null){const c=context();return {scope:scope(c),body:{tenant_id:c.tenantId,site_id:c.siteId,request_id:newId(),message,history,content_id:contentId}};},
  async send(pending){
   const ctx=context(),stamp=generation;if(scope(ctx)!==pending.scope)throw fail('CONTEXT_CHANGED');
   const response=await host.transport('/api/v1/seo/workbench/assistant/chat',{method:'POST',body:JSON.stringify(pending.body),signal:AbortSignal.timeout(60000)});
   const data=await response.json();if(stamp!==generation||scope(host.getContext())!==pending.scope)throw fail('CONTEXT_CHANGED');
   if(!response.ok){const error=fail(data?.detail?.code||'AI_REQUEST_FAILED',response.status);const seconds=Number(response.headers?.get?.('Retry-After'));if(Number.isFinite(seconds)&&seconds>0)error.retryAfter=Math.min(86400,Math.ceil(seconds));throw error;}
   if(data?.tenant_id!==ctx.tenantId||data.site_id!==ctx.siteId||data.request_id!==pending.body.request_id||data.advisory_only!==true||data.provider!=='deepseek'||typeof data.answer!=='string'||!data.answer.trim()||data.answer.length>6000||!Array.isArray(data.sources))throw fail('AI_CONTRACT_MISMATCH');
   return {...data,sources:data.sources.filter(s=>['content','tasks','pages','keywords','selected_content'].includes(s))};
  },
 };
}
