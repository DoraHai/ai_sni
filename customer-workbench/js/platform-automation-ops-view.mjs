import {escapeText as esc} from './customer-display.mjs';

const count=n=>Number.isSafeInteger(n)&&n>=0?String(n):'未知';
const states={loading:'正在读取',not_deployed:'接口未部署',schema_pending:'执行结构尚未就绪',
  unavailable:'读取失败',timeout:'读取超时',invalid:'响应或范围未通过核验',forbidden:'无读取权限',unauthorized:'登录已失效',
  available:'已读取',unknown:'未采集'};
const phases={not_started:'未启动',idle:'空闲',active:'执行中',paused:'已暂停',taken_over:'人工接管',
  pausing:'暂停收尾中',taking_over:'接管收尾中',ending:'结束收尾中',ended:'项目已结束',
  queued:'排队中',running:'运行中',succeeded:'运行已完成',failed:'运行失败',cancelled:'已取消',
  awaiting_human:'待人工',waiting_human:'待人工',waiting_input:'待补资料',blocked:'受阻',unknown:'结果未知',none:'无本次运行'};
const phase=s=>s===null?'无本次运行':phases[s]||'未知';

export function automationScopePath(module,row){
  if(!['seo','geo'].includes(module)||!Number.isSafeInteger(row?.tenant_id)||row.tenant_id<1||
    !Number.isSafeInteger(row.scope_id)||row.scope_id<1)return null;
  return '/customer-workbench/?'+new URLSearchParams({...(module==='geo'?{module:'geo'}:{}),
    tenant_id:row.tenant_id,[module==='geo'?'project_id':'site_id']:row.scope_id});
}

function workerLabel(data,now){
  const w=data.worker,age=Date.parse(data.as_of)-Date.parse(w?.last_tick_at),sampleAge=now-Date.parse(data.as_of);
  if(w?.state==='active'&&w.verified===true&&w.evidence?.kind==='local_tick'&&w.evidence.scope==='this_process'&&
    Number.isFinite(age)&&age>=0&&age<=120000&&sampleAge>=0&&sampleAge<=120000)return '采样时当前进程有心跳';
  return ({stopped:'执行器报告已停止',disabled:'执行器报告未启用',degraded:'执行器报告异常'}[w?.state]||'执行器存活尚未验证');
}

export function automationNotifications(state){
  return ['seo','geo'].flatMap(module=>{
    const r=state?.modules?.[module],d=r?.data;
    if(r?.state!=='available'||d?.state!=='available')return [];
    return ['pending_human','unknown_cost'].filter(k=>d.counts[k]>0).map(k=>({tenant_id:null,severity:'warning',
      message:`${module.toUpperCase()} ${k==='pending_human'?'待人工项目':'费用未知步骤'} ${count(d.counts[k])} ${k==='pending_human'?'个':'项'}；进入自动执行运维核对范围与采样时间。`}));
  });
}

export function renderAutomationOps({state,card,table,time,tenant=id=>'客户 '+id,now=Date.now()}){
  const modules=state?.modules||{};
  const summary=['seo','geo'].map(module=>{
    const r=modules[module],d=r?.data,ready=r?.state==='available'&&d?.state==='available';
    return [module.toUpperCase(),esc(states[d?.state&&r?.state==='available'?d.state:r?.state]||states.unknown),
      ...['projects','runs','pending_human','unknown_cost'].map(k=>ready?count(d.counts[k]):'未知'),
      esc(d?.as_of?time(d.as_of):'无已核验采样')];
  });
  const details=['seo','geo'].map(module=>{
    const r=modules[module],d=r?.data;
    if(r?.state!=='available'||d?.state!=='available')return card(module.toUpperCase()+' 执行健康',
      `<p>${esc(states[d?.state&&r?.state==='available'?d.state:r?.state]||states.unknown)}，项目与队列保持未知。</p>`,'',['not_deployed','schema_pending'].includes(d?.state&&r?.state==='available'?d.state:r?.state)?'执行健康接口尚未启用，项目与队列数量未知。':'');
    const q=d.queue,queue=q?.state==='available'?[q.queued,q.running,q.unknown].map(count).join(' / '):'未知 / 未知 / 未知';
    const rows=d.rows.map(row=>{
      const path=automationScopePath(module,row);
      return [esc(tenant(row.tenant_id)),esc((module==='seo'?'网站 #':'项目 #')+row.scope_id),
        esc(phase(row.project_state)),esc(phase(row.run_state)),count(row.pending_human),count(row.unknown_cost),
        row.cycle_enabled===true?'周期已启用':row.cycle_enabled===false?'周期未启用':'周期未知',
        esc(time(row.updated_at)),path?`<a href="${esc(path)}">进入范围核验</a>`:'范围未核验'];
    });
    return card(module.toUpperCase()+' 执行健康',
      `<p>${esc(workerLabel(d,now))} · 最后心跳 ${esc(time(d.worker?.last_tick_at))}</p>`+
      `<p>排队 / 执行 / 结果未知：${esc(queue)}</p><p>采样时间 ${esc(time(d.as_of))}</p>`+
      table(['客户','业务范围','项目状态','本次运行','待人工项目','费用未知步骤','后续周期','更新时间','查看'],rows)+
      `<p>${d.truncated?'按客户与范围排序显示前 50 个范围；全局汇总独立统计，不从本页求和。':'显示本次服务端返回的范围。'}</p>`,
      '当前进程心跳不能证明全部服务正常；队列为零不能证明执行器存活。进入范围后仍由原模块核验账号权限。');
  }).join('');
  return card('自动执行运维',`<p>SEO / GEO 项目与运行只读汇总</p><button data-pc="automation-refresh" ${state?.busy?'disabled':''}>${state?.busy?'正在读取…':'刷新执行状态'}</button>`+
    table(['模块','读取状态','已配置项目','历史运行','待人工项目','费用未知步骤','采样时间'],summary),
    '待人工统计当前运行待补资料、待人工或已接管的项目。费用未知统计历史已准入供应商调用且费用待核实的步骤，按步骤去重，不能当作金额或请求数。SEO 与 GEO 分别采样；刷新不会重试任务或结算费用。','seo geo'.split(' ').every(m=>['not_deployed','schema_pending'].includes(modules[m]?.state)||modules[m]?.data?.state==='schema_pending')?'SEO 与 GEO 执行健康接口均待启用。':'')+
    card('SEM 本轮边界','<p>SEM 本轮未接入 AI 接管，保留已有人工流程。</p>','','SEM AI 接管未接入，继续人工处理。')+details;
}
