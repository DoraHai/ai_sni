import test from 'node:test'
import assert from 'node:assert/strict'
import { dashboardChannels } from './dashboard-signals.mjs'
import { historical, indexedTrends, trendSelection, health, commandInsights, acquisitionTouches, costAnnotation, shown } from './command-center.mjs'
const c=(id,moduleCode,label,values,extra={})=>({id,moduleCode,moduleLabel:moduleCode.toUpperCase(),label,state:'available',display:'12',periodLabel:'本周',contextRevision:1,visualization:values?{type:'trend',state:'available',coverage:{label:'读取依据'},points:values.map((value,i)=>({key:`2026-09-${14+i}`,label:`09-${14+i}`,value,display:value===null?'缺报':String(value)}))}:null,...extra})
test('overlays independent units by base index and keeps zero and missing distinct',()=>{
 const {series}=indexedTrends([c('a','sem','点击',[10,null,0,20]),c('b','geo','提及率',[.2,.4,.1,.6])])
 assert.deepEqual(series[0].points.map(p=>p.value),[100,null,0,200])
 assert.equal(series[1].points[1].value,200);assert.equal(series[1].points[1].raw,.4)
 assert.equal(series[0].points[1].display,'缺报')
})
test('unobserved dates remain missing and zero baseline cannot be normalized',()=>{
 const a=c('a','sem','点击',[0,10]),b=c('b','geo','提及率',[10,20,30])
 const {series}=indexedTrends([a,b])
 assert.equal(series[0].baseline,null);assert.ok(series[0].points.every(p=>p.value===null));assert.equal(series[0].points[2].raw,null)
})
test('one observation, denied data and malformed visualization never become a trend',()=>{
 assert.equal(historical(c('a','sem','点击',[10])),false)
 assert.equal(historical(c('a','sem','点击',[10,20],{state:'denied'})),false)
 assert.equal(historical(c('a','sem','点击',['10','20'])),false)
 assert.equal(trendSelection([c('a','sem','点击',[10,null])]).length,0)
})
test('scope filtering precedes chart selection, insights and acquisition flow',()=>{
 const channels=dashboardChannels([c('a','sem','点击量',[10,20]),c('b','geo','品牌提及率',[1,2]),c('old','sem','广告消耗',[10,20],{contextRevision:0})],[{module_code:'sem'}],1)
 assert.deepEqual(trendSelection(channels.flatMap(c=>c.metrics)).map(c=>c.id),['a'])
 assert.equal(commandInsights(channels).length,1)
 assert.ok(acquisitionTouches(channels).every(t=>t.code==='sem'))
})
test('health states report reads without claiming completeness or business growth',()=>{
 assert.equal(health({metrics:[]}), '尚未读取')
 assert.equal(health({metrics:[{state:'denied'}]}),'无权限')
 assert.equal(health({metrics:[{state:'available'},{state:'partial'}]}),'部分读取')
 assert.equal(health({metrics:[{state:'available'}]}),'已读取')
 assert.equal(shown({state:'no_data',display:'0'}),'—');assert.equal(shown({state:'available',display:'0'}),'0')
})
test('annotations require comparable periods, complete cards and adjacent valid observations',()=>{
 const cost=c('cost','sem','广告消耗',[100,120]),click=c('click','sem','广告点击量',[100,110])
 assert.equal(costAnnotation([cost,click]).key,'2026-09-15')
 assert.equal(costAnnotation([cost,{...click,state:'partial'}]),null)
 assert.equal(costAnnotation([cost,{...click,periodLabel:'上周'}]),null)
 assert.equal(costAnnotation([cost,c('click','sem','广告点击量',[null,110])]),null)
 const gap={...cost,visualization:{...cost.visualization,points:[cost.visualization.points[0],{...cost.visualization.points[1],key:'2026-09-17'}]}}
 assert.equal(costAnnotation([gap,click]),null)
})
test('snapshots yield truthful insights and unmeasured touchpoints stay empty',()=>{
 const channels=dashboardChannels([c('seo','seo','已发布内容',null)],[{module_code:'seo'}],1)
 assert.match(commandInsights(channels)[0].title,/已发布内容 12/)
 assert.doesNotMatch(commandInsights(channels)[0].title,/增长|转化率/)
 const touches=acquisitionTouches([{code:'geo',metrics:[]}]);assert.ok(touches.every(t=>!t.card));assert.ok(touches.every(t=>shown(t.card)==='—'))
})
