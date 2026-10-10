import test from 'node:test';
import assert from 'node:assert/strict';
import {createPlatformConsoleClient} from './js/platform-console-client.mjs';
import {renderAiGovernance,governanceRoute} from './js/platform-ai-governance-view.mjs';
const admin={id:7,tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
const snapshot={schema:1,mode:'read_only_inventory',sources:{},costs:{}};
const response=(body,status=200)=>({ok:status===200,status,json:async()=>body});
const make=(handler)=>{const session={user:admin,token:'fixture',authRevision:0,refreshUser(u){this.user=u;},logout(){this.token='';}};
  return {session,client:createPlatformConsoleClient({session,fetchImpl:(p,o)=>p.endsWith('/me')?response({user:admin}):p.endsWith('/snapshot')?response(snapshot):handler(p,o)})};};
const render=(data,error)=>renderAiGovernance({data,error,card:(t,b,n='')=>t+b+n,table:(h,r)=>h.join('|')+r.flat().join('|')});
test('governance route requires verified server identity and is strictly read-only',async()=>{
  const calls=[];const {client}=make((p,o)=>{calls.push([p,o]);return response({schema:1,state:'available',modules:[]});});
  await assert.rejects(client.governance(),{status:403});assert.equal(calls.length,0);
  await client.initialize();await client.governance();assert.equal(calls[0][0],governanceRoute);assert.equal(calls[0][1].method,'GET');
  assert.equal(calls[0][1].credentials,'omit');assert.equal(calls[0][1].cache,'no-store');
});
test('missing endpoint, invalid schema and permission denial are not successful empty results',async()=>{
  for(const status of [404,403,401]){const {client}=make(()=>response({},status));await client.initialize();await assert.rejects(client.governance(),{status});if(status!==404)assert.equal(client.getIdentity(),null);}
  const {client}=make(()=>response({schema:1,state:'available'}));await client.initialize();await assert.rejects(client.governance(),{code:'CONSOLE_INVALID_GOVERNANCE'});
});
test('late governance response after identity change is rejected',async()=>{
  let release;const {client,session}=make(()=>({ok:true,status:200,json:()=>new Promise(r=>release=r)}));await client.initialize();
  const promise=client.governance();while(!release)await new Promise(r=>setTimeout(r,1));session.token='changed';release({schema:1,state:'available',modules:[]});await assert.rejects(promise,{code:'CONSOLE_STALE'});
});
test('only allowlisted presentation fields render; unknown counts and unapproved schema stay honest',()=>{
  const data={schema:1,state:'available',api_key:'fixture-secret',modules:[{module:'seo',provider:'dashscope',model:'qwen',configured:true,metering:{state:'recording'},calls:{failed:0,unknown:null},limits:[{kind:'budget',state:'disabled',value:100}],secrets:{api_key:'fixture-secret'}}],website:{enabled:true}};
  const html=render(data);assert.match(html,/阿里云百炼/);assert.match(html,/计量中/);assert.match(html,/0\|未知/);assert.doesNotMatch(html,/fixture-secret|100/);assert.match(html,/reserved \/ disabled/);
  const pending=render({...data,state:'schema_pending'});assert.match(pending,/等待数据库人工审核/);assert.match(pending,/qwen/);assert.match(pending,/计量中/);assert.match(pending,/0\|未知/);assert.match(pending,/治理编辑保持禁用/);assert.doesNotMatch(pending,/fixture-secret|100/);assert.match(pending,/<button disabled>/);
  assert.match(render(null,'AI 治理接口未部署，运行状态未接入。'),/接口未部署/);
});
