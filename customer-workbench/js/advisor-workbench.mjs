import {createAdvisorClient} from './advisor-client.mjs';
import {escapeText as esc} from './customer-display.mjs';
import {workbenchPath,geoWorkbenchPath} from './workbench-entry.mjs';
const phases={draft:'待制定方案',review:'待人工审核',implementation:'待网站实施',recheck:'待页面复检',acceptance:'待人工验收',done:'已验收',cancelled:'已取消'};
export function advisorTaskPath(row){
  return (row.module==='geo'?geoWorkbenchPath(row.tenant_id,row.scope_id):workbenchPath(row.tenant_id,row.scope_id))+'&'+new URLSearchParams({onsite_task_id:row.id});
}
export function advisorPageView(module,page){
  return Object.entries(phases).map(([phase,label])=>{
    const rows=page.items.filter(t=>t.workflow.phase===phase);if(!rows.length)return '';
    return `<section class="advisor-group"><h3>${label} · 本页 ${rows.length} 项</h3>${rows.map(t=>`<article class="advisor-task"><h4>${esc(t.title||'站内任务')} #${t.id}</h4><p>${module.toUpperCase()} · ${esc(t.tenant_name||'客户 #'+t.tenant_id)} / ${esc(t.scope_name||(module==='geo'?'项目 #':'网站 #')+t.scope_id)}</p><p>月份：${esc(t.workflow.month||'不适用')} · 实施负责人：${esc(t.workflow.owner_name||'尚未指定')} · 服务端版本 v${t.workflow.revision}</p><p>下一步人工动作：${esc(t.next_action||'接口未提供，请进入任务核对')}</p><p>阻塞原因：${esc(t.blocker||'接口未提供阻塞说明')}</p>${phase==='review'?'<strong>方案待人工审核，请核实事实与适用范围。</strong>':''}${t.workflow.ai_proposal?`<p>AI 提案已提供，需人工核实：${esc(t.workflow.ai_proposal.summary||'进入原任务查看提案依据')}</p><p>需补充资料：${esc(Array.isArray(t.workflow.ai_proposal.missing_information)?t.workflow.ai_proposal.missing_information.join('；'):t.workflow.ai_proposal.missing_information||'接口未提供')}</p>`:''}<p><a href="${esc(advisorTaskPath(t))}">进入原模块方案与验收</a></p></article>`).join('')}</section>`;
  }).join('')||'<p>当前页没有获分配的站内任务。</p>';
}
export function mountAdvisorWorkbench({root,session,subscribeSession,fetchImpl=fetch,browser=window}){
  root.classList.add('advisor-workbench');const client=createAdvisorClient({session,subscribeSession,fetchImpl});
  let identity=null,states={},filter='all',epoch=0,disposed=false,message='正在核验顾问身份与模块…';
  const labels={NOT_INTEGRATED:'未接入：专用顾问接口尚不可用',READ_FAILED:'读取失败，请重试',CONTRACT_MISMATCH:'接口范围或版本未通过核验',PERMISSION_DENIED:'权限已变化，列表已清除',AUTH_EXPIRED:'登录已失效，列表已清除',NOT_AUTHENTICATED:'请先登录',IDENTITY_MISMATCH:'账号身份未通过核验'};
  function render(){if(disposed)return;
    root.innerHTML=`<header class="entry-header"><b>G-SNIPERS</b><span>顾问工作台</span><a href="/customer-workbench/">客户工作台</a><a href="/customer-workbench/?module=geo">GEO</a><a href="/workspace/cockpit">平台工作台</a><button data-advisor="logout">退出账号</button></header><main class="advisor-main"><h1>我的站内交付任务</h1><p>${esc(identity?.user.display_name||identity?.user.username||'')} · 仅显示后端授权并分配给当前顾问的任务。</p><p>AI 提供建议；事实核实、重要发布与最终验收由人工完成。网站修改由维护人员实施。</p><p role="status" aria-live="polite">${esc(message)}</p><div class="advisor-tools"><label>模块 <select id="advisor-module"><option value="all">全部可用模块</option>${(identity?.modules||[]).map(m=>`<option value="${m}" ${filter===m?'selected':''}>${m.toUpperCase()}</option>`).join('')}</select></label><button data-advisor="refresh">重新核验与刷新</button></div>${!identity&& !session.token?'<a href="/customer-workbench/?console=advisor&login=1">登录顾问工作台</a>':''}${identity&&!identity.modules.length?'<p>当前账号没有可用的顾问模块入口。顾问资格及任务分配由后端核验。</p>':''}${(identity?.modules||[]).filter(m=>filter==='all'||filter===m).map(m=>{const s=states[m];return `<section class="advisor-module" data-module="${m}"><h2>${m.toUpperCase()} 站内任务</h2><p role="status">${esc(s?.error|| (s?.busy?'正在读取…':''))}</p>${s?.page?advisorPageView(m,s.page):''}<div class="advisor-tools"><button data-advisor="latest" data-module="${m}" ${s?.busy?'disabled':''}>读取最新一页</button>${s?.page?.next_before_id?`<button data-advisor="next" data-module="${m}" ${s.busy?'disabled':''}>下一页（最多 25 项）</button>`:''}</div></section>`;}).join('')}</main>`;
  }
  async function load(module,beforeId=null){const stamp=epoch;states[module]={busy:true};render();try{const page=await client.list(module,{beforeId});if(!disposed&&epoch===stamp){states[module]={page,busy:false};render();}}catch(e){if(!disposed&&epoch===stamp){states[module]={error:labels[e.code]||'读取未完成，请重试'};render();}}}
  async function initialize(){const stamp=++epoch;identity=null;states={};message='正在核验顾问身份与模块…';render();try{const result=await client.initialize();if(disposed||epoch!==stamp)return;identity=result;message='按真实阶段分组；数量仅为当前页。';render();await Promise.all(result.modules.map(m=>load(m)));}catch(e){if(!disposed&&epoch===stamp){message=labels[e.code]||'核验未完成，请重试';render();}}}
  const stop=client.subscribe(reason=>{if(reason==='context_changed'||reason==='expired'||reason==='forbidden'){epoch++;identity=null;states={};message=reason==='forbidden'?'权限已变化，全部列表已清除。':'会话已变化，全部列表已清除。';render();}});
  function click(e){const b=e.target.closest('[data-advisor]');if(!b||b.disabled)return;const action=b.dataset.advisor;
    if(action==='logout'){epoch++;identity=null;states={};client.invalidate();session.logout();message='已退出。';render();}
    if(action==='refresh')void initialize();
    if(['latest','next'].includes(action)&&identity?.modules.includes(b.dataset.module)){const m=b.dataset.module;void load(m,action==='next'?states[m]?.page?.next_before_id:null);}
  }
  function change(e){if(e.target.id==='advisor-module'){filter=e.target.value;render();}}
  root.addEventListener('click',click);root.addEventListener('change',change);render();void initialize();
  return {dispose(){disposed=true;epoch++;stop();client.dispose();root.removeEventListener('click',click);root.removeEventListener('change',change);root.classList.remove('advisor-workbench');root.replaceChildren();}};
}
