import {createSeoWorkflowClient} from './seo-workflow-client.mjs';
import {createSeoContentReader} from './seo-readonly-client.mjs';
import {createServicePlanController} from './service-plan-controller.mjs';
import {contentDeliveryView,serviceStatusView} from './seo-contract-view.mjs';
import {createSeoExecutionClient} from './seo-execution-client.mjs';
import {executionListView,executionDetailView} from './seo-execution-view.mjs';
import {contentOperationsView,publicationsView,isAssignedAdvisor} from './seo-content-operations-view.mjs';
import {createSeoTriggerClient} from './seo-trigger-client.mjs';
import {aiPlanView,triggerView} from './seo-ai-plan-view.mjs';
import {cycleForm} from './seo-cycle-config.mjs';

const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const btn=(label,action,attrs='')=>`<button data-action="${action}" ${attrs}>${label}</button>`;
const names={'SEO-A01':'资料与服务计划','SEO-A02':'网站检查','SEO-A03':'关键词与搜索','SEO-A04':'内容','SEO-A05':'发布核验','SEO-A06':'数据报告','SEO-A07':'异常与运行'};
const executionErrors={report_version_conflict:'报告版本已变化，请重新读取后填写说明',REPORT_VERSION_MISMATCH:'报告文件与已读取哈希不一致，请重新读取核对',INVALID_REPORT_EXPLANATION:'请填写1–4000字的顾问说明',EXECUTION_REQUIRED:'操作资格已失效，请重新读取任务',INVALID_CYCLE_CONFIG:'周期范围不符合限制，请检查间隔与页面数量'};
const workflowErrors={INVALID_AI_SELECTION:'请选择1–20条已读资料和1–5个本站关键词',AI_SELECTION_READ_REQUIRED:'资料或关键词尚未读取、已过期或不在本站，请重新读取并选择',AI_CONFIGURE_DENIED:'当前无权配置AI草稿；请重新读取资格',AI_MATERIAL_TOO_LARGE:'所选资料超过总量限制，请减少资料',INVALID_PUBLICATION_INPUT:'请填写真实平台、公开链接和北京时间，并勾选已人工核实',TRIGGER_OUTCOME_UNRESOLVED:'上次触发结果未知，请读取执行进度核对，不重发',content_version_precondition_required:'缺少准确版本前提，请重新读取稿件',PUBLICATION_SELECTION_REQUIRED:'请先读取并选择本任务的发布记录'};
const failure=e=>workflowErrors[e.code]||executionErrors[e.code]||({INVALID_CONTENT:'请填写1–300字的标题，检查正文与提纲',CONTENT_VERSION_OR_SCOPE_MISMATCH:'稿件版本或范围已变化，请重新读取核对',ADVISOR_REQUIRED:'当前身份未取得该站点顾问资格',CONTENT_PROTECTED:'稿件受保护，请先按明确退回流程处理'}[e.code])||(e.code==='content_version_conflict'?'稿件版本已变化，请重新读取后确认':e.code==='service_plan_version_conflict'?'服务计划已被更新，请重新读取':e.code==='REJECTION_NOTE_REQUIRED'?'退回必须填写意见':e.code==='WRITE_OUTCOME_UNKNOWN'?'写入结果未知，请重新读取核对，不自动重试':e.status===409?'内容状态或版本已变化，请重新读取核对':e.status===503?'服务能力尚未启用':e.status===403?'权限或顾问资格已变化，请重新读取':e.code==='CONFIRMATION_UNAVAILABLE'?'确认能力未启用':e.code==='MODULE_UNAVAILABLE'?'当前未开通SEO；SEM/GEO连接能力待接入':(e.code||e.message)==='READ_FAILED'?'读取失败，请重试当前页面':`请求未完成：${e.code||e.message}`);

export function mountConnectedWorkbench({root,host,environmentLabel,demoHref='index.html'}) {
  const client=createSeoWorkflowClient({transport:host.transport,getContext:host.getContext});
  const triggerClient=createSeoTriggerClient({transport:host.transport,getContext:host.getContext});
  const reader=createSeoContentReader({transport:host.transport,getContext:host.getContext});
  const controller=createServicePlanController(client);
  const executionClient=createSeoExecutionClient({transport:host.transport,getContext:host.getContext});
  let identity=null,page='首页',contents=null,delivery=null,status=null,busy=false,message='',epoch=0,level='L1',listPage=1,selectedContentId=null;
  let editor=null,publicationRecords=null,publicationAttempts=null,manualDraft=null,publicationReceipt=null;
  let aiDraft=null,aiMaterial=null,planDraft=null,triggerActions=null;
  let executionPublications=null;
  let executions=null,execution=null,executionPage=1,selectedTaskId=null;
  const clear=()=>{aiDraft=null;aiMaterial=null;planDraft=null;triggerActions=null;triggerClient.invalidate();manualDraft=null;publicationReceipt=null;editor=null;publicationRecords=null;publicationAttempts=null;client.invalidate();identity=null;contents=null;delivery=null;status=null;listPage=1;selectedContentId=null;controller.invalidate();reader.invalidate();executionClient.invalidate();executionPublications=null;executions=null;execution=null;executionPage=1;selectedTaskId=null;};
  function render(){
    const connection=host.getState();
    root.innerHTML=`<div class="connected-notice">${esc(environmentLabel)} · 数据和操作只来自契约接口 · 无演示回退</div><header><b>G-SNIPERS</b><span>客户工作台</span><small id="identity">${identity?`${esc(identity.user.display_name||identity.user.username||identity.user.id)} · ${esc(identity.tenant.name||identity.tenant.id)} / ${esc(identity.site.name)}`:'尚未取得授权身份'}</small>${demoHref?`<a href="${esc(demoHref)}">独立演示模式</a>`:''}</header><div class="workspace"><main class="connected-main"><div id="connected-message" class="connected-status" role="status">${esc(message)}</div><div id="connected-content"></div></main><aside class="chat"><div class="chat-head"><b>本客户空间 · 对话</b><small>消息接口尚未接入</small></div><div class="messages"><p>顾问与客户消息、内部备注及发送回执待接入。</p></div><div class="composer"><textarea aria-label="消息未接入" disabled placeholder="暂未接入"></textarea><button disabled>发送（未接入）</button></div></aside></div>`;
    const main=root.querySelector('#connected-content');
    const modules=document.createElement('div');modules.className='module-navigation';modules.setAttribute('aria-label','服务模块');modules.innerHTML=['sem','seo','geo'].map(code=>{const item=connection.modules?.find(m=>m.module_code===code);const label=!connection.modulesChecked?'待核验':!item?.available?'未开通':code!=='seo'?'已开通 · 待接入':identity?'可使用':'待完成范围核验';return btn(`${code.toUpperCase()} · ${label}`,'page',`data-page="首页" data-module="${code}" ${code==='seo'&&identity&&!busy?'':'disabled'}`);}).join('');main.before(modules);
    if(!identity){
      const labels={disconnected:'未连接宿主身份',unauthenticated:'尚未登录，请使用现有登录入口',forbidden:'当前身份无权进入此客户空间',scope_required:'请在宿主选择获授权客户与站点',connecting:'正在核验身份、模块和客户范围',connection_error:'连接未完成，请重试',module_pending:'已开通模块尚未接入此入口'};
      main.innerHTML=`<section class="connected-state"><h2>${labels[connection.phase]||'未连接'}</h2><p>请从现有工作台进入已选择的客户与站点。</p><a href="/workspace/cockpit">返回现有工作台</a>${btn('前往现有登录','login')}${btn('重新连接','connect',busy?'disabled':'')}</section>`;return;
    }
    const siteRead=['view','edit'].includes(identity.user.permissions['seo.site']);
    main.innerHTML=`<div class="navigation">${['首页','内容','SEO工作','进度','数据','服务计划','交付记录'].map(n=>btn(n,'page',`data-page="${n}" ${busy||(!siteRead&&['SEO工作','进度','数据','服务计划'].includes(n))?'disabled':''}`)).join('')}</div><section id="page" class="page-card"></section>`;
    const panel=root.querySelector('#page');
    if(page==='首页'||page==='内容'){
      panel.innerHTML=`<h2>${page==='首页'?'当前客户 · 稿件与待办':'内容'}</h2><p>客户确认稿件，顾问可以代确认；发布状态另按实际记录展示。</p>${contents?`<small id="pagination-summary">第${listPage}页${listPage>Math.max(1,Math.ceil(contents.total/50))?'（列表已变化，请返回前页）':` / 共${Math.max(1,Math.ceil(contents.total/50))}页`} · 本页${contents.items.length}篇 / 共${contents.total}篇 · 每页50篇</small>${contents.items.map(item=>`<div class="task-item"><div class="task-content"><b>${esc(item.title||`稿件${item.id}`)}</b><p>v${esc(item.version_count)} · ${esc(item.status)}</p></div>${btn('查看准确交付稿','delivery',`data-id="${item.id}" ${busy?'disabled':''}`)}</div>`).join('')||'<p>当前授权范围没有稿件。</p>'}`:`<p>第${listPage}页尚未读取，请重试。</p>`}<div class="pagination">${btn('上一页','list-page',`data-number="${listPage-1}" ${busy||listPage<=1?'disabled':''}`)}${btn('下一页','list-page',`data-number="${listPage+1}" ${busy||!contents||listPage*50>=contents.total?'disabled':''}`)}${btn('刷新本页','refresh',busy?'disabled':'')}</div><p><button disabled>基础资料（未接入）</button> <button disabled>关键词维护（未接入）</button></p>`;
    }else if(page==='稿件'){
      if(!delivery){panel.innerHTML=`<p>稿件数据未取得或已失效，请重新读取核对。</p>${selectedContentId?btn('重新读取交付稿','delivery',`data-id="${selectedContentId}" ${busy?'disabled':''}`):''}${btn('返回列表','page','data-page="内容" '+(busy?'disabled':''))}`;return;}
      const view=contentDeliveryView(delivery),allowed=key=>!busy&&view.actions.includes(key);
      panel.innerHTML=`<h2>${esc(delivery.content.title)}</h2><p>准确版本 <b>v${view.version}</b> · ${esc(view.workflowStatus)}</p><small>摘要：${esc(view.hash)} · 服务端更新 ${esc(delivery.content.updated_at||'未知')}</small><pre id="delivery-body">${esc(view.body)}</pre>${view.capabilityMessage?`<p>${esc(view.capabilityMessage)}</p>`:''}${view.confirmation?`<div class="${view.confirmation.approvedCurrent?'confirmed':'phase-row'}">${esc(view.confirmation.label)} · ${esc(view.confirmation.actorName)}（actor ${view.confirmation.actorId}） · v${view.confirmation.version}<p>${esc(view.confirmation.at||'时间未提供')} · 状态 ${esc(view.confirmationStatusLabel)}</p></div>`:''}<p>确认不等于发布。发布事实：${esc(view.resultBasis?.publication_status||'未提供')}；页面核验：${esc(view.resultBasis?.page_check_status||'未提供')}</p><label for="decision-note">确认或退回意见</label><textarea id="decision-note" ${busy?'disabled':''}></textarea><div class="actions">${btn(`本人确认 v${view.version}`,'confirm','data-mode="customer_direct" '+(allowed('confirm_as_customer')?'':'disabled'))}${btn(`顾问代确认 v${view.version}`,'confirm','data-mode="advisor_proxy" '+(allowed('confirm_as_advisor_proxy')?'':'disabled'))}${btn('本人退回稿件','reject','data-mode="customer_direct" '+(allowed('reject_as_customer')?'':'disabled'))}${btn('顾问代退回','reject','data-mode="advisor_proxy" '+(allowed('reject_as_advisor_proxy')?'':'disabled'))}${btn('顾问复核通过','review',allowed('review')&&isAssignedAdvisor(delivery)?'':'disabled')}${btn('复核退回修改','review-reject',allowed('review')&&isAssignedAdvisor(delivery)?'':'disabled')}</div>${contentOperationsView(delivery,editor,busy)}${publicationsView(delivery,publicationRecords,publicationAttempts,busy,manualDraft,publicationReceipt)}${btn('重新读取交付稿','delivery',`data-id="${view.id}" ${busy?'disabled':''}`)}`;
    }else if(page==='进度'){
      panel.innerHTML=executionListView(executions,executionPage,busy);
    }else if(page==='执行详情'){
      panel.innerHTML=executionDetailView(execution,selectedTaskId,busy,executionPublications);
    }else if(page==='服务计划'){
      const state=controller.getState(),view=state.view?{...state.view,...planDraft}:null;
      panel.innerHTML=`<h2>服务计划</h2><p id="plan-message">${esc(state.message)}</p>${view?`<p>revision ${view.revision} · 更新人 ${esc(view.updatedBy??'未提供')} · ${esc(view.updatedAt||'时间未提供')}</p><label for="plan-directions">优化方向（每行一个）</label><textarea id="plan-directions" ${state.canSave&&!busy?'':'disabled'}>${esc(view.optimizationDirections.join('\n'))}</textarea><label for="plan-topics">内容选题（每行一个）</label><textarea id="plan-topics" ${state.canSave&&!busy?'':'disabled'}>${esc(view.contentTopics.join('\n'))}</textarea><label for="plan-note">服务备注</label><textarea id="plan-note" ${state.canSave&&!busy?'':'disabled'}>${esc(view.serviceNote)}</textarea><label for="plan-status">服务状态</label><select id="plan-status" ${state.canSave&&!busy?'':'disabled'}><option value="active" ${view.status==='active'?'selected':''}>运行</option><option value="paused" ${view.status==='paused'?'selected':''}>暂停后续采集调度</option></select><p>${esc(view.disabledMessage||'本次编辑资格由服务端提供，保存时仍会重检。')}</p>${cycleForm(view.cycles,!state.canSave||busy,identity.user.permissions['seo.keywords']==='edit')}${aiPlanView(view.ai,aiDraft,aiMaterial,busy,state.canSave)}${btn('保存服务计划（含本次AI授权变更）','save-plan',state.canSave&&!busy?'':'disabled')}`:''}${btn('重新读取计划与资格','refresh-plan',busy?'disabled':'')}${triggerView(triggerActions,triggerClient.pending(),busy)}<p>资料和关键词维护入口尚未接入；上述选择使用同站点的已读记录，不生成客户审批。</p>`;
    }else if(['SEO工作','数据'].includes(page)){
      const phases=status?serviceStatusView(status):[];
      panel.innerHTML=`<h2>${page==='SEO工作'?'SEO 工作 · 服务准备情况':'固定数据入口'}</h2><p>ready是持久化事实就绪，不能当作任务完成。A04稿件以交付稿为准。</p><div class="data-links">${['L1','L2','L3'].map(l=>btn(l,'level',`data-level="${l}" ${busy?'disabled':''}`)).join('')}</div><p>数据层 ${level} · 读取时间 ${esc(status?.read_at||'未知')}</p>${phases.map(p=>`<div class="phase-row"><b>${esc(names[p.id]||p.id)} · ${esc(p.label)}</b><p>观察时间 ${esc(p.asOf||'未知')} · 缺项 ${esc(p.blockers.join('、')||'未列出')}</p>${level==='L2'?`<pre>${esc(JSON.stringify(p.facts,null,2))}</pre>`:''}${level==='L3'?`<p>证据引用（读取页面未挂载）</p><pre>${esc(JSON.stringify(p.evidenceEndpoints,null,2))}</pre><p>任务完成口径：${esc(p.semantics?.task_completion||'未提供')}</p>`:''}<small>负责人/时间线：未提供；不合成完成记录。</small></div>`).join('')||'<p>服务准备结果未读取。</p>'}${btn('重新读取状态','refresh',busy?'disabled':'')}${btn('进入内容交付','page','data-page="内容" '+(busy?'disabled':''))}`;
    }else{
      const view=delivery?contentDeliveryView(delivery):null;
      panel.innerHTML=`<h2>交付记录</h2><p>完整发布/核验/报告历史尚未挂载。当前只展示本次已读取稿件的确认记录，不是全部交付。</p>${view?.confirmation?`<div class="record">${esc(view.confirmation.label)} · ${esc(view.confirmation.actorName)} · v${view.confirmation.version} · ${esc(view.confirmationStatus)}<p>${esc(view.confirmation.at)} · 发布事实 ${esc(view.resultBasis?.publication_status||'未提供')}</p></div>`:'<p>当前没有已读取的确认记录。</p>'}<p>客户不需额外报告签收。</p>`;
    }
  }
  async function run(action){const stamp=++epoch;busy=true;message='正在读取或等待服务器结果…';render();try{await action(()=>stamp===epoch);if(stamp===epoch)message='';}catch(e){if(stamp===epoch){message=failure(e);manualDraft=null;publicationReceipt=null;triggerActions=null;triggerClient.invalidate();aiDraft=null;aiMaterial=null;planDraft=null;delivery=null;editor=null;publicationRecords=null;publicationAttempts=null;if(controller.getState().phase==='error')client.invalidate();else controller.invalidate();execution=null;executionClient.invalidate();}}finally{if(stamp===epoch){busy=false;render();}}}
  async function connect(){const stamp=++epoch;clear();busy=true;message='正在核验现有会话…';render();try{const result=await host.initialize();if(stamp!==epoch)return;identity=result.identity??null;page='首页';if(identity){contents=await reader.contents();}if(stamp===epoch)message='';}catch(e){if(stamp===epoch){clear();message=failure(e);}}finally{if(stamp===epoch){busy=false;render();}}}
  async function navigate(next){page=next;if(next==='进度')executions=null;if(next==='服务计划'){aiDraft=null;aiMaterial=null;planDraft=null;triggerActions=null;}if(['首页','内容'].includes(next))contents=null;if(['SEO工作','数据'].includes(next))status=null;await run(async current=>{if(['首页','内容'].includes(next)){const data=await reader.contents({page:listPage});if(current())contents=data;}else if(next==='进度'){const data=await executionClient.list({page:executionPage});if(current()){executions=data;triggerClient.reconcile(data.items);}}else if(next==='服务计划'){await controller.load();const actions=await triggerClient.load(controller.getState().view?.revision);if(current())triggerActions=actions;}else if(['SEO工作','数据'].includes(next)){const data=await client.serviceStatus();if(current())status=data;}});}
  const unsubscribe=host.subscribe(({reason})=>{epoch++;busy=false;clear();message=reason==='forbidden'?'权限已失效，已清空当前客户数据':reason==='expired'?'登录已过期，已清空数据':'身份或客户范围已变化，旧数据已清除';render();if(reason==='context_changed')queueMicrotask(connect);});
  root.addEventListener('input',event=>{
    const el=event.target;
    if(page==='服务计划'){
      const view=controller.getState().view;
      if(el.id.startsWith('plan-')||el.dataset.cycle){planDraft??={optimizationDirections:[...view.optimizationDirections],contentTopics:[...view.contentTopics],serviceNote:view.serviceNote,status:view.status,cycles:{...view.cycles}};const key={'plan-directions':'optimizationDirections','plan-topics':'contentTopics','plan-note':'serviceNote','plan-status':'status'}[el.id];if(key)planDraft[key]=['optimizationDirections','contentTopics'].includes(key)?el.value.split('\n'):el.value;if(el.dataset.cycle)planDraft.cycles[el.dataset.cycle]=el.type==='checkbox'?el.checked:Number(el.value);}
      if(el.id==='ai-enabled'||el.dataset.aiFact||el.dataset.aiKeyword){aiDraft??={enabled:view.ai.enabled,factIds:[...view.ai.factIds],keywordIds:[...view.ai.keywordIds],dirty:false};aiDraft.dirty=true;if(el.id==='ai-enabled')aiDraft.enabled=el.checked;else{const key=el.dataset.aiFact?'factIds':'keywordIds',id=Number(el.dataset.aiFact||el.dataset.aiKeyword);aiDraft[key]=el.checked?[...new Set([...aiDraft[key],id])]:aiDraft[key].filter(v=>v!==id);if(el.dataset.aiFact&&!el.checked&&aiMaterial?.facts.find(f=>f.id===id)?.current!==true)el.disabled=true;}}
    }
    if(aiDraft&&root.querySelector('#ai-selected-count'))root.querySelector('#ai-selected-count').textContent=`已选 ${aiDraft.factIds.length} 条资料、${aiDraft.keywordIds.length} 个关键词。改选并保持开启时，保存将重新记录本次明确授权。`;
    if(manualDraft){const key={'manual-platform':'platformName','manual-url':'pageUrl','manual-time':'localTime','manual-verified':'verified'}[el.id];if(key)manualDraft[key]=el.type==='checkbox'?el.checked:el.value;}
if(editor){const field={'content-title':'title','content-outline':'outline','content-body':'body'}[event.target.id];if(field)editor[field]=event.target.value;}});
  root.addEventListener('click',async event=>{
    const el=event.target.closest('[data-action]');if(!el||el.disabled)return;const a=el.dataset.action;
    if(a==='login'){host.login();return;}if(a==='connect'){await connect();return;}if(busy)return;
    if(a==='page'){await navigate(el.dataset.page);return;}
    if(a==='execution-detail'){executionPublications=null;const id=Number(el.dataset.id);selectedTaskId=id;page='执行详情';execution=null;await run(async current=>{const data=await executionClient.detail(id);if(current())execution=data;});return;}
    if(a==='execution-publications'){executionPublications=null;await run(async current=>{const items=await executionClient.publicationOptions(selectedTaskId);if(current())executionPublications=items;});return;}
    if(a==='execution-page'){executionPage=Number(el.dataset.number);await navigate('进度');return;}
    if(a==='execution-refresh'){await navigate('进度');return;}
    if(a==='execution-report'){
      const id=selectedTaskId;await run(async current=>{const result=await executionClient.report(id);if(!current())return;const url=URL.createObjectURL(new Blob([result.bytes],{type:'application/octet-stream'}));const link=document.createElement('a');link.href=url;link.download=result.filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});return;
    }
    if(['execution-advance','execution-retry','execution-explain','execution-cancel'].includes(a)){
      const id=selectedTaskId,publication=root.querySelector('#execution-publication')?.value;
      const input={publicationId:publication?Number(publication):undefined,pageId:Number(el.dataset.pageId),explanation:root.querySelector('#execution-explanation')?.value};
      await run(async current=>{const data=await executionClient.act(id,a.slice('execution-'.length),input);if(current()){execution=data;executionPublications=null;}});return;
    }
    if(a==='level'){level=el.dataset.level;render();return;}
    if(a==='refresh'){await navigate(page);return;}
    if(a==='list-page'){const target=Number(el.dataset.number);if(!Number.isSafeInteger(target)||target<1)return;listPage=target;await navigate(page);return;}
    if(a==='refresh-plan'){await navigate('服务计划');return;}
    if(a==='delivery'){manualDraft=null;publicationReceipt=null;editor=null;publicationRecords=null;publicationAttempts=null;const id=Number(el.dataset.id);selectedContentId=id;page='稿件';delivery=null;await run(async current=>{const data=await client.delivery(id);if(current())delivery=data;});return;}
    if(['confirm','reject','review','review-reject'].includes(a)){
      const id=delivery.content.id,note=root.querySelector('#decision-note').value;
      await run(async current=>{let data;if(a==='review'||a==='review-reject'){await client.review(id,{decision:a==='review'?'approve':'reject',note});data=await client.delivery(id);}else data=await client.confirm(id,{actorMode:el.dataset.mode,decision:a==='reject'?'reject':'approve',note:note||null});if(current())delivery=data;});return;
    }
    if(a==='edit-content'){const id=delivery.content.id;await run(async current=>{const data=await client.editor(id);if(current())editor=data;});return;}
    if(a==='save-content'){
      const id=delivery.content.id,input={title:root.querySelector('#content-title').value,outline:root.querySelector('#content-outline').value,body:root.querySelector('#content-body').value};
      await run(async current=>{await client.saveContent(id,input);const data=await client.delivery(id);if(current()){delivery=data;editor=null;publicationRecords=null;publicationAttempts=null;}});return;
    }
    if(a==='submit-review'){const id=delivery.content.id,note=root.querySelector('#decision-note').value;await run(async current=>{await client.submitReview(id,{note:note||null});const data=await client.delivery(id);if(current())delivery=data;});return;}
    if(a==='publications'){manualDraft=null;const id=delivery.content.id;publicationRecords=null;publicationAttempts=null;await run(async current=>{const data=await client.publications(id);if(current())publicationRecords=data;});return;}
    if(a==='publication-attempts'){const id=Number(el.dataset.id),contentId=delivery.content.id;publicationAttempts=null;await run(async current=>{const data=await client.publicationAttempts(contentId,id);if(current())publicationAttempts={id,items:data.items};});return;}
    if(a==='manual-open'){manualDraft={publicationId:el.dataset.id?Number(el.dataset.id):null,expectedVersion:delivery.content.version_count,expectedHash:delivery.content.payload_hash,platformName:'',pageUrl:'',localTime:'',verified:false};render();return;}
    if(a==='manual-cancel'){manualDraft=null;render();return;}
    if(a==='manual-save'){
      const id=delivery.content.id,input={...manualDraft,publishedAt:manualDraft.localTime?manualDraft.localTime+(manualDraft.localTime.length===16?':00':'')+'+08:00':null};
      await run(async current=>{const receipt=await client.recordPublication(id,input);const data=await client.delivery(id),records=await client.publications(id);if(current()){delivery=data;publicationRecords=records;publicationAttempts=null;manualDraft=null;publicationReceipt=receipt;}});return;
    }
    if(a==='ai-clear'){const ai=controller.getState().view.ai;aiDraft={enabled:aiDraft?.enabled??ai.enabled,factIds:[],keywordIds:[],dirty:true};render();return;}
    if(a==='ai-materials'){await run(async current=>{const facts=await client.aiFacts(),keywords=await client.aiKeywords();if(current())aiMaterial={facts,keywords};});return;}
    if(a==='ai-keyword-page'){await run(async current=>{const keywords=await client.aiKeywords(Number(el.dataset.number));if(current())aiMaterial={...aiMaterial,keywords};});return;}
    if(a==='refresh-triggers'){triggerActions=null;await run(async current=>{const actions=await triggerClient.load(controller.getState().view?.revision);if(current())triggerActions=actions;});return;}
    if(a==='trigger'){await run(async current=>{const result=await triggerClient.trigger(el.dataset.kind);const data=await executionClient.detail(result.id);if(current()){selectedTaskId=result.id;execution=data;executionPublications=null;page='执行详情';triggerActions=null;}});return;}
    if(a==='save-plan'){

      const lines=id=>root.querySelector(id).value.split('\n').map(x=>x.trim()).filter(Boolean);
      const input={optimizationDirections:lines('#plan-directions'),contentTopics:lines('#plan-topics'),serviceNote:root.querySelector('#plan-note').value,status:root.querySelector('#plan-status').value};
      input.cycles=Object.fromEntries([...root.querySelectorAll('[data-cycle]')].filter(node=>identity.user.permissions['seo.keywords']==='edit'||!node.dataset.cycle.startsWith('monitoring_')).map(node=>[node.dataset.cycle,node.type==='checkbox'?node.checked:Number(node.value)]));
      if(aiDraft?.dirty)input.ai=aiDraft;
      await run(async()=>{await controller.save(input);planDraft=null;aiDraft=null;aiMaterial=null;triggerActions=null;triggerClient.invalidate();});
    }
  });
  void connect();
  return {reconnect:connect,dispose(){epoch++;unsubscribe();clear();host.dispose();root.replaceChildren();}};
}
