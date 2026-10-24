import test from 'node:test';
import assert from 'node:assert/strict';
import {createAdvisorClient,validateAdvisorPage,advisorModuleEligible} from './js/advisor-client.mjs';
import {advisorTaskPath,advisorPageView} from './js/advisor-workbench.mjs';
import {onsiteTaskFromSearch,readOnsiteDeepLink} from './js/advisor-task-link.mjs';
import {entryScope} from './js/workbench-entry.mjs';
export const row=(module='seo',id=77)=>({id,module,tenant_id:2,scope_id:module==='geo'?10:9,title:'实际任务',workflow:{module,revision:3,phase:'review',month:'2026-10',owner_name:'实施人员',items:[]},allowed_actions:['approve'],next_action:'核实事实并审核',blocker:'等待审核',capabilities:{website_write:{enabled:false}}});
export const page=(module='seo',items=[row(module)],next=null)=>({schema:1,module,items,next_before_id:next});
function fixture(){const session={token:'ordinary-token',user:{id:7,tenant_id:null,permissions:{'seo.site':'edit','geo.assets':'edit','geo.content':'edit'}},authRevision:1,logout(){this.token='';this.user=null;this.authRevision++;}},calls=[];let status=200,hold=null,enabled=['seo','geo'];
 const client=createAdvisorClient({session,fetchImpl:async(path,opt)=>{calls.push({path,opt});const module=path.includes('/geo/')?'geo':'seo';const data=path.endsWith('/me')?{user:structuredClone(session.user)}:path.endsWith('/modules')?{tenant_id:session.user.tenant_id,modules:enabled.map(module_code=>({module_code,available:true}))}:page(module);if(hold)await hold;return {ok:status===200,status,json:async()=>data};}});
 return {client,session,calls,setStatus:v=>status=v,hold:v=>hold=v,enabled:v=>enabled=v};
}
test('advisor preflight uses real identity, enabled modules and edit eligibility without tenant enumeration',async()=>{const f=fixture();f.enabled(['seo']);assert.deepEqual((await f.client.initialize()).modules,['seo']);await f.client.list('seo');await assert.rejects(()=>f.client.list('geo'),/PERMISSION_DENIED/);assert.equal(f.calls.length,3);assert(f.calls.every(v=>v.opt.method==='GET'&&v.opt.credentials==='omit'));assert(f.calls.every(v=>!v.path.includes('/tenants')));assert.equal(advisorModuleEligible({...f.session.user,tenant_id:2},'seo'),true);assert.equal(advisorModuleEligible({...f.session.user,permissions:{'seo.site':'view'}},'seo'),false);f.client.dispose();});
test('bounded queries and cursor integrity reject invalid or cross-module data',async()=>{const f=fixture();await f.client.initialize();for(const input of [{limit:51},{limit:0},{beforeId:0},{tenantId:-1}])await assert.rejects(()=>f.client.list('seo',input),/QUERY_DENIED/);await assert.rejects(()=>f.client.list('admin'),/PERMISSION_DENIED/);assert.equal(f.calls.length,2);
 for(const value of [{...page(),module:'geo'},page('seo',[{...row(),scope_id:0}]),page('seo',[{...row(),project_id:9}]),page('seo',[{...row(),workflow:{...row().workflow,revision:0}}]),page('seo',[row(),row()]),page('seo',[row()],78),{...page(),schema:2}])assert.throws(()=>validateAdvisorPage(value,'seo'),/CONTRACT_MISMATCH/);
 assert.throws(()=>validateAdvisorPage(page(),'seo',{beforeId:77}),/CONTRACT_MISMATCH/);assert.equal(validateAdvisorPage(page('seo',[row()],77),'seo').next_before_id,77);f.client.dispose();});
test('account switch rejects late header and JSON responses',async()=>{const f=fixture();await f.client.initialize();let release;f.hold(new Promise(r=>release=r));const pending=f.client.list('seo');f.session.user={...f.session.user,id:8};f.session.authRevision++;release();await assert.rejects(()=>pending,/CONTEXT_CHANGED/);await assert.rejects(()=>f.client.list('seo'),/PERMISSION_DENIED/);f.client.dispose();});
test('ordinary module failures preserve other modules and permit retry; 401 clears the session',async()=>{for(const status of [401,403,404,503]){const f=fixture();await f.client.initialize();f.setStatus(status);await assert.rejects(()=>f.client.list('seo'),status===401?/AUTH_EXPIRED/:status===403?/PERMISSION_DENIED/:/NOT_INTEGRATED/);if(status===401)assert.equal(f.session.token,'');else{f.setStatus(200);assert.equal((await f.client.list('geo')).module,'geo');assert.equal((await f.client.list('seo')).module,'seo');}f.client.dispose();}});

test('a module 403 does not abort a concurrent successful module request',async()=>{
 const f=fixture();let release,started;
 const ready=new Promise(resolve=>started=resolve),held=new Promise(resolve=>release=resolve),invalidations=[];
 const client=createAdvisorClient({session:f.session,fetchImpl:async path=>{
  if(path.endsWith('/me'))return new Response(JSON.stringify({user:f.session.user}));
  if(path.endsWith('/modules'))return new Response(JSON.stringify({tenant_id:null,modules:['seo','geo'].map(module_code=>({module_code,available:true}))}));
  if(path.includes('/geo/')){started();await held;return new Response(JSON.stringify(page('geo')));}
  return new Response(JSON.stringify({detail:{code:'ADVISOR_ROUTE_UNAVAILABLE'}}),{status:403});
 }});
 await client.initialize();client.subscribe(reason=>invalidations.push(reason));
 const geo=client.list('geo');await ready;await assert.rejects(()=>client.list('seo'),/PERMISSION_DENIED/);release();
 assert.equal((await geo).module,'geo');assert.deepEqual(invalidations,[]);assert.equal(f.session.token,'ordinary-token');client.dispose();f.client.dispose();
});

test('explicit grant revocation and role changes invalidate every module',async()=>{
 for(const code of ['ADVISOR_GRANT_REVOKED','ADVISOR_ROLE_CHANGED']){
  const f=fixture();let denied=false;const reasons=[];
  const client=createAdvisorClient({session:f.session,fetchImpl:async path=>new Response(JSON.stringify(denied?{detail:{code}}:path.endsWith('/me')?{user:f.session.user}:{tenant_id:null,modules:['seo','geo'].map(module_code=>({module_code,available:true}))}),{status:denied?403:200})});
  await client.initialize();client.subscribe(reason=>reasons.push(reason));denied=true;
  await assert.rejects(()=>client.list('seo'),new RegExp(code));assert.deepEqual(reasons,['forbidden']);await assert.rejects(()=>client.list('geo'),/PERMISSION_DENIED/);client.dispose();f.client.dispose();
 }
});

test('empty task pages explain that the current customer has no assigned onsite tasks',()=>{
 for(const module of ['seo','geo'])assert.equal(advisorPageView(module,page(module,[])),'<p>这个客户还没有分配给你的站内任务</p>');
});
test('deep links retain exact module scope and reread the original scoped record',async()=>{assert.equal(advisorTaskPath(row()),'/customer-workbench/?tenant_id=2&site_id=9&onsite_task_id=77');assert.equal(advisorTaskPath(row('geo')),'/customer-workbench/?module=geo&tenant_id=2&project_id=10&onsite_task_id=77');for(const q of ['?onsite_task_id=0','?onsite_task_id=1&onsite_task_id=2','?onsite_task_id=9007199254740991'])assert.equal(onsiteTaskFromSearch(q),null);const calls=[];const result=await readOnsiteDeepLink({list:async before=>{calls.push(before);return page();}},77);assert.equal(result.selected.workflow.revision,3);assert.deepEqual(calls,[78]);await assert.rejects(()=>readOnsiteDeepLink({list:async()=>page('seo',[])},77),/当前不可见/);});
test('display escapes real metadata, uses page counts and preserves manual next actions',()=>{const value=page('seo',[{...row(),tenant_name:'<img onerror=x>',scope_name:'网站 & 1'}]);const html=advisorPageView('seo',value);assert(html.includes('&lt;img'));assert(html.includes('本页 1 项'));assert(html.includes('核实事实并审核'));assert(!html.includes('AI 提案已提供'));assert(!html.includes('<img'));});
test('entry rejects ambiguous or invalid task hints and preserves valid exact IDs',()=>{assert.equal(entryScope('?tenant_id=2&site_id=9&onsite_task_id=77').onsiteTaskId,77);for(const tail of ['0','1&onsite_task_id=2','NaN','9007199254740991'])assert.equal(entryScope('?tenant_id=2&site_id=9&onsite_task_id='+tail).invalid,true);});
test('server action codes and structured blockers show clear advisor next steps',()=>{const html=advisorPageView('seo',page('seo',[{...row(),next_action:'save_proposal',blocker:{code:'proposal_evidence_missing',message:'补齐本轮公开依据'}}]));assert.match(html,/顾问完善并提交当前方案/);assert.match(html,/补齐本轮公开依据/);assert(!html.includes('[object Object]'));});
test('bound advisor cannot receive another customer through the aggregate contract',async()=>{const f=fixture();f.session.user.tenant_id=1;await f.client.initialize();await assert.rejects(()=>f.client.list('seo'),/CONTRACT_MISMATCH/);f.client.dispose();});
test('explicit customer queries retain module and cursor bounds and reject foreign rows',async()=>{
 const f=fixture();await f.client.initialize();
 for(const module of ['seo','geo']){
  await f.client.list(module,{tenantId:2,beforeId:78});
  const url=new URL(f.calls.at(-1).path,'https://advisor.test');
  assert.equal(url.pathname,`/api/v1/${module}/workbench/advisor-tasks`);
  assert.deepEqual(Object.fromEntries(url.searchParams),{limit:'25',before_id:'78',tenant_id:'2'});
  await assert.rejects(()=>f.client.list(module,{tenantId:1}),/CONTRACT_MISMATCH/);
 }
 f.client.dispose();
});
test('late JSON body cannot survive a changed canonical auth revision',async()=>{const f=fixture();let release,bodyStarted;const started=new Promise(r=>bodyStarted=r),held=new Promise(r=>release=r);const client=createAdvisorClient({session:f.session,fetchImpl:async path=>({ok:true,status:200,json:async()=>{if(path.endsWith('/me'))return {user:f.session.user};if(path.endsWith('/modules'))return {tenant_id:null,modules:[{module_code:'seo',available:true}]};bodyStarted();await held;return page();}})});await client.initialize();const pending=client.list('seo');await started;f.session.authRevision++;release();await assert.rejects(()=>pending,/CONTEXT_CHANGED/);client.dispose();f.client.dispose();});
test('a tenant scope change with the same login ID invalidates pending advisor reads',async()=>{const f=fixture();await f.client.initialize();let release;f.hold(new Promise(resolve=>release=resolve));const pending=f.client.list('seo');f.session.user.tenant_id=2;release();await assert.rejects(()=>pending,/CONTEXT_CHANGED/);await assert.rejects(()=>f.client.list('seo'),/PERMISSION_DENIED/);f.client.dispose();});
test('an account change between advisor identity and module reads rejects the old identity',async()=>{const f=fixture();let release,ready;const started=new Promise(resolve=>ready=resolve),held=new Promise(resolve=>release=resolve);const client=createAdvisorClient({session:f.session,fetchImpl:async path=>({ok:true,status:200,json:async()=>{if(path.endsWith('/me'))return {user:structuredClone(f.session.user)};ready();await held;return {tenant_id:null,modules:[{module_code:'seo',available:true}]};}})});const pending=client.initialize();await started;f.session.user={...f.session.user,id:8};release();await assert.rejects(()=>pending,/CONTEXT_CHANGED/);await assert.rejects(()=>client.list('seo'),/PERMISSION_DENIED/);client.dispose();f.client.dispose();});

test('advisor starts identity and modules concurrently',async()=>{
  const f=fixture();let release;const started=[];
  const held=new Promise(resolve=>release=resolve);
  const client=createAdvisorClient({session:f.session,fetchImpl:async path=>{
    started.push(path);await held;
    return Response.json(path.endsWith('/me')?{user:f.session.user}:{tenant_id:null,modules:[{module_code:'seo',available:true}]});
  }});
  const pending=client.initialize();
  assert.deepEqual(started,['/api/v1/auth/me','/api/v1/auth/modules']);
  release();assert.deepEqual((await pending).modules,['seo']);
  client.dispose();f.client.dispose();
});
