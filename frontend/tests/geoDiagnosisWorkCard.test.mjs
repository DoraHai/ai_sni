import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import {readFileSync} from 'node:fs'
const source=readFileSync(new URL('../src/components/GeoDiagnosisWorkCard.vue',import.meta.url),'utf8')
const handlers=source.slice(source.indexOf('async function load()'),source.indexOf('watch(() =>'))
function fixture(){
 const events=[]
 const ctx=vm.createContext({epoch:0,props:{tenantId:7,ticket:{id:4,status:'todo'},disabled:false},plan:{value:{}},error:{value:''},loading:{value:false},busy:{value:false},owner:{value:'运营'},due:{value:'2026-09-10'},
 fetchGeoDiagnosisWork:async()=>({ticket_id:4}),patchGeoActionTicket:async()=>({id:4}),emit:(...args)=>events.push(args)})
 vm.runInContext(handlers,ctx);return{ctx,events}
}
test('assignment only stores owner and deadline, never marks completion',async()=>{
 const {ctx}=fixture();let payload
 ctx.patchGeoActionTicket=async(t,id,p)=>{payload=p;return{id}}
 await ctx.save(false)
 assert.equal(payload.owner_name,'运营');assert.equal(payload.due_date,'2026-09-10');assert.equal(payload.status,undefined)
})
test('late save cannot update another customer',async()=>{
 const {ctx,events}=fixture();let done
 ctx.patchGeoActionTicket=()=>new Promise(resolve=>{done=resolve})
 const pending=ctx.save(true);ctx.epoch++;ctx.props.tenantId=8
 done({id:4});await pending;assert.deepEqual(events,[])
})
test('failed assignment preserves draft for correction',async()=>{
 const {ctx}=fixture()
 ctx.patchGeoActionTicket=async()=>{throw new Error('failed')}
 await ctx.save(false);assert.equal(ctx.owner.value,'运营');assert.equal(ctx.busy.value,false)
})
test('late plan response is discarded after switching customer',async()=>{
 const {ctx}=fixture();let done
 ctx.fetchGeoDiagnosisWork=()=>new Promise(resolve=>{done=resolve})
 const pending=ctx.load();ctx.epoch++;ctx.props.tenantId=8
 done({ticket_id:4});await pending;assert.equal(ctx.plan.value,null)
})


test('ticket list rejects a late response after switching customer',async()=>{
 const page=readFileSync(new URL('../src/views/geo/GeoTicketsView.vue',import.meta.url),'utf8')
 const start=page.indexOf('async function load()')
 const end=page.indexOf('\nasync function ',start+1)
 let done
 const ctx=vm.createContext({loadEpoch:0,loadedTenant:7,tenantId:{value:7},error:{value:''},items:{value:[]},mediaItems:{value:[]},mediaPick:{value:null},loading:{value:false},statusFilter:{value:''},auditIdNum:{value:null},
 listGeoActionTickets:()=>new Promise(resolve=>{done=resolve}),listGeoMediaPlacements:async()=>({items:[]})})
 vm.runInContext(page.slice(start,end),ctx)
 const pending=ctx.load();ctx.loadEpoch++;ctx.tenantId.value=8
 done({items:[{id:4,tenant_id:7}]});await pending
 assert.equal(ctx.items.value.length,0)
})
