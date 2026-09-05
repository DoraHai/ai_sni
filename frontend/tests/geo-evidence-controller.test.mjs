import test from 'node:test'
import assert from 'node:assert/strict'
import { createEvidenceController } from '../src/utils/geoEvidenceController.js'
const deferred = () => { let resolve, reject; const promise=new Promise((a,b)=>{resolve=a;reject=b}); return {promise,resolve,reject} }
function setup(api={}) {
 let tenant=1
 const state={items:[],selected:null,detail:null,busy:false,loading:false}
 return {state,change:v=>tenant=v,c:createEvidenceController(state,api,()=>tenant)}
}
test('late customer list cannot replace current list',async()=>{
 const a=deferred(); const x=setup({list:t=>t===1?a.promise:Promise.resolve([{id:2}])})
 const first=x.c.load();x.change(2);await x.c.load();a.resolve([{id:1}]);await first
 assert.deepEqual(x.state.items,[{id:2}])
})
test('late task details cannot replace selected task',async()=>{
 const a=deferred();const x=setup({readiness:(_,id)=>id===1?a.promise:Promise.resolve({task_id:2})})
 const first=x.c.select({id:1});await x.c.select({id:2});a.resolve({task_id:1});await first
 assert.equal(x.state.detail.task_id,2)
})
test('an accepted action keeps its original customer and does not refresh another',async()=>{
 const a=deferred();const calls=[];const x=setup({baseline:(t,id)=>{calls.push([t,id]);return a.promise},list:async()=>[],get:()=>assert.fail('stale refresh')})
 x.state.selected={id:3};const first=x.c.act('baseline');x.change(2);await x.c.load();a.resolve({});await first
 assert.deepEqual(calls,[[1,3]]);assert.equal(x.state.selected,null)
})
test('failed completion does not mark a task done',async()=>{
 const x=setup({complete:async()=>{throw Error('week incomplete')}})
 x.state.selected={id:1,status:'in_progress'};await x.c.act('complete')
 assert.equal(x.state.selected.status,'in_progress');assert.equal(x.state.error,'week incomplete')
})
test('double clicks send only one action and completion comes from server',async()=>{
 const a=deferred();let calls=0
 const x=setup({complete:()=>{calls++;return a.promise},get:async()=>({id:1,status:'done'}),readiness:async()=>({completion_evidence:{delta:2}})})
 x.state.selected={id:1,status:'in_progress'};x.state.items=[x.state.selected]
 const first=x.c.act('complete');await x.c.act('complete');assert.equal(calls,1);a.resolve({});await first
 assert.equal(x.state.items[0].status,'done');assert.equal(x.state.detail.completion_evidence.delta,2)
})
test('invalid publication ids cannot trigger a request',async()=>{
 const x=setup({publication:()=>assert.fail('invalid request')});x.state.selected={id:1}
 for(const id of [0,-1,1.2,NaN]) await x.c.act('publication',id)
 assert.ok(x.state.error)
})
test('pagination uses last id instead of silently dropping tasks',async()=>{
 const cursors=[];const x=setup({list:async(_,cursor)=>{cursors.push(cursor);return cursor? [{id:201}]:Array.from({length:200},(_,i)=>({id:i+1}))}})
 await x.c.load();assert.ok(x.state.more);await x.c.load(true)
 assert.deepEqual(cursors,[0,200]);assert.equal(x.state.items.length,201);assert.equal(x.state.more,false)
})
test('unmounted details cannot mutate state',async()=>{
 const a=deferred();const x=setup({readiness:()=>a.promise});const first=x.c.select({id:1})
 x.c.invalidate();a.resolve({task_id:1});await first;assert.equal(x.state.detail,null)
})
