import test from 'node:test';import assert from 'node:assert/strict';
import {createHostSessionAdapter,sameOriginLoginUrl,existingSessionBridge} from './js/host-session-adapter.mjs';
import {startFixtureServer} from './tests/fixture-server.mjs';

const conversationPath='/api/v1/seo/workbench/content-assets/88/conversation';
test('only the exact conversation forbidden code stays local for GET and POST',async()=>{
  const server=await startFixtureServer(),events=[];
  const host=createHostSessionAdapter({origin:server.origin,allowLocalHttp:true,getSession:()=>({token:'fixture-advisor',userId:7,tenantId:1,siteId:9,revision:1})});
  const stop=host.subscribe(event=>events.push(event));
  try{
    await host.initialize();const context=host.getContext();
    for(const [method,suffix,body] of [['GET',''],['GET','/messages'],['POST','/messages',{tenant_id:1,site_id:9,request_id:'fixture',body:'消息'}],['POST','/read',{tenant_id:1,site_id:9,last_read_message_id:1}]]){
      const detail={code:'conversation_forbidden',message:'当前账号没有活动站点顾问分配'};
      server.state.forceError={path:conversationPath+suffix,status:403,detail};
      const response=await host.transport(conversationPath+suffix+(method==='GET'?'?tenant_id=1&site_id=9':''),{method,...(body?{body:JSON.stringify(body)}:{})});
      assert.equal(response.ok,false);assert.equal(response.status,403);assert.deepEqual(await response.json(),{detail});assert.deepEqual(host.getContext(),context);assert.equal(host.getState().phase,'connected');
    }
    assert.deepEqual(events,[]);
    const delivery=await host.transport('/api/v1/seo/workbench/content-assets/88/delivery?tenant_id=1&site_id=9');assert.equal(delivery.status,200);assert.equal((await delivery.json()).content.id,88);
  }finally{stop();host.dispose();await server.close();}
});

test('other conversation errors and non-conversation 403 still invalidate, and 401 still logs out',async()=>{
  const server=await startFixtureServer();let loggedOut=0,redirects=0,malformed=false;
  const host=createHostSessionAdapter({origin:server.origin,allowLocalHttp:true,getSession:()=>({token:'fixture-advisor',userId:7,tenantId:1,siteId:9,revision:1}),logout:()=>loggedOut++,redirectToLogin:()=>redirects++,fetchImpl:async(url,options)=>malformed?new Response('{',{status:403}):fetch(url,options)});
  try{
    for(const [path,status,detail,badJson] of [
      [conversationPath,403,{code:'tenant_forbidden'}],
      [conversationPath,403,'forbidden'],
      [conversationPath,403,null,true],
      ['/api/v1/seo/workbench/content-assets/88/delivery',403,{code:'conversation_forbidden'}],
      [conversationPath,401,{code:'conversation_forbidden'}],
    ]){
      malformed=false;await host.initialize();malformed=!!badJson;const events=[],stop=host.subscribe(event=>events.push(event.reason));
      if(!malformed)server.state.forceError={path,status,detail};
      await assert.rejects(host.transport(path+'?tenant_id=1&site_id=9'),e=>e.code===(status===401?'AUTH_EXPIRED':'PERMISSION_DENIED')&&e.status===status);
      assert.equal(host.getContext(),null);assert.deepEqual(events,[status===401?'expired':'forbidden']);stop();
    }
    assert.equal(loggedOut,1);assert.equal(redirects,1);
  }finally{host.dispose();await server.close();}
});

test('conversation route matching rejects invalid IDs, lookalikes and methods before fetch',async()=>{
  const server=await startFixtureServer();
  const host=createHostSessionAdapter({origin:server.origin,allowLocalHttp:true,getSession:()=>({token:'fixture-advisor',userId:7,tenantId:1,siteId:9,revision:1})});
  try{
    await host.initialize();const calls=server.state.calls.length;
    for(const path of ['0/conversation','-1/conversation','01/conversation','88/conversations','88/conversation-evil','88/conversation/messages/evil','88/conversation/'])await assert.rejects(host.transport('/api/v1/seo/workbench/content-assets/'+path+'?tenant_id=1&site_id=9'),/ROUTE_DENIED/);
    await assert.rejects(host.transport(conversationPath,{method:'DELETE'}),/ROUTE_DENIED/);assert.equal(server.state.calls.length,calls);assert(host.getContext());
  }finally{host.dispose();await server.close();}
});

test('scope change during forbidden body parsing or before caller json discards the old response',async()=>{
  const server=await startFixtureServer();let session={token:'fixture-advisor',userId:7,tenantId:1,siteId:9,revision:1},resolveBody,bodyStarted;
  const parsing=new Promise(resolve=>bodyStarted=resolve);
  const host=createHostSessionAdapter({origin:server.origin,allowLocalHttp:true,getSession:()=>session,fetchImpl:async(url,options)=>String(url).includes('/conversation')?{ok:false,status:403,clone:()=>({json:()=>{bodyStarted();return new Promise(resolve=>resolveBody=resolve);}})}:fetch(url,options)});
  try{
    await host.initialize();const pending=host.transport(conversationPath+'?tenant_id=1&site_id=9');await parsing;
    session={...session,tenantId:2,siteId:19,revision:2};resolveBody({detail:{code:'conversation_forbidden'}});
    await assert.rejects(pending,e=>e.code==='CONTEXT_CHANGED');assert.equal(host.getContext(),null);
  }finally{host.dispose();await server.close();}
  const second=await startFixtureServer();session={token:'fixture-advisor',userId:7,tenantId:1,siteId:9,revision:1};
  const next=createHostSessionAdapter({origin:second.origin,allowLocalHttp:true,getSession:()=>session});
  try{
    await next.initialize();second.state.forceError={path:conversationPath,status:403,detail:{code:'conversation_forbidden'}};
    const response=await next.transport(conversationPath+'?tenant_id=1&site_id=9');session={...session,tenantId:2,siteId:19,revision:2};
    await assert.rejects(response.json(),e=>e.code==='CONTEXT_CHANGED');assert.equal(next.getContext(),null);
  }finally{next.dispose();await second.close();}
});
test('keyword deletion requires edit permission and both exact tenant and site scope, with no body',async()=>{
  const server=await startFixtureServer();server.state.keywordLevel='view';
  const host=createHostSessionAdapter({origin:server.origin,allowLocalHttp:true,getSession:()=>({token:'fixture-advisor',userId:7,tenantId:1,siteId:9,revision:1})});
  const path='/api/v1/seo/keywords/1001?tenant_id=1&site_id=9';
  try{
    await host.initialize();await assert.rejects(host.transport(path,{method:'DELETE'}),/PERMISSION_DENIED/);
    server.state.keywordLevel='edit';await host.initialize();
    for(const url of ['/api/v1/seo/keywords/1001?tenant_id=1','/api/v1/seo/keywords/1001?tenant_id=2&site_id=9','/api/v1/seo/keywords/1001?tenant_id=1&site_id=19'])await assert.rejects(host.transport(url,{method:'DELETE'}),/SCOPE_MISMATCH/);
    await assert.rejects(host.transport(path,{method:'DELETE',body:'{}'}),/BODY_DENIED/);
    assert.equal(server.state.calls.filter(c=>c.method==='DELETE').length,0);
  }finally{host.dispose();await server.close();}
});
test('caller abort reaches an authorized media fetch and its response body',async()=>{
  const server=await startFixtureServer();let signal;
  const host=createHostSessionAdapter({origin:server.origin,allowLocalHttp:true,getSession:()=>({token:'fixture-advisor',userId:7,tenantId:1,siteId:9,revision:1}),fetchImpl:async(url,options)=>{if(String(url).includes('/page-captures/')){signal=options.signal;return {ok:true,status:200,headers:new Headers(),arrayBuffer:()=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}))};}return fetch(url,options);}});
  try{await host.initialize();const controller=new AbortController(),response=await host.transport('/api/v1/seo/site/page-captures/1/image?tenant_id=1',{method:'GET',signal:controller.signal});const pending=response.arrayBuffer();controller.abort();await assert.rejects(pending,e=>e.name==='AbortError');assert.equal(signal.aborted,true);assert(host.getContext());}finally{host.dispose();await server.close();}
});
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
