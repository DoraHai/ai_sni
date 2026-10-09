import {escapeText as esc} from './customer-display.mjs';
// Local read-only guidance. Never sends text or impersonates a model.
export function createWorkspaceAssistant(root,getHome){
 let draft='',history=[],collapsed=false,context='首页',fullscreen=false,width=null,drag=null;
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
  target.insertAdjacentHTML('afterbegin','<div class="assistant-resizer" role="separator" aria-label="调整对话宽度，左右方向键调整" aria-orientation="vertical" aria-valuemin="320" aria-valuemax="720" tabindex="0"></div>');
  const heading=target.querySelector('.assistant-heading');
  heading.insertAdjacentHTML('beforeend',`<button data-assistant-action="fullscreen" aria-pressed="${fullscreen}">${fullscreen?'恢复窗口':'全屏对话'}</button>`);
  layout();resizeInput();
 }
 function ask(q){if(!q.trim())return;history.push({question:q.slice(0,1000),...reply(q)});history=history.slice(-8);draft='';collapsed=false;paint();}
 function click(e){const p=e.target.closest('[data-assistant-prompt]');if(p){ask(p.dataset.assistantPrompt);return;}const b=e.target.closest('[data-assistant-action]');if(!b||b.disabled)return;if(b.dataset.assistantAction==='fullscreen'){fullscreen=!fullscreen;collapsed=false;paint();root.querySelector('[data-assistant-action=fullscreen]')?.focus();}else if(b.dataset.assistantAction==='collapse'){collapsed=!collapsed;paint();}else ask(draft);}
 function input(e){if(e.target.id!=='workspace-question')return;draft=e.target.value;resizeInput();const b=root.querySelector('[data-assistant-action=ask]');if(b)b.disabled=!draft.trim();}
 root.addEventListener('click',click);root.addEventListener('input',input);
 root.addEventListener('pointerdown',pointer);root.addEventListener('pointermove',move);root.addEventListener('pointerup',stopDrag);root.addEventListener('pointercancel',stopDrag);root.addEventListener('keydown',key);window.addEventListener('resize',layout);
 return {render(page){stopDrag();context=page;paint();},clear(){stopDrag();draft='';history=[];context='首页';fullscreen=false;paint();},dispose(){stopDrag();root.removeEventListener('click',click);root.removeEventListener('input',input);root.removeEventListener('pointerdown',pointer);root.removeEventListener('pointermove',move);root.removeEventListener('pointerup',stopDrag);root.removeEventListener('pointercancel',stopDrag);root.removeEventListener('keydown',key);window.removeEventListener('resize',layout);draft='';history=[];}};
}
