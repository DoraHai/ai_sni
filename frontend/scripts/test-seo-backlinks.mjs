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
  .replace('export default','return'))(Vue,api)
const flush=async()=>{await Promise.resolve();await Vue.nextTick();await Promise.resolve();await Vue.nextTick()}

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
