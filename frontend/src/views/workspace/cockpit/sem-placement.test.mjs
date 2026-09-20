import{test}from'node:test'
import assert from'node:assert/strict'
import{demoSemPlacement,validSemPlacement,allocateClicks,clickColor}from'./sem-placement.mjs'
test('region and hourly breakdown reconcile with clicks, including zero',()=>{
 for(const total of [0,1,61,6821]){
 const p=demoSemPlacement([{date:'2026-09-20',click:total}]);assert.ok(validSemPlacement(p))
 assert.equal(p.regions.reduce((s,r)=>s+r.clicks,0),total)
 assert.ok(p.cells.slice(0,144).every(c=>c.clicks===null))
 assert.equal(p.cells.slice(144).reduce((s,c)=>s+c.clicks,0),total)
 }
})
test('multiple weeks aggregate the same weekday and hourly bucket',()=>{
 const a=demoSemPlacement([{date:'2026-09-07',click:90},{date:'2026-09-14',click:120}]);assert.ok(validSemPlacement(a));assert.equal(a.cells.slice(0,24).reduce((s,c)=>s+c.clicks,0),210)
 assert.ok(a.cells.slice(24).every(c=>c.clicks===null))
})
test('reject inconsistent totals, duplicate provinces and invalid hours',()=>{
 const p=demoSemPlacement([{date:'2026-09-20',click:61}]);assert.equal(validSemPlacement({...p,total:62}),false)
 assert.equal(validSemPlacement({...p,regions:[...p.regions,p.regions[0]]}),false)
 assert.equal(validSemPlacement({...p,cells:p.cells.slice(1)}),false)
})
test('zero clicks use lightest color, missing is distinct, maximum is darkest',()=>{
 assert.equal(clickColor(0,100),'rgb(190,230,247)');assert.equal(clickColor(100,100),'rgb(22,86,161)')
 assert.notEqual(clickColor(null,100),clickColor(0,100));assert.deepEqual(allocateClicks(5,[1,1,1]),[2,2,1])
})
