import {test} from 'node:test'
import assert from 'node:assert/strict'
import {isTigerDemoTenant,tigerDemoCards,TIGER_DEMO_NAME} from './tiger-demo.mjs'
import {validVisualization} from './visualization-model.mjs'
const scope={dateStart:'2026-09-14',dateEnd:'2026-09-20',contextRevision:7,modules:['sem','seo','geo']}
test('only the exact authorized demo customer receives fixtures',()=>{
 const tenants=[{id:42,name:TIGER_DEMO_NAME},{id:43,name:'SZ-老虎新材料'}]
 assert.equal(isTigerDemoTenant(42,tenants),true)
 assert.equal(isTigerDemoTenant(43,tenants),false)
 assert.equal(isTigerDemoTenant(42,[]),false)
 assert.equal(isTigerDemoTenant(null,[{id:0,name:TIGER_DEMO_NAME}]),false)
 assert.equal(isTigerDemoTenant(42,[{id:42,name:'TIGER 老虎新材料'}]),false)
})
test('all fixtures are labeled, scoped, and valid visualizations',()=>{
 const cards=tigerDemoCards(scope)
 assert.equal(cards.length,15)
 for(const c of cards){assert.equal(c.contextRevision,7);assert.match(c.sourceLabel,/模拟/);assert.match(c.reason,/演示|模拟/);assert.ok(validVisualization(c.visualization),c.id)}
 assert.ok(tigerDemoCards({...scope,modules:['geo']}).every(c=>c.moduleCode==='geo'))
 assert.deepEqual(tigerDemoCards({...scope,modules:[]}),[])
})
test('dates, totals, funnel and distributions reconcile',()=>{
 const cards=tigerDemoCards(scope),get=k=>cards.find(c=>c.id===`tiger-demo-${k}`)
 assert.equal(get('click').series[0].key,scope.dateStart)
 assert.equal(get('click').series.at(-1).key,scope.dateEnd)
 const clicks=get('click').series.reduce((s,p)=>s+p.value,0)
 assert.equal(Number(get('click').display.replaceAll(',','')),clicks)
 assert.equal(get('funnel').visualization.stages[1].value,clicks)
 assert.equal(get('engines').visualization.items.reduce((s,i)=>s+i.value,0),560)
 assert.equal(get('content-status').visualization.items.reduce((s,i)=>s+i.value,0),Number(get('content').display))
 assert.equal(tigerDemoCards({...scope,dateStart:scope.dateEnd}).find(c=>c.id==='tiger-demo-click').series.length,1)
 assert.deepEqual(tigerDemoCards({...scope,dateEnd:'2026-09-01'}),[])
})
