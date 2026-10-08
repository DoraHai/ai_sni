export function handleUi15({url,req,res,send,body,state,tenant,site,advisor}){
  const match=url.pathname.match(/^\/api\/v1\/seo\/workbench\/content-assets\/(\d+)\/conversation(?:\/(messages|read))?$/);if(!match)return false;
  const content=state.contents.get(tenant),user=advisor?7:12;
  if(state.messageDenied){send(403,{detail:{code:'conversation_forbidden'}});return true;}
  if(Number(match[1])!==content.id||Number(url.searchParams.get('site_id')??body?.site_id)!==site){send(404,{detail:{code:'conversation_content_not_found'}});return true;}
  state.messages??=new Map();state.messageRead??=new Map();const items=state.messages.get(tenant)||[],conversationId=items.length?tenant:null;
  const readState=()=>({last_read_message_id:state.messageRead.get(`${tenant}:${user}`)||0,latest_message_id:items.at(-1)?.id||null,unread_count:items.filter(m=>m.sender.id!==user&&m.id>(state.messageRead.get(`${tenant}:${user}`)||0)).length});
  if(!match[2]){send(200,{scope:{tenant_id:tenant,site_id:site,content_id:content.id},conversation_id:conversationId,actor:{id:user,name:advisor?'顾问实名':'客户实名',kind:advisor?'advisor':'customer'},allowed_actions:{read:true,send:true,mark_read:true},read_state:readState(),semantics:'human_messages_only'});return true;}
  if(match[2]==='messages'&&req.method==='GET'){
    const before=Number(url.searchParams.get('before_id'))||Infinity,limit=Number(url.searchParams.get('limit'))||20,rows=items.filter(m=>m.id<before),page=rows.slice(-limit);
    send(200,{conversation_id:conversationId,items:page,has_more:rows.length>limit,next_before_id:page[0]?.id||null,read_state:readState()});return true;
  }
  if(match[2]==='messages'&&req.method==='POST'){
    state.messageKeys??=new Map();const key=`${tenant}:${user}:${body.request_id}`,existing=state.messageKeys.get(key);
    if(existing&&existing.body!==body.body){send(409,{detail:{code:'message_request_conflict'}});return true;}
    const row=existing||{id:(state.messageCounter??100)+1,conversation_id:tenant,body:body.body,sender:{id:user,name:advisor?'顾问实名':'客户实名',kind:advisor?'advisor':'customer'},created_at:'2026-10-08T12:00:00Z'};
    if(!existing){state.messageCounter=row.id;items.push(row);state.messages.set(tenant,items);state.messageKeys.set(key,row);}
    if(state.messageDropOnce){const mode=state.messageDropOnce;state.messageDropOnce=false;if(mode==='status')send(500,{detail:'Committed response unavailable'});else res.destroy();return true;}
    send(200,{message:row,replayed:!!existing});return true;
  }
  if(match[2]==='read'&&req.method==='POST'){
    if(!items.some(m=>m.id===body.last_read_message_id)){send(404,{detail:{code:'conversation_cursor_not_found'}});return true;}
    state.messageRead.set(`${tenant}:${user}`,Math.max(state.messageRead.get(`${tenant}:${user}`)||0,body.last_read_message_id));send(200,{conversation_id:conversationId,read_state:readState()});return true;
  }
  send(405,{detail:'Method not allowed'});return true;
}
