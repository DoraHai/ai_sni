import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
const source = readFileSync(new URL('../src/components/GeoPublicationMonitor.vue', import.meta.url), 'utf8')
const handlers = source.slice(source.indexOf('async function load()'), source.indexOf('watch(() =>'))
function fixture() {
 const ctx=vm.createContext({epoch:0,props:{tenantId:7,taskId:12},rows:{value:[]},error:{value:''},busy:{value:false},loading:{value:false},monitoringActive:{value:true},
   listGeoPublicationMonitor:async()=>({items:[]}),checkGeoPublicationMonitor:async()=>({state:'healthy'})})
 vm.runInContext(handlers,ctx);return ctx
}
test('late monitor response cannot leak into another customer',async()=>{
 const ctx=fixture();let done
 ctx.listGeoPublicationMonitor=()=>new Promise(resolve=>{done=resolve})
 const pending=ctx.load();ctx.epoch++;ctx.props.tenantId=8;done({items:[{publication_id:1}]});await pending
 assert.equal(ctx.rows.value.length,0)
})
test('late recheck cannot replace current customer state',async()=>{
 const ctx=fixture();let done;const row={state:'mismatch',publication_id:1}
 ctx.checkGeoPublicationMonitor=()=>new Promise(resolve=>{done=resolve})
 const pending=ctx.check(row);ctx.epoch++;done({state:'healthy'});await pending
 assert.equal(row.state,'mismatch')
})
test('failed recheck preserves observed state and permits retry',async()=>{
 const ctx=fixture();const row={state:'mismatch',publication_id:1}
 ctx.checkGeoPublicationMonitor=async()=>{throw new Error('network')};await ctx.check(row)
 assert.equal(row.state,'mismatch');assert.equal(ctx.error.value,'network');assert.equal(ctx.busy.value,false)
})

test('archived content keeps history but does not send a new check',async()=>{
 const ctx=fixture();let calls=0
 ctx.listGeoPublicationMonitor=async()=>({monitoring_active:false,items:[{publication_id:1,state:'healthy'}]})
 ctx.checkGeoPublicationMonitor=async()=>{calls++}
 await ctx.load();await ctx.check(ctx.rows.value[0])
 assert.equal(calls,0);assert.equal(ctx.rows.value[0].state,'healthy')
})
test('records with no checkable URL cannot initiate a request',async()=>{
 const ctx=fixture();let calls=0
 ctx.checkGeoPublicationMonitor=async()=>{calls++}
 await ctx.check({publication_id:1,can_check:false})
 assert.equal(calls,0)
})
