import test from 'node:test';
import assert from 'node:assert/strict';
import {createOnsiteClient,onsiteTaskId} from './js/onsite-client.mjs';
import {onsiteView,onsiteTaskStatus} from './js/onsite-view.mjs';
import {createHostSessionAdapter} from './js/host-session-adapter.mjs';
import {createGeoHostAdapter} from './js/geo-host-session-adapter.mjs';

function fixture(module='seo'){
 let context={connected:true,tenantId:1,siteId:9,projectId:10,userId:7,revision:1},hold=null,loss=false,nonceMismatch=false;
 const calls=[],row={id:20,module,tenant_id:1,scope_id:module==='seo'?9:10,title:'站内任务',
  workflow:{module,revision:3,phase:'draft',items:[],history:[],owner_name:'维护人员',source:{}},
  capabilities:{ai_planning:{enabled:true,can_generate:true}},allowed_actions:['save_proposal']};
 const client=createOnsiteClient({module,getContext:()=>context,transport:async(path,options)=>{
  calls.push({path,options});if(options.method==='GET')return {ok:true,status:200,json:async()=>({module,tenant_id:1,scope_id:row.scope_id,can_create:true,items:[row]})};
  if(hold)await hold;if(loss)throw Error('lost');
  const body=JSON.parse(options.body);return {ok:true,status:200,json:async()=>({...row,workflow:{...row.workflow,phase:'review',revision:4,ai_run:{request_id:nonceMismatch?'other':body.request_id,state:'ready'}}})};
 }});
 return {client,calls,row,setContext:value=>context={...context,...value},hold:p=>hold=p,lose:()=>loss=true,wrongNonce:()=>nonceMismatch=true};
}
for(const module of ['seo','geo']){
 test(module+' AI proposals bind server revision and scope, coalescing duplicate requests',async()=>{
  const f=fixture(module);await f.client.list();let release;f.hold(new Promise(r=>release=r));
  const first=f.client.propose(20),second=f.client.propose(20);release();const [a,b]=await Promise.all([first,second]);
  assert.equal(a.workflow.revision,4);assert.deepEqual(a,b);assert.equal(f.calls.length,2);
  const call=f.calls[1],body=JSON.parse(call.options.body);
  assert.equal(call.path,`/api/v1/${module}/workbench/onsite-tasks/20/ai-proposal`);
  assert.equal(body.expected_revision,3);assert.equal(body.tenant_id,1);assert.equal(body[module==='seo'?'site_id':'project_id'],module==='seo'?9:10);
  assert.match(body.request_id,/^[a-f0-9-]{36}$/);assert.equal(body.mode,'initial');
 });
 test(module+' AI call requires fresh capabilities and a writable proposal',async()=>{
  for(const change of [r=>delete r.capabilities,r=>r.allowed_actions=[],r=>r.capabilities.ai_planning.can_generate=false,r=>r.workflow.ai_run={state:'unknown'},r=>r.workflow.ai_run={state:'running'}]){
   const f=fixture(module);change(f.row);await f.client.list();await assert.rejects(()=>f.client.propose(20),/AI_PLANNING_UNAVAILABLE/);assert.equal(f.calls.length,1);
  }
 });
 test(module+' uncertain or mismatched AI replies cannot be resent from stale read state',async()=>{
  for(const kind of ['loss','nonce']){
   const f=fixture(module);await f.client.list();if(kind==='loss')f.lose();else f.wrongNonce();
   await assert.rejects(()=>f.client.propose(20),/WRITE_OUTCOME_UNKNOWN/);
   await assert.rejects(()=>f.client.propose(20),/AI_PLANNING_UNAVAILABLE/);assert.equal(f.calls.length,2);
  }
 });
 test(module+' late AI proposal cannot enter another account or project context',async()=>{
  const f=fixture(module);await f.client.list();let release;f.hold(new Promise(r=>release=r));
  const pending=f.client.propose(20);f.setContext({userId:8,revision:2});release();await assert.rejects(()=>pending,/CONTEXT_CHANGED/);
 });
}
test('focused onsite links accept only one safe positive task ID',()=>{
 assert.equal(onsiteTaskId('?onsite_task_id=77'),77);assert.equal(onsiteTaskId('?tenant_id=1'),null);
 for(const query of ['?onsite_task_id=0','?onsite_task_id=1&onsite_task_id=2','?onsite_task_id=1e3','?onsite_task_id=9007199254740991'])assert.throws(()=>onsiteTaskId(query),/INVALID_ONSITE_TASK/);
});
test('customer status never claims effect gains, exposes unavailable writes, and escapes AI explanations',()=>{
 const f=fixture();f.row.workflow.ai_proposal={summary:'<script>attack()</script>',items:[{id:'a',reason:'<img src=x onerror=attack()>',source_refs:['事实 #2']}]};
 const html=onsiteView({items:[f.row],can_create:false},f.row,false);
 assert(html.includes('官网自动修改暂未接入'));assert(html.includes('搜索收录、排名和 AI 引用效果分别记录'));
 assert(!html.includes('<script>'));assert(!html.includes('<img src=x'));assert(html.includes('&lt;script&gt;'));
 f.row.allowed_actions=[];assert(!onsiteView({items:[f.row],can_create:false},f.row,false).includes('data-action="onsite-ai-proposal"'));
 f.row.workflow.phase='done';assert(onsiteTaskStatus(f.row).next.includes('后续观测'));
});
for(const module of ['seo','geo']){
 test(module+' host denies customer AI writes and foreign scope or injected body fields',async()=>{
  for(const role of ['view','edit']){
   const calls=[],session={token:'fixture',userId:7,tenantId:1,siteId:9,projectId:10,revision:1};
   const fetchImpl=async(url,opt)=>{calls.push({url,opt});const p=new URL(url).pathname;
    const data=p.endsWith('/me')?{user:{id:7,tenant_id:null,permissions:{'seo.site':role,'seo.content':role,'geo.assets':role,'geo.content':role}}}:
     p.endsWith('/modules')?{tenant_id:null,modules:[{module_code:module,available:true}]}:
     p.endsWith('/tenants')?{module,tenants:[{id:1}]}:
     p.endsWith('/sites')?{tenant_id:1,selection_policy:{selectable_statuses:['active']},sites:[{id:9,status:'active'}]}:
     p.endsWith('/projects')?{projects:[{id:10,tenant_id:1,status:'active'}]}:{ok:true};
    return {ok:true,status:200,json:async()=>data};};
   const factory=module==='seo'?createHostSessionAdapter:createGeoHostAdapter;
   const host=factory({origin:'https://scoped.test',getSession:()=>session,fetchImpl});await host.initialize();
   const path=`/api/v1/${module}/workbench/onsite-tasks/20/ai-proposal`;
   const body={tenant_id:1,[module==='seo'?'site_id':'project_id']:module==='seo'?9:10,expected_revision:3,request_id:crypto.randomUUID(),mode:'initial'};
   if(role==='view')await assert.rejects(()=>host.transport(path,{method:'POST',body:JSON.stringify(body)}),/PERMISSION_DENIED/);
   else{
    for(const extra of [{tenant_id:2},{target_url:'https://foreign.test'},{api_key:'injected'},{project_id:30,site_id:30}])
     await assert.rejects(()=>host.transport(path,{method:'POST',body:JSON.stringify({...body,...extra})}),/SCOPE_MISMATCH|BODY_DENIED/);
    await host.transport(path,{method:'POST',body:JSON.stringify(body)});
   }
   assert.equal(calls.length,role==='edit'?5:4);
   const query=`tenant_id=1&${module==='seo'?'site_id=9':'project_id=10'}`;
   const readPath=`/api/v1/${module}/workbench/onsite-tasks/20/ai-requests/${body.request_id}`;
   const count=calls.length;
   for(const denied of [readPath+'?'+query.replace('tenant_id=1','tenant_id=2'),readPath+'?'+query+'&before_id=20',
     readPath.replace(body.request_id,'not-a-uuid')+'?'+query,readPath+'?'+query+'&api_key=injected'])
    await assert.rejects(()=>host.transport(denied),/SCOPE_MISMATCH|QUERY_DENIED|ROUTE_DENIED/);
   assert.equal(calls.length,count);
   await host.transport(readPath+'?'+query);assert.equal(calls.length,count+1);host.dispose();
  }
 });
}
