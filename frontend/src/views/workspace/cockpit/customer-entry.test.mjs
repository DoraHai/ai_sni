import test from 'node:test';
import assert from 'node:assert/strict';
import {customerWorkbenchHref,probeCustomerWorkbench} from './customer-entry.mjs';
const valid={ready:true,token:'synthetic',demo:false,tenantId:17,siteId:3,modules:[{module_code:'seo'}],sites:[{id:3,status:'active'}]};
test('entry carries the selected tenant and site only',()=>{
  assert.equal(customerWorkbenchHref(valid),'/customer-workbench/?tenant_id=17&site_id=3');
  for(const change of [{ready:false},{token:''},{demo:true},{tenantId:0},{tenantId:'17'},{siteId:NaN},{siteId:2},{modules:[]},{sites:[{id:3,status:'disabled'}]}])assert.equal(customerWorkbenchHref({...valid,...change}),null);
});
test('probe sends no identity and rejects redirects, generic shells, errors',async()=>{
  const html='<title>客户工作台</title><link href="./app.css"><script src="./app.js"></script>';
  const fetchImpl=async(url,options)=>{
    assert.equal(url,'/customer-workbench/');assert.equal(options.credentials,'omit');assert.equal(options.redirect,'error');assert.equal(options.headers.Authorization,undefined);
    return new Response(html,{headers:{'content-type':'text/html; charset=utf-8'}});
  };
  assert.equal(await probeCustomerWorkbench({fetchImpl}),true);
  for(const response of [new Response('old SEM shell',{headers:{'content-type':'text/html'}}),new Response(html,{status:404,headers:{'content-type':'text/html'}}),new Response(html,{headers:{'content-type':'application/json'}})])assert.equal(await probeCustomerWorkbench({fetchImpl:async()=>response}),false);
  assert.equal(await probeCustomerWorkbench({fetchImpl:async()=>{throw Error('network unavailable')}}),false);
});
