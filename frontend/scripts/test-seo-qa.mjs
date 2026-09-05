import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'
const renderer = Vue.createRenderer({ createElement:()=>({}), createText:()=>({}), createComment:()=>({}), setText(){}, setElementText(){}, patchProp(){}, insert(){}, remove(){}, parentNode:()=>null, nextSibling:()=>null })
const flush = async()=>{ for(let i=0;i<10;i++) await Vue.nextTick() }
async function mount(api={},canEdit=true) {
  const source=await readFile(new URL('../src/views/seo/SeoQaWorkbenchView.vue',import.meta.url),'utf8')
  const compiled=compileScript(parse(source).descriptor,{id:'qa',genDefaultAs:'component'}).content
  const tenant=Vue.ref(1),site=Vue.ref(10),writes=[]
  const bindings={...Vue,SeoQaPlanning:{},currentTenantId:tenant,siteId:site,session:{canEdit:()=>canEdit},useRouter:()=>({push(){}}),ElMessage:{success(){}},
    seoQaGet:async path=>path==='questions'?{items:[],total:0}:path==='maintenance'?{items:[]}:path==='capabilities'?{platforms:[]}:[],
    seoQaPost:async(...args)=>{writes.push(args);return {created:1,merged:0}},seoQaPatch:async()=>({}),assistSeoContent:async()=>({content:'草稿'}),
    submitSeoContentReview:async(...args)=>writes.push(args),decideSeoContentReview:async()=>({}),...api}
  const names=Object.keys(bindings).filter(k=>/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(k))
  const code=compiled.replace(/^import .* from .*$/gm,'').replace(/^import ['"].*['"]\s*;?$/gm,'')
  const component=new Function('b',`const {${names.join(',')}}=b;${code};return component`)(bindings)
  component.render=()=>null
  const app=renderer.createApp({render:()=>Vue.h(component)}),root=app.mount({});await flush()
  return {app,state:root.$.subTree.component.setupState,tenant,site,writes}
}

test('site switch discards delayed question, fact and placement data',async()=>{
  const pending=[]
  const m=await mount({seoQaGet:(path,params)=>new Promise(resolve=>pending.push({path,params,resolve}))})
  try {
    m.site.value=20;await flush()
    for(const p of [...pending].reverse())p.resolve(p.path==='questions'?{items:[{id:p.params.site_id}],total:1}:p.path==='maintenance'?{items:[]}:p.path==='capabilities'?{platforms:[]}:[])
    await flush();assert.equal(m.state.items[0].id,20)
  } finally {m.app.unmount()}
})

test('read-only workbench does not import or invoke AI',async()=>{
  let aiCalls=0
  const m=await mount({assistSeoContent:async()=>{aiCalls++;return {content:'draft'}}},false)
  try {m.state.dialog='import';m.state.importing='问题';await m.state.importQuestions();m.state.selected={id:1};await m.state.generate();assert.equal(m.writes.length,0);assert.equal(aiCalls,0)}finally{m.app.unmount()}
})

test('unsaved answer changes cannot submit old content or prepare a placement',async()=>{
  const m=await mount()
  try {
    const row={id:1,content_id:3,content_version:1,body:'已保存',format:'short',fact_snapshots:[{id:2}],status:'drafting'}
    m.state.answerItems=[row];m.state.editAnswer(row);m.state.answerForm.body='未保存'
    await m.state.review('submit');m.state.openPlacement()
    assert.equal(m.writes.length,0);assert.equal(m.state.dialog,'');assert.match(m.state.error,/保存/)
  }finally{m.app.unmount()}
})

test('AI response cannot populate another tenant workspace',async()=>{
  let resolve
  const m=await mount({assistSeoContent:()=>new Promise(r=>resolve=r)})
  try {
    m.state.selected={id:1};m.state.answerForm.fact_ids=[1]
    const request=m.state.generate();await flush();m.tenant.value=2;await flush()
    resolve({content:'旧租户资料'});await request
    assert.equal(m.state.answerForm.body,'');assert.equal(m.state.selected,null)
  }finally{m.app.unmount()}
})

test('maintenance navigation clears stale filters and pagination',async()=>{
  const reads=[]
  const m=await mount({seoQaGet:async(path,params)=>{
    reads.push({path,params})
    return path==='questions'?{items:[],total:0}:path==='maintenance'?{items:[]}:path==='capabilities'?{platforms:[]}:[]
  }})
  try {
    m.state.status='archived';m.state.page=4;m.state.query='之前的搜索';m.state.tab='maintenance'
    await m.state.findMaintenanceQuestion({title:'需要更新的问题'})
    const request=reads.filter(r=>r.path==='questions').at(-1)
    assert.equal(request.params.status,undefined);assert.equal(request.params.page,1)
    assert.equal(request.params.q,'需要更新的问题');assert.equal(m.state.tab,'questions')
  } finally {m.app.unmount()}
})

async function mountPlanning(api={},canEdit=true) {
  const source=await readFile(new URL('../src/views/seo/SeoQaPlanning.vue',import.meta.url),'utf8')
  const compiled=compileScript(parse(source).descriptor,{id:'planning',genDefaultAs:'component'}).content
  const props=Vue.reactive({tenantId:1,siteId:10,canEdit,revision:1}),writes=[]
  const sample={groups:[{topic:'主题',intents:[{intent:'learn',questions:[{id:1,version:3,title:'问题',topic:'主题',answer_count:0}]}]}],similar_pairs:[]}
  const bindings={...Vue,seoQaGet:async()=>sample,seoQaPost:async(...args)=>{writes.push(args);return {updated:1}},...api}
  const names=Object.keys(bindings).filter(k=>/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(k))
  const component=new Function('b',`const {${names.join(',')}}=b;${compiled.replace(/^import .* from .*$/gm,'')};return component`)(bindings)
  component.render=()=>null
  const app=renderer.createApp({render:()=>Vue.h(component,props)}),root=app.mount({});await flush()
  return {app,state:root.$.subTree.component.setupState,props,writes,sample}
}

test('planning batch carries scoped IDs and expected versions without merging',async()=>{
  const m=await mountPlanning()
  try {
    m.state.toggle(1,true);m.state.value='归入选型';await m.state.apply()
    assert.deepEqual(m.writes,[['questions/batch',{tenant_id:1,site_id:10,items:[{id:1,version:3}],changes:{topic:'归入选型'}}]])
    assert.equal(m.state.chosen.length,0)
  }finally{m.app.unmount()}
})

test('planning read-only users cannot select or submit a batch',async()=>{
  const m=await mountPlanning({},false)
  try {m.state.toggle(1,true);assert.equal(m.state.chosen.length,0);m.state.chosen=[1];m.state.value='测试';await m.state.apply();assert.equal(m.writes.length,0)}finally{m.app.unmount()}
})

test('planning discards late data and selected versions on site switch',async()=>{
  const reads=[]
  const m=await mountPlanning({seoQaGet:(_,params)=>new Promise(resolve=>reads.push({params,resolve}))})
  try {
    m.state.chosen=[1];m.props.siteId=20;await flush()
    reads[1].resolve({groups:[],similar_pairs:[]});await flush()
    reads[0].resolve(m.sample);await flush()
    assert.equal(m.state.questions.length,0);assert.equal(m.state.chosen.length,0)
  }finally{m.app.unmount()}
})

test('planning conflict preserves selection and never silently retries',async()=>{
  let calls=0
  const m=await mountPlanning({seoQaPost:async()=>{calls++;throw {response:{data:{detail:'记录已更新，请刷新后重试'}}}}})
  try {m.state.toggle(1,true);m.state.value='主题';await m.state.apply();assert.equal(calls,1);assert.deepEqual(m.state.chosen,[1]);assert.match(m.state.error,/更新/)}finally{m.app.unmount()}
})


test('backlink presentation distinguishes unknown, internal and verified absence', async()=>{
  const m=await mount()
  try {
    const summary=m.state.backlinkSummary
    assert.match(summary(null),/尚未检查/)
    assert.match(summary({backlink_discovery:{state:'permission_required'}}),/权限/)
    assert.match(summary({backlink_discovery:{state:'internal'}}),/不计入/)
    assert.match(summary({backlink_discovery:{state:'unavailable'}}),/无法核验/)
    assert.match(summary({backlink_discovery:{state:'readable',found:0,created:0}}),/发现 0 条/)
    assert.match(summary({backlink_discovery:{state:'readable',found:2,created:1}}),/新增 1 条/)
  } finally {m.app.unmount()}
})
