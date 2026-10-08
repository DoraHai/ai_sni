import test from 'node:test';
import assert from 'node:assert/strict';
import {createSeoContentReader} from './js/seo-readonly-client.mjs';
const fixture = () => ({items:[{id:3,tenant_id:1,site_id:2,version_count:1}],total:1,page:1,page_size:50});
test('GET-only exact scope and verified history reference; no invented writes',async()=>{
  const calls=[],context={tenantId:1,siteId:2,revision:1};
  const reader=createSeoContentReader({getContext:()=>context,transport:async(path,options)=>{calls.push({path,options});return {ok:true,json:async()=>fixture()};}});
  await assert.rejects(reader.reviewHistory(3),/CONTENT_NOT_VERIFIED/);
  await reader.contents();await reader.reviewHistory(3);
  assert.equal(calls[0].path,'/api/v1/seo/content-assets?tenant_id=1&site_id=2&page=1&page_size=50');
  assert.equal(calls[1].path,'/api/v1/seo/content-assets/3/review-history?tenant_id=1');
  assert(calls.every(c=>c.options.method==='GET'));
  context.revision=2;await assert.rejects(reader.reviewHistory(3),/CONTEXT_CHANGED/);
});
test('forbidden has no demo fallback; foreign site is rejected',async()=>{
  const context={tenantId:1,siteId:2,revision:1};
  const denied=createSeoContentReader({getContext:()=>context,transport:async()=>({ok:false,status:403})});
  await assert.rejects(denied.contents(),/PERMISSION_DENIED/);
  const wrong=createSeoContentReader({getContext:()=>context,transport:async()=>({ok:true,json:async()=>({...fixture(),items:[{id:3,tenant_id:1,site_id:9}]})})});
  await assert.rejects(wrong.contents(),/SCOPE_MISMATCH/);await assert.rejects(wrong.reviewHistory(3),/CONTENT_NOT_VERIFIED/);
});
test('pagination uses the server page contract, invalidates prior references and rejects bad values',async()=>{
  const context={tenantId:1,siteId:2,revision:1};let calls=0,mismatch=false;
  const reader=createSeoContentReader({getContext:()=>context,transport:async path=>{calls++;const page=Number(new URL(path,'https://fixture.invalid').searchParams.get('page'));return {ok:true,json:async()=>({...fixture(),page:mismatch?1:page,total:53,items:[{id:page===1?3:4,tenant_id:1,site_id:2}]})};}});
  await reader.contents();await reader.contents({page:2});await assert.rejects(reader.reviewHistory(3),/CONTENT_NOT_VERIFIED/);
  assert.equal(calls,2);for(const page of [0,-1,1.5,NaN])await assert.rejects(reader.contents({page}),/INVALID_PAGINATION/);assert.equal(calls,2);
  mismatch=true;await assert.rejects(reader.contents({page:2}),/CONTRACT_MISMATCH/);
});
test('context change during response discards old payload',async()=>{
  const context={tenantId:1,siteId:2,revision:1};
  const reader=createSeoContentReader({getContext:()=>context,transport:async()=>({ok:true,json:async()=>{context.siteId=9;return fixture();}})});
  await assert.rejects(reader.contents(),/CONTEXT_CHANGED/);
});
