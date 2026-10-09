import assert from 'node:assert/strict'
import { test, after } from 'node:test'
import { readFile } from 'node:fs/promises'
import { JSDOM } from 'jsdom'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'

const dom = new JSDOM('<!doctype html><html><body></body></html>')
for (const key of ['window','document','Element','HTMLElement','SVGElement','Node','Event']) globalThis[key] = dom.window[key]
const Vue = await import('vue')
after(() => dom.window.close())
const source = await readFile(new URL('../src/views/seo/SeoKeywordAssetsView.vue', import.meta.url), 'utf8')
const descriptor = parse(source).descriptor
const compiled = compileScript(descriptor, { id: 'keywords', genDefaultAs: 'component' })
const code = compiled.content.replace(/^import .*$/gm, '')
let template = compileTemplate({ source: descriptor.template.content, id: 'keywords', compilerOptions: { bindingMetadata: compiled.bindings } }).code
 template = template.replace(/import \{([\s\S]*?)\} from "vue"/g, (_, names) => `const {${names.replace(/ as /g, ':')}}=Vue`).replace('export function render', 'function render')
const flush = async () => { await new Promise(resolve => setTimeout(resolve, 0)); await Vue.nextTick() }
async function mount(options={}) {
  const writes=[], notices=[]
  let records=[{id:11, keyword:'测试词', status: options.status || 'active'}]
  const bindings={computed:Vue.computed,onMounted:Vue.onMounted,reactive:Vue.reactive,ref:Vue.ref,watch:Vue.watch, useRoute:()=>({query:{}}), useRouter:()=>({push(){}}),
    currentTenantId:Vue.ref(1), siteId:Vue.ref(8),
    session:{isLoggedIn:true,canEdit:()=>options.edit!==false,user:{id:7}},
    ElMessage:{success:x=>notices.push(x),error:x=>notices.push(x)},
    ElMessageBox:{confirm:options.confirm || (async()=>{})},
    fetchSeoSites:async()=>({sites:[{id:8,status:'active'}]}),
    fetchSeoKeywords:async()=>({items:records,total:records.length,stats:{active:records.length}}),
    deleteSeoKeyword:async payload=>{writes.push(payload); if(options.fail)throw Error('删除失败'); records=[]},
    createSeoKeyword(){},importSeoKeywords(){},updateSeoKeyword(){}}
  const component=new Function('b',`const {${Object.keys(bindings).join(',')}}=b;${code};return component`)(bindings)
  component.render=new Function('Vue',`${template};return render`)(Vue)
  const host=document.createElement('div');document.body.append(host)
  const app=Vue.createApp(component);app.directive('loading',{})
  for(const name of ['el-select','el-option','el-alert','el-dialog','el-form','el-form-item','el-input','el-input-number','el-button'])app.component(name,{render(){return Vue.h('div',this.$slots.default?.())}})
  const instance=app.mount(host);await flush()
  return {host,state:instance.$.setupState,bindings,writes,notices,close(){app.unmount();host.remove()}}
}
test('active and paused rows render delete, confirmed removal refreshes the list',async()=>{
  for(const status of ['active','paused']){
    const f=await mount({status});try{
      const button=f.host.querySelector('.keyword-actions .danger');assert.equal(button.textContent,'删除')
      button.click();await flush();assert.deepEqual(f.writes,[{keywordId:11,tenantId:1}])
      assert.equal(f.host.querySelectorAll('.keyword-actions').length,0)
      assert.ok(f.notices.includes('关键词已删除'))
    }finally{f.close()}
  }
})
test('read-only users see no delete action and cannot invoke it',async()=>{
  const f=await mount({edit:false});try{assert.equal(f.host.querySelector('.danger'),null);await f.state.removeKeyword({id:11});assert.equal(f.writes.length,0)}finally{f.close()}
})
test('cancel and close preserve the keyword without sending DELETE',async()=>{
  for(const reason of ['cancel','close']){const f=await mount({confirm:async()=>{throw reason}});try{await f.state.removeKeyword({id:11});assert.equal(f.writes.length,0);assert.equal(f.notices.length,0);assert.ok(f.host.querySelector('.danger'))}finally{f.close()}}
})
test('failed deletion retains row and enables retry',async()=>{
  const f=await mount({fail:true});try{await f.state.removeKeyword({id:11});await flush();assert.ok(f.host.querySelector('.danger'));assert.equal(f.state.deletingId,null);assert.deepEqual(f.notices,['删除失败'])}finally{f.close()}
})
test('double click sends only one request and scope changes cancel pending confirmation',async()=>{
  for(const changed of [false,true]){
    let confirm;const f=await mount({confirm:()=>new Promise(resolve=>{confirm=resolve})});try{
      const pending=f.state.removeKeyword({id:11});await f.state.removeKeyword({id:11})
      if(changed)f.bindings.currentTenantId.value=2
      confirm();await pending;assert.equal(f.writes.length,changed?0:1)
    }finally{f.close()}
  }
})
