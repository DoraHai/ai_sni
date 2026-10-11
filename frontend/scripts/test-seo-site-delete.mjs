import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import vm from 'node:vm'
const source=await readFile(new URL('../src/views/seo/SeoSitesView.vue',import.meta.url),'utf8')
const handler=source.slice(source.indexOf('async function remove(row)'),source.indexOf('watch(currentTenantId'))
function fixture({confirm=async()=>{},fail=false}={}){
 const writes=[],messages=[],prompts=[]
 const state={deletingId:{value:null},currentTenantId:{value:1},currentSeoSiteId:{value:10},session:{user:{id:7}},
 ElMessageBox:{confirm:async(...args)=>{prompts.push(args);return confirm()}},
 ElMessage:{success:x=>messages.push(x),error:x=>messages.push(x)},
 deleteSeoSite:async(...args)=>{writes.push(args);if(fail)throw Error('删除失败')},
 load:async()=>{},notifySeoSitesChanged:()=>{state.refreshed=true}}
 vm.createContext(state);new vm.Script(handler+';globalThis.remove=remove').runInContext(state)
 return {state,writes,messages,prompts,row:{id:10,name:'测试网站',canonical_domain:'example.com'}}
}
test('confirmation explains all data loss and external publishing boundary, then deletes once and refreshes scope',async()=>{
 const f=fixture();await f.state.remove(f.row)
 assert.deepEqual(f.writes,[[10,1,'example.com']]);assert.equal(f.state.currentSeoSiteId.value,null);assert.equal(f.state.refreshed,true)
 assert.match(f.prompts[0][0],/永久删除，无法恢复/);assert.match(f.prompts[0][0],/不会撤回/)
 assert.equal(f.prompts[0][2].confirmButtonText,'确认永久删除')
})
test('cancel and closing confirmation never send DELETE',async()=>{
 for(const reason of ['cancel','close']){const f=fixture({confirm:async()=>{throw reason}});await f.state.remove(f.row);assert.equal(f.writes.length,0);assert.equal(f.messages.length,0)}
})
test('scope changes and repeated clicks while confirming cannot delete the wrong site',async()=>{
 for(const scopeChanged of [true,false]){
  let resolve;const f=fixture({confirm:()=>new Promise(r=>{resolve=r})})
  const pending=f.state.remove(f.row);await f.state.remove(f.row)
  if(scopeChanged)f.state.currentTenantId.value=2
  resolve();await pending;assert.equal(f.writes.length,scopeChanged?0:1)
 }
})
test('failure retains selection and allows retry',async()=>{
 const f=fixture({fail:true});await f.state.remove(f.row)
 assert.equal(f.state.currentSeoSiteId.value,10);assert.equal(f.state.deletingId.value,null);assert.equal(f.state.refreshed,undefined);assert.deepEqual(f.messages,['删除失败'])
})
test('website status has no archive choice and changes invalidate the workspace site cache',async()=>{
 assert.doesNotMatch(source,/<el-option[^>]+value="archived"/)
 const shell=await readFile(new URL('../src/views/seo/SeoWorkspaceShell.vue',import.meta.url),'utf8')
 assert.match(shell,/watch\(seoSitesRevision, validateCurrentScope\)/)
 assert.match(source,/notifySeoSitesChanged\(\)/)
})
