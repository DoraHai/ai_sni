import test from 'node:test';
import assert from 'node:assert/strict';
import {createAdvisorTenantSwitch,advisorScopedFetch} from './js/advisor-tenant-switch.mjs';
const response=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
const fixture=()=>({token:'identity',user:{id:7},authRevision:0,isAdvisorSession:true,replaceAuthForAdvisorTenant(token,tid){this.token=token;this.tenantId=tid;this.authRevision++;}});
test('tenant selection uses only the new endpoints and the latest server list',async()=>{
  const session=fixture(),calls=[];let tenants=[{id:1,name:'客户甲'},{id:2,name:'客户乙'}];
  const client=createAdvisorTenantSwitch({session,fetchImpl:async(path,opts)=>{
    calls.push({path,opts});return response(opts.method==='GET'?tenants:{access_token:'business',token_type:'bearer',tenant_id:2,tenant_name:'客户乙',expires_at:'2099-01-01'});
  }});
  assert.deepEqual(await client.list(),tenants);tenants=[];assert.deepEqual(await client.list(),[]);
  await client.select(2);assert.equal(session.tenantId,2);
  assert.equal(calls[2].path,'/api/v1/auth/select-tenant');assert.deepEqual(JSON.parse(calls[2].opts.body),{tenant_id:2});
  assert(calls.every(c=>c.opts.cache==='no-store'&&c.opts.credentials==='omit'));
});
test('empty/invalid tenant IDs cannot select; denied and disabled codes are preserved',async()=>{
  const session=fixture();let code='ADVISOR_TENANT_NOT_GRANTED',count=0;
  const client=createAdvisorTenantSwitch({session,fetchImpl:async()=>{count++;return response({detail:{code}},403);}});
  for(const id of [null,0,-1,true,'1'])await assert.rejects(client.select(id),{code:'INVALID_TENANT'});
  assert.equal(count,0);await assert.rejects(client.select(3),{code});assert.equal(session.token,'identity');
  code='ADVISOR_MULTI_TENANT_DISABLED';await assert.rejects(client.list(),{code});
});
test('a late selection response cannot replace a changed session',async()=>{
  const session=fixture();let finish;
  const client=createAdvisorTenantSwitch({session,fetchImpl:()=>new Promise(resolve=>finish=resolve)});
  const pending=client.select(2);client.invalidate();
  finish(response({access_token:'late',token_type:'bearer',tenant_id:2,tenant_name:'客户乙',expires_at:'2099'}));
  await assert.rejects(pending,{code:'CONTEXT_CHANGED'});assert.equal(session.token,'identity');
});
test('panel rejections notify the workbench and late business responses are discarded',async()=>{
  const session=fixture(),denied=[];let finish;
  const fetchImpl=advisorScopedFetch({session,onDenied:code=>denied.push(code),fetchImpl:async()=>response({detail:{code:'ADVISOR_GRANT_REVOKED'}},401)});
  await assert.rejects(fetchImpl('/api/v1/seo/workbench/advisor-tasks'),{code:'ADVISOR_GRANT_REVOKED'});
  assert.deepEqual(denied,['ADVISOR_GRANT_REVOKED']);
  const late=advisorScopedFetch({session,onDenied:()=>assert.fail(),fetchImpl:()=>new Promise(r=>finish=r)})('/api/v1/seo/workbench/advisor-tasks');
  session.authRevision++;finish(response({items:[{tenant_id:1}]}));
  await assert.rejects(late,{code:'CONTEXT_CHANGED'});
});

test('bare business 401 clears business context and recovers only the saved identity',async()=>{
  const session={...fixture(),token:'business',advisorScope:'advisor_tenant'},denied=[];
  const scoped=advisorScopedFetch({session,fetchImpl:async()=>new Response('',{status:401}),onDenied:code=>{
    denied.push(code);session.token='saved-identity';session.authRevision++;
  }});
  await assert.rejects(scoped('/api/v1/seo/workbench/advisor-tasks'),{code:'ADVISOR_TENANT_SESSION_EXPIRED'});
  assert.deepEqual(denied,['ADVISOR_TENANT_SESSION_EXPIRED']);
  assert.equal(session.token,'saved-identity');
});

test('bare identity 401 logs out instead of retrying expired identity credentials',async()=>{
  let logouts=0;
  const session={...fixture(),advisorScope:'advisor_identity',logout(){logouts++;this.token='';this.authRevision++;}},denied=[];
  const scoped=advisorScopedFetch({session,fetchImpl:async()=>response({},401),onDenied:code=>denied.push(code)});
  await assert.rejects(scoped('/api/v1/auth/tenants'),{code:'ADVISOR_IDENTITY_SESSION_EXPIRED'});
  assert.equal(logouts,1);assert.equal(session.token,'');
  assert.deepEqual(denied,['ADVISOR_IDENTITY_SESSION_EXPIRED']);
});
