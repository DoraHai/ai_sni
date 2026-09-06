import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import {readFileSync} from 'node:fs'
const source=readFileSync(new URL('../src/views/geo/GeoDistributionView.vue',import.meta.url),'utf8')
const code=source.slice(source.indexOf('let contextVersion'),source.indexOf('onMounted(load)'))
function fixture() {
 const notices=[];let changed,unmount
 const ctx=vm.createContext({tenantId:{value:7},taskId:{value:12},error:{value:''},loading:{value:false},busy:{value:''},
 channels:{value:[]},accounts:{value:[]},task:{value:{id:12}},pushTargets:{value:[]},webhookAccounts:{value:[]},
 webhookAccountId:{value:null},webhookUrl:{value:''},backfillChannel:{value:'website'},backfillUrl:{value:'https://example.invalid/a'},backfillNote:{value:'test'},
 listGeoPublishingChannels:async()=>({items:[]}),listGeoChannelAccounts:async()=>({items:[]}),getGeoContentTask:async()=>({id:12}),fetchTaskPushTargets:async()=>({targets:[]}),
 pushGeoVariantWebhook:async()=>({}),publishGeoVariant:async()=>({}),
 ElMessage:{success:x=>notices.push(x),error:x=>notices.push(x),warning:x=>notices.push(x)},
 watch:(_,fn)=>{changed=fn},onBeforeUnmount:fn=>{unmount=fn}})
 vm.runInContext(code,ctx)
 return {ctx,notices,change:()=>changed(),unmount:()=>unmount()}
}
test('customer switch clears old data and drops late load',async()=>{
 const f=fixture();let finish
 f.ctx.getGeoContentTask=()=>new Promise(resolve=>{finish=resolve})
 const pending=f.ctx.load()
 f.ctx.tenantId.value=8;f.ctx.getGeoContentTask=async()=>({id:12,tenant_id:8})
 f.change();await new Promise(resolve=>setImmediate(resolve))
 finish({id:12,tenant_id:7});await pending
 assert.equal(f.ctx.task.value.tenant_id,8)
 assert.equal(f.ctx.backfillUrl.value,'');assert.equal(f.ctx.webhookAccountId.value,null)
})
test('older refresh cannot overwrite a newer response',async()=>{
 const f=fixture();let finish
 f.ctx.getGeoContentTask=()=>new Promise(resolve=>{finish=resolve})
 const old=f.ctx.load();f.ctx.getGeoContentTask=async()=>({id:12,title:'new'})
 await f.ctx.load();finish({id:12,title:'old'});await old
 assert.equal(f.ctx.task.value.title,'new')
})
test('double click initiates only one push and keeps server dedup as fallback',async()=>{
 const f=fixture();let finish,calls=0
 f.ctx.pushGeoVariantWebhook=()=>{calls++;return new Promise(resolve=>{finish=resolve})}
 const row={ready:true,accountId:3,key:'website'}
 const first=f.ctx.pushRow(row,'publish');await f.ctx.pushRow(row,'publish')
 assert.equal(calls,1);finish({});await first
})
test('late backfill response cannot clear new customer draft or show success',async()=>{
 const f=fixture();let finish
 f.ctx.publishGeoVariant=()=>new Promise(resolve=>{finish=resolve})
 const pending=f.ctx.backfill();f.ctx.tenantId.value=8;f.change()
 f.ctx.backfillUrl.value='https://example.invalid/new'
 finish({});await pending
 assert.equal(f.ctx.backfillUrl.value,'https://example.invalid/new');assert.deepEqual(f.notices,[])
})
test('late failure after unmount does not show a toast or mutate state',async()=>{
 const f=fixture();let reject
 f.ctx.pushGeoVariantWebhook=()=>new Promise((_,r)=>{reject=r})
 const pending=f.ctx.pushRow({ready:true,accountId:3,key:'website'},'publish')
 f.unmount();reject(new Error('old failure'));await pending
 assert.deepEqual(f.notices,[])
})
test('failed backfill preserves entered URL and does not retry itself',async()=>{
 const f=fixture();let calls=0
 f.ctx.publishGeoVariant=async()=>{calls++;throw new Error('timeout')}
 await f.ctx.backfill()
 assert.equal(calls,1);assert.equal(f.ctx.busy.value,'');assert.equal(f.ctx.backfillUrl.value,'https://example.invalid/a')
})
