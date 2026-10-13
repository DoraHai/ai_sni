import {escapeText as esc} from './customer-display.mjs';
export const governanceRoute='/api/v1/platform/ai-governance';
const states={available:'已接入',enabled:'已生效',disabled:'未启用',schema_pending:'等待数据库人工审核启用',recording:'计量中',observed:'已观测到调用计量',schema_ready:'计量表就绪，运行开关未启用',available_no_recent_events:'台账可用，近期无调用',configured:'已配置',unavailable:'未接入',unknown:'未知',reserved:'预留未接入'};
const state=s=>s==='runtime_unverified'?'独立服务生效状态待核对':states[s]||'未知';
const count=n=>Number.isSafeInteger(n)&&n>=0?String(n):'未知';
const provider=value=>({dashscope:'阿里云百炼','dashscope.aliyuncs.com':'阿里云百炼',deepseek:'DeepSeek','api.deepseek.com':'DeepSeek'}[value]||(typeof value==='string'&&value?value:'未提供'));
const windowLabel=value=>({day:'当天',today:'当天','24h':'近24小时',last_24_hours:'近24小时',month:'本月',unavailable:'未接入'}[typeof value==='object'?value?.kind:value]||'未提供统计窗口');
export function renderAiGovernance({data,error='',card,table}){
  const ready=data?.schema===1&&['available','schema_pending'].includes(data?.state)&&Array.isArray(data.modules);
  const note=error||(data?.state==='schema_pending'?states.schema_pending+'；已接入的只读配置与计量仍可查看，治理编辑保持禁用。':!ready?'治理接口未接入或响应不完整；不能据此判断配置、限制已生效。':'来自服务端运行配置与调用台账；配置状态不代表供应商实时连通。');
  const rows=['sem','seo','geo'].map(module=>{
    const r=ready?data.modules.find(r=>r.module===module):null;
    return [module.toUpperCase(),r?esc(provider(r.provider)):'未接入',
      r?esc(typeof r.model==='string'?r.model:'未提供'):'未接入',r?.configured===true?'已配置':r?.configured===false?'未配置':'未知',
      state(r?.metering?.state),count(r?.calls?.failed),count(r?.calls?.unknown),esc(({api_metering:'API 调用台账',api_usage_ledger:'API 调用台账',api_usage_events:'API 调用台账',module_ledger:'模块运行台账',unavailable:'未接入'}[r?.calls?.source]||'未提供来源')),esc(windowLabel(r?.calls?.window))];
  });
  const limits=ready?data.modules.flatMap(r=>(Array.isArray(r.limits)?r.limits:[]).map(l=>[
    esc(String(r.module).toUpperCase()),esc(({scope:'范围隔离',budget:'预算',calls:'调用上限',concurrency:'并发上限',revision:'版本检查',deduplication:'任务去重'}[l.kind]||'未识别限制')),state(l.state),
    l.state==='enabled'&&['number','boolean'].includes(typeof l.value)?esc(typeof l.value==='boolean'?(l.value?'是':'否'):String(l.value)):'未提供生效值'
  ])):[];
  return card('AI 自动化治理',`<p role="status">${esc(note)}</p>${table(['模块','供应商','模型','配置','计量','失败调用','结果未知调用','统计来源','统计窗口'],rows)}`)+
    card('调用保护生效范围',table(['模块','管理结构','运行保护'],['sem','seo','geo'].map(module=>{
      const controls=ready?data.modules.find(r=>r.module===module)?.controls:null;
      return [module.toUpperCase(),controls?.schema==='ready'?'管理表就绪':controls?.schema==='schema_pending'?states.schema_pending:'未知',state(controls?.state)];
    })),'SEM 的运行开关只证明本进程状态；SEO/GEO 的独立版本和启用状态需分别核对。共享配置或已有调用记录不能证明所有服务的限制已生效。')+
    card('已生效限制与未启用控制',table(['模块','限制','运行状态','生效值'],limits)+`<p class="pc-note">结果未知不能视为成功，重试前应核对调用台账。缺少审核通过的控制 schema 时，不能保存新治理策略。</p><button disabled>治理策略编辑暂未接入</button><button data-pc-page="controls">查看已有 API 与预算管理</button><button data-pc-page="config">查看已有系统配置</button>`)+
    card('人工审核与实施边界','<div class="pc-gap-grid"><div><b>AI 提出建议</b><p>站内方案、方案修订和下期建议需要进入原有业务流程。</p></div><div><b>人工核实与审核</b><p>事实确认、重要发布和最终验收由人工完成。</p></div><div><b>人工实施</b><p>记录实施结果，真实页面复检后再提交最终验收。</p></div></div>')+
    card('官网适配器','<p>reserved / disabled · 官网自动修改未接入。当前通过人工实施完成站点修改。</p><button disabled>官网自动写入已关闭</button>','官网适配器尚未接入，自动执行开关保持关闭。');
}
