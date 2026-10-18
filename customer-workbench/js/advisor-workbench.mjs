import {createAdvisorTenantSwitch,advisorScopedFetch} from './advisor-tenant-switch.mjs';
import {advisorMessages} from '../../frontend/src/store/advisorTenant.js';
import {createAdvisorClient} from './advisor-client.mjs';
import {createAdvisorRemotePanel} from './advisor-remote-panel.mjs';
import {createAdvisorDistributionPanel} from './distribution-panel.mjs';
import {escapeText as esc} from './customer-display.mjs';
import {workbenchPath,geoWorkbenchPath} from './workbench-entry.mjs';
import {createAdvisorAutomationPanel} from './advisor-automation-panel.mjs';
import {createAdvisorAccountSwitch} from './advisor-account-switch.mjs';
const phases={draft:'待制定方案',review:'待人工审核',implementation:'待网站实施',recheck:'待页面复检',acceptance:'待人工验收',done:'已验收',cancelled:'已取消'};
const nextActions={save_proposal:'顾问完善并提交当前方案',approve:'人工核实事实并审核当前方案',implement:'网站维护人员实施已审核方案',recheck:'发起真实页面复检',accept:'人工核对质量并最终验收'};
const nextLabel=t=>nextActions[t.next_action]||t.next_action||(['done','cancelled'].includes(t.workflow.phase)?'任务已结束，核对后续效果与安排':'接口未提供，请进入任务核对');
const blockerLabel=t=>typeof t.blocker==='string'?t.blocker:t.blocker?.message||'接口未提供阻塞说明';
export function advisorTaskPath(row){
  return (row.module==='geo'?geoWorkbenchPath(row.tenant_id,row.scope_id):workbenchPath(row.tenant_id,row.scope_id))+'&'+new URLSearchParams({onsite_task_id:row.id});
}
export function advisorPageView(module,page){
  return Object.entries(phases).map(([phase,label])=>{
    const rows=page.items.filter(t=>t.workflow.phase===phase);if(!rows.length)return '';
    return `<section class="advisor-group"><h3>${label} · 本页 ${rows.length} 项</h3>${rows.map(t=>`<article class="advisor-task"><h4>${esc(t.title||'站内任务')} #${t.id}</h4><p>${module.toUpperCase()} · ${esc(t.tenant_name||'客户 #'+t.tenant_id)} / ${esc(t.scope_name||(module==='geo'?'项目 #':'网站 #')+t.scope_id)}</p><p>月份：${esc(t.workflow.month||'不适用')} · 实施负责人：${esc(t.workflow.owner_name||'尚未指定')} · 服务端版本 v${t.workflow.revision}</p><p>下一步人工动作：${esc(nextLabel(t))}</p><p>阻塞原因：${esc(blockerLabel(t))}</p>${phase==='review'?'<strong>方案待人工审核，请核实事实与适用范围。</strong>':''}${t.workflow.ai_proposal?`<p>AI 提案已提供，需人工核实：${esc(t.workflow.ai_proposal.summary||'进入原任务查看提案依据')}</p><p>需补充资料：${esc(Array.isArray(t.workflow.ai_proposal.missing_information)?t.workflow.ai_proposal.missing_information.join('；'):t.workflow.ai_proposal.missing_information||'接口未提供')}</p>`:''}<p><a href="${esc(advisorTaskPath(t))}">进入原模块方案与验收</a></p></article>`).join('')}</section>`;
  }).join('')||'<p>这个客户还没有分配给你的站内任务</p>';
}
export function mountAdvisorWorkbench({root,session,subscribeSession,fetchImpl=fetch,browser=window}){
  root.classList.add('advisor-workbench');
  // A known display hint survives the connected-page redirect; it never grants scope.
  const entryUrl=new URL(browser.location.href),noticeCode=entryUrl.searchParams.get('advisor_notice');
  const noticeMessage=['ADVISOR_GRANT_REVOKED','ADVISOR_ROLE_CHANGED'].includes(noticeCode)?'你的客户授权已变化，请重新选择客户':['ADVISOR_TENANT_NOT_GRANTED','ADVISOR_NO_TENANT','ADVISOR_GRANTS_UNAVAILABLE','ADVISOR_TENANT_SESSION_EXPIRED','ADVISOR_IDENTITY_SESSION_EXPIRED','ADVISOR_TENANT_SELECTION_REQUIRED'].includes(noticeCode)?advisorMessages[noticeCode]:'';
  if(entryUrl.searchParams.has('advisor_notice')){entryUrl.searchParams.delete('advisor_notice');browser.history?.replaceState(null,'',entryUrl.pathname+entryUrl.search+entryUrl.hash);}
  let tenantOptions=[],tenantName='',tenantMessage=noticeMessage,tenantBusy=false,multiMode=session.isAdvisorSession===true;
  const originalFetch=fetchImpl;
  fetchImpl=advisorScopedFetch({session,fetchImpl:originalFetch,onDenied:denyTenant});
  const tenantSwitch=createAdvisorTenantSwitch({session,fetchImpl});
  function clearCustomer(){epoch++;identity=null;states={};linkedAccounts=[];selectedAccount=null;filter='all';client.invalidate('tenant_changing');automation.invalidate();distribution.invalidate();remote?.invalidate();}
  function denyTenant(code){
    clearCustomer();tenantSwitch.invalidate();tenantBusy=false;tenantName='';tenantMessage=['ADVISOR_GRANT_REVOKED','ADVISOR_ROLE_CHANGED'].includes(code)?'你的客户授权已变化，请重新选择客户':advisorMessages[code]||'请重新选择客户';message='';
    if(code==='ADVISOR_NO_TENANT')tenantOptions=[];
    if(code==='ADVISOR_ROLE_CHANGED')session.logout();
    else if(!['ADVISOR_GRANTS_UNAVAILABLE','ADVISOR_IDENTITY_SESSION_EXPIRED'].includes(code))session.restoreAdvisorIdentity();
    render();
    if(session.token&&!['ADVISOR_GRANTS_UNAVAILABLE','ADVISOR_NO_TENANT'].includes(code))void loadTenants();
  }
  async function loadTenants(){
    const stamp=epoch;
    try{const rows=await tenantSwitch.list();if(disposed||epoch!==stamp)return;tenantOptions=rows;
      tenantName=rows.find(t=>t.id===session.tenantId)?.name||'';
      if(!rows.length){clearCustomer();tenantName='';tenantMessage=advisorMessages.ADVISOR_NO_TENANT;message='';}
      render();
    }catch(error){if(!disposed&&epoch===stamp){tenantOptions=[];tenantMessage=advisorMessages[error.code]||'客户清单读取失败，请重试';render();}}
  }
  async function switchTenant(tenantId){
    if(tenantBusy||!tenantOptions.some(t=>t.id===tenantId))return;
    if(identity&&!browser.confirm('切换客户将清除当前客户的未保存草稿和筛选，是否继续？')){render();return;}
    clearCustomer();tenantSwitch.invalidate();tenantBusy=true;tenantName='';tenantMessage='正在切换客户…';message='';render();
    try{const result=await tenantSwitch.select(tenantId);if(disposed)return;tenantName=result.tenant_name;tenantMessage='';tenantBusy=false;
      browser.history?.replaceState(null,'','/customer-workbench/?console=advisor');await initialize();}
    catch(error){if(!disposed&&error.code!=='CONTEXT_CHANGED'){tenantBusy=false;tenantMessage=advisorMessages[error.code]||'客户切换未完成，请重试';render();}}
  }
  function tenantView(){
    if(!multiMode)return '';
    const current=tenantOptions.find(t=>t.id===session.tenantId);
    return `<section class="advisor-tenant-picker" aria-label="当前客户"><strong>当前客户：${esc(tenantName||'尚未选择')}</strong>${tenantOptions.length>1||(!current&&tenantOptions.length)?`<details><summary>切换客户</summary><div role="group" aria-label="可切换客户">${tenantOptions.map(t=>`<button data-advisor="select-tenant" data-tenant="${t.id}" ${tenantBusy?'disabled':''}>${esc(t.name)}${current?.id===t.id?'（当前）':''}</button>`).join('')}</div></details>`:''}${tenantMessage?`<p role="alert">${esc(tenantMessage)}</p>`:''}${!session.token?'<p>请重新登录后选择其他客户。</p>':''}</section>`;
  }
  const client=createAdvisorClient({session,subscribeSession,fetchImpl});
  const accountSwitch=createAdvisorAccountSwitch({session,fetchImpl,navigate:path=>browser.location.assign(path)});
  let linkedAccounts=[],selectedAccount=null,switching=false;
  const selectionPrompt='请先在上方选择客户，再查看站内任务';
  const needsTenant=()=>session.isAdvisorSession===true&&(session.advisorScope!=='advisor_tenant'||!session.tenantId);
  let identity=null,states={},filter='all',epoch=0,disposed=false,message='正在核验顾问身份与模块…';
  const distribution=createAdvisorDistributionPanel({session,subscribeSession,fetchImpl,browser,onChange:renderDistribution,
    scopesForAdvisor:()=>[...new Map([...Object.values(states).flatMap(state=>state.page?.items||[]),...automation.assignedScopes()].map(row=>[
      `${row.module}:${row.tenant_id}:${row.scope_id}`,{module:row.module,tenant_id:row.tenant_id,scope_id:row.scope_id,
        tenant_name:row.tenant_name,scope_name:row.scope_name}])).values()]});
  function renderDistribution(){const host=root.querySelector('.advisor-distribution-host');if(!disposed&&host){host.innerHTML=identity?distribution.html():'';remote?.render();}}
  const remote=session.isAdvisorSession===true?null:createAdvisorRemotePanel({root,session,subscribeSession,fetchImpl,browser,getContext:()=>identity?distribution.remoteContext():null,getTasks:()=>identity?distribution.remoteTasks():[]});

  const automation=createAdvisorAutomationPanel({session,subscribeSession,fetchImpl,browser,onChange:()=>{renderAutomation();renderDistribution();},onDenied:reason=>client.invalidate(reason),tasksForProject:project=>(states[project.module]?.page?.items||[]).filter(task=>task.tenant_id===project.tenant_id&&task.scope_id===project.scope_id&&task.workflow.phase==='draft'&&!task.workflow.ai_proposal)});
  function renderAutomation(){if(disposed)return;const host=root.querySelector('.advisor-automation-host');if(!host)return;
    const focused=browser.document.activeElement,focusedKey=host.contains(focused)?focused.closest('[data-automation-project]')?.dataset.automationProject:null,field=focusedKey?focused.name:null;
    const selection=field&&typeof focused.selectionStart==='number'?[focused.selectionStart,focused.selectionEnd]:null;
    const openKeys=[...host.querySelectorAll('details[open]')].map(details=>details.closest('[data-automation-project]')?.dataset.automationProject);
    host.innerHTML=identity?automation.html(filter):'';
    for(const key of openKeys){const details=host.querySelector(`[data-automation-project="${key}"] details`);if(details)details.open=true;}
    if(focusedKey&&['task_ids','operation','max_dispatches','max_external_calls','cycle_mode','cycle_enabled'].includes(field)){const next=host.querySelector(`[data-automation-project="${focusedKey}"] [name="${field}"]`);if(next){next.focus({preventScroll:true});if(selection)next.setSelectionRange(...selection);}}
  }
  const labels={NOT_INTEGRATED:'未接入：专用顾问接口尚不可用',READ_FAILED:'读取失败，请重试',CONTRACT_MISMATCH:'接口范围或版本未通过核验',PERMISSION_DENIED:'当前账号无权读取站内任务',AUTH_EXPIRED:'登录已过期，请重新登录',ADVISOR_GRANT_REVOKED:'你的客户授权已变化，请重新选择客户',ADVISOR_ROLE_CHANGED:'你的客户授权已变化，请重新选择客户',NOT_AUTHENTICATED:'请先登录',IDENTITY_MISMATCH:'账号身份未通过核验'};
  function render(){if(disposed)return;
    root.innerHTML=`<header class="entry-header"><b>G-SNIPERS</b><span>顾问工作台</span><a href="${multiMode?'/customer-workbench/?console=advisor&module=seo':'/customer-workbench/'}">${multiMode?'SEO':'客户工作台'}</a><a href="/customer-workbench/?${multiMode?'console=advisor&':''}module=geo">GEO</a><a href="/workspace/cockpit">平台工作台</a><button data-advisor="logout">退出账号</button></header><main class="advisor-main">${tenantView()}<h1>我的站内交付任务</h1><p>${esc(identity?.user.display_name||identity?.user.username||'')} · 仅显示后端授权并分配给当前顾问的任务。</p><p>AI 提供建议；事实核实、重要发布与最终验收由人工完成。网站修改由维护人员实施。</p><p class="advisor-boundary">SEM 本轮暂不接入 AI 接管，继续人工处理；SEO/GEO 的自动控制范围以项目记录为准。</p><p role="status" aria-live="polite">${esc(message)}</p><div class="advisor-tools"><label>模块 <select id="advisor-module"><option value="all">全部可用模块</option>${(identity?.modules||[]).map(m=>`<option value="${m}" ${filter===m?'selected':''}>${m.toUpperCase()}</option>`).join('')}</select></label><button data-advisor="refresh">重新检查任务权限并刷新</button></div>${!identity&& !session.token?'<a href="/customer-workbench/?console=advisor&login=1">登录顾问工作台</a>':''}${identity&&!identity.modules.length?'<p>当前账号没有可用的顾问模块入口。顾问资格及任务分配由后端核验。</p>':''}${needsTenant()?`<section class="advisor-module"><h2>站内任务</h2><p role="status">${selectionPrompt}</p></section>`:''}${(identity?.modules||[]).filter(m=>filter==='all'||filter===m).map(m=>{const s=states[m];return `<section class="advisor-module" data-module="${m}"><h2>${m.toUpperCase()} 站内任务</h2><p role="status">${esc(s?.error|| (s?.busy?'正在读取…':''))}</p>${s?.page?advisorPageView(m,s.page):''}<div class="advisor-tools"><button data-advisor="latest" data-module="${m}" ${s?.busy?'disabled':''}>返回第一页并刷新</button>${s?.page?.next_before_id?`<button data-advisor="next" data-module="${m}" ${s.busy?'disabled':''}>下一页（最多 25 项）</button>`:''}</div></section>`;}).join('')}<div class="advisor-automation-host">${identity?automation.html(filter):''}</div></main>`;
    if(identity){
      if(!multiMode&&linkedAccounts.length){
        const tools=root.querySelector('.advisor-tools'),label=browser.document.createElement('label');
        label.textContent='切换顾问账号 ';
        const select=browser.document.createElement('select');select.id='advisor-account';
        const blank=browser.document.createElement('option');blank.value='';blank.textContent='请选择客户账号';select.append(blank);
        for(const account of linkedAccounts){const option=browser.document.createElement('option');option.value=String(account.id);option.textContent=`${account.customer_name} · ${account.display_name}`;select.append(option);}
        select.value=selectedAccount?String(selectedAccount):'';label.append(select);tools.append(label);
        const button=browser.document.createElement('button');button.dataset.advisor='switch-account';button.textContent='切换账号';button.disabled=!selectedAccount||switching;tools.append(button);
      }
      const host=browser.document.createElement('div');host.className='advisor-distribution-host';root.querySelector('.advisor-main').append(host);host.innerHTML=distribution.html();if(remote){const remoteHost=browser.document.createElement('div');remoteHost.className='advisor-remote-host';root.querySelector('.advisor-main').append(remoteHost);remote.render();}
    }
  }
  async function load(module,beforeId=null){if(needsTenant()){states[module]={error:selectionPrompt};render();return;}const stamp=epoch;states[module]={busy:true};render();try{const page=await client.list(module,{beforeId,tenantId:session.advisorScope==='advisor_tenant'?session.tenantId:null});if(!disposed&&epoch===stamp){states[module]={page,busy:false};render();}}catch(e){if(!disposed&&epoch===stamp){states[module]={error:`${module.toUpperCase()} 站内任务暂时读不到，其他模块不受影响`};render();}}}
  async function initialize(){
    multiMode=session.isAdvisorSession===true;
    if(multiMode){
      clearCustomer();filter=['seo','geo'].includes(entryUrl.searchParams.get('module'))?entryUrl.searchParams.get('module'):'all';message='';render();await loadTenants();
      if(disposed||!tenantOptions.length)return;
      if(needsTenant()){tenantMessage=tenantMessage||'请先选择客户';render();return;}
      if(!tenantOptions.some(t=>t.id===session.tenantId)){denyTenant('ADVISOR_TENANT_NOT_GRANTED');return;}
      const requested=new URL(browser.location.href).searchParams.get('tenant_id');
      if(requested&&Number(requested)!==session.tenantId){denyTenant('ADVISOR_TENANT_NOT_GRANTED');return;}
    }
    const stamp=++epoch;identity=null;states={};linkedAccounts=[];selectedAccount=null;automation.invalidate();distribution.invalidate();remote?.invalidate();message='正在核验顾问身份与模块…';render();try{const result=await client.initialize();if(disposed||epoch!==stamp)return;identity=result;if(!multiMode)void accountSwitch.list().then(accounts=>{if(!disposed&&epoch===stamp){linkedAccounts=accounts;render();}}).catch(()=>{});message='按真实阶段分组；数量仅为当前页。';render();await Promise.all([...result.modules.map(m=>load(m)),automation.initialize(result.modules)]);if(!disposed&&epoch===stamp){if(multiMode)distribution.filterModule(filter);await distribution.initialize(result.modules.filter(m=>m!=='seo'||result.user.permissions?.['seo.content']==='edit'));}}catch(e){if(!disposed&&epoch===stamp){message=labels[e.code]||'核验未完成，请重试';render();}}}
  // Logout emits a context change after expiry; keep the actionable login message.
  const stop=client.subscribe(reason=>{if(reason==='context_changed'||reason==='expired'||reason==='forbidden'){epoch++;identity=null;states={};linkedAccounts=[];selectedAccount=null;automation.invalidate();distribution.invalidate();remote?.invalidate();message=reason==='expired'||reason==='context_changed'&&message===labels.AUTH_EXPIRED?labels.AUTH_EXPIRED:'你的客户授权已变化，请重新选择客户';render();}});
  function click(e){automation.click(e);distribution.click(e);const b=e.target.closest('[data-advisor]');if(!b||b.disabled)return;const action=b.dataset.advisor;
    if(action==='select-tenant'){void switchTenant(Number(b.dataset.tenant));return;}
    if(action==='switch-account'&&selectedAccount&&!switching){switching=true;render();void accountSwitch.switchTo(selectedAccount).catch(()=>{switching=false;message='账号切换未完成，请重试。';render();});return;}
    if(action==='logout'){tenantSwitch.invalidate();tenantOptions=[];tenantName='';tenantMessage='';epoch++;identity=null;states={};linkedAccounts=[];selectedAccount=null;automation.invalidate();distribution.invalidate();remote?.invalidate();client.invalidate();session.logout();message='已退出。';render();}
    if(action==='refresh')void initialize();
    if(['latest','next'].includes(action)&&identity?.modules.includes(b.dataset.module)){const m=b.dataset.module;void load(m,action==='next'?states[m]?.page?.next_before_id:null);}
  }
  function change(e){if(e.target.id==='advisor-account'){selectedAccount=Number(e.target.value)||null;render();return;}if(['distribution_scope','distribution_binding'].includes(e.target.name)||e.target.id==='advisor-module')remote?.invalidate();distribution.change(e);if(e.target.id==='advisor-module'){filter=e.target.value;distribution.filterModule(filter);render();}}
  root.addEventListener('click',click);root.addEventListener('change',change);root.addEventListener('input',automation.input);root.addEventListener('submit',automation.submit);render();void initialize();
  return {dispose(){disposed=true;tenantSwitch.invalidate();epoch++;stop();client.dispose();automation.dispose();distribution.dispose();remote?.dispose();root.removeEventListener('click',click);root.removeEventListener('change',change);root.removeEventListener('input',automation.input);root.removeEventListener('submit',automation.submit);root.classList.remove('advisor-workbench');root.replaceChildren();}};
}
