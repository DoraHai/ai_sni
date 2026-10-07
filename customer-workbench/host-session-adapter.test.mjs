import test from 'node:test';import assert from 'node:assert/strict';
import {createHostSessionAdapter,sameOriginLoginUrl,existingSessionBridge} from './js/host-session-adapter.mjs';
import {startFixtureServer} from './tests/fixture-server.mjs';
test('no session sends no request; login keeps same-origin safe redirect',async()=>{
  let count=0,url=null;const host=createHostSessionAdapter({origin:'https://example.invalid',getSession:()=>null,fetchImpl:async()=>{count++;},redirectToLogin:value=>url=value,returnPath:'//foreign.invalid'});
  assert.equal((await host.initialize()).phase,'unauthenticated');assert.equal(count,0);host.login();assert.equal(url,'/login?redirect=%2Fcustomer-workbench%2F');assert.equal(sameOriginLoginUrl('/customer-workbench/?a=1'),'/login?redirect=%2Fcustomer-workbench%2F%3Fa%3D1');host.dispose();
});
test('login returns to scope, rejects encoded external paths and login loops',()=>{
  const expected='/login?redirect=%2Fcustomer-workbench%2F';
  for(const value of ['/login','/login/','/../login','/%2fforeign.invalid','/%5cforeign.invalid','/%0alogin','/%zz'])assert.equal(sameOriginLoginUrl(value),expected);
  assert.equal(new URL(sameOriginLoginUrl('/customer-workbench/?tenant_id=1&site_id=9#content'),'https://fixture.invalid').searchParams.get('redirect'),'/customer-workbench/?tenant_id=1&site_id=9#content');
});
test('preflight scope and route allowlist reject foreign clients and unapproved writes',async()=>{
  const server=await startFixtureServer();let session={token:'fixture-advisor',userId:7,tenantId:1,siteId:9,revision:1};
  const host=createHostSessionAdapter({origin:server.origin,allowLocalHttp:true,getSession:()=>session});
  try{
    assert.equal((await host.initialize()).phase,'connected');
    for(const path of ['https://foreign.invalid/api/v1/seo/content-assets','/api/v1/seo/content-assets?tenant_id=2&site_id=19','/api/v1/seo/content-assets?tenant_id=1&site_id=9&token=bad'])await assert.rejects(host.transport(path,{method:'GET'}));
    await assert.rejects(host.transport('/api/v1/seo/content-distribution/publish',{method:'POST',body:'{}'}),/ROUTE_DENIED/);
    assert.equal(server.state.calls.filter(c=>c.method!=='GET').length,0);
    session={token:'fixture-customer',userId:12,tenantId:2,siteId:19,revision:2};
    await assert.rejects(host.initialize(),/IDENTITY_SCOPE_MISMATCH/);assert.equal(host.getContext(),null);
  }finally{host.dispose();await server.close();}
});
test('session bridge tracks tenant changes independently of authRevision',()=>{
  const session={token:'fixture-advisor',user:{id:7},tenantId:1,authRevision:0,modules:[],logout(){}};let watched,listener;
  const browser={addEventListener(){},removeEventListener(){}};
  const bridge=existingSessionBridge({session,getSiteId:()=>9,browser,watch:(getter,callback)=>{watched=getter;listener=callback;return()=>{};}});
  let events=0;const stop=bridge.subscribeSession(()=>events++);const before=watched();session.tenantId=2;assert.notDeepEqual(watched(),before);listener();assert.equal(events,1);assert.equal(bridge.getSession().tenantId,2);stop();
});
