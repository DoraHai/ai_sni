import {escapeText as esc} from './customer-display.mjs';
// Local guidance and explicit server-backed advisory chat never execute business actions.
export function createWorkspaceAssistant(root,getHome,{aiClient=null,getContentId=()=>null}={}){
 let draft='',history=[],collapsed=false,context='首页',fullscreen=false,width=null,drag=null;
 let mode=aiClient?'ai':'guide',aiHistory=[],pending=null,sending=false,feedback='',recoverable=false,generation=0;
 const sourceLinks={content:['稿件','内容'],selected_content:['当前稿件','内容'],tasks:['任务进度','进度'],pages:['网站页面','数据','pages'],keywords:['关键词','数据','keywords']};
 function aiMessages(){return aiHistory.map(m=>`<div class="bubble user">${esc(m.question)}</div><div class="bubble"><small>DeepSeek AI · 建议，未经业务执行</small><div class="assistant-ai-answer">${esc(m.answer)}</div>${m.sources.map(s=>{const [label,page,kind]=sourceLinks[s];return `<button data-action="home-data" data-page="${page}" ${kind?`data-kind="${kind}"`:''}>查看${label} ↗</button>`;}).join('')}</div>`).join('');}
 async function askAi(q,{retry=false}={}){
  if(sending||!q.trim()||(!retry&&pending))return;const stamp=generation;
  try{
   if(!retry){let turns=aiHistory.slice(-6).flatMap(m=>[{role:'user',content:m.question},{role:'assistant',content:m.answer}]);while(turns.reduce((n,t)=>n+t.content.length,0)>24000)turns.splice(0,2);pending=aiClient.prepare(q.trim().slice(0,1000),turns,getContentId());}
   sending=true;feedback='AI 正在回答…';collapsed=false;paint();
   const result=await aiClient.send(pending);if(stamp!==generation)return;
   aiHistory.push({question:pending.body.message,answer:result.answer,sources:result.sources});aiHistory=aiHistory.slice(-8);pending=null;draft='';feedback='';recoverable=false;
  }catch(e){if(stamp!==generation||e.code==='CONTEXT_CHANGED')return;
   recoverable=!e.status||e.code==='operation_running';
   const limitMessages={assistant_rate_limited:`提问较频繁，请${e.retryAfter?`等待 ${e.retryAfter} 秒`:'稍等片刻'}再发送，问题已保留。`,assistant_user_busy:'上一条问题仍在回答，请稍后再提问。',assistant_workspace_busy:'当前客户的 AI 正在处理其他问题，请稍后再试。',assistant_user_daily_limit:'今天的账号 AI 对话额度已用完，明天恢复，问题已保留。',assistant_tenant_daily_limit:'今天的客户 AI 对话额度已用完，明天恢复，问题已保留。',assistant_request_out_of_scope:'此对话支持当前客户的网站、SEO、推广策略和稿件；其他客户资料和系统内部信息不在可访问范围。'};
   feedback=limitMessages[e.code]||(e.code==='assistant_customer_binding_required'?'当前账号尚未绑定客户，请联系管理员核对账号绑定。':e.status===429?'AI 对话暂时受限，请稍后再试，问题已保留。':e.status===403?'当前身份没有此对话权限，请重新核对工作空间。':e.status===401?'登录已失效，请重新登录。':e.status===503?'AI 暂时不可用，问题已保留。':e.code==='operation_refunded'?'上次请求已结束且额度已退还，可重新提问。':recoverable?'回答结果尚未取得。可取回同一次请求，不会重复调用 AI。':'AI 未完成回答，问题已保留。');
   if(!recoverable)pending=null;
  }finally{if(stamp===generation){sending=false;paint();}}
 }
 function resizeInput(){const t=root.querySelector('#workspace-question');if(t){t.style.height='auto';t.style.height=Math.min(200,Math.max(96,t.scrollHeight))+'px';}}
 function layout(){
  const panel=root.querySelector('.workbench-dialogue'),workspace=root.querySelector('.workspace');
  if(!panel||!workspace)return;
  panel.classList.toggle('assistant-fullscreen',fullscreen);
  if(width!==null){width=Math.max(320,Math.min(width,Math.min(720,workspace.clientWidth*.55)));workspace.style.setProperty('--assistant-width',width+'px');}
  const handle=root.querySelector('.assistant-resizer');if(handle)handle.setAttribute('aria-valuenow',Math.round(panel.getBoundingClientRect().width));
 }
 function stopDrag(){if(!drag)return;try{drag.handle.releasePointerCapture(drag.id);}catch{}drag=null;}
 function pointer(e){const handle=e.target.closest('.assistant-resizer');if(!handle||fullscreen||innerWidth<=800||e.button!==0)return;e.preventDefault();drag={handle,id:e.pointerId,x:e.clientX,width:root.querySelector('.workbench-dialogue').getBoundingClientRect().width};handle.setPointerCapture(e.pointerId);}
 function move(e){if(!drag||e.pointerId!==drag.id)return;width=drag.width+drag.x-e.clientX;layout();}
 function key(e){
  if(e.key==='Escape'&&fullscreen){e.preventDefault();fullscreen=false;paint();root.querySelector('[data-assistant-action=fullscreen]')?.focus();return;}
  if(!e.target.matches('.assistant-resizer')||!['ArrowLeft','ArrowRight','Home'].includes(e.key))return;
  e.preventDefault();width=e.key==='Home'?440:root.querySelector('.workbench-dialogue').getBoundingClientRect().width+(e.key==='ArrowLeft'?24:-24);layout();
 }
 const prompts=['现在需要我做什么？','关键词表现怎么样？','发布进展如何？'];
 function reply(q){
  const h=getHome();if(!h)return {text:'当前数据尚未读完，请稍后再试。',page:'首页'};
  if(/词|排名|搜索/.test(q))return {text:h.keywords?'当前筛选有 '+h.keywords.total+' 个关键词，首页展示其中 '+h.keywords.items.length+' 个的观测。排名不等于点击；明细可看时间、名次和逐词历史。':'关键词数据未取得，请在数据页核对。',page:'数据',kind:'keywords'};
  if(/发布|交付/.test(q))return {text:h.publications?'当前网站有 '+h.publications.total+' 条发布记录。登记、页面检查和搜索效果分别判断。':'发布记录尚未取得，可进入交付记录查看。',page:'交付记录'};
  if(/页面|网站|问题/.test(q))return {text:'网站检查和待处理问题已放回首页，具体依据见页面明细。允许索引不等于搜索引擎已收录。',page:'数据',kind:'pages'};
  if(/进度|任务/.test(q))return {text:h.executions?'已登记 '+h.executions.total+' 项服务任务。查看进度可了解正在等待谁处理及完成依据。':'尚未取得任务数据，请查看进度读取状态。',page:'进度'};
  if(/稿|确认|需要|处理/.test(q)){const n=h.deliveries.filter(v=>v.workflow_status==='awaiting_customer_confirmation'&&(v.allowed_actions.confirm_as_customer||v.allowed_actions.confirm_as_advisor_proxy)).length;return {text:'本次已核对 '+h.deliveries.length+' 篇稿件，其中 '+n+' 篇可由当前身份确认。打开稿件可看全文、图片和与顾问沟通；确认不会发布文章。',page:'内容'};}
  return {text:'AI 自由问答尚未接通。当前只按已读数据提供导览，不会把问题发给模型或顾问。可问稿件、关键词、页面和进度；具体修改请打开稿件与顾问沟通。',page:'内容'};
 }
 function paint(){
  const target=root.querySelector('#workspace-assistant');if(!target)return;
  target.innerHTML=`<div class="assistant-heading"><div><b>获客推广 AI 智能体</b><small>AI 待接通 · 数据导览可用</small></div><button data-assistant-action="collapse" aria-expanded="${!collapsed}">${collapsed?'展开对话':'收起对话'}</button></div><div class="assistant-expanded" ${collapsed?'hidden':''}><p class="assistant-context">正在查看 · ${esc(context)}</p><div class="assistant-messages" aria-live="polite"><div class="bubble"><small>工作台导览 · 非 AI 回复</small>这里保留你的对话空间。可查看本期工作、定位数据，或打开稿件与顾问沟通。</div>${history.map(m=>`<div class="bubble user">${esc(m.question)}</div><div class="bubble"><small>工作台导览 · 根据已读数据</small>${esc(m.text)}<p><button data-action="home-data" data-page="${m.page}" ${m.kind?`data-kind="${m.kind}"`:''}>查看相关数据 ↗</button></p></div>`).join('')}</div><div class="assistant-composer"><div class="assistant-prompts">${prompts.map(p=>`<button data-assistant-prompt="${esc(p)}">${p}</button>`).join('')}</div><label for="workspace-question">问当前工作</label><textarea id="workspace-question" maxlength="1000" placeholder="例如：现在哪些稿件需要我确认？">${esc(draft)}</textarea><button data-assistant-action="ask" ${draft.trim()?'':'disabled'}>查看相关数据</button><small>当前仅在本页解读，不发送消息、不执行业务操作。</small></div></div>`;
  const list=target.querySelector('.assistant-messages');if(list)list.scrollTop=list.scrollHeight;
  if(aiClient){
   target.querySelector('.assistant-heading small').textContent=mode==='ai'?'AI 对话 · 当前客户与网站':'规则数据导览 · 非 AI 回复';
   const expanded=target.querySelector('.assistant-expanded');expanded.insertAdjacentHTML('afterbegin',`<div class="assistant-modes"><button data-assistant-action="mode-ai" aria-pressed="${mode==='ai'}">AI 对话</button><button data-assistant-action="mode-guide" aria-pressed="${mode==='guide'}">数据导览</button></div>`);
   if(mode==='ai'){
    list.innerHTML=`<div class="bubble"><small>AI 对话</small>可以连续提问当前客户的网站、SEO、推广策略和稿件。只读取当前客户、当前网站且你有权查看的数据；问题及相关数据过滤常见敏感信息后发送给 DeepSeek。回答是建议，确认和发布请在业务页面处理。当前窗口保留对话，切换工作空间或退出时清空。</div>${aiMessages()}${sending?`<div class="bubble user">${esc(pending?.body.message||draft)}</div>`:''}`;
    const composer=target.querySelector('.assistant-composer');composer.querySelector('[data-assistant-action=ask]').textContent=sending?'正在回答…':'发送给 AI';
    composer.querySelector('[data-assistant-action=ask]').disabled=sending||!!pending||!draft.trim();
    composer.querySelector('textarea').disabled=sending||!!pending;
    composer.querySelector('small').textContent='AI 仅提供解释和建议，不自动操作业务。';
    composer.insertAdjacentHTML('beforeend',`<p class="assistant-feedback" role="status">${esc(feedback)}</p>${pending&&!sending?'<button data-assistant-action="retry-ai">取回本次回答</button><button data-assistant-action="abandon-ai">放弃本次请求</button>':''}`);
    target.querySelectorAll('[data-assistant-prompt]').forEach(b=>b.disabled=sending||!!pending);
    list.scrollTop=list.scrollHeight;
   }
  }
  target.insertAdjacentHTML('afterbegin','<div class="assistant-resizer" role="separator" aria-label="调整对话宽度，左右方向键调整" aria-orientation="vertical" aria-valuemin="320" aria-valuemax="720" tabindex="0"></div>');
  const heading=target.querySelector('.assistant-heading');
  heading.insertAdjacentHTML('beforeend',`<button data-assistant-action="fullscreen" aria-pressed="${fullscreen}">${fullscreen?'恢复窗口':'全屏对话'}</button>`);
  layout();resizeInput();if(list)list.scrollTop=list.scrollHeight;
  target.querySelectorAll('[data-assistant-action^="mode-"]').forEach(b=>b.disabled=sending||!!pending);
 }
 function ask(q){if(mode==='ai'&&aiClient){void askAi(q);return;}if(!q.trim())return;history.push({question:q.slice(0,1000),...reply(q)});history=history.slice(-8);draft='';collapsed=false;paint();}
 function click(e){const p=e.target.closest('[data-assistant-prompt]');if(p&&!p.disabled){ask(p.dataset.assistantPrompt);return;}const b=e.target.closest('[data-assistant-action]');if(!b||b.disabled)return;const action=b.dataset.assistantAction;if(action.startsWith('mode-')){mode=action==='mode-ai'?'ai':'guide';paint();}else if(action==='retry-ai'){void askAi(pending.body.message,{retry:true});}else if(action==='abandon-ai'){pending=null;recoverable=false;feedback='已放弃取回；服务器可能已完成本次回答。';paint();}else if(action==='fullscreen'){fullscreen=!fullscreen;collapsed=false;paint();root.querySelector('[data-assistant-action=fullscreen]')?.focus();}else if(action==='collapse'){collapsed=!collapsed;paint();}else ask(draft);}
 function input(e){if(e.target.id!=='workspace-question')return;draft=e.target.value;resizeInput();const b=root.querySelector('[data-assistant-action=ask]');if(b)b.disabled=!draft.trim()||(mode==='ai'&&(sending||!!pending));}
 root.addEventListener('click',click);root.addEventListener('input',input);
 root.addEventListener('pointerdown',pointer);root.addEventListener('pointermove',move);root.addEventListener('pointerup',stopDrag);root.addEventListener('pointercancel',stopDrag);root.addEventListener('keydown',key);window.addEventListener('resize',layout);
 return {render(page){stopDrag();context=page;paint();},clear(){generation++;aiClient?.clear();aiHistory=[];pending=null;sending=false;feedback='';stopDrag();draft='';history=[];context='首页';fullscreen=false;paint();},dispose(){generation++;aiClient?.clear();stopDrag();root.removeEventListener('click',click);root.removeEventListener('input',input);root.removeEventListener('pointerdown',pointer);root.removeEventListener('pointermove',move);root.removeEventListener('pointerup',stopDrag);root.removeEventListener('pointercancel',stopDrag);root.removeEventListener('keydown',key);window.removeEventListener('resize',layout);draft='';history=[];aiHistory=[];pending=null;}};
}
