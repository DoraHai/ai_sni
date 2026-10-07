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
import {statusLabel,formatTime} from './customer-display.mjs';
import {contentPreview} from './content-preview.mjs';
import {createInputProtection} from './input-protection.mjs';
import {createSeoDataClient} from './seo-data-client.mjs';
import {homeView} from './home-view.mjs';
import {maintenanceView,expirationLocal} from './maintenance-view.mjs';
import {dataWorkspaceView,dataDetailView,preparationView} from './data-workspace-view.mjs';

const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const btn=(label,action,attrs='')=>`<button data-action="${action}" ${attrs}>${label}</button>`;
const names={'SEO-A01':'资料与服务计划','SEO-A02':'网站检查','SEO-A03':'关键词与搜索','SEO-A04':'内容','SEO-A05':'发布核验','SEO-A06':'数据报告','SEO-A07':'异常与运行'};
const executionErrors={report_version_conflict:'报告版本已变化，请重新读取后填写说明',REPORT_VERSION_MISMATCH:'报告文件与已读取哈希不一致，请重新读取核对',INVALID_REPORT_EXPLANATION:'请填写1–4000字的顾问说明',EXECUTION_REQUIRED:'操作资格已失效，请重新读取任务',INVALID_CYCLE_CONFIG:'周期范围不符合限制，请检查间隔与页面数量'};
const workflowErrors={INVALID_MAINTENANCE_INPUT:'请填写必填资料，检查链接和到期时间格式',WRITE_FAILED:'保存未完成，请重新读取核对；输入已保留，不自动重发',INVALID_AI_SELECTION:'请选择1–20条已读资料和1–5个本站关键词',AI_SELECTION_READ_REQUIRED:'资料或关键词尚未读取、已过期或不在本站，请重新读取并选择',AI_CONFIGURE_DENIED:'当前无权配置AI草稿；请重新读取资格',AI_MATERIAL_TOO_LARGE:'所选资料超过总量限制，请减少资料',INVALID_PUBLICATION_INPUT:'请填写真实平台、公开链接和北京时间，并勾选已人工核实',TRIGGER_OUTCOME_UNRESOLVED:'上次触发结果未知，请读取执行进度核对，不重发',content_version_precondition_required:'缺少准确版本前提，请重新读取稿件',PUBLICATION_SELECTION_REQUIRED:'请先读取并选择本任务的发布记录'};
const failure=e=>workflowErrors[e.code]||executionErrors[e.code]||({INVALID_CONTENT:'请填写1–300字的标题，检查正文与提纲',CONTENT_VERSION_OR_SCOPE_MISMATCH:'稿件版本或范围已变化，请重新读取核对',ADVISOR_REQUIRED:'当前身份未取得该站点顾问资格',CONTENT_PROTECTED:'稿件受保护，请先按明确退回流程处理'}[e.code])||(e.code==='content_version_conflict'?'稿件版本已变化，请重新读取后确认':e.code==='service_plan_version_conflict'?'服务计划已被更新，请重新读取':e.code==='REJECTION_NOTE_REQUIRED'?'退回必须填写意见':e.code==='WRITE_OUTCOME_UNKNOWN'?'写入结果未知，请重新读取核对，不自动重试':e.status===409?'内容状态或版本已变化，请重新读取核对':e.status===503?'服务能力尚未启用':e.status===403?'权限或顾问资格已变化，请重新读取':e.code==='CONFIRMATION_UNAVAILABLE'?'确认能力未启用':e.code==='MODULE_UNAVAILABLE'?'当前未开通SEO；SEM/GEO连接能力待接入':(e.code||e.message)==='READ_FAILED'?'读取失败，请重试当前页面':`请求未完成：${e.code||e.message}`);

export function mountConnectedWorkbench({root,host,environmentLabel,demoHref='index.html'}) {
  root.classList.add('customer-connected');
  const protection=createInputProtection(root);
  const client=createSeoWorkflowClient({transport:host.transport,getContext:host.getContext});
  const triggerClient=createSeoTriggerClient({transport:host.transport,getContext:host.getContext});
  const reader=createSeoContentReader({transport:host.transport,getContext:host.getContext});
  const controller=createServicePlanController(client);
  const canMaintain=kind=>controller.getState().view?.canUpdate===true&&controller.getState().view?.permissionBasis?.active_site_advisor_assignment===true&&identity?.user.permissions[kind==='keywords'?'seo.keywords':'seo.content']==='edit';
  const dataClient=createSeoDataClient({transport:host.transport,getContext:host.getContext,canMaintain});
  let maintenance=null,maintenanceTarget=null,hadAdvisorAssignment=false;
  function observeAssignment(basis){if(typeof basis?.active_site_advisor_assignment!=='boolean')return;const current=basis.active_site_advisor_assignment;if(hadAdvisorAssignment&&!current){protection.clear();editor=null;manualDraft=null;maintenance=null;planDraft=null;aiDraft=null;}hadAdvisorAssignment=current;}
  let home=null,dataKind='keywords',dataPayload=null,dataPage=1,dataFilters={engine:'baidu',device:'desktop',status:'active'},dataDetail=null;
  const executionClient=createSeoExecutionClient({transport:host.transport,getContext:host.getContext});
  let identity=null,page='首页',contents=null,delivery=null,status=null,busy=false,message='',epoch=0,level='L1',listPage=1,selectedContentId=null;
  let editor=null,publicationRecords=null,publicationAttempts=null,manualDraft=null,publicationReceipt=null;
  let aiDraft=null,aiMaterial=null,planDraft=null,triggerActions=null;
  let executionPublications=null;
  let executions=null,execution=null,executionPage=1,selectedTaskId=null;
  const clear=()=>{protection.clear();maintenance=null;maintenanceTarget=null;hadAdvisorAssignment=false;home=null;dataPayload=null;dataDetail=null;dataPage=1;dataKind='keywords';dataFilters={engine:'baidu',device:'desktop',status:'active'};dataClient.invalidate();aiDraft=null;aiMaterial=null;planDraft=null;triggerActions=null;triggerClient.invalidate();manualDraft=null;publicationReceipt=null;editor=null;publicationRecords=null;publicationAttempts=null;client.invalidate();identity=null;contents=null;delivery=null;status=null;listPage=1;selectedContentId=null;controller.invalidate();reader.invalidate();executionClient.invalidate();executionPublications=null;executions=null;execution=null;executionPage=1;selectedTaskId=null;};
  function render(){protection.setContext(JSON.stringify([page,page==='稿件'?selectedContentId:page==='执行详情'?selectedTaskId:null,manualDraft?manualDraft.publicationId??'new':null,page==='顾问维护'?maintenanceTarget:null]));renderContent();protection.render();}
  function renderContent(){
    const connection=host.getState();
    root.innerHTML=`<div class="connected-notice">${esc(environmentLabel)}</div><header><b>G-SNIPERS</b><span>客户工作台</span><small id="identity">${identity?`${esc(identity.user.display_name||identity.user.username||identity.user.id)} · ${esc(identity.tenant.name||identity.tenant.id)} / ${esc(identity.site.name)}`:'尚未取得授权身份'}</small>${demoHref?`<a href="${esc(demoHref)}">独立演示模式</a>`:''}</header><div class="workspace"><main class="connected-main"><div id="connected-message" class="connected-status" role="status">${esc(message)}</div><div id="connected-content"></div></main><details class="chat compact-chat"><summary>客户与顾问对话</summary><p>消息功能尚未接入。后续可在这里沟通稿件与服务事项。</p></details></div>`;
    const main=root.querySelector('#connected-content');
    const modules=document.createElement('div');modules.className='module-navigation';modules.setAttribute('aria-label','服务模块');modules.innerHTML=['sem','seo','geo'].map(code=>{const item=connection.modules?.find(m=>m.module_code===code);const label=!connection.modulesChecked?'待核验':!item?.available?'未开通':code!=='seo'?'已开通 · 待接入':identity?'可使用':'待完成范围核验';return btn(`${code.toUpperCase()} · ${label}`,'page',`data-page="首页" data-module="${code}" ${code==='seo'&&identity&&!busy?'':'disabled'}`);}).join('');main.before(modules);
    if(!identity){
      const labels={disconnected:'未连接宿主身份',unauthenticated:'尚未登录，请使用现有登录入口',forbidden:'当前身份无权进入此客户空间',scope_required:'请在宿主选择获授权客户与站点',connecting:'正在核验身份、模块和客户范围',connection_error:'连接未完成，请重试',module_pending:'已开通模块尚未接入此入口'};
      main.innerHTML=`<section class="connected-state"><h2>${labels[connection.phase]||'未连接'}</h2><p>请从现有工作台进入已选择的客户与站点。</p><a href="/workspace/cockpit">返回现有工作台</a>${btn('前往现有登录','login')}${btn('重新连接','connect',busy?'disabled':'')}</section>`;return;
    }
    const siteRead=['view','edit'].includes(identity.user.permissions['seo.site']);
    main.innerHTML=`<div class="navigation">${['首页','内容','SEO工作','进度','数据','服务计划','交付记录'].map(n=>btn(n,'page',`data-page="${n}" ${busy||(!siteRead&&['SEO工作','进度','数据','服务计划'].includes(n))?'disabled':''}`)).join('')}</div><section id="page" class="page-card"></section>`;
    const panel=root.querySelector('#page');
    if(page==='首页'){panel.innerHTML=homeView(home);if(busy)panel.querySelectorAll('button').forEach(b=>b.disabled=true);
    }else if(page==='内容'){
      panel.innerHTML=`<h2>${page==='首页'?'当前客户 · 稿件与待办':'内容'}</h2><p>客户确认稿件，顾问可以代确认；发布状态另按实际记录展示。</p>${contents?`<small id="pagination-summary">第${listPage}页${listPage>Math.max(1,Math.ceil(contents.total/50))?'（列表已变化，请返回前页）':` / 共${Math.max(1,Math.ceil(contents.total/50))}页`} · 本页${contents.items.length}篇 / 共${contents.total}篇 · 每页50篇</small>${contents.items.map(item=>`<div class="task-item"><div class="task-content"><b>${esc(item.title||`稿件${item.id}`)}</b><p>v${esc(item.version_count)} · ${esc(statusLabel(item.status))}</p></div>${btn('查看准确交付稿','delivery',`data-id="${item.id}" ${busy?'disabled':''}`)}</div>`).join('')||'<p>当前授权范围没有稿件。</p>'}`:`<p>第${listPage}页尚未读取，请重试。</p>`}<div class="pagination">${btn('上一页','list-page',`data-number="${listPage-1}" ${busy||listPage<=1?'disabled':''}`)}${btn('下一页','list-page',`data-number="${listPage+1}" ${busy||!contents||listPage*50>=contents.total?'disabled':''}`)}${btn('刷新本页','refresh',busy?'disabled':'')}</div><p>${btn('查看资料与关键词','page','data-page="数据"')}</p>`;
    }else if(page==='稿件'){
      if(!delivery){panel.innerHTML=`<p>稿件数据未取得或已失效，请重新读取核对。</p>${selectedContentId?btn('重新读取交付稿','delivery',`data-id="${selectedContentId}" ${busy?'disabled':''}`):''}${btn('返回列表','page','data-page="内容" '+(busy?'disabled':''))}`;return;}
      const view=contentDeliveryView(delivery),allowed=key=>!busy&&view.actions.includes(key);
      panel.innerHTML=`<h2>${esc(delivery.content.title)}</h2><p>准确版本 <b>v${view.version}</b> · ${esc(statusLabel(view.workflowStatus))}</p><small>更新于 ${esc(formatTime(delivery.content.updated_at))}</small><article id="delivery-body" class="content-preview">${contentPreview(view.body)}</article>${view.capabilityMessage?`<p>${esc(view.capabilityMessage)}</p>`:''}${view.confirmation?`<div class="${view.confirmation.approvedCurrent?'confirmed':'phase-row'}">${esc(view.confirmation.label)} · ${esc(view.confirmation.actorName)} · v${view.confirmation.version}<p>${esc(formatTime(view.confirmation.at))} · 状态 ${esc(view.confirmationStatusLabel)}</p></div>`:''}<p class="meaning-note">确认表示同意当前稿件。实际发布和页面核验会分别记录。</p><details><summary>版本与核验依据</summary><p>稿件摘要 ${esc(view.hash)}</p><p>发布：${esc(statusLabel(view.resultBasis?.publication_status,'publication'))} · 页面核验：${esc(statusLabel(view.resultBasis?.page_check_status,'publication'))}</p><p>确认记录对应 v${esc(view.confirmation?.version??'未提供')}，当前稿件 v${view.version}</p></details>${['confirm_as_customer','confirm_as_advisor_proxy','reject_as_customer','reject_as_advisor_proxy','review'].some(k=>view.actions.includes(k))?`<section class="primary-action"><h3>当前可处理</h3><label for="decision-note">确认或退回意见</label><textarea id="decision-note" ${busy?'disabled':''}></textarea><div class="actions">${[
        ['confirm_as_customer',`本人确认 v${view.version}`,'confirm','data-mode="customer_direct"'],
        ['confirm_as_advisor_proxy',`顾问代确认 v${view.version}`,'confirm','data-mode="advisor_proxy"'],
        ['reject_as_customer','退回并提出修改意见','reject','data-mode="customer_direct"'],
        ['reject_as_advisor_proxy','顾问代退回','reject','data-mode="advisor_proxy"'],
        ['review','顾问复核通过','review',''],['review','复核退回修改','review-reject','']
      ].filter(([key])=>view.actions.includes(key)&&(!['review','confirm_as_advisor_proxy','reject_as_advisor_proxy'].includes(key)||isAssignedAdvisor(delivery))).map(([key,label,action,attrs])=>btn(label,action,attrs+(allowed(key)?'':' disabled'))).join('')}</div></section>`:''}${contentOperationsView(delivery,editor,busy)}${publicationsView(delivery,publicationRecords,publicationAttempts,busy,manualDraft,publicationReceipt)}${btn('重新读取交付稿','delivery',`data-id="${view.id}" ${busy?'disabled':''}`)}`;
    }else if(page==='进度'){
      panel.innerHTML=executionListView(executions,executionPage,busy);
    }else if(page==='执行详情'){
      panel.innerHTML=executionDetailView(execution,selectedTaskId,busy,executionPublications);
    }else if(page==='服务计划'){
      const state=controller.getState(),view=state.view?{...state.view,...planDraft}:null;
      if(view&&!view.canUpdate){panel.innerHTML=`<h2>服务计划</h2><p>顾问准备服务方向和资料，您只需在稿件备好后确认内容。</p><section><h3>优化方向</h3>${view.optimizationDirections.length?'<ul>'+view.optimizationDirections.map(v=>'<li>'+esc(v)+'</li>').join('')+'</ul>':'<p>顾问尚未填写优化方向。</p>'}<h3>内容选题</h3>${view.contentTopics.length?'<ul>'+view.contentTopics.map(v=>'<li>'+esc(v)+'</li>').join('')+'</ul>':'<p>顾问尚未填写选题。</p>'}<h3>服务备注</h3><p class=preserve-lines>${esc(view.serviceNote||'暂无备注')}</p><p>服务${view.status==='active'?'进行中':'已暂停'} · 更新于 ${esc(formatTime(view.updatedAt))}</p></section>${btn('刷新服务计划','refresh-plan',busy?'disabled':'')}`;return;}
      panel.innerHTML=`<h2>服务计划</h2><p id="plan-message">${esc(state.message)}</p>${view?`<p>更新于 ${esc(formatTime(view.updatedAt))}</p><details><summary>计划版本依据</summary><p>修订 ${view.revision} · 更新记录 ${esc(view.updatedBy??'未提供')}</p></details><label for="plan-directions">优化方向（每行一个）</label><textarea id="plan-directions" ${state.canSave&&!busy?'':'disabled'}>${esc(view.optimizationDirections.join('\n'))}</textarea><label for="plan-topics">内容选题（每行一个）</label><textarea id="plan-topics" ${state.canSave&&!busy?'':'disabled'}>${esc(view.contentTopics.join('\n'))}</textarea><label for="plan-note">服务备注</label><textarea id="plan-note" ${state.canSave&&!busy?'':'disabled'}>${esc(view.serviceNote)}</textarea><label for="plan-status">服务状态</label><select id="plan-status" ${state.canSave&&!busy?'':'disabled'}><option value="active" ${view.status==='active'?'selected':''}>运行</option><option value="paused" ${view.status==='paused'?'selected':''}>暂停后续采集调度</option></select><p>${esc(view.disabledMessage||'本次编辑资格由服务端提供，保存时仍会重检。')}</p>${cycleForm(view.cycles,!state.canSave||busy,identity.user.permissions['seo.keywords']==='edit')}${aiPlanView(view.ai,aiDraft,aiMaterial,busy,state.canSave)}${btn('保存服务计划（含本次AI授权变更）','save-plan',state.canSave&&!busy?'':'disabled')}`:''}${btn('重新读取计划与资格','refresh-plan',busy?'disabled':'')}${triggerView(triggerActions,triggerClient.pending(),busy)}<p>资料与关键词可在数据页维护。计划中的选择使用本站已读取记录，无需客户审批。</p>`;
    }else if(page==='SEO工作'){
      panel.innerHTML=preparationView(status,names);
    }else if(page==='顾问维护'){panel.innerHTML=maintenanceView(maintenance,maintenanceTarget,busy);
    }else if(page==='数据详情'){
      panel.innerHTML=dataDetailView(dataKind,dataDetail);
    }else if(page==='数据'||page==='交付记录'){
      panel.innerHTML=dataWorkspaceView({kind:page==='交付记录'?'publications':dataKind,payload:dataPayload,page:dataPage,filters:dataFilters,busy,history:page==='交付记录',canMaintain:canMaintain(dataKind)});
      if(busy)panel.querySelectorAll('button,input,select').forEach(e=>e.disabled=true);
    }
    panel.querySelectorAll('button').forEach(b=>{if(busy)b.disabled=true;});
    root.querySelectorAll('.navigation [data-page]').forEach(b=>b.setAttribute('aria-current',b.dataset.page===page?'page':'false'));
  }
  async function readHome(current){
    const rows=await reader.contents({page:1,pageSize:8});
    const results=await Promise.allSettled(rows.items.map(v=>client.delivery(v.id)));
    const tasks=['view','edit'].includes(identity?.user.permissions['seo.site'])?await executionClient.list({page:1,pageSize:5}):null;
    if(current())home={contents:rows,deliveries:results.filter(r=>r.status==='fulfilled').map(r=>r.value),failed:results.filter(r=>r.status==='rejected').length,executions:tasks};
  }
  async function readData(current){dataPayload=null;dataDetail=null;const kind=page==='交付记录'?'publications':dataKind;const value=await dataClient.list(kind,{page:dataPage,filters:kind==='publications'||kind==='facts'?{}:dataFilters});if(['view','edit'].includes(identity?.user.permissions['seo.site']))await controller.load();if(!current())return;observeAssignment(controller.getState().view?.permissionBasis);if(current())dataPayload=value;}
  async function readMaintenance(current){const {kind,id}=maintenanceTarget;await controller.load();observeAssignment(controller.getState().view?.permissionBasis);if(!canMaintain(kind)){protection.clear();throw Object.assign(Error('ADVISOR_REQUIRED'),{code:'ADVISOR_REQUIRED'});}await dataClient.list(kind,{page:dataPage,filters:kind==='facts'?{}:dataFilters});const value=id?dataClient.selected(kind,id):kind==='keywords'?{keyword:'',priority:'P2',landing_page:''}:{title:'',statement:'',source_name:'',source_url:'',expires_at:'',status:'active'};if(kind==='facts'){value.expires_local=expirationLocal(value.expires_at);value._initialExpiresLocal=value.expires_local;}if(current())maintenance=value;}

  async function run(action){const inputSnapshot=protection.capture();const stamp=++epoch;busy=true;message='正在读取或等待服务器结果…';render();try{await action(()=>stamp===epoch);if(stamp===epoch)message='';}catch(e){if(stamp===epoch){message=failure(e);if(e.code==='ADVISOR_REQUIRED')protection.clear();else protection.recover(inputSnapshot);maintenance=null;dataPayload=null;dataDetail=null;dataClient.invalidate();manualDraft=null;publicationReceipt=null;triggerActions=null;triggerClient.invalidate();aiDraft=null;aiMaterial=null;planDraft=null;delivery=null;editor=null;publicationRecords=null;publicationAttempts=null;if(controller.getState().phase==='error')client.invalidate();else controller.invalidate();execution=null;executionClient.invalidate();}}finally{if(stamp===epoch){busy=false;render();}}}
  async function connect(){const stamp=++epoch;clear();busy=true;message='正在核验现有会话…';render();try{const result=await host.initialize();if(stamp!==epoch)return;identity=result.identity??null;page='首页';if(identity){await readHome(()=>stamp===epoch);}if(stamp===epoch)message='';}catch(e){if(stamp===epoch){clear();message=failure(e);}}finally{if(stamp===epoch){busy=false;render();}}}
  async function navigate(next){const previous=page;page=next;if(['数据','交付记录'].includes(next))dataPayload=null;if(next==='进度')executions=null;if(next==='服务计划'){aiDraft=null;aiMaterial=null;planDraft=null;triggerActions=null;}if(next==='首页')home=null;if(next==='内容')contents=null;if(next==='SEO工作')status=null;if(['数据','交付记录'].includes(next)&&next!==previous&&previous!=='数据详情')dataPage=1;await run(async current=>{if(next==='首页'){await readHome(current);}else if(next==='内容'){const data=await reader.contents({page:listPage});if(current())contents=data;}else if(next==='进度'){const data=await executionClient.list({page:executionPage});if(current()){executions=data;triggerClient.reconcile(data.items);}}else if(next==='服务计划'){await controller.load();observeAssignment(controller.getState().view?.permissionBasis);if(controller.getState().view?.canUpdate){const actions=await triggerClient.load(controller.getState().view?.revision);if(current())triggerActions=actions;}}else if(next==='SEO工作'){const data=await client.serviceStatus();if(current())status=data;}else if(['数据','交付记录'].includes(next)){await readData(current);}});}

  const unsubscribe=host.subscribe(({reason})=>{epoch++;busy=false;clear();message=reason==='forbidden'?'权限已失效，已清空当前客户数据':reason==='expired'?'登录已过期，已清空数据':'身份或客户范围已变化，旧数据已清除';render();if(reason==='context_changed')queueMicrotask(connect);});
  root.addEventListener('input',event=>{
    const el=event.target;
    if(maintenance&&el.id.startsWith('maint-'))maintenance[el.id.slice(6)]=el.value;
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
    if(a==='restore-input'){protection.restore();return;}if(a==='discard-input'){protection.discardRecovery();render();return;}
    if(['page','delivery','refresh','refresh-plan','execution-detail','execution-refresh','execution-page','list-page','manual-cancel','maintenance-open','maintenance-reload'].includes(a)&&!protection.leave(['refresh','refresh-plan','maintenance-reload'].includes(a)||(a==='delivery'&&Number(el.dataset.id)===selectedContentId)||(a==='execution-detail'&&Number(el.dataset.id)===selectedTaskId)))return;
    if(a==='page'){editor=null;manualDraft=null;await navigate(el.dataset.page);return;}
    if(a==='maintenance-open'){maintenanceTarget={kind:dataKind,id:el.dataset.id?Number(el.dataset.id):null};maintenance=null;page='顾问维护';await run(readMaintenance);return;}
    if(a==='maintenance-reload'){maintenance=null;await run(readMaintenance);return;}
    if(a==='maintenance-save'){const input=structuredClone(maintenance),kind=maintenanceTarget.kind;if(kind==='facts'&&input.expires_local!==input._initialExpiresLocal)input.expires_at=input.expires_local?input.expires_local+'+08:00':null;await run(async current=>{await controller.load();observeAssignment(controller.getState().view?.permissionBasis);if(!canMaintain(kind))throw Object.assign(Error('ADVISOR_REQUIRED'),{code:'ADVISOR_REQUIRED'});await dataClient.save(kind,input);if(!current())return;protection.saved();maintenance=null;page='数据';await readData(current);});return;}
    if(a==='data-kind'){dataPayload=null;dataKind=el.dataset.kind;dataFilters=dataKind==='keywords'?{engine:'baidu',device:'desktop',status:'active'}:{};dataPage=1;await run(readData);return;}
    if(a==='data-search'){dataFilters={q:root.querySelector('#data-q').value.trim(),status:root.querySelector('#data-status').value,...(dataKind==='keywords'?{engine:root.querySelector('#data-engine').value,device:root.querySelector('#data-device').value}:{})};dataPage=1;await run(readData);return;}
    if(a==='data-page'){dataPage=Number(el.dataset.number);await run(readData);return;}
    if(['data-keyword-detail','data-page-detail'].includes(a)){const id=Number(el.dataset.id);page='数据详情';dataDetail=null;await run(async current=>{const value=await dataClient.detail(dataKind,id);if(current())dataDetail=value;});return;}
    if(a==='data-publication-detail'){const row=dataPayload?.items.find(v=>v.publication.id===Number(el.dataset.id));if(!row)return;selectedContentId=row.content.id;page='稿件';delivery=null;manualDraft=null;editor=null;await run(async current=>{const value=await client.delivery(selectedContentId);const records=await client.publications(selectedContentId);if(current()){delivery=value;observeAssignment(value.permission_basis);publicationRecords=records;}});return;}
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
      await run(async current=>{const data=await executionClient.act(id,a.slice('execution-'.length),input);if(current()){execution=data;executionPublications=null;protection.saved();}});return;
    }
    if(a==='level'){level=el.dataset.level;render();return;}
    if(a==='refresh'){await navigate(page);return;}
    if(a==='list-page'){const target=Number(el.dataset.number);if(!Number.isSafeInteger(target)||target<1)return;listPage=target;await navigate(page);return;}
    if(a==='refresh-plan'){await navigate('服务计划');return;}
    if(a==='delivery'){manualDraft=null;publicationReceipt=null;editor=null;publicationRecords=null;publicationAttempts=null;const id=Number(el.dataset.id);selectedContentId=id;page='稿件';delivery=null;await run(async current=>{const data=await client.delivery(id);if(current()){delivery=data;observeAssignment(data.permission_basis);}});return;}
    if(['confirm','reject','review','review-reject'].includes(a)){
      const id=delivery.content.id,note=root.querySelector('#decision-note')?.value||'';
      await run(async current=>{let data;if(a==='review'||a==='review-reject'){await client.review(id,{decision:a==='review'?'approve':'reject',note});data=await client.delivery(id);}else data=await client.confirm(id,{actorMode:el.dataset.mode,decision:a==='reject'?'reject':'approve',note:note||null});if(current()){delivery=data;observeAssignment(data.permission_basis);protection.saved();}});return;
    }
    if(a==='edit-content'){const id=delivery.content.id;await run(async current=>{const data=await client.editor(id);if(current())editor=data;});return;}
    if(a==='save-content'){
      const id=delivery.content.id,input={title:root.querySelector('#content-title').value,outline:root.querySelector('#content-outline').value,body:root.querySelector('#content-body').value};
      await run(async current=>{await client.saveContent(id,input);const data=await client.delivery(id);if(current()){delivery=data;observeAssignment(data.permission_basis);protection.saved();editor=null;publicationRecords=null;publicationAttempts=null;}});return;
    }
    if(a==='submit-review'){const id=delivery.content.id,note=root.querySelector('#decision-note')?.value||'';await run(async current=>{await client.submitReview(id,{note:note||null});const data=await client.delivery(id);if(current()){delivery=data;observeAssignment(data.permission_basis);protection.saved();}});return;}
    if(a==='publications'){if(manualDraft&&!protection.leave(true))return;manualDraft=null;const id=delivery.content.id;publicationRecords=null;publicationAttempts=null;await run(async current=>{const data=await client.publications(id);if(current())publicationRecords=data;});return;}
    if(a==='publication-attempts'){const id=Number(el.dataset.id),contentId=delivery.content.id;publicationAttempts=null;await run(async current=>{const data=await client.publicationAttempts(contentId,id);if(current())publicationAttempts={id,items:data.items};});return;}
    if(a==='manual-open'){if(manualDraft&&!protection.leave(true))return;manualDraft={publicationId:el.dataset.id?Number(el.dataset.id):null,expectedVersion:delivery.content.version_count,expectedHash:delivery.content.payload_hash,platformName:'',pageUrl:'',localTime:'',verified:false};render();return;}
    if(a==='manual-cancel'){manualDraft=null;render();return;}
    if(a==='manual-save'){
      const id=delivery.content.id,input={...manualDraft,publishedAt:manualDraft.localTime?manualDraft.localTime+(manualDraft.localTime.length===16?':00':'')+'+08:00':null};
      await run(async current=>{const receipt=await client.recordPublication(id,input);const data=await client.delivery(id),records=await client.publications(id);if(current()){delivery=data;observeAssignment(data.permission_basis);publicationRecords=records;publicationAttempts=null;manualDraft=null;publicationReceipt=receipt;protection.saved();}});return;
    }
    if(a==='ai-clear'){const ai=controller.getState().view.ai;aiDraft={enabled:aiDraft?.enabled??ai.enabled,factIds:[],keywordIds:[],dirty:true};render();root.querySelector('#ai-enabled')?.dispatchEvent(new Event('input',{bubbles:true}));return;}
    if(a==='ai-materials'){await run(async current=>{const facts=await client.aiFacts(),keywords=await client.aiKeywords();if(current())aiMaterial={facts,keywords};});return;}
    if(a==='ai-keyword-page'){await run(async current=>{const keywords=await client.aiKeywords(Number(el.dataset.number));if(current())aiMaterial={...aiMaterial,keywords};});return;}
    if(a==='refresh-triggers'){triggerActions=null;await run(async current=>{const actions=await triggerClient.load(controller.getState().view?.revision);if(current())triggerActions=actions;});return;}
    if(a==='trigger'){await run(async current=>{const result=await triggerClient.trigger(el.dataset.kind);const data=await executionClient.detail(result.id);if(current()){selectedTaskId=result.id;execution=data;executionPublications=null;page='执行详情';triggerActions=null;}});return;}
    if(a==='save-plan'){

      const lines=id=>root.querySelector(id).value.split('\n').map(x=>x.trim()).filter(Boolean);
      const input={optimizationDirections:lines('#plan-directions'),contentTopics:lines('#plan-topics'),serviceNote:root.querySelector('#plan-note').value,status:root.querySelector('#plan-status').value};
      input.cycles=Object.fromEntries([...root.querySelectorAll('[data-cycle]')].filter(node=>identity.user.permissions['seo.keywords']==='edit'||!node.dataset.cycle.startsWith('monitoring_')).map(node=>[node.dataset.cycle,node.type==='checkbox'?node.checked:Number(node.value)]));
      if(aiDraft?.dirty)input.ai=aiDraft;
      await run(async()=>{await controller.save(input);protection.saved();planDraft=null;aiDraft=null;aiMaterial=null;triggerActions=null;triggerClient.invalidate();});
    }
  });
  void connect();
  return {reconnect:connect,dispose(){epoch++;unsubscribe();clear();protection.dispose();host.dispose();root.replaceChildren();}};
}
