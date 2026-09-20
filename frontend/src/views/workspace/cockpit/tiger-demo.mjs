import { demoSemPlacement } from './sem-placement.mjs'
// Explicit presentation-only fixture. Never persisted or used as production metrics.
export const TIGER_DEMO_NAME = 'TIGER 老虎新材料（演示）'
export function isTigerDemoTenant(tenantId, authorizedTenants = []) {
  return Number.isSafeInteger(Number(tenantId)) && Number(tenantId) > 0
    && authorizedTenants.some(t => Number(t.id) === Number(tenantId) && t.name === TIGER_DEMO_NAME)
}
export function tigerDemoCards({ dateStart, dateEnd, contextRevision, modules = [] }) {
  const start = Date.parse(`${dateStart}T00:00:00Z`), end = Date.parse(`${dateEnd}T00:00:00Z`)
  if (![start, end].every(Number.isFinite) || end < start || (end-start)/86400000 >= 366) return []
  const days = Array.from({length: (end-start)/86400000+1}, (_, i) => {
    const date = new Date(start+i*86400000).toISOString().slice(0,10)
    const seed = Math.floor((start+i*86400000)/86400000)
    const phase = ((seed % 30)+30)%30
    const impression = 14800 + phase*173 + (seed%7)*290
    const click = Math.round(impression * (0.045 + (seed%5)*0.002))
    const cost = Math.round(click * (1.72 + (seed%9)*0.04)*100)/100
    const samples = 80, mentions = 27 + seed%14, citations = 18 + seed%9
    return {date, impression, click, cost, cpc:cost/click, content:72+phase,
      indexed:48+phase, pending:4+seed%4, samples, mentions, citations,
      mentionRate:mentions/samples*100, visibility:(mentions+citations)/samples*50}
  })
  const total = key => days.reduce((sum,d)=>sum+d[key],0)
  const last = days.at(-1)
  const num = n => new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(n)
  const card = (moduleCode,key,label,value,unit='',aggregate=false) => {
    const points = days.map(d=>({key:d.date,label:d.date.slice(5),value:d[key],display:num(d[key])+unit}))
    return {id:`tiger-demo-${key}`,moduleCode,moduleLabel:moduleCode.toUpperCase(),label,
      display:num(value),unit,state:'available',contextRevision,summaryRole:'outcome',
      sourceLabel:'TIGER 驾驶舱模拟数据 v1 · 非真实业务',updatedLabel:'演示样本',
      periodLabel:`${dateStart} 至 ${dateEnd}（模拟）`,
      reason:`演示数据，不代表真实业务。${aggregate?'主数字为所选日期合计，曲线为每日模拟值。':'主数字为期末模拟快照，曲线为每日模拟值。'}`,
      changeLabel:'模拟数据',series:points,visualization:{type:'trend',state:'available',points,coverage:{state:'covered',missingCount:0,label:'模拟日序列'}},
      columns:[{key:'date',label:'日期（模拟）'},{key:'value',label}],rows:points.map(p=>({date:p.key,value:p.display}))}
  }
  const cards = [
    card('sem','impression','广告展现量',total('impression'),'次',true),
    card('sem','click','广告点击',total('click'),'次',true),
    card('sem','cost','推广花费',total('cost'),'元',true),
    card('sem','cpc','平均点击价格 (CPC)',total('cost')/total('click'),'元'),
    card('seo','content','内容总数',last.content,'篇'),card('seo','indexed','有效收录页面',last.indexed,'页'),
    {...card('seo','pending','SEO 页面待处理',last.pending,'项'),urgentCount:last.pending,summaryRole:null},
    card('geo','mentionRate','AI 回答提及率',last.mentionRate,'%'),card('geo','visibility','AI 可见度',last.visibility,'分'),
    card('geo','samples','合格回答样本',total('samples'),'条',true),card('geo','mentions','品牌提及回答',total('mentions'),'条',true),
    card('geo','citations','自有域引用回答',total('citations'),'条',true),
  ]
  cards.find(c=>c.id==='tiger-demo-cpc').reason='演示数据，不代表真实业务。主数字为模拟总花费 ÷ 模拟总点击；曲线为每日均价。'
  const distribution = (moduleCode,key,label,items) => ({...card(moduleCode,key,label,items.reduce((s,i)=>s+i.value,0)),
    series:[],rows:items.map(i=>({date:i.label,value:num(i.value)})),reason:'模拟结构分布，不代表真实业务。',
    visualization:{type:'distribution',state:'available',items:items.map(i=>({...i,display:num(i.value)})),note:'仅供驾驶舱演示的模拟分布'}})
  cards.push(distribution('seo','content-status','内容状态分布',[
    {key:'published',label:'已发布',value:last.content-12},{key:'review',label:'审核中',value:8},{key:'draft',label:'撰写中',value:4}]),
    distribution('geo','engines','AI 模型样本分布',[
      {key:'deepseek',label:'DeepSeek',value:total('samples')/4},{key:'doubao',label:'豆包',value:total('samples')/4},
      {key:'qwen',label:'通义千问',value:total('samples')/4},{key:'kimi',label:'Kimi',value:total('samples')/4}]))
  cards.push({...card('sem','funnel','曝光到点击',total('click'),'次'),series:[],rows:[],
    visualization:{type:'funnel',state:'available',stages:[
      {key:'impression',metricId:'tiger-demo-impression',label:'曝光',value:total('impression'),display:num(total('impression'))},
      {key:'click',metricId:'tiger-demo-click',label:'点击',value:total('click'),display:num(total('click'))}],
      rate:total('click')/total('impression'),rateLabel:`模拟点击率 ${num(total('click')/total('impression')*100)}%`,coverage:{state:'covered',label:'仅 SEM 模拟曝光与点击'}}})
  cards.find(c=>c.id==='tiger-demo-click').semPlacement = demoSemPlacement(days)
  return cards.filter(c=>modules.includes(c.moduleCode))
}
