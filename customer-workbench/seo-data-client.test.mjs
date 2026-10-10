import test from 'node:test';import assert from 'node:assert/strict';
import {createSeoDataClient} from './js/seo-data-client.mjs';import {homeView} from './js/home-view.mjs';
const context={connected:true,tenantId:1,siteId:9,userId:7,revision:1};
function setup(){let current={...context},reply,permission=true;const calls=[];const client=createSeoDataClient({getContext:()=>current,canMaintain:()=>permission,transport:async(path,options)=>{calls.push({path,...options});const value=typeof reply==='function'?await reply():reply;return {ok:typeof value?.status!=='number',status:typeof value?.status==='number'?value.status:200,json:async()=>value?.data??value};}});return {client,calls,set:v=>reply=v,scope:v=>current={...current,...v},deny:()=>permission=false};}
const row={id:2,tenant_id:1,site_id:9,keyword:'example',priority:'P2',landing_page:null};const list=(items=[row],page=1,total=1)=>({items,page,page_size:20,total});
test('keyword deletion requires the latest owned selection and advisor permission, binds the site, and consumes selection once',async()=>{
  const s=setup();await assert.rejects(s.client.removeKeyword(2),/SELECTION_REQUIRED/);assert.equal(s.calls.length,0);
  s.set(list());await s.client.list('keywords');await assert.rejects(s.client.removeKeyword(99),/SELECTION_REQUIRED/);
  s.set(list());await s.client.list('keywords');s.set({deleted:true,keyword_id:2});
  const first=s.client.removeKeyword(2);await assert.rejects(s.client.removeKeyword(2),/SELECTION_REQUIRED/);await first;
  const call=s.calls.find(c=>c.method==='DELETE');assert.equal(call.path,'/api/v1/seo/keywords/2?tenant_id=1&site_id=9');assert.equal(call.body,undefined);
  await assert.rejects(s.client.removeKeyword(2),/SELECTION_REQUIRED/);assert.equal(s.calls.filter(c=>c.method==='DELETE').length,1);
  s.set(list());await s.client.list('keywords');s.deny();await assert.rejects(s.client.removeKeyword(2),/ADVISOR_REQUIRED/);
});
test('keyword deletion fails closed across context changes and uncertain outcomes without automatic resends',async()=>{
  for(const result of [{deleted:true,keyword_id:99},{deleted:false,keyword_id:2},null,{status:500},()=>{throw Error('network lost');}]){
    const s=setup();s.set(list());await s.client.list('keywords');s.set(result);
    await assert.rejects(s.client.removeKeyword(2),/DELETE_OUTCOME_UNKNOWN/);
    await assert.rejects(s.client.removeKeyword(2),/SELECTION_REQUIRED/);assert.equal(s.calls.filter(c=>c.method==='DELETE').length,1);
  }
  const s=setup();s.set(list());await s.client.list('keywords');s.scope({siteId:19});await assert.rejects(s.client.removeKeyword(2),/CONTEXT_CHANGED/);assert.equal(s.calls.filter(c=>c.method==='DELETE').length,0);
  s.scope({siteId:9});s.set(list());await s.client.list('keywords');s.set({status:409});await assert.rejects(s.client.removeKeyword(2),e=>e.code==='DELETE_FAILED'&&e.status===409);
});
test('data reader sends only real supported filters, preserves scoped paging, and requires list ownership for details',async()=>{
  const s=setup();s.set(list());await s.client.list('keywords',{filters:{q:'a b',engine:'baidu',device:'mobile',status:'active'}});const url=new URL(s.calls[0].path,'https://local.invalid');assert.equal(url.searchParams.get('q'),'a b');assert.equal(url.searchParams.get('site_id'),'9');await assert.rejects(s.client.detail('keywords',99),/SELECTION_REQUIRED/);
  s.set(list());await s.client.list('keywords');s.set({keyword:row,rank_history:[]});await s.client.detail('keywords',2);assert.match(s.calls.at(-1).path,/region=%E5%85%A8%E5%9B%BD/);
  s.set(list([{...row,site_id:10}]));await assert.rejects(s.client.list('keywords'),/SCOPE_MISMATCH/);await assert.rejects(s.client.list('publications',{filters:{status:'published'}}),/QUERY_DENIED/);
  s.set({status:500});await assert.rejects(s.client.list('pages'),/READ_FAILED/);
});
test('late data responses are discarded on scope change and publication rows must belong to requested site',async()=>{
  const s=setup();s.set(()=>{s.scope({revision:2});return list();});await assert.rejects(s.client.list('keywords'),/CONTEXT_CHANGED/);
  s.set({...list([{content:{...row,tenant_id:2},publication:{id:1}}]),tenant_id:1,site_id:9,read_only:true});await assert.rejects(s.client.list('publications'),/SCOPE_MISMATCH/);
});
test('fact saves include all fields and frozen version; unknown writes are not retried, keyword updates stay limited',async()=>{
  const s=setup(),fact={...row,title:'资料',statement:'说明',source_name:'来源',version:4,status:'active',source_url:null,expires_at:null};s.set([fact]);await s.client.list('facts');s.set({...fact,version:5});await s.client.save('facts',{...fact,statement:'修改说明'});const body=JSON.parse(s.calls.at(-1).body);assert.equal(body.version,4);assert.equal(body.source_url,null);assert.equal(body.expires_at,null);assert.equal(body.site_id,9);
  s.set(list());await s.client.list('keywords');s.set({...row,priority:'P1'});await s.client.save('keywords',{id:2,priority:'P1',landing_page:'https://example.com/'});assert.deepEqual(Object.keys(JSON.parse(s.calls.at(-1).body)).sort(),['landing_page','priority']);
  s.set([fact]);await s.client.list('facts');s.set({status:409});await assert.rejects(s.client.save('facts',fact),e=>e.status===409);assert.equal(s.calls.filter(c=>c.method==='PATCH').length,3);s.deny();await assert.rejects(s.client.save('facts',fact),/ADVISOR_REQUIRED/);
});
test('home counts actionable delivery status, not ready content, and clearly limits coverage',()=>{
  const delivery=(id,workflow,allowed)=>({content:{id,title:'稿件'+id,version_count:1,status:'ready'},workflow_status:workflow,allowed_actions:allowed});
  const html=homeView({contents:{items:[{id:1},{id:2}],total:500},deliveries:[delivery(1,'approved_waiting_publication',{confirm_as_customer:false}),delivery(2,'awaiting_customer_confirmation',{confirm_as_customer:true})],failed:0,executions:{total:0,items:[]}});
  assert.match(html,/仅覆盖本次 2 篇/);assert.match(html,/还有稿件未核对/);assert.equal((html.match(/查看并确认/g)||[]).length,1);assert(!html.includes('全站待确认'));
});
