import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
const source=readFileSync(new URL('../src/components/GeoLaunchChecklist.vue',import.meta.url),'utf8')
const handlers=source.slice(source.indexOf('async function load()'),source.indexOf('function openEvidence()'))
function fixture(){
 const events=[]
 const ctx=vm.createContext({epoch:0,props:{tenantId:7,task:{id:12,article:{id:17},updated_at:'revision'},disabled:false},
 targets:{value:[]},linked:{value:[]},selectedId:{value:null},detail:{value:null},error:{value:''},loading:{value:false},busy:{value:false},confirmed:{value:true},
 fetchTaskPushTargets:async()=>({targets:[]}),evidenceApi:{listForContent:async()=>[],readiness:async()=>({})},
 submitGeoTaskReview:async()=>{},decideGeoTaskReview:async()=>{},emit:x=>events.push(x)})
 vm.runInContext(handlers,ctx);return{ctx,events}
}
test('customer confirmation carries the saved version and task revision',async()=>{
 const {ctx,events}=fixture();let sent
 ctx.decideGeoTaskReview=async(...args)=>{sent=args}
 await ctx.review('approved')
 assert.equal(sent[0],7);assert.equal(sent[1],12)
 assert.equal(sent[4].expected_article_id,17);assert.equal(sent[4].expected_updated_at,'revision')
 assert.deepEqual(events,['changed'])
})
test('unchecked or unsaved customer confirmation cannot submit',async()=>{
 const {ctx}=fixture();let calls=0
 ctx.decideGeoTaskReview=async()=>{calls++}
 ctx.confirmed.value=false;await ctx.review('approved')
 ctx.confirmed.value=true;ctx.props.disabled=true;await ctx.review('approved')
 assert.equal(calls,0)
})
test('late review response never refreshes another customer',async()=>{
 const {ctx,events}=fixture();let done
 ctx.decideGeoTaskReview=()=>new Promise(resolve=>{done=resolve})
 const pending=ctx.review('approved');ctx.epoch++;ctx.props.tenantId=8
 done({});await pending;assert.deepEqual(events,[])
})
test('late checklist reads are discarded after customer switch',async()=>{
 const {ctx}=fixture();let done
 ctx.evidenceApi.listForContent=()=>new Promise(resolve=>{done=resolve})
 const pending=ctx.load();ctx.epoch++;ctx.props.tenantId=8
 done([{id:99,status:'open'}]);await pending
 assert.equal(ctx.linked.value.length,0)
})
