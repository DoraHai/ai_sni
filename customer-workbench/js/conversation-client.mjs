const positive=n=>Number.isSafeInteger(n)&&n>0;
const fail=(code,status)=>Object.assign(Error(code),{code,status});
const fingerprint=ctx=>JSON.stringify([ctx?.tenantId,ctx?.siteId,ctx?.userId,ctx?.revision]);
export function createConversationClient({host,newId=()=>crypto.randomUUID()}){
  const known=new Map();let generation=0;
  function context(){const ctx=host.getContext();if(!ctx?.connected||![ctx.tenantId,ctx.siteId,ctx.userId].every(positive))throw fail('NOT_CONNECTED');return ctx;}
  const base=id=>{if(!positive(id))throw fail('INVALID_CONTENT');return `/api/v1/seo/workbench/content-assets/${id}/conversation`;};
  async function request(path,ctx,body){const stamp=generation;const response=await host.transport(path,{method:body?'POST':'GET',signal:AbortSignal.timeout(20000),...(body?{body:JSON.stringify(body)}:{})});const data=await response.json();if(stamp!==generation||fingerprint(host.getContext())!==fingerprint(ctx))throw fail('CONTEXT_CHANGED');if(!response.ok)throw fail(data?.detail?.code||'CONVERSATION_REQUEST_FAILED',response.status);return data;}
  function readState(data){if(!data||!Number.isSafeInteger(data.unread_count)||data.unread_count<0||!Number.isSafeInteger(data.last_read_message_id)||data.last_read_message_id<0)throw fail('CONTRACT_MISMATCH');return data;}
  function message(row,conversationId,ctx){if(!positive(row?.id)||!positive(row.conversation_id)||conversationId&&row.conversation_id!==conversationId||!positive(row.sender?.id)||!['customer','advisor'].includes(row.sender?.kind)||typeof row.sender?.name!=='string'||typeof row.body!=='string'||!row.created_at)throw fail('CONTRACT_MISMATCH');return {id:row.id,text:row.body,senderName:row.sender.name,senderRole:row.sender.kind==='advisor'?'顾问':'客户',createdAt:row.created_at,mine:row.sender.id===ctx.userId};}
  return {
    clear(){generation++;known.clear();},
    async list(id,before=null){
      const ctx=context(),query=new URLSearchParams({tenant_id:ctx.tenantId,site_id:ctx.siteId});
      const meta=await request(base(id)+'?'+query,ctx);
      if(meta.scope?.tenant_id!==ctx.tenantId||meta.scope?.site_id!==ctx.siteId||meta.scope?.content_id!==id||meta.actor?.id!==ctx.userId||meta.semantics!=='human_messages_only'||meta.allowed_actions?.read!==true)throw fail('CONTRACT_MISMATCH');
      if(before!==null&&!positive(before))throw fail('INVALID_CURSOR');query.set('limit','20');if(before!==null)query.set('before_id',String(before));
      const data=await request(base(id)+'/messages?'+query,ctx);readState(data.read_state);
      if(!Array.isArray(data.items)||data.items.length>20||typeof data.has_more!=='boolean'||data.has_more&&!positive(data.next_before_id)||meta.conversation_id!==null&&meta.conversation_id!==data.conversation_id)throw fail('CONTRACT_MISMATCH');
      const items=data.items.map(row=>message(row,data.conversation_id,ctx));
      if(items.some((row,i)=>before!==null&&row.id>=before||i>0&&row.id<=items[i-1].id)||data.has_more&&data.next_before_id!==items[0]?.id)throw fail('CONTRACT_MISMATCH');
      known.set(id,{scope:fingerprint(ctx),conversationId:data.conversation_id,canSend:meta.allowed_actions.send===true,canMarkRead:meta.allowed_actions.mark_read===true});
      return {items,unread:data.read_state.unread_count,hasMore:data.has_more,before:data.next_before_id,canSend:meta.allowed_actions.send===true,canMarkRead:meta.allowed_actions.mark_read===true};
    },
    prepare(id,text){const ctx=context(),entry=known.get(id);if(entry?.scope!==fingerprint(ctx)||!entry.canSend)throw fail('CONVERSATION_READ_REQUIRED');if(typeof text!=='string'||!text.trim()||[...text.trim()].length>4000)throw fail('INVALID_MESSAGE');return {contentId:id,scope:fingerprint(ctx),requestId:newId(),text:text.trim()};},
    async send(pending){const ctx=context();if(pending.scope!==fingerprint(ctx))throw fail('CONTEXT_CHANGED');const data=await request(base(pending.contentId)+'/messages',ctx,{tenant_id:ctx.tenantId,site_id:ctx.siteId,request_id:pending.requestId,body:pending.text});const row=message(data.message,known.get(pending.contentId)?.conversationId,ctx);if(!row.mine||row.text!==pending.text||typeof data.replayed!=='boolean')throw fail('CONTRACT_MISMATCH');return data;},
    async markRead(id,through){const ctx=context(),entry=known.get(id);if(entry?.scope!==fingerprint(ctx)||!entry.canMarkRead||!positive(through))throw fail('CONVERSATION_READ_REQUIRED');const data=await request(base(id)+'/read',ctx,{tenant_id:ctx.tenantId,site_id:ctx.siteId,last_read_message_id:through});if(data.conversation_id!==entry.conversationId)throw fail('CONTRACT_MISMATCH');return readState(data.read_state);},
  };
}
