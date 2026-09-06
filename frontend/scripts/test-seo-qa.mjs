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
  const bindings={...Vue,SeoQaResearch:{},SeoQaPlanning:{},publisherZip:()=>null,qaRunnerSource:'',runnerSource:'',runnerRequirements:'',currentTenantId:tenant,siteId:site,session:{canEdit:()=>canEdit},useRouter:()=>({push(){}}),ElMessage:{success(){}},
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
  const bindings={...Vue,SeoQaBatchDrafts:{},analyzeSeoQaSemantic:async payload=>{if(api.seoQaPost)return api.seoQaPost('planning/semantic',payload);writes.push(['planning/semantic',payload]);return {pairs:[]}},seoQaGet:async()=>sample,seoQaPost:async(...args)=>{writes.push(args);return {updated:1}},...api}
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


test('follow-up filter shows only flagged placements and updates after verification',async()=>{
  const m=await mount()
  try {
    m.state.placements=[{id:1,followup:{needed:true}},{id:2,followup:{needed:false}},{id:3}]
    assert.equal(m.state.followupCount,1)
    assert.equal(m.state.visiblePlacements.length,3)
    m.state.followupOnly=true
    assert.deepEqual(m.state.visiblePlacements.map(r=>r.id),[1])
    m.state.placements=[{id:1,followup:{needed:false}}]
    assert.equal(m.state.visiblePlacements.length,0)
    assert.equal(m.state.followupCount,0)
  }finally{m.app.unmount()}
})


test('bulk verification is capped, sequential and keeps per-row errors',async()=>{
  let active=0,maxActive=0,calls=[]
  const m=await mount({seoQaPost:async path=>{
    active++;maxActive=Math.max(maxActive,active);calls.push(path);await flush();active--
    if(path.includes('/2/'))throw new Error('单条失败')
    return {status:'content_observed'}
  }})
  try {
    m.state.placements=Array.from({length:25},(_,i)=>({id:i+1,answer_url:'https://public.example/a'}))
    await m.state.verifyBatch()
    assert.equal(calls.length,20);assert.equal(maxActive,1)
    assert.equal(m.state.batchResults.length,20)
    assert.equal(m.state.batchResults.filter(r=>r.failed).length,1)
  }finally{m.app.unmount()}
})

test('bulk verification stops after a tenant switch without showing old results',async()=>{
  let resolve,calls=0
  const m=await mount({seoQaPost:()=>{calls++;return new Promise(r=>resolve=r)}})
  try {
    m.state.placements=[{id:1,answer_url:'https://public.example/a'},{id:2,answer_url:'https://public.example/b'}]
    const request=m.state.verifyBatch();await flush();m.tenant.value=2;await flush()
    resolve({status:'content_observed'});await request
    assert.equal(calls,1);assert.equal(m.state.batchResults.length,0)
  }finally{m.app.unmount()}
})

test('bulk verification allows stopping and prevents read-only writes',async()=>{
  const readonly=await mount({},false)
  try {readonly.state.placements=[{id:1,answer_url:'https://public.example/a'}];await readonly.state.verifyBatch();assert.equal(readonly.writes.length,0)}finally{readonly.app.unmount()}
  let m,calls=0
  m=await mount({seoQaPost:async()=>{calls++;m.state.batchStop=true;return {status:'unavailable'}}})
  try {
    m.state.placements=[{id:1,answer_url:'https://public.example/a'},{id:2,answer_url:'https://public.example/b'}]
    await m.state.verifyBatch();assert.equal(calls,1);assert.equal(m.state.batchResults.length,1)
  }finally{m.app.unmount()}
})

test('CSV preserves unknowns and historical link dates while neutralizing formulas',async()=>{
  const m=await mount()
  try {
    const link={checked_at:'2026-09-01T00:00:00Z',backlink_discovery:{state:'readable',found:1,created:1}}
    const row={id:1,platform:'=1+1',status:'content_observed',observations:[link,{checked_at:'2026-09-06T00:00:00Z',backlink_discovery:{state:'not_checked'}}]}
    m.state.placements=[row]
    assert.equal(m.state.latestBacklink(row),link)
    assert.match(m.state.resultsCsv(),/"'=1\+1"/)
    assert.match(m.state.resultsCsv(),/2026-09-01T00:00:00Z/)
    assert.match(m.state.resultsCsv(),/2026-09-06T00:00:00Z/)
    assert.equal(m.state.csvCell('"quoted",value'),'"""quoted"",value"')
    assert.equal(m.state.csvCell('  @SUM(A1)'), '"\'  @SUM(A1)"')
  }finally{m.app.unmount()}
})


test('semantic analysis sends chosen versions and does not apply changes',async()=>{
  const m=await mountPlanning()
  try {
    m.state.result.groups[0].intents[0].questions.push({id:2,version:1,title:'另一问题'})
    m.state.chosen=[1,2]
    await m.state.analyzeSemantic()
    assert.equal(m.writes.length,1)
    assert.equal(m.writes[0][0],'planning/semantic')
    assert.equal(m.writes[0][1].items.length,2)
    assert.equal(m.writes[0][1].request_id,undefined)
  }finally{m.app.unmount()}
})

test('semantic analysis is disabled for read-only users',async()=>{
  const m=await mountPlanning({},false)
  try {m.state.chosen=[1,2];await m.state.analyzeSemantic();assert.equal(m.writes.length,0)}finally{m.app.unmount()}
})


test('semantic response is discarded after site change',async()=>{
  let resolve
  const m=await mountPlanning({seoQaPost:()=>new Promise(r=>resolve=r)})
  try {
    m.state.result.groups[0].intents[0].questions.push({id:2,version:1,title:'另一问题'})
    m.state.chosen=[1,2]
    const request=m.state.analyzeSemantic();await flush();m.props.siteId=20;await flush()
    resolve({pairs:[{left_id:1,right_id:2}]});await request
    assert.equal(m.state.semantic,null)
  }finally{m.app.unmount()}
})


test('recovered semantic candidates require current versions before classification',async()=>{
  const m=await mountPlanning()
  try {
    m.state.result.groups[0].intents[0].questions.push({id:2,version:1,title:'问题二'})
    m.state.semantic={questions:[{id:1,version:3},{id:2,version:1}]}
    assert.equal(m.state.semanticPairCurrent({left_id:1,right_id:2}),true)
    m.state.semantic.questions[0].version=2
    assert.equal(m.state.semanticPairCurrent({left_id:1,right_id:2}),false)
  }finally{m.app.unmount()}
})


test('demand priority uses recent positive evidence and unanswered state, not mixed totals',async()=>{
  const m=await mountPlanning()
  try {
    const source={count:1,period_end:new Date().toISOString().slice(0,10)}
    assert.equal(m.state.demandPriority({answer_count:0,sources:[source]}),1)
    assert.equal(m.state.demandPriority({answer_count:1,sources:[source]}),0)
    assert.equal(m.state.demandPriority({sources:[{...source,count:0}]}),0)
    assert.equal(m.state.demandPriority({sources:[{...source,period_end:'2000-01-01'}]}),0)
    assert.equal(m.state.demandPriority({sources:[]}),0)
  }finally{m.app.unmount()}
})


test('import requires a preview and changing input invalidates it',async()=>{
  const m=await mount({seoQaPost:async(path,payload)=>({preview_token:'a'.repeat(64),summary:{new_question:1},rows:[]})})
  try {
    m.state.dialog='csv';m.state.importing='title\n如何排查';await flush()
    await m.state.importQuestions();assert.equal(m.writes.length,0)
    await m.state.previewImport();assert.ok(m.state.importPreview)
    m.state.importing='title\n另一问题';await flush()
    assert.equal(m.state.importPreview,null)
    assert.match(m.state.messageOf({response:{data:{detail:[{msg:'第 2 条记录日期无效'}]}}}),/第 2 条/)
  }finally{m.app.unmount()}
})


function assistantFixture() {
  return {kind:'seo_qa_receipt',schema_version:1,tenant_id:1,site_id:10,placement_id:7,version:2,
    content_version:3,platform:'zhihu',question_url:'https://www.zhihu.com/question/12',
    answer_url:'https://www.zhihu.com/question/12/answer/34'}
}
async function setupReceipt(m) {
  const item=assistantFixture()
  m.state.placements=[{...item,id:7}]
  Object.assign(m.state.receiptForm,{id:7,version:2,answer_url:''})
  m.state.dialog='receipt';await flush()
  return item
}
function receiptFile(item) {return {target:{value:'file',files:[{size:300,text:async()=>JSON.stringify(item)}]}}}
test('assistant receipt previews locally then submits scoped versioned report',async()=>{
  const m=await mount()
  try {
    const item=await setupReceipt(m)
    await m.state.readAssistantReceipt(receiptFile(item))
    assert.equal(m.writes.length,0);assert.equal(m.state.receiptForm.answer_url,item.answer_url)
    await m.state.saveReceipt()
    assert.equal(m.writes[0][0],'placements/7/assistant-receipt')
    assert.deepEqual(m.writes[0][1],item)
  }finally{m.app.unmount()}
})
test('assistant receipt rejects other scopes and stale versions before any write',async()=>{
  const m=await mount()
  try {
    const item=await setupReceipt(m)
    for(const patch of [{tenant_id:2},{site_id:2},{placement_id:8},{version:99},{content_version:99},{kind:'published'}, {answer_url:'javascript:alert(1)'}]) {
      await m.state.readAssistantReceipt(receiptFile({...item,...patch}))
      assert.equal(m.state.assistantReceipt,null);assert.ok(m.state.error)
    }
    assert.equal(m.writes.length,0)
  }finally{m.app.unmount()}
})
test('late receipt read is discarded after closing and reopening dialog',async()=>{
  const m=await mount()
  try {
    const item=await setupReceipt(m);let resolve
    const work=m.state.readAssistantReceipt({target:{value:'file',files:[{size:300,text:()=>new Promise(r=>{resolve=r})}]}})
    m.state.dialog='';await flush();m.state.dialog='receipt';await flush()
    resolve(JSON.stringify(item));await work
    assert.equal(m.state.assistantReceipt,null);assert.equal(m.state.receiptForm.answer_url,'')
  }finally{m.app.unmount()}
})


test('question detail and quality responses never cross selected questions',async()=>{
  const pending=[]
  const m=await mount({seoQaGet:(path)=>path==='answers'||path.endsWith('/detail')?new Promise(resolve=>pending.push({path,resolve})):Promise.resolve(path==='questions'?{items:[],total:0}:[])})
  try {
    const first=m.state.openQuestion({id:1,sources:[]}),second=m.state.openQuestion({id:2,sources:[]})
    pending[2].resolve([{id:22,quality:{method:'rules'}}]);pending[3].resolve({question:{id:2},coverage:{state:'draft_only'}});await second
    pending[0].resolve([{id:11}]);pending[1].resolve({question:{id:1}});await first
    assert.equal(m.state.questionDetail.question.id,2);assert.equal(m.state.answerItems[0].id,22)
  }finally{m.app.unmount()}
})
test('coverage gap filter includes stale and draft answers but excludes valid coverage',async()=>{
  const sample={groups:[{topic:'主题',intents:[{intent:'learn',questions:[
    {id:1,title:'草稿',topic:'主题',answer_count:1,valid_answer_count:0},
    {id:2,title:'过期',topic:'主题',answer_count:1,valid_answer_count:0},
    {id:3,title:'有效',topic:'主题',answer_count:1,valid_answer_count:1}]}]}]}
  const m=await mountPlanning({seoQaGet:async()=>sample})
  try {m.state.flags.coverageGap=true;assert.deepEqual(m.state.groups[0].intents[0].questions.map(q=>q.id),[1,2])}finally{m.app.unmount()}
})


async function mountResearch(api={},options={}) {
  const source=await readFile(new URL('../src/views/seo/SeoQaResearch.vue',import.meta.url),'utf8')
  const compiled=compileScript(parse(source).descriptor,{id:'research',genDefaultAs:'component'}).content
  const props=Vue.reactive({tenantId:1,siteId:10,canEdit:true,mode:'extract',answerId:7,contentVersion:2,questionVersion:3,blocked:false,...options}),writes=[]
  const bindings={...Vue,previewSeoQaFile:async()=>({text:'解析原文'.repeat(10),warnings:['请核对']}),seoQaGet:async()=>({items:[]}),seoQaPost:async(...args)=>{writes.push(args);return {accepted:{0:{question_id:4,fact_id:5}}}},extractSeoQaDocument:async()=>({action:'qa_extract',operation_id:'extract-op',candidates:[{index:0,question:'如何使用',quote:'使用前先确认条件'}],accepted:{}}),analyzeSeoQaQuality:async()=>({action:'qa_quality',answer_id:7,content_version:2,question_version:3,issues:[]}),...api}
  const names=Object.keys(bindings).filter(k=>/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(k))
  const component=new Function('b',`const {${names.join(',')}}=b;${compiled.replace(/^import .* from .*$/gm,'')};return component`)(bindings)
  component.render=()=>null
  const app=renderer.createApp({render:()=>Vue.h(component,props)}),root=app.mount({});await flush()
  return {app,state:root.$.subTree.component.setupState,props,writes}
}
test('document analysis is a preview; explicit selected acceptance is scoped',async()=>{
  const m=await mountResearch()
  try{await m.state.analyze();assert.equal(m.writes.length,0);m.state.chosen=[0];await m.state.accept();assert.deepEqual(m.writes[0],['research/extract-op/accept',{tenant_id:1,site_id:10,indices:[0]}]);assert.equal(m.state.result.accepted[0].fact_id,5)}finally{m.app.unmount()}
})
test('read-only research cannot charge AI or import facts',async()=>{
  let charged=0;const m=await mountResearch({extractSeoQaDocument:async()=>{charged++}},{canEdit:false})
  try{await m.state.analyze();m.state.result={operation_id:'op'};m.state.chosen=[0];await m.state.accept();assert.equal(charged,0);assert.equal(m.writes.length,0)}finally{m.app.unmount()}
})
test('research drops late AI responses and clears source text on site switch',async()=>{
  let resolve;const m=await mountResearch({extractSeoQaDocument:()=>new Promise(r=>{resolve=r})})
  try{m.state.source.text='资料';await flush();const work=m.state.analyze();m.props.siteId=20;await flush();resolve({operation_id:'old',candidates:[]});await work;assert.equal(m.state.result,null);assert.equal(m.state.source.text,'')}finally{m.app.unmount()}
})
test('quality suggestions become historical when saved version changes',async()=>{
  const m=await mountResearch({}, {mode:'quality'})
  try{await m.state.analyze();assert.equal(m.state.current,true);m.props.contentVersion=3;await flush();assert.equal(m.state.current,false);assert.equal(m.writes.length,0);m.props.blocked=true;await m.state.analyze();assert.equal(m.state.result.content_version,2)}finally{m.app.unmount()}
})
test('research recovery refuses another answer or operation kind',async()=>{
  const m=await mountResearch({seoQaGet:async()=>({action:'qa_extract',answer_id:8})},{mode:'quality'})
  try{await m.state.recover({id:'other',has_result:true});assert.equal(m.state.result,null);assert.ok(m.state.error)}finally{m.app.unmount()}
})

test('file preview only parses, resets source provenance and never calls AI',async()=>{
  let charged=0;const m=await mountResearch({extractSeoQaDocument:async()=>{charged++}})
  try{m.state.source.source_url='https://old.example';await m.state.readText({target:{files:[{name:'手册.docx',size:123}],value:'x'}});assert.equal(m.state.source.source_name,'手册.docx');assert.equal(m.state.source.source_url,'');assert.ok(m.state.source.text);assert.equal(charged,0);assert.deepEqual([...m.state.fileWarnings],['请核对']);assert.equal(m.writes.length,0)}finally{m.app.unmount()}
})
test('late file preview cannot populate another site',async()=>{
  let resolve;const m=await mountResearch({previewSeoQaFile:()=>new Promise(r=>{resolve=r})})
  try{const work=m.state.readText({target:{files:[{name:'手册.pdf',size:123}]}});m.props.siteId=20;await flush();resolve({text:'旧站点资料',warnings:[]});await work;assert.equal(m.state.source.text,'')}finally{m.app.unmount()}
})
test('oversize and read-only file selection never upload',async()=>{
  let count=0;const m=await mountResearch({previewSeoQaFile:async()=>{count++}})
  try{await m.state.readText({target:{files:[{name:'大.pdf',size:6*1024*1024}]}});assert.ok(m.state.error);m.props.canEdit=false;await flush();await m.state.readText({target:{files:[{name:'手册.pdf',size:1}]}});assert.equal(count,0)}finally{m.app.unmount()}
})

async function mountBatch(api={},options={}){
  const source=await readFile(new URL('../src/views/seo/SeoQaBatchDrafts.vue',import.meta.url),'utf8')
  const compiled=compileScript(parse(source).descriptor,{id:'batch',genDefaultAs:'component'}).content
  const props=Vue.reactive({tenantId:1,siteId:10,canEdit:true,questions:[{id:1,version:2,title:'问题'}],...options}),writes=[]
  const batch={id:8,status:'queued',items:[{question_id:1,title:'问题',state:'pending'}]}
  const bindings={...Vue,SeoQaBatchReview:{},seoQaGet:async path=>path==='facts'?[{id:3,version:4,current:true,title:'手册'}]:path==='batches'?{items:[batch]}:batch,seoQaPost:async(path,payload)=>{writes.push([path,payload]);return batch},...api}
  const names=Object.keys(bindings).filter(k=>/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(k))
  const component=new Function('b',`const {${names.join(',')}}=b;${compiled.replace(/^import .* from .*$/gm,'')};return component`)(bindings)
  component.render=()=>null
  const app=renderer.createApp({render:()=>Vue.h(component,props)}),root=app.mount({});await flush()
  const state=root.$.subTree.component.setupState
  return {app,state,props,writes}
}
test('durable batch submits versions once without browser AI generation',async()=>{
  const m=await mountBatch();try{await m.state.prepare();m.state.rows[0].factIds=[3];await m.state.submit();assert.equal(m.writes[0][0],'batches');assert.deepEqual(m.writes[0][1].items,[{question:{id:1,version:2},facts:[{id:3,version:4}],format:'short'}]);assert.ok(m.writes[0][1].request_id);assert.equal(m.state.current.id,8);assert.equal(m.state.rows.length,0)}finally{m.app.unmount()}
})
test('uncertain batch submission retries with the same durable request key',async()=>{
  const ids=[];const m=await mountBatch({seoQaPost:async(p,v)=>{ids.push(v.request_id);throw Error('断网')}})
  try{await m.state.prepare();m.state.rows[0].factIds=[3];await m.state.submit();await m.state.submit();assert.equal(ids.length,2);assert.equal(ids[0],ids[1])}finally{m.app.unmount()}
})
test('read-only batch view can recover server progress but cannot enqueue or control',async()=>{
  const m=await mountBatch({}, {canEdit:false});try{await m.state.prepare();assert.equal(m.state.rows.length,0);await m.state.selectBatch(8);assert.equal(m.state.current.id,8);await m.state.control('pause');assert.equal(m.writes.length,0)}finally{m.app.unmount()}
})
test('batch controls address only selected scope and question',async()=>{
  const m=await mountBatch();try{await m.state.selectBatch(8);await m.state.control('retry',1);assert.deepEqual(m.writes[0],['batches/8/control',{tenant_id:1,site_id:10,action:'retry',question_id:1}])}finally{m.app.unmount()}
})
test('late recovered batch does not enter a different site',async()=>{
  let release;const m=await mountBatch({seoQaGet:async path=>path==='batches'?{items:[]}:new Promise(r=>{release=r})})
  try{const work=m.state.selectBatch(8);m.props.siteId=99;await flush();release({id:8,items:[]});await work;assert.equal(m.state.current,null)}finally{m.app.unmount()}
})
test('fresh mount lists previously submitted batches without starting work',async()=>{
  const m=await mountBatch();try{assert.equal(m.state.history[0].id,8);assert.equal(m.writes.length,0);await m.state.selectBatch(8);assert.equal(m.state.current.items[0].state,'pending')}finally{m.app.unmount()}
})

async function mountBatchReview(api={},options={}){
  const source=await readFile(new URL('../src/views/seo/SeoQaBatchReview.vue',import.meta.url),'utf8')
  const compiled=compileScript(parse(source).descriptor,{id:'review',genDefaultAs:'component'}).content
  const props=Vue.reactive({tenantId:1,siteId:10,batchId:8,canEdit:true,disabled:false,...options}),writes=[]
  const row={question_id:1,answer_id:2,title:'问题',available:true,content_version:3,question_version:4,status:'review',bucket:'review',problems:[],facts:[],quality:{hints:[],manual_review:[]}}
  const value={batch_id:8,items:[row],counts:{review:1}}
  const bindings={...Vue,seoQaGet:async()=>value,seoQaPost:async(path,payload)=>{writes.push([path,payload]);return {}},...api}
  const names=Object.keys(bindings).filter(k=>/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(k))
  const component=new Function('b',`const {${names.join(',')}}=b;${compiled.replace(/^import .* from .*$/gm,'')};return component`)(bindings)
  component.render=()=>null
  const app=renderer.createApp({render:()=>Vue.h(component,props)}),root=app.mount({});await flush()
  return {app,state:root.$.subTree.component.setupState,props,writes,row}
}
test('batch review requires explicit action and sends displayed versions',async()=>{
  const m=await mountBatchReview();try{assert.equal(m.writes.length,0);await m.state.review(m.row,'approve');assert.deepEqual(m.writes[0],['batches/8/answers/2/review',{tenant_id:1,site_id:10,action:'approve',note:null,content_version:3,question_version:4}])}finally{m.app.unmount()}
})
test('batch review read-only and invalid evidence cannot approve',async()=>{
  const m=await mountBatchReview({}, {canEdit:false});try{await m.state.review(m.row,'approve');assert.equal(m.writes.length,0);m.props.canEdit=true;await flush();m.row.problems=['资料过期'];await m.state.review(m.row,'approve');assert.equal(m.writes.length,0)}finally{m.app.unmount()}
})
test('batch rejection requires an opinion but remains possible with stale evidence',async()=>{
  const m=await mountBatchReview();try{m.row.problems=['失效'];await m.state.review(m.row,'reject');assert.equal(m.writes.length,0);assert.ok(m.state.rowErrors[m.state.key(m.row)]);m.state.notes[m.state.key(m.row)]='补充新证据';await m.state.review(m.row,'reject');assert.equal(m.writes[0][1].note,'补充新证据')}finally{m.app.unmount()}
})
test('version conflict is shown without automatic approval retry',async()=>{
  let calls=0;const m=await mountBatchReview({seoQaPost:async()=>{calls++;throw {response:{data:{detail:'正文已更新'}}}}})
  try{await m.state.review(m.row,'approve');assert.equal(calls,1);assert.equal(m.state.rowErrors[m.state.key(m.row)],'正文已更新');assert.equal(m.state.result.items[0].status,'review')}finally{m.app.unmount()}
})
test('switching batch drops a delayed review snapshot and fetches the new batch',async()=>{
  const pending=[];const m=await mountBatchReview({seoQaGet:path=>new Promise(resolve=>pending.push({path,resolve}))})
  try{m.props.batchId=9;await flush();assert.equal(pending.length,2);pending[1].resolve({batch_id:9,items:[],counts:{}});await flush();pending[0].resolve({batch_id:8,items:[{answer_id:99}],counts:{}});await flush();assert.equal(m.state.result.batch_id,9);assert.equal(m.state.loading,false)}finally{m.app.unmount()}
})
test('batch review source links reject executable protocols and embedded credentials',async()=>{
  const m=await mountBatchReview();try{assert.equal(m.state.href('javascript:alert(1)'),null);assert.equal(m.state.href('https://user:pass@example.com'),null);assert.equal(m.state.href('https://example.com/manual'),'https://example.com/manual')}finally{m.app.unmount()}
})

test('export downloads fresh scoped server snapshot even for read-only viewer',async()=>{
  let clicked=0,removed=0;const requests=[]
  const m=await mountBatchReview({document:{body:{appendChild(){}},createElement:()=>({click(){clicked++},remove(){removed++}})},seoQaGet:async(path,params)=>{requests.push([path,params]);return path.endsWith('/export')?{filename:'qa.zip',content_base64:'UEs=',included_count:1,excluded_count:2,as_of:'now'}:{items:[],counts:{}}}},{canEdit:false})
  try{await m.state.exportBatch('approved');assert.equal(clicked,1);assert.equal(removed,1);assert.deepEqual(requests.at(-1),['batches/8/export',{tenant_id:1,site_id:10,kind:'approved'}]);assert.match(m.state.exportMessage,/1 条，未包含 2 条/);assert.equal(m.writes.length,0)}finally{m.app.unmount()}
})
test('export refuses download after scope change and exposes server conflict',async()=>{
  let resolve,clicked=0;const m=await mountBatchReview({document:{createElement(){clicked++;return {}}},seoQaGet:async path=>path.endsWith('/export')?new Promise(r=>{resolve=r}):{items:[],counts:{}}})
  try{const work=m.state.exportBatch('approved');m.props.siteId=20;await flush();resolve({content_base64:'UEs='});await work;assert.equal(clicked,0);assert.equal(m.state.exportMessage,'')}finally{m.app.unmount()}
  const failed=await mountBatchReview({seoQaGet:async path=>{if(path.endsWith('/export'))throw {response:{data:{detail:'当前没有可导出的已审核回答'}}};return {items:[],counts:{}}}})
  try{await failed.state.exportBatch('approved');assert.match(failed.state.error,/没有可导出/);assert.equal(failed.state.acting,false)}finally{failed.app.unmount()}
})

import { publicationEvidence, channelBoundary, countPublishedListedContents } from '../src/views/seo/seoPublicationEvidence.js'

test('publication labels distinguish reported and API evidence without claiming verification',()=>{
  for(const publish_mode of ['manual','assisted','share']) assert.equal(publicationEvidence({status:'published',publish_mode}),'人工确认 / 链接登记')
  for(const publish_mode of ['publish','draft']) assert.equal(publicationEvidence({status:'published',publish_mode}),'接口任务，确认依据见尝试记录')
  assert.equal(publicationEvidence({status:'published'}),'历史发布记录，依据待确认')
  for(const status of ['manual_required','draft_created','publishing','failed']) assert.equal(publicationEvidence({status,publish_mode:'publish'}),'尚无发布成功记录')
})
test('catalog support does not imply account or publishing acceptance',()=>{
  assert.match(channelBoundary({available:true,mode:'assisted'}),/最终发布由真人/)
  assert.match(channelBoundary({available:true,mode:'api'}),/连接成功不代表发布/)
  assert.equal(channelBoundary({available:false,mode:'api'}),'当前尚未开放')
})

test('coverage uses current list scope and deduplicates platforms',()=>{
  const rows=[{status:'published',content_id:1},{status:'published',content_id:1},{status:'published',content_id:99},{status:'manual_required',content_id:2}]
  assert.equal(countPublishedListedContents([{id:1},{id:2}],rows),1)
  assert.equal(countPublishedListedContents([],rows),0)
})
