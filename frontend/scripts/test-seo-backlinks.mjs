import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { JSDOM } from 'jsdom'
import { parse, compileScript } from '@vue/compiler-sfc'
const dom = new JSDOM('<div id="app"></div>', {url:'https://local.example/'})
for (const key of ['window','document','Element','SVGElement','HTMLElement']) globalThis[key]=dom.window[key]
const Vue = await import('vue')
const {descriptor}=parse(await readFile(new URL('../src/views/seo/SeoBacklinkWorkbench.vue',import.meta.url),'utf8'))
const source=compileScript(descriptor,{id:'backlink-test'}).content
const compile=(api)=>new Function('Vue','api',source
  .replace(/import\s*\{([^}]+)\}\s*from\s*['"]vue['"]/g,(_,names)=>`const {${names.replace(/\s+as\s+/g,':')}}=Vue`)
  .replace(/import\s*\{[^}]+\}\s*from\s*['"]element-plus['"]/g,'const ElMessage={warning(){}}')
  .replace(/import\s*\{([^}]+)\}\s*from\s*['"]\.\.\/\.\.\/api\/seo['"]/g,(_,names)=>`const {${names}}=api`)
  .replace(/import SeoBacklinkInsights from '[^']+'/, 'const SeoBacklinkInsights = {}')
  .replace(/import SeoBacklinkOpportunities from '[^']+'/, 'const SeoBacklinkOpportunities = {}')
  .replace('export default','return'))(Vue,api)
const flush=async()=>{await Promise.resolve();await Vue.nextTick();await Promise.resolve();await Vue.nextTick()}
const opportunitiesDescriptor=parse(await readFile(new URL('../src/views/seo/SeoBacklinkOpportunities.vue',import.meta.url),'utf8')).descriptor
const compileOpportunities=(api)=>new Function('Vue','api',compileScript(opportunitiesDescriptor,{id:'opportunities-test'}).content
  .replace(/import SeoBacklinkWorkflow from '[^']+'/, 'const SeoBacklinkWorkflow = {}')
  .replace(/import\s*\{([^}]+)\}\s*from\s*['"]vue['"]/g,(_,names)=>`const {${names.replace(/\s+as\s+/g,':')}}=Vue`)
  .replace(/import\s*\{([^}]+)\}\s*from\s*['"]\.\.\/\.\.\/api\/seo['"]/g,(_,names)=>`const {${names}}=api`)
  .replace('export default','return'))(Vue,api)

test('opportunity query captures scope, prevents repeat calls and ignores late results',async()=>{
  let release;const calls=[]
  const component=compileOpportunities({fetchSeoBacklinkOpportunities:async()=>({provider:{configured:true},result:null}),
    querySeoBacklinkOpportunities:async args=>{calls.push(args);return new Promise(resolve=>release=resolve)}})
  component.render=()=>null
  const props=Vue.reactive({tenantId:1,siteId:10,canEdit:true})
  const app=Vue.createApp({render:()=>Vue.h(component,props)}),root=app.mount(document.getElementById('app'));await flush()
  const state=root.$.subTree.component.setupState
  state.competitors='peer.example';const pending=state.run();await state.run();assert.equal(calls.length,1)
  props.tenantId=2;props.siteId=20;await flush();release({items:[{source_domain:'old.example'}]});await pending
  assert.equal(state.result,null);assert.equal(calls[0].site_id,10);assert.equal(state.competitors,'')
  props.canEdit=false;await flush();state.competitors='peer.example';await state.run();assert.equal(calls.length,1)
  app.unmount()
})
const insightsDescriptor=parse(await readFile(new URL('../src/views/seo/SeoBacklinkInsights.vue',import.meta.url),'utf8')).descriptor
const compileInsights=(api)=>new Function('Vue','api',compileScript(insightsDescriptor,{id:'insights-test'}).content
  .replace(/import\s*\{([^}]+)\}\s*from\s*['"]vue['"]/g,(_,names)=>`const {${names.replace(/\s+as\s+/g,':')}}=Vue`)
  .replace(/import\s*\{([^}]+)\}\s*from\s*['"]\.\.\/\.\.\/api\/seo['"]/g,(_,names)=>`const {${names}}=api`)
  .replace('export default','return'))(Vue,api)

test('CSV preview rejects stale customer responses and invalid rows cannot commit',async()=>{
  let release
  const calls=[]
  const component=compileInsights({fetchSeoBacklinkAnalysis:async()=>({pending:0}),fetchSeoBacklinkIndexStatus:async()=>({configured:true}),
    importSeoBacklinkCsv:async(args)=>{calls.push(args);return new Promise(resolve=>release=resolve)}})
  component.render=()=>null
  const props=Vue.reactive({tenantId:1,siteId:10,canEdit:true})
  const app=Vue.createApp({render:()=>Vue.h(component,props)}),root=app.mount(document.getElementById('app'));await flush()
  const state=root.$.subTree.component.setupState
  const pending=state.chooseFile({target:{files:[{size:10}],value:'file'}});await flush()
  props.siteId=20;await flush();release({items:[{}],errors:[]});await pending
  assert.equal(state.preview,null);assert.equal(state.dialog,false);assert.equal(calls[0].siteId,10)
  state.file={size:10};state.preview={items:[{}],errors:[{reason:'invalid'}]};await state.commit();assert.equal(calls.length,1)
  props.canEdit=false;await flush();state.preview={items:[{}],errors:[]};await state.commit();assert.equal(calls.length,1)
  app.unmount()
})

test('index query blocks duplicate clicks and discards response after site switch',async()=>{
  let release;let calls=0
  const component=compileInsights({fetchSeoBacklinkAnalysis:async()=>({pending:0}),fetchSeoBacklinkIndexStatus:async()=>({configured:true}),
    querySeoBacklinkIndex:async()=>{calls++;return new Promise(resolve=>release=resolve)}})
  component.render=()=>null
  const props=Vue.reactive({tenantId:1,siteId:10,canEdit:true})
  const app=Vue.createApp({render:()=>Vue.h(component,props)}),root=app.mount(document.getElementById('app'));await flush()
  const state=root.$.subTree.component.setupState
  const pending=state.queryIndex();await flush();await state.queryIndex();assert.equal(calls,1)
  props.siteId=20;await flush();release({state:'completed',received:1,created:1});await pending
  assert.equal(state.message,'');assert.equal(state.busy,false)
  props.canEdit=false;await flush();await state.queryIndex();assert.equal(calls,1);app.unmount()
})

test('batch discovery uses captured site, stops on scope change and discards late results',async()=>{
  let release
  const calls=[]
  const api={
    fetchSeoBacklinks:async({siteId})=>({items:[{id:siteId,source_domain:'media.example',source_url:'https://media.example/story',target_url:'https://brand.example',status:'active'}]}),
    fetchSeoBacklinkSources:async()=>({items:[]}),
    discoverSeoBacklinks:async(payload)=>{calls.push(payload);await new Promise(resolve=>release=resolve);return {state:'readable',found:1,created:1}},
    verifySeoBacklink:async()=>({verification:{state:'found'}}), monitorSeoBacklink:async()=>({}),
  }
  const component=compile(api);component.render=()=>null
  const props=Vue.reactive({tenantId:1,siteId:10,canEdit:true})
  const app=Vue.createApp({render:()=>Vue.h(component,props)})
  const root=app.mount(document.getElementById('app'));await flush()
  const state=root.$.subTree.component.setupState
  assert.equal(state.rows[0].id,10)
  const running=state.discover([{source_url:'https://media.example/a'},{source_url:'https://media.example/b'}])
  await flush();assert.equal(calls.length,1)
  props.siteId=20;await flush();release();await running;await flush()
  assert.equal(calls.length,1);assert.equal(calls[0].site_id,10)
  assert.equal(state.rows[0].id,20);assert.equal(state.results.length,0);assert.equal(state.busy,false)
  app.unmount()
})

test('read-only workbench cannot execute discovery or verification',async()=>{
  let writes=0
  const component=compile({fetchSeoBacklinks:async()=>({items:[]}),fetchSeoBacklinkSources:async()=>({items:[]}),discoverSeoBacklinks:async()=>writes++,verifySeoBacklink:async()=>writes++,monitorSeoBacklink:async()=>writes++})
  component.render=()=>null
  const app=Vue.createApp(component,{tenantId:1,siteId:10,canEdit:false})
  const vm=app.mount(document.getElementById('app'));await flush()
  await vm.$.setupState.discover([{source_url:'https://media.example/a'}])
  await vm.$.setupState.verify([{id:1}])
  assert.equal(writes,0);app.unmount()
})
