import {escapeText as esc} from './customer-display.mjs';
import {createPlatformConsoleClient,platformConsolePath,isPlatformAdmin} from './platform-console-client.mjs';
import {renderControlPanel,hydrateControlForm,controlPayload} from './platform-control-panel.mjs';
import {renderSystemConfig,hydrateConnectionForm,setConnectionMode,connectionPayload} from './platform-system-config.mjs';
import {renderUsagePanel,renderAlertsPanel,renderSuppliersPanel,renderBackupPanel} from './platform-ops-panel.mjs';

const tabs=[['overview','平台总览'],['customers','客户与服务'],['accounts','账号与权限'],['apis','API 与调用'],
  ['costs','成本与用量'],['controls','API 与预算管理'],['config','系统配置'],['alerts','告警与处理'],['tasks','任务与调度'],['security','安全与运维'],['inventory','系统盘点']];
const value=n=>n==null?'待接入':Number(n).toLocaleString('zh-CN');
const time=s=>s?new Date(s).toLocaleString('zh-CN',{hour12:false}):'暂无记录';
const providerLabel=p=>({chinaz:'站长之家',dataforseo:'DataForSEO',dashscope:'阿里云百炼',deepseek:'DeepSeek',baidu:'百度推广'}[p]||p||'未提供');
const labels={active:'正常',paused:'已暂停',disabled:'已停用',expired:'已到期',open:'待处理',in_progress:'进行中',
  done:'已完成',cancelled:'已取消',pending:'待执行',running:'执行中',succeeded:'已完成',failed:'失败',refunded:'已退回',todo:'待处理',closed:'已关闭'};
const status=s=>`<span class="pc-tag ${['failed','expired','disabled'].includes(s)?'pc-tag-warning':''}">${esc(labels[s]||s||'未提供')}</span>`;
const empty=text=>`<div class="pc-empty">${esc(text)}</div>`;
const card=(title,body,note='')=>`<section class="pc-card"><div class="pc-section-head"><h2>${esc(title)}</h2></div>${note?`<p class="pc-note">${esc(note)}</p>`:''}${body}</section>`;
const link=(text,path)=>`<a class="pc-link" href="${path}">${esc(text)} <span aria-hidden="true">↗</span></a>`;
const table=(headers,rows)=>rows.length?`<div class="pc-table-wrap"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(cells=>`<tr>${cells.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:empty('暂无已记录数据');
const inventory=[
  ['客户与服务','已接入','客户、SEM/SEO/GEO 开通状态、服务到期时间、站点与项目。','客户与模块已有管理入口。'],
  ['账号与权限','已接入','实名账号、客户绑定、角色与权限、启停状态、最近登录。','维护沿用现有账号与角色页面。'],
  ['API 调用','已接入','完整台账筛选、分页和 CSV 导出；模型、Token、耗时和状态。','逐步补齐尚未接入计量的外部服务。'],
  ['成本与预算','已接入','客户与全部账号费用归集、单价版本、日/月预算及超限暂停。','服务商实际账单与估算费用对账。'],
  ['任务与调度','部分接入','查看 SEM/SEO 工单、GEO 异步任务和工单。','全局调度控制与统一恢复操作待接入。'],
  ['告警与通知','部分接入','异常统计、告警认领、处理说明、再次异常提醒及人工额度登记。','处理记录等待管理启用；外部告警发送待接入。'],
  ['配置与密钥','已接入','服务商开关、单价及已配置密钥在线轮换，密钥加密保存。','百度 OAuth 沿用原授权流程，增加服务商连通监测。'],
  ['操作审计','部分接入','接口配置、告警处理、账号创建启停、角色权限与密码重置均有审计。','等待管理启用；继续接入其他业务操作。'],
  ['备份与恢复','部分接入','读取实际数据库备份结果，区分归档校验与恢复验证。','定时备份与完整恢复演练继续完善。'],
];

export function mountPlatformConsole({root,session,fetchImpl=fetch,browser=window}){
  root.classList.add('platform-console');browser.document.title='超级管理员工作台 · G-SNIPERS';
  let page='overview',snapshot=null,identity=null,busy=false,disposed=false,ownChange=false,query='',revision=0;
  let loginController=null,notice='',saving=false,connectionId=null,alertId=null,supplierHost=null;
  const today=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date());
  const blankHistory=()=>({filters:{from:today().slice(0,7)+'-01',to:today()},data:null,cursors:[],busy:false,error:''});
  let history=blankHistory();
  const client=createPlatformConsoleClient({session,fetchImpl,onExpired:()=>login('登录已失效，请重新登录。'),
    refreshUser(user){ownChange=true;try{session.refreshUser(user);}finally{ownChange=false;}}});
  const source=name=>snapshot?.sources[name]||{state:'unavailable',total:null,rows:[],truncated:false};
  const tenant=id=>source('tenants').rows.find(t=>t.id===id)?.name||(id==null?'平台':'客户 '+id);
  const matches=text=>!query||String(text).toLocaleLowerCase().includes(query.toLocaleLowerCase());
  const summary=()=>[
    ['客户',source('tenants').total,'平台客户总数'],['使用账号',source('users').total,'客户与内部账号'],
    ['SEO 网站',source('seo_sites').total,'已登记站点'],['GEO 项目',source('geo_projects').total,'已登记项目'],
    ['24 小时调用',snapshot.api_costs?.calls_24h??snapshot.calls.total,'仅统计已记录接口'],['本月 API 估算',snapshot.api_costs?.estimated_amount??snapshot.costs.actual_amount,'已记录调用的估算费用'],
  ].map(([name,n,note])=>`<div class="pc-kpi"><small>${name}</small><strong>${name==='本月 API 估算'&&snapshot.api_costs?(n==null?'待定价':'¥'+Number(n).toLocaleString('zh-CN',{minimumFractionDigits:4,maximumFractionDigits:12})):value(n)}</strong><span>${note}</span></div>`).join('');
  function sourceNote(name){const s=source(name);return s.state!=='available'?'此数据源尚未接入，不能据此判断数量为零。':s.truncated?`显示最近 ${s.rows.length} 条，共 ${value(s.total)} 条。完整管理请进入对应页面。`:'';}
  function moduleRows(){
    return ['sem','seo','geo'].map(code=>{
      const rows=source('tenant_modules').rows.filter(m=>m.module_code===code),active=rows.filter(m=>m.status==='active'&&(!m.expires_at||m.expires_at>=snapshot.costs.date)).length;
      return `<div class="pc-module"><div><b>${code.toUpperCase()}</b><span>${{sem:'搜索广告服务',seo:'搜索优化服务',geo:'AI 搜索可见度服务'}[code]}</span></div><strong>${source('tenant_modules').state==='available'?value(active):'待接入'}<small> 个客户服务可用</small></strong></div>`;
    }).join('');
  }
  function overview(){
    return card('今天的平台情况',`<p class="pc-lead">集中查看客户、账号和服务运行情况。</p><div class="pc-module-grid">${moduleRows()}</div>`)+
      card('常用管理',`<div class="pc-shortcuts">${link('客户与模块','/platform/customers')}${link('账号管理','/platform/accounts')}${link('角色与权限','/platform/roles')}<button data-pc-page="apis">查看 API 调用</button><button data-pc-page="costs">查看成本与用量</button><button data-pc-page="inventory">查看系统盘点</button></div>`)+
      card('管理与后续接入',`<div class="pc-gap-grid">${[['API 成本与预算','调用与费用已统一，配置管理生效状态见系统配置；单价与预算见管理页。'],['账单对账','估算费用已归集，实际扣费以服务商账单为准。'],['运维记录','管理配置已有审计，备份状态和业务操作审计继续接入。']].map(([h,p])=>`<div><b>${h}</b><p>${p}</p></div>`).join('')}</div>`);
  }
  function customers(){
    const rows=source('tenants').rows.filter(t=>matches(t.name+' '+(t.industry||''))).map(t=>{
      const modules=source('tenant_modules').rows.filter(m=>m.tenant_id===t.id),sites=source('seo_sites').rows.filter(s=>s.tenant_id===t.id),projects=source('geo_projects').rows.filter(p=>p.tenant_id===t.id);
      const moduleState=m=>m.status==='active'&&m.expires_at&&m.expires_at<snapshot.costs.date?'expired':m.status;
      return [`<b>${esc(t.name)}</b><small class="pc-cell-note">${esc(t.industry||'行业未填写')}</small>`,source('tenant_modules').state!=='available'?'待接入':modules.map(m=>`<div class="pc-inline">${esc(m.module_code.toUpperCase())} ${status(moduleState(m))}${m.expires_at?`<small>${esc(m.expires_at)} 到期</small>`:''}</div>`).join('')||'暂未开通',
        source('seo_sites').state!=='available'?'待接入':sites.length?sites.map(s=>`<div>${esc(s.domain)}</div>`).join(''):'未登记',source('geo_projects').state!=='available'?'待接入':projects.length?projects.map(p=>`<div>${esc(p.name)}</div>`).join(''):'未登记',link('管理','/platform/customers')];
    });
    return card('客户与服务',`${search('搜索客户或行业')}${table(['客户','服务开通','SEO 网站','GEO 项目','操作'],rows)}`,sourceNote('tenants'));
  }
  function accounts(){
    const users=source('users').rows.filter(u=>matches(u.username+' '+(u.display_name||'')+' '+tenant(u.tenant_id))),roles=source('roles').rows;
    return card('账号管理',`${search('搜索账号、姓名或客户')}<div class="pc-shortcuts">${link('创建 / 编辑账号','/platform/accounts')}${link('维护角色与权限','/platform/roles')}</div>${table(['账号','角色','数据范围','状态','最近登录'],users.map(u=>[
      `<b>${esc(u.display_name||u.username)}</b><small class="pc-cell-note">${esc(u.username)}</small>`,esc(roles.find(r=>r.id===u.role_id)?.name||'未读取角色'),esc(u.tenant_id==null?'全局范围 · 受角色权限控制':tenant(u.tenant_id)),status(u.is_active?'active':'disabled'),esc(time(u.last_login_at)),
    ]))}`,sourceNote('users'))+
      card('角色与权限',table(['角色','授权范围','当前清单账号数'],roles.map(r=>[
        `<b>${esc(r.name)}</b><small class="pc-cell-note">${esc(r.description||'')}</small>`,`${Object.values(r.permissions||{}).filter(p=>p==='edit').length} 项编辑 / ${Object.values(r.permissions||{}).filter(p=>p==='view').length} 项查看`,value(source('users').rows.filter(u=>u.role_id===r.id).length),
      ])),'超管入口要求全局账号同时拥有客户管理和账号管理编辑权限。客户绑定仍由服务端校验。');
  }
  function apis(){
    const calls=(snapshot.api_costs?.recent||[]).filter(r=>matches(providerLabel(r.provider)+' '+(r.provider||'')+' '+(r.model||'')+' '+(r.endpoint||'')+' '+tenant(r.tenant_id)));
    return card('API 调用情况',`<div class="pc-metrics"><div><small>近 24 小时已记录</small><b>${value(snapshot.calls.total)}</b></div><div><small>异常记录</small><b>${value(snapshot.calls.failed)}</b></div><div><small>平均耗时</small><b>${snapshot.calls.average_latency_ms==null?'暂无记录':value(snapshot.calls.average_latency_ms)+' ms'}</b></div></div><p class="pc-note">${esc(snapshot.coverage.api)}</p>`)+
      card('本月服务商与具体接口',table(['模块','服务商','模型 / 接口','请求数','未定价请求'],(snapshot.api_costs?.provider_totals||[]).map(r=>[esc(r.module.toUpperCase()),esc(providerLabel(r.provider)),esc(r.model||r.endpoint||'按次接口'),value(r.calls),value(r.unpriced)])),'覆盖本月已计量调用；按具体接口分别统计。站长之家在此显示，不受最近 50 条明细限制。')+
      card('最近调用',`${search('搜索服务商、接口或客户')}${table(['时间','客户','服务商','接口 / 模型','结果','耗时','请求编号'],calls.map(r=>[esc(time(r.started_at)),esc(tenant(r.tenant_id)),esc(providerLabel(r.provider)),esc(r.model||r.endpoint||'未记录'),status(r.state),r.latency_ms==null?'未记录':value(r.latency_ms)+' ms',esc(r.provider_request_id||r.id||'未记录')]))}`,'与成本页使用同一调用台账，显示最近 50 次真实外部请求。')+
      renderUsagePanel({snapshot,history,esc,card,table,tenant,time,providerLabel})+
      card('GEO 采样引擎',table(['客户','引擎','采样方式','模型','状态'],source('geo_tracking_engines').rows.map(e=>[esc(tenant(e.tenant_id)),esc(e.display_name||e.engine_key),e.sample_mode==='openai_compat'?'真实接口配置':e.sample_mode==='mock_persona'?'模拟采样':esc(e.sample_mode||'未提供'),esc(e.model||'未提供'),status(e.enabled?'active':'disabled')])),'采样方式来自已有配置，不表示接口已通过实时测试。运行密钥由服务器管理。');
  }
  function costs(){
    const api=snapshot.api_costs;
    if(api&&['recording','ready'].includes(api.state)){
      const money=n=>n==null?'待定价':`¥${Number(n).toLocaleString('zh-CN',{minimumFractionDigits:4,maximumFractionDigits:12})}`;
      const blank={calls:0,input_tokens:0,output_tokens:0,known_amount:'0',estimated_amount:'0',unpriced:0};
      const cells=r=>[value(r.calls),`${value(r.input_tokens)} / ${value(r.output_tokens)}`,money(r.estimated_amount),value(r.unpriced)];
      const userRows=source('users').rows.filter(u=>matches(u.username+' '+(u.display_name||''))).map(u=>{
        const r=api.user_totals.find(r=>r.user_id===u.id)||blank;
        return [esc(u.display_name||u.username),esc(tenant(u.tenant_id)),status(u.is_active?'active':'disabled'),...cells(r)];
      });
      const customerRows=source('tenants').rows.filter(t=>matches(t.name)).map(t=>[esc(t.name),...cells(api.tenant_totals.find(r=>r.tenant_id===t.id)||blank)]);
      const system=api.user_totals.find(r=>r.user_id==null)||blank;
      return card('本月 API 费用',`<div class="pc-metrics"><div><small>已定价小计</small><b>${money(api.known_amount)}</b></div><div><small>本月估算合计</small><b>${money(api.estimated_amount)}</b></div><div><small>已记录请求</small><b>${value(api.calls)}</b></div></div><p class="pc-lead">${esc(api.note)}</p><p class="pc-note">${esc(api.period)} · ${api.state==='recording'?'计量已启用':'计量等待启用'} · 未定价请求 ${value(api.unpriced)} · 等待完成 ${value(api.pending)}</p>`)+
        card('全部账号的 API 用量与费用',`${search('搜索客户或账号')}${table(['账号','所属客户','状态','请求数','输入 / 输出 Token','估算费用','未定价请求'],userRows)}`,`覆盖清单内全部 ${value(source('users').total)} 个登录账号，包括停用和当月无调用账号。无登录账号的自动任务另行汇总。${sourceNote('users')}`)+
        card('无登录账号的任务与运维调用',table(['归属','请求数','输入 / 输出 Token','估算费用','未定价请求'],[['系统任务 / 运维调用',...cells(system)]]),'客户归属取服务端已授权范围；无法确认客户的请求保留在“未归属”汇总。')+
        card('全部客户的 API 用量与费用',table(['客户','请求数','输入 / 输出 Token','估算费用','未定价请求'],customerRows),'客户汇总和账号汇总是同一批调用的不同视角，不能相加。')+
        card('未归属客户的调用',table(['归属','请求数','输入 / 输出 Token','估算费用','未定价请求'],[['未归属客户',...cells(api.unattributed)]]))+
        card('服务商与模型',table(['模块','服务商','模型 / 接口','请求数','输入 / 输出 Token','估算费用','未定价请求'],api.provider_totals.map(r=>[esc(r.module.toUpperCase()),esc(providerLabel(r.provider)),esc(r.model||r.endpoint||'按次接口'),...cells(r)])))+
        card('最近真实调用',table(['时间','客户','账号 / 任务','模块','模型 / 接口','状态','费用'],api.recent.map(r=>[esc(time(r.started_at)),esc(r.tenant_id==null?'未归属':tenant(r.tenant_id)),esc(source('users').rows.find(u=>u.id===r.user_id)?.username||r.job_ref||'系统'),esc(r.module),esc(r.model||r.operation),status(r.state),money(r.estimated_amount)])),'每次真实请求分别记录；本地规则、模拟采样和缓存命中不产生新的外部调用记录。');
    }
    const rows=snapshot.costs.usage.filter(r=>matches(tenant(r.tenant_id)));
    return card('平台成本',`<div class="pc-metrics"><div><small>实际费用</small><b>待接入</b></div><div><small>估算费用</small><b>待接入</b></div><div><small>费用预算</small><b>待统一</b></div></div><p class="pc-lead">${esc(snapshot.costs.note)}</p><p class="pc-note">客户广告投放预算与平台 API 成本分别管理。</p>`)+
      card('今日已记录用量',`${search('搜索客户')}${table(['客户','AI 请求','工作台对话请求','抓取 URL'],rows.map(r=>[esc(tenant(r.tenant_id)),value(r.ai_requests),value(r.chat_requests),value(r.crawl_urls)]))}`,`北京时间 ${snapshot.costs.date} · 此表仅覆盖已有 SEO 配额计数；工作台对话可能同时计入 AI 请求，两列不能相加。`)+
      card('成本建设清单',`<div class="pc-gap-grid">${[['用量与归属','按客户、项目、模型记录 token、调用量及请求编号。'],['计价与预算','维护单价版本与预算上限，超限按服务策略处理。'],['账单与对账','实际账单、估算费用及退款分别记录。']].map(([h,p])=>`<div><b>${h}</b><p>${p}</p></div>`).join('')}</div>`);
  }
  function tasks(){
    return ['sem_tasks','seo_tasks','geo_async_jobs','geo_action_tickets'].map(name=>{
      const title={sem_tasks:'SEM 工作任务',seo_tasks:'SEO 执行任务',geo_async_jobs:'GEO 异步任务',geo_action_tickets:'GEO 处理工单'}[name];
      return card(title,table(['客户','任务','状态','更新时间'],source(name).rows.map(t=>[esc(tenant(t.tenant_id)),esc(t.title||({generate_article:'生成稿件',push_batch:'批量推送',create_variants:'生成渠道版本'}[t.kind]||t.kind||'未提供')),status(t.status),esc(time(t.updated_at||t.created_at))])),sourceNote(name));
    }).join('')+card('执行与恢复',`<p>任务处理沿用各模块工作区，进入对应客户范围后查看执行依据。</p><div class="pc-shortcuts">${link('打开运营工作台','/workspace')}${link('打开客户工作台','/customer-workbench/')}</div>`,'此页面读取已有任务状态，不会自动触发、重试或发布任务。');
  }
  function security(){
    return card('数据与权限',`<div class="pc-gap-grid"><div><b>全局超管</b><p>当前账号：${esc(identity.display_name||identity.username)}。入口由服务端校验双重管理权限。</p></div><div><b>客户隔离</b><p>客户账号仍绑定自己的客户范围，业务操作继续校验站点、项目与权限。</p></div><div><b>密钥管理</b><p>${esc(snapshot.coverage.credentials)}</p></div></div>`)+
      card('授权状态',table(['客户','服务','状态','到期时间'],source('baidu_oauth_grants').rows.map(r=>[esc(tenant(r.tenant_id)),'百度推广',status(r.expires_at&&new Date(r.expires_at)<new Date()?'expired':r.status),esc(time(r.expires_at))])),sourceNote('baidu_oauth_grants'))+
      card('运维接入情况',`<div class="pc-gap-grid"><div><b>备份与恢复</b><p>${esc(snapshot.coverage.backup)}</p></div><div><b>操作审计</b><p>${esc(snapshot.coverage.audit)}</p></div><div><b>配置版本</b><p>管理配置带版本检查，密钥可恢复服务器原配置；历史请求保留当时单价。</p></div></div>`)+
      renderBackupPanel({snapshot,esc,card,table,time})+
      card('最近管理操作',table(['时间','管理员','操作','范围','变更前','变更后'],(snapshot.controls?.audit||[]).map(r=>[
        esc(time(r.created_at)),esc(source('users').rows.find(u=>u.id===r.actor_id)?.username||'账号 '+r.actor_id),
        esc({'budget.update':'预算设置','provider.update':'接口开关','rate.update':'单价修改','credential.update':'密钥设置','connection.update':'接口配置',
          'user.create':'创建账号','user.update':'修改账号与范围','user.password':'重置密码','role.create':'创建角色','role.update':'修改角色权限','role.delete':'删除角色',
          'alert.claim':'认领告警','alert.resolve':'标记告警处理','alert.reopen':'重新打开告警','supplier.update':'登记服务商额度'}[r.action]||r.action),
        esc(r.resource),esc(JSON.stringify(r.before_value)),esc(JSON.stringify(r.after_value))])), '显示最近 50 条记录。密钥变更仅显示来源与版本，不记录密钥内容。');
  }
  function controls(){return renderControlPanel({snapshot,esc,card,table,tenant});}
  function config(){return renderSystemConfig({snapshot,esc,card,table,selected:connectionId});}
  function alertsPage(){return renderAlertsPanel({snapshot,selected:alertId,esc,card,table,tenant,time,users:source('users').rows})+
    renderSuppliersPanel({snapshot,selected:supplierHost,esc,card,table,time});}
  function inventoryView(){return card('系统盘点',table(['能力','当前接入','已有基础','后续开发'],inventory.map(([n,s,d,next])=>{
    const pending=snapshot.controls?.state!=='enabled'&&['成本与预算','配置与密钥','操作审计'].includes(n);
    return [`<b>${n}</b>`,status(pending?'管理待启用':s),esc(d),esc(pending?'管理模块代码已就绪，等待数据库审核启用。':next)];
  })),'盘点以当前源码、接口和本页实际接入范围为依据。已接入、部分接入与待接入分别标注。');}
  function search(placeholder){return `<label class="pc-search"><span>筛选</span><input id="pc-search" type="search" value="${esc(query)}" placeholder="${placeholder}" maxlength="100"></label>`;}
  function render(){
    if(disposed||!snapshot)return;
    const alerts=[...(snapshot.alerts||[])].filter(a=>a.handling?.status!=='resolved');
    if(snapshot.api_costs?.unpriced>0)alerts.unshift({tenant_id:null,severity:'warning',message:`本月 ${value(snapshot.api_costs.unpriced)} 次调用尚未定价，请按接口维护单价。`});
    if(snapshot.controls?.state!=='enabled')alerts.push({tenant_id:null,severity:'warning',message:'接口配置与预算管理尚未启用，调用计量继续运行。'});
    root.innerHTML=`<header class="pc-header"><a class="pc-brand" href="${platformConsolePath}">G-SNIPERS</a><span class="pc-header-label">超级管理员工作台</span><span class="pc-admin-badge">平台管理</span><div class="pc-header-actions"><span>${esc(identity.display_name||identity.username)}</span><a href="/customer-workbench/">客户工作台</a><button data-pc="logout">退出</button></div></header><div class="pc-layout"><aside class="pc-sidebar"><small>全局管理</small><nav aria-label="超级管理员导航">${tabs.map(([id,label])=>`<button data-pc-page="${id}" ${page===id?'aria-current="page" class="active"':''}>${label}</button>`).join('')}</nav><div class="pc-sidebar-foot"><b>统一管理入口</b><p>客户、账号和服务记录集中查看。</p></div></aside><main class="pc-main"><div class="pc-title"><div><small>平台管理 / ${tabs.find(t=>t[0]===page)[1]}</small><h1>${tabs.find(t=>t[0]===page)[1]}</h1></div><button data-pc="refresh" ${busy?'disabled':''}>${busy?'正在读取…':'刷新数据'}</button></div><p class="pc-updated" role="status">最近读取 ${esc(time(snapshot.generated_at))} · 数据来自现有系统</p><p class="pc-save-notice" role="status">${esc(notice)}</p><div class="pc-kpis">${summary()}</div><div class="pc-content">${({overview,customers,accounts,apis,costs,controls,config,alerts:alertsPage,tasks,security,inventory:inventoryView})[page]()}</div></main><aside class="pc-right"><section class="pc-card"><div class="pc-section-head"><h2>告警与待处理</h2><span class="pc-tag">${alerts.length}</span></div><p class="pc-note">来自已有记录的提醒</p>${alerts.length?alerts.map(a=>`<div class="pc-alert"><span class="pc-alert-dot ${a.severity==='error'?'error':''}"></span><div><b>${esc(tenant(a.tenant_id))}</b><p>${esc(a.message)}</p></div></div>`).join(''):empty('暂无已记录告警')}<p class="pc-note">告警覆盖随数据源接入逐步完善。</p></section><section class="pc-card pc-help"><h2>管理入口</h2>${link('客户与模块','/platform/customers')}${link('账号与角色','/platform/accounts')}<button data-pc-page="inventory">查看系统盘点 →</button></section></aside></div>`;
    root.querySelectorAll(".pc-control-form").forEach(form=>form.dataset.controlKind==='connection'?hydrateConnectionForm(form,snapshot):hydrateControlForm(form,snapshot));
  }
  function gate(title,note){root.innerHTML=`<header class="pc-header"><a class="pc-brand" href="${platformConsolePath}">G-SNIPERS</a><span>超级管理员工作台</span></header><main class="pc-gate"><section class="pc-card"><small>平台管理</small><h1>${esc(title)}</h1><p role="status">${esc(note)}</p><div class="pc-shortcuts"><button data-pc="refresh">重新读取</button><button data-pc="logout">切换账号</button><a href="/customer-workbench/">返回客户工作台</a></div></section></main>`;}
  function login(note=''){
    snapshot=null;identity=null;history=blankHistory();
    root.innerHTML=`<header class="pc-header"><a class="pc-brand" href="${platformConsolePath}">G-SNIPERS</a><span>超级管理员工作台</span></header><main class="pc-gate"><section class="pc-card"><small>平台管理</small><h1>登录超级管理员工作台</h1><p>使用现有的全局管理员账号。</p><form id="pc-login"><label>账号<input name="username" autocomplete="username" minlength="2" maxlength="50" required></label><label>密码<input name="password" type="password" autocomplete="current-password" maxlength="100" required></label><label class="pc-remember"><input name="remember" type="checkbox">记住登录状态</label><p role="status">${esc(note)}</p><button class="primary" type="submit">登录并进入</button></form><a href="/customer-workbench/">返回客户工作台</a></section></main>`;
  }
  async function queryUsage(cursor=null,direction='first'){
    if(!snapshot||history.busy)return;
    const started=revision,oldCursor=history.cursor||null;
    history.busy=true;history.error='';history.data=null;render();
    try{
      const data=await client.usage({...history.filters,...(cursor?{cursor}:{})});
      if(disposed||started!==revision)return;
      if(data?.state!=='available'&&data?.state!=='schema_pending')throw Error('invalid-history');
      if(direction==='next')history.cursors.push(oldCursor);
      if(direction==='prev')history.cursors.pop();
      history.cursor=cursor;history.data=data;
    }catch(e){
      if(disposed||started!==revision||e.code==='CONSOLE_STALE')return;
      if(e.status===403||e.status===401){snapshot=null;identity=null;history=blankHistory();gate('无法读取调用明细','登录或管理员权限已变化，请重新登录。');return;}
      history.error='明细未读取，请检查日期和筛选条件后重试。';
    }finally{if(!disposed&&started===revision){history.busy=false;render();}}
  }
  async function downloadUsage(){
    if(!snapshot||history.busy)return;
    const form=root.querySelector('#pc-usage-query');if(!form?.reportValidity())return;
    const filters=Object.fromEntries(new FormData(form)),started=revision;
    history.filters=filters;history.data=null;history.cursors=[];history.busy=true;history.error='';render();
    try{
      const blob=await client.exportUsage(filters);if(disposed||started!==revision)return;
      const url=browser.URL.createObjectURL(blob),a=browser.document.createElement('a');
      try{a.href=url;a.download='api-usage-'+filters.from+'-'+filters.to+'.csv';a.click();notice='已导出筛选范围内的调用明细。';}
      finally{browser.setTimeout(()=>browser.URL.revokeObjectURL(url),1000);}
    }catch(e){
      if(disposed||started!==revision||e.code==='CONSOLE_STALE')return;
      if(e.status===403||e.status===401){snapshot=null;identity=null;history=blankHistory();gate('无法导出调用明细','登录或管理员权限已变化，请重新登录。');return;}
      history.error=e.status===422?'导出未完成，请缩小日期或筛选范围；每次最多 50000 条。':'导出未完成，请稍后重试。';
    }finally{if(!disposed&&started===revision){history.busy=false;render();}}
  }
  async function load(){
    if(disposed)return;revision++;const started=revision;snapshot=null;identity=null;busy=true;query='';history=blankHistory();
    if(!session.token){busy=false;login();return;}
    gate('正在读取平台数据','正在核对账号权限…');
    try{
      const result=await client.initialize();
      if(disposed||started!==revision)return;
      identity=result.user;snapshot=result.data;busy=false;render();
    }catch(e){
      if(disposed||started!==revision||e.code==='CONSOLE_STALE')return;busy=false;
      if(e.code==='CONSOLE_EXPIRED'||!session.token){login('登录已失效，请重新登录。');return;}
      snapshot=null;identity=null;gate(e.status===403?'此账号无法进入超管工作台':'平台数据暂时无法读取',e.status===403?'需要未绑定客户、且同时拥有客户和账号管理编辑权限的全局账号。':'请稍后重试。读取失败不会显示为零或沿用旧数据。');
    }
  }
  async function submit(event){
    if(event.target.id==='pc-usage-query'){
      event.preventDefault();if(history.busy)return;
      history.filters=Object.fromEntries(new FormData(event.target));history.cursors=[];
      await queryUsage();return;
    }
    if(['pc-alert-operation','pc-supplier-operation'].includes(event.target.id)){
      event.preventDefault();if(saving||snapshot?.operations?.state!=='enabled')return;
      const form=event.target,fields=Object.fromEntries(new FormData(form)),started=revision;
      let payload;
      if(form.id==='pc-alert-operation'){
        const alert=snapshot.alerts.find(a=>a.id===fields.alert_id);if(!alert)return;
        payload={kind:'alert',key:alert.id,expected_revision:alert.handling?.revision||0,
          value:{action:fields.action,note:fields.note,signal:alert.signal}};
      }else{
        const row=snapshot.operations.suppliers.find(r=>r.host===fields.host)||{};
        const count=name=>fields[name]===''?null:Number(fields[name]);
        payload={kind:'supplier',key:fields.host,expected_revision:row.revision||0,
          value:{currency:fields.currency,balance:fields.balance||null,warning_balance:fields.warning_balance||null,
            remaining_calls:count('remaining_calls'),warning_calls:count('warning_calls'),expires_on:fields.expires_on||null}};
      }
      payload.request_id=browser.crypto.randomUUID();saving=true;form.querySelector('button').disabled=true;
      try{
        await client.operation(payload);if(disposed||started!==revision)return;
        notice='已保存处理记录并记录审计。';await load();
      }catch(e){
        if(disposed||started!==revision||e.code==='CONSOLE_STALE')return;
        notice=e.status===409?'记录已有新变化，请刷新后重新处理。':e.status===422?'字段未通过检查，标记已处理需要填写说明；额度必须为非负数。':'操作未保存，请刷新核对后重试。';
        if(e.status===403){snapshot=null;identity=null;history=blankHistory();gate('无法保存管理记录','管理员权限已变化，请重新登录。');}else render();
      }finally{saving=false;}
      return;
    }
    if(event.target.matches('.pc-control-form')){
      event.preventDefault();if(saving)return;const form=event.target,started=revision;
      if(form.querySelector('button').disabled)return;
      const payload=form.dataset.controlKind==='connection'?connectionPayload(form):controlPayload(form);saving=true;form.querySelector('button').disabled=true;
      try{
        await client.change(payload);
        if(disposed||started!==revision)return;
        notice='已保存管理配置并记录审计。';await load();
      }catch(e){
        if(disposed||started!==revision||e.code==='CONSOLE_STALE')return;
        notice=e.status===409?'配置版本已变化，请刷新后重新填写。':e.status===403?'管理员权限已变化，请重新登录。':e.status===422?'配置格式未通过检查，请核对输入。':'保存未完成，请刷新核对配置后重试。';
        if(e.status===403){snapshot=null;identity=null;gate('无法保存管理配置',notice);}else render();
      }finally{payload.value.key=null;if(payload.value.secrets)payload.value.secrets={};saving=false;}
      return;
    }
    if(event.target.id!=='pc-login')return;event.preventDefault();const form=event.target,button=form.querySelector('button');if(button.disabled)return;
    const started=revision;button.disabled=true;loginController=new AbortController();
    try{
      const r=await fetchImpl('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json'},
        body:JSON.stringify({username:form.elements.username.value.trim(),password:form.elements.password.value}),credentials:'omit',cache:'no-store',redirect:'error',signal:AbortSignal.any([loginController.signal,AbortSignal.timeout(20000)])});
      if(disposed||started!==revision)return;
      if(!r.ok)throw Error(r.status===401?'用户名或密码不正确，或账号暂时被锁定。':'登录未完成，请稍后重试。');
      const data=await r.json();if(disposed||started!==revision)return;
      if(!isPlatformAdmin(data.user)||typeof data.token!=='string'||!data.token||/\s/.test(data.token))throw Error('此账号没有全局超级管理员权限。');
      ownChange=true;try{session.setAuth(data.token,data.user,form.elements.remember.checked);}finally{ownChange=false;}
      form.elements.password.value='';await load();
    }catch(e){if(!disposed&&started===revision){form.elements.password.value='';form.querySelector('[role=status]').textContent=e.name==='TimeoutError'?'登录超时，请重试。':e.message;button.disabled=false;}}
    finally{loginController=null;}
  }
  function click(event){const b=event.target.closest('[data-pc],[data-pc-page],[data-pc-connection]');if(!b||b.disabled)return;
    if(b.dataset.pc==='usage-next'&&history.data?.next_cursor&&!history.busy)void queryUsage(history.data.next_cursor,'next');
    if(b.dataset.pc==='usage-prev'&&history.cursors.length&&!history.busy)void queryUsage(history.cursors.at(-1),'prev');
    if(b.dataset.pc==='usage-export'&&!history.busy)void downloadUsage();
    if(b.dataset.pcConnection){connectionId=b.dataset.pcConnection;page='config';render();return;}
    if(b.dataset.pcPage&&tabs.some(t=>t[0]===b.dataset.pcPage)){page=b.dataset.pcPage;query='';render();}
    if(b.dataset.pc==='refresh')void load();
    if(b.dataset.pc==='logout'){notice='';revision++;client.invalidate();loginController?.abort();ownChange=true;try{session.logout();}finally{ownChange=false;}login('已退出。');}
  }
  function input(event){if(event.target.id==='pc-search'){query=event.target.value;const position=event.target.selectionStart;render();const field=root.querySelector('#pc-search');field?.focus();field?.setSelectionRange?.(position,position);}}
  function change(event){
    if(event.target.matches('#pc-alert-operation [name=alert_id]')){alertId=event.target.value;render();return;}
    if(event.target.matches('#pc-supplier-operation [name=host]')){supplierHost=event.target.value;render();return;}
    const form=event.target.closest('.pc-control-form');if(!form||!snapshot)return;
    const field=event.target.name;
    if(form.dataset.controlKind==='connection'){
      if(field==='connection_id'){connectionId=event.target.value;render();}
      else if(field==='connection_mode')setConnectionMode(form);
      return;
    }
    if(['target','host','model','binding'].includes(field))hydrateControlForm(form,snapshot);
    else if(['unit','mode'].includes(field))hydrateControlForm(form,snapshot,false);
  }
  function changed(){if(disposed||ownChange)return;notice='';revision++;client.invalidate();loginController?.abort();snapshot=null;identity=null;if(!session.token)login('账号已退出。');else void load();}
  root.addEventListener('click',click);root.addEventListener('submit',submit);root.addEventListener('input',input);root.addEventListener('change',change);browser.addEventListener('sem:auth-context-changed',changed);
  void load();
  return {dispose(){disposed=true;revision++;client.invalidate();loginController?.abort();browser.removeEventListener('sem:auth-context-changed',changed);root.removeEventListener('click',click);root.removeEventListener('submit',submit);root.removeEventListener('input',input);root.removeEventListener('change',change);root.classList.remove('platform-console');root.replaceChildren();}};
}
