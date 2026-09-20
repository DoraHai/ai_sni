import { validVisualization } from './visualization-model.mjs'
export const readable = card => card && ['available', 'partial'].includes(card.state)
export const shown = card => readable(card) ? String(card.display ?? '—') : '—'
export const stateLabel = state => ({available:'已读取',partial:'部分数据',no_data:'暂无数据',unavailable:'暂不可用',denied:'无权限',loading:'读取中'}[state] || '待核验')
export function metricIcon(card) {
 const label=card?.label || ''
 return /消耗|花费|成本/.test(label)?'wallet':/CPC|点击/.test(label)?'pointer':/收录/.test(label)?'search':/内容|发布/.test(label)?'file':/提及/.test(label)?'radar':/可见/.test(label)?'eye':'database'
}
export function health(channel) {
 const states=channel.metrics.map(card=>card.state)
 if(!states.length) return '尚未读取'
 if(states.every(state=>state==='denied')) return '无权限'
 if(states.every(state=>state==='available')) return '已读取'
 if(states.some(state=>['available','partial'].includes(state))) return '部分读取'
 if(states.some(state=>state==='loading')) return '读取中'
 return '暂无可用数据'
}
export function historical(card) {
 const v=card?.visualization
 return readable(card) && validVisualization(v) && v.type==='trend' && v.state==='available' && v.points.filter(p=>p.value!==null).length>=2
}
export function trendSelection(cards, module='all') {
 const valid=cards.filter(historical)
 if(module!=='all') return valid.filter(card=>card.moduleCode===module).slice(0,4)
 return ['sem','seo','geo'].map(code=>{
  const list=valid.filter(card=>card.moduleCode===code)
  const preferred={sem:/点击量|广告点击/,seo:/新增收录|收录/,geo:/提及率/}[code]
  return list.find(card=>preferred.test(card.label)) || list[0]
 }).filter(Boolean)
}
// Overlay compares indexed movement, never adds different units or fills gaps.
export function indexedTrends(cards) {
 const keys=[...new Set(cards.flatMap(card=>card.visualization.points.map(p=>p.key)))].sort()
 return {keys,series:cards.map(card=>{
  const points=new Map(card.visualization.points.map(p=>[p.key,p]))
  const first=keys.map(key=>points.get(key)).find(point=>point?.value!==null && point?.value!==undefined)
  const baseline=first?.value>0?first.value:null
  return {card,baseline,points:keys.map(key=>{
   const p=points.get(key)
   return {key,label:p?.label || key,display:p?.display || '未提供观测',raw:p?.value??null,value:baseline!==null && p?.value!==null && p?.value!==undefined?p.value/baseline*100:null}
  })}
 })}
}
export function costAnnotation(cards) {
 const cost=cards.find(c=>c.moduleCode==='sem' && /消耗|花费/.test(c.label))
 const click=cards.find(c=>c.moduleCode==='sem' && /点击量|广告点击/.test(c.label))
 if(!historical(cost)||!historical(click)||cost.state!=='available'||click.state!=='available'||!cost.periodLabel||cost.periodLabel!==click.periodLabel) return null
 const clicks=new Map(click.visualization.points.map(p=>[p.key,p.value]))
 const points=cost.visualization.points
 for(let i=points.length-1;i>0;i--){
  const a=points[i-1],b=points[i],x=clicks.get(a.key),y=clicks.get(b.key)
  if(!(a.value>0&&b.value!==null&&x>0&&y!==null&&y!==undefined))continue
  if(/^\d{4}-\d{2}-\d{2}$/.test(a.key) && Date.parse(b.key)-Date.parse(a.key)!==86400000)continue
  const spend=(b.value/a.value-1)*100,traffic=(y/x-1)*100
  if(spend>0&&spend>traffic) return {key:b.key,label:b.label,metricId:cost.id,text:`消耗较前一观测 +${spend.toFixed(1)}%，点击 ${traffic>=0?'+':''}${traffic.toFixed(1)}%；消耗增速较高，转化效果待核对。`}
 }
 return null
}
export function commandInsights(channels) {
 return channels.map(channel=>{
  const cards=channel.metrics,boundaries=cards.filter(card=>card.state!=='available')
  const annotation=costAnnotation(cards)
  const metric=cards.find(card=>readable(card)&&({sem:/消耗|花费/,seo:/内容|发布/,geo:/提及率/}[channel.code]||/./).test(card.label))||cards.find(readable)||cards[0]
  if(!metric)return {code:channel.code,title:'当前渠道等待数据读取',status:'尚未读取',icon:'database',question:`检查 ${channel.code.toUpperCase()} 数据状态`}
  const title=annotation?`${annotation.label} · ${annotation.text}`:boundaries.length?`${metric.label} ${shown(metric)}；${boundaries.length} 项指标需核对读取边界。`:`${metric.label} ${shown(metric)}；${metric.periodLabel || '当前读取范围'}的观测已就绪。`
  return {code:channel.code,metricId:metric.id,title,status:boundaries.length?'需核对数据':'观测依据',icon:annotation?'activity':boundaries.length?'alert':metricIcon(metric),question:`分析 ${channel.code.toUpperCase()} 的${metric.label}和数据边界`}
 })
}
export function acquisitionTouches(channels) {
 const cards=channels.flatMap(c=>c.metrics)
 const specs=[['sem','付费曝光',/展现|曝光/,'eye'],['sem','广告点击',/点击量|广告点击/,'pointer'],['seo','搜索内容承接',/内容|发布/,'file'],['geo','AI 品牌发现',/可见度/,'radar'],['geo','品牌提及',/提及率/,'spark']]
 return specs.filter(([code])=>channels.some(c=>c.code===code)).map(([code,label,pattern,icon])=>({code,label,icon,card:cards.find(c=>c.moduleCode===code && pattern.test(c.label))}))
}
