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

const creation=source.slice(source.indexOf('function open(row=null)'),source.indexOf('async function remove(row)'))
function createFixture({create=async()=>({id:101})}={}){
 const writes=[],messages=[]
 const state={currentTenantId:{value:4},currentSeoSiteId:{value:10},session:{user:{id:7},isAdvisorSession:true},
  formScope:{value:null},editing:{value:null},visible:{value:false},saving:{value:false},form:{},
  ElMessage:{success:x=>messages.push(x),warning:x=>messages.push(x),error:x=>messages.push(x)},
  createSeoSite:async body=>{writes.push({...body});return create()},updateSeoSite:async()=>{throw Error('unexpected edit')},
  load:async()=>{},notifySeoSitesChanged:()=>{state.refreshed=true}}
 vm.createContext(state);new vm.Script(creation+';globalThis.open=open;globalThis.save=save').runInContext(state)
 return {state,writes,messages}
}
test('advisor sees add button and missing customer disables it with guidance',()=>{
 assert.doesNotMatch(source,/v-if="!session.isAdvisorSession"[^>]*>添加网站/)
 assert.match(source,/:disabled="!currentTenantId"[^>]*@click="open\(\)">添加网站/)
 assert.match(source,/请先在右上角选择客户，再添加网站/)
 const f=createFixture();f.state.currentTenantId.value=null;f.state.open()
 assert.equal(f.state.visible.value,false);assert.match(f.messages[0],/先.*选择客户/)
})
test('creation sends only captured tenant name and domain and does not grant or select unassigned site',async()=>{
 const f=createFixture();f.state.open();Object.assign(f.state.form,{name:'官网',domain:'example.test'})
 await f.state.save()
 assert.deepEqual(f.writes,[{tenant_id:4,name:'官网',domain:'example.test'}])
 assert.equal(f.state.currentSeoSiteId.value,10);assert.equal(f.state.refreshed,true)
 assert.match(f.messages[0],/超管分配/)
})
test('switching customer or account after opening cannot create in the new scope',async()=>{
 for(const change of [s=>s.currentTenantId.value=5,s=>s.session.user.id=8]){
  const f=createFixture();f.state.open();Object.assign(f.state.form,{name:'官网',domain:'example.test'});change(f.state)
  await f.state.save();assert.equal(f.writes.length,0);assert.equal(f.state.visible.value,false)
 }
})
test('pending creation prevents duplicate submission and ignores stale response after customer switch',async()=>{
 let resolve;const f=createFixture({create:()=>new Promise(r=>{resolve=r})})
 f.state.open();Object.assign(f.state.form,{name:'官网',domain:'example.test'})
 const pending=f.state.save();await f.state.save();f.state.currentTenantId.value=5;resolve({id:101});await pending
 assert.equal(f.writes.length,1);assert.equal(f.messages.length,0)
 assert.equal(f.state.refreshed,undefined);assert.equal(f.state.currentSeoSiteId.value,10)
})
test('customer creation retains new-site selection',async()=>{
 const f=createFixture();f.state.session.isAdvisorSession=false;f.state.open()
 Object.assign(f.state.form,{name:'官网',domain:'example.test'});await f.state.save()
 assert.equal(f.state.currentSeoSiteId.value,101)
})
