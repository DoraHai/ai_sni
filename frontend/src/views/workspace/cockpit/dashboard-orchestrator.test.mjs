import test from 'node:test'
import assert from 'node:assert/strict'
import { createCommandEpoch, createDashboardPlan, inferDashboardIntent, metricDisplay } from './dashboard-orchestrator.mjs'
const modules=['sem','seo','geo'].map(module_code=>({module_code}))
const card=(id,label,extra={})=>({id,label,moduleCode:'sem',contextRevision:4,state:'available',display:'12',periodLabel:'本周',...extra})
const plan=(text,cards,extra={})=>createDashboardPlan({text,cards,modules,revision:4,...extra})
test('routes supported scenes and respects explicit module over generic attention',()=>{
 assert.equal(inferDashboardIntent('今天关注什么'),'priority')
 assert.equal(inferDashboardIntent('SEM 今天怎么样'),'sem-focus')
 assert.equal(inferDashboardIntent('只看 GEO'),'geo-focus')
 assert.equal(inferDashboardIntent('查看 SEO 数据边界'),'seo-focus')
 assert.equal(inferDashboardIntent('分析一下',{focus_module:'sem'}),'sem-focus')
})
test('never includes revoked modules or stale scope metrics',()=>{
 const result=plan('SEM',[card('old','点击量',{contextRevision:3}),card('new','点击量')],{modules:[]})
 assert.equal(result.metrics.length,0)
 assert.equal(plan('SEM',[card('old','点击量',{contextRevision:3})]).metrics.length,0)
})
test('SEM layout uses real ordered evidence and preserves zero vs missing',()=>{
 const result=plan('SEM',[card('cost','广告消耗',{state:'unavailable',display:'0'}),card('click','广告点击量',{display:'0'}),card('imp','广告展现量'),card('cpc','平均点击价格 (CPC)')])
 assert.deepEqual(result.metrics.map(x=>x.id),['imp','click','cost','cpc'])
 assert.equal(result.metrics[1].display,'0'); assert.equal(result.metrics[2].display,'—')
 assert.equal(metricDisplay(card('x','x',{state:'no_data',display:0})),'—')
})
test('cost vs clicks insight requires complete data and matching periods',()=>{
 const click=card('click','广告点击量',{changeLabel:'↑ +10%'})
 const cost=card('cost','广告消耗',{changeLabel:'↑ +20%'})
 assert.match(plan('SEM',[click,cost]).insight,/消耗增速高于点击/)
 for(const extra of [{periodLabel:'昨天'},{state:'partial'},{changeLabel:'—'}]) assert.doesNotMatch(plan('SEM',[click,{...cost,...extra}]).insight,/消耗增速高于点击/)
})
test('priority retains missing-data boundary instead of asserting business risk',()=>{
 const result=plan('今天关注什么',[card('missing','广告消耗',{state:'no_data',display:'0'})])
 assert.equal(result.metrics[0].display,'—'); assert.match(result.insight,/缺失或部分数据不等于业务异常/)
})
test('GEO reuses only provided metrics and never fabricates provider breakdown',()=>{
 const result=plan('只看 GEO',[card('visibility','AI 可见度',{moduleCode:'geo'}),card('mention','品牌提及率',{moduleCode:'geo'})])
 assert.deepEqual(result.metrics.map(x=>x.id),['mention','visibility'])
 assert.equal(result.trend,null); assert.doesNotMatch(JSON.stringify(result),/豆包|通义|DeepSeek/)
})
test('explicit trend requests are preserved; missing history stays absent',()=>{
 assert.equal(plan('SEM',[card('click','点击量')]).trendRequested,false)
 const result=plan('SEM 最近趋势',[card('click','点击量')])
 assert.equal(result.trendRequested,true); assert.equal(result.trend,null)
})
test('superseded and cancelled commands cannot deliver results',()=>{
 const epoch=createCommandEpoch(), first=epoch.next(), second=epoch.next()
 assert.equal(epoch.current(first),false); assert.equal(epoch.current(second),true)
 epoch.cancel(); assert.equal(epoch.current(second),false)
})

test('requested metric determines trend and retains missing observations',()=>{
 const visualization={type:'trend',state:'available',points:[{key:'a',label:'a',value:null,display:'缺报'},{key:'b',label:'b',value:2,display:'2'}],coverage:{label:'部分'}}
 const result=plan('SEM 消耗趋势',[card('click','点击量',{visualization}),card('cost','广告消耗',{visualization})])
 assert.equal(result.trend.id,'cost'); assert.equal(result.trend.visualization.points[0].value,null)
 assert.equal(plan('SEM',[card('cost','广告消耗',{visualization})]).trend,null)
})

test('SEO command contains only current search evidence and visualizations',()=>{
 const result=plan('分析 SEO 内容',[card('sem','广告点击量'),card('seo','已发布内容',{moduleCode:'seo'})])
 assert.equal(result.mode,'seo-focus');assert.deepEqual(result.visualCards.map(c=>c.id),['seo'])
 assert.deepEqual(result.metrics.map(c=>c.id),['seo']);assert.match(result.insight,/不推断自然流量/)
})
