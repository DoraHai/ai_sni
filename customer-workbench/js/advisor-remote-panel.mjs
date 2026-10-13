import {createAdvisorRemoteSession} from './advisor-remote-session.mjs';
import {createAdvisorRemoteProvider} from './advisor-remote-provider.mjs';
import {advisorRemoteView} from './advisor-remote-view.mjs';
import {escapeText as esc} from './customer-display.mjs';
import {createRemotePoller} from './advisor-remote-poller.mjs';
export function createAdvisorRemotePanel({root,session,subscribeSession,getContext,getTasks=()=>[],browser=window,fetchImpl=fetch}){
  let disposed=false,scopeStamp='',busy=false,note='';
  const contextKey=()=>JSON.stringify([getContext(),getTasks()]);
  const controller=createAdvisorRemoteSession({getAuthContext:()=>[session.token,session.user?.id,session.authRevision,session.tenantId,session.modules,contextKey()],provider:createAdvisorRemoteProvider({session,fetchImpl,origin:browser.location.origin}),onChange:()=>render()});
  const poller=createRemotePoller({controller,browser,onError:()=>{note='画面暂不可用，等待新鲜画面核验；不会重发输入。';render();}});
  function render(){if(disposed)return;const host=root.querySelector('.advisor-remote-host');if(!host)return;const s=controller.snapshot(),old=host.querySelector('[data-remote-text]'),value=s.canInput&&!busy?old?.value||'':'',focused=old===browser.document.activeElement;host.innerHTML=advisorRemoteView(s)+`<p role="status" data-remote-note></p><button data-remote-action="open" ${busy||!!s.session||!session.token||!getContext()?'disabled':''}>打开当前账号远程登录</button><button data-remote-action="verify" ${busy||!!s.session||!session.token||!getContext()?'disabled':''}>验证码与账号异常介入</button>${getTasks().map(task=>`<p>任务 ${esc(task.id)} · ${task.action==='handoff'?'素材交接':'预检'} · ${esc(task.status)} <button data-remote-action="task" data-task-id="${esc(task.id)}" ${busy||!!s.session||!session.token||!getContext()?'disabled':''}>介入此任务账号窗口</button></p>`).join('')}`;host.querySelector('[data-remote-note]').textContent=note;const next=host.querySelector('[data-remote-text]');if(value&&next){next.value=value;if(focused)next.focus({preventScroll:true});}}
  function invalidate(){poller.pause();scopeStamp=contextKey();controller.invalidate('context-changed');note='账号范围或登录状态已变化，画面与输入已清除。';render();}
  const stop=subscribeSession?.(invalidate);
  async function perform(fn){if(busy)return;poller.pause();busy=true;note='正在等待服务器核验…';render();try{await fn();note='会话状态已读取；正式发布仍关闭。';}catch(e){note=e.code==='NOT_INTEGRATED'?'远程能力未启用或尚未接入。':e.code==='REMOTE_CONFLICT'?'画面或账号状态已变化，请刷新核验。':'操作未完成，请重新核验账号；不会自动重发输入。';}finally{busy=false;render();if(!disposed)poller.resume();}}
  function click(e){const b=e.target.closest('[data-remote-action],.advisor-remote-frame');if(!b||b.disabled)return;const s=controller.snapshot();
    if(b.classList.contains('advisor-remote-frame')){if(!s.canInput||!s.viewport)return;const rect=b.getBoundingClientRect();if(rect.width<=0||rect.height<=0)return;void perform(()=>controller.input({kind:'mouse',event:'click',button:'left',x:Math.floor((e.clientX-rect.left)*s.viewport.width/rect.width),y:Math.floor((e.clientY-rect.top)*s.viewport.height/rect.height)}));return;}
    const action=b.dataset.remoteAction;
    if(action==='task'){const c=getContext(),task=getTasks().find(t=>t.id===b.dataset.taskId);scopeStamp=contextKey();if(c&&task)void perform(()=>controller.open(c,'task-intervention',{task_id:task.id,expected_source_revision:task.source_revision,expected_content_digest:task.content_digest}));}
    if(['open','verify'].includes(action)){const c=getContext();scopeStamp=contextKey();if(c)void perform(()=>controller.open(c,action==='open'?'account-login':'account-verification'));}
    if(action==='refresh')void perform(async()=>{await controller.status();await controller.frame();});
    if(action==='close')void perform(()=>controller.close());
    if(action==='key')void perform(()=>controller.input({kind:'key',key:b.dataset.key}));
    if(action==='text'){const el=root.querySelector('[data-remote-text]'),text=el?.value||'';if(el)el.value='';if(text)void perform(()=>controller.input({kind:'text',text}));}
  }
  const timer=browser.setInterval(()=>{if(disposed)return;const stamp=contextKey();if(stamp!==scopeStamp){invalidate();return;}controller.snapshot();},500);
  scopeStamp=contextKey();root.addEventListener('click',click);
  return {render,invalidate,dispose(){disposed=true;poller.dispose();browser.clearInterval(timer);stop?.();controller.dispose();root.removeEventListener('click',click);root.querySelector('.advisor-remote-host')?.replaceChildren();}};
}
