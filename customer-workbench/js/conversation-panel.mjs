import {conversationView} from './conversation-view.mjs';

// Text and retry keys belong only to this authenticated, mounted content scope.
export function createConversationPanel({root,host,client}){
  let generation=0,key=null,state=fresh();
  function fresh(){return {context:null,open:false,busy:false,draft:'',pending:null,error:'',notice:'',items:[],unread:0,hasMore:false,before:null,canSend:false};}
  function clear(){generation++;key=null;state=fresh();client.clear();paint();}
  function paint(){const target=root.querySelector('#conversation-panel');if(target)target.innerHTML=conversationView(state);}
  async function run(action){
    if(state.busy||!state.context)return;const stamp=generation;state.busy=true;state.error='';state.notice='';paint();
    try{await action(()=>stamp===generation);}catch(error){if(stamp!==generation)return;if(error.status===422)state.pending=null;state.error=state.notice==='消息已发送。'?'消息已发送，但记录刷新失败，请刷新消息核对。':error.status===503?'消息功能尚未启用，请稍后刷新。':error.status===403?'沟通权限已变化，请重新进入当前客户空间。':error.status===409?'这条消息的重试凭据不一致，请刷新记录核对。':error.code==='INVALID_MESSAGE'||error.status===422?'请填写1–4000字的消息。':state.pending?'发送结果未确认，文字已保留。请重试同一条消息核对结果。':'消息请求未完成，请重试。';}
    finally{if(stamp===generation){state.busy=false;paint();}}
  }
  function accept(data,older=false){state.items=older?[...data.items,...state.items].filter((item,i,all)=>all.findIndex(other=>other.id===item.id)===i):data.items;state.unread=data.unread;state.hasMore=data.hasMore;state.before=data.before;state.canSend=data.canSend;state.canMarkRead=data.canMarkRead;}
  async function load(older=false){await run(async current=>{const data=await client.list(state.context.contentId,older?state.before:null);if(current())accept(data,older);});}
  async function click(event){
    const button=event.target.closest('[data-chat-action]');if(!button||button.disabled||state.busy)return;
    const action=button.dataset.chatAction;
    if(action==='refresh'||action==='older'){await load(action==='older');return;}
    if(action==='read'){
      if(!state.open||!state.items.length)return;
      const through=Math.max(...state.items.map(item=>item.id));
      await run(async current=>{await client.markRead(state.context.contentId,through);if(!current())return;const data=await client.list(state.context.contentId);if(current()){accept(data);state.notice='已更新本人已读位置。';}});return;
    }
    if(action==='send'){
      if(!state.canSend||!state.draft.trim())return;
      await run(async current=>{
        state.pending??=client.prepare(state.context.contentId,state.draft);
        await client.send(state.pending);if(!current())return;
        state.pending=null;state.draft='';state.notice='消息已发送。';
        // Sending and reading are separate actions; this GET never advances read state.
        const data=await client.list(state.context.contentId);if(current()){accept(data);state.notice='消息已发送。';}
      });
      root.querySelector('#conversation-draft')?.focus({preventScroll:true});
    }
  }
  function input(event){if(event.target.id!=='conversation-draft'||state.pending)return;state.draft=event.target.value;const send=root.querySelector('[data-chat-action=send]');if(send)send.disabled=state.busy||!state.canSend||!state.draft.trim();}
  function toggle(event){if(event.target.matches?.('.conversation'))state.open=event.target.open;}
  function unload(event){if(state.draft||state.pending){event.preventDefault();event.returnValue='';}}
  root.addEventListener('click',click);root.addEventListener('input',input);root.addEventListener('toggle',toggle,true);window.addEventListener('beforeunload',unload);
  return {
    clear,
    render(context){const scope=host.getContext();const next=context&&scope?JSON.stringify([scope.tenantId,scope.siteId,scope.userId,scope.revision,context.contentId]):null;if(next!==key){clear();key=next;if(next){state.context=context;paint();void load();}}else{if(context)state.context=context;paint();}},
    leave(){return !state.draft&&!state.pending||window.confirm('还有未发送或结果未确认的沟通文字。确定离开并清除这些文字？');},
    dispose(){clear();root.removeEventListener('click',click);root.removeEventListener('input',input);root.removeEventListener('toggle',toggle,true);window.removeEventListener('beforeunload',unload);},
  };
}
