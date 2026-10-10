import test from 'node:test';
import assert from 'node:assert/strict';
import {createGeoHostAdapter} from './js/geo-host-session-adapter.mjs';
import {createOnsiteClient} from './js/onsite-client.mjs';
import {entryScope} from './js/workbench-entry.mjs';

test('GEO entry accepts only an explicit unambiguous project scope',()=>{
  assert.equal(entryScope('?module=geo&tenant_id=1&project_id=10').invalid,false);
  for(const q of ['?module=geo&tenant_id=1','?module=geo&tenant_id=1&project_id=10&project_id=11','?module=geo&tenant_id=1&project_id=10&site_id=9'])assert.equal(entryScope(q).invalid,true);
});
function fixture(){
 let session={token:'fixture',userId:7,tenantId:1,projectId:10,revision:1},held=null,role='edit';const calls=[];
 const host=createGeoHostAdapter({origin:'https://scope.example',getSession:()=>session,fetchImpl:async(url,opt)=>{
  calls.push({url,opt});const p=new URL(url).pathname;
  const data=p.endsWith('/me')?{user:{id:7,tenant_id:null,permissions:{'geo.assets':role,'geo.content':role}}}:p.endsWith('/modules')?{tenant_id:null,modules:[{module_code:'geo',available:true}]}:p.endsWith('/tenants')?{tenants:[{id:1,name:'客户'}]}:p.endsWith('/projects')?{projects:[{id:10,tenant_id:1,name:'项目',status:'active'}]}: {value:true};
  if(held)await held;
  return {ok:true,status:200,async json(){return data;}};
 }});
 return {host,calls,setSession:s=>session={...session,...s},hold:p=>held=p,setRole:r=>role=r};
}
test('GEO host verifies entitlement, tenant and project separately, then rejects foreign routes and bodies',async()=>{
 const f=fixture();await f.host.initialize();
 assert.equal(f.host.getContext().projectId,10);
 for(const path of ['/api/v1/seo/workbench/onsite-tasks?tenant_id=1&site_id=10','/api/v1/geo/workbench/onsite-tasks?tenant_id=2&project_id=10','/api/v1/geo/workbench/onsite-tasks?tenant_id=1&project_id=11'])await assert.rejects(()=>f.host.transport(path),/DENIED|MISMATCH/);
 await assert.rejects(()=>f.host.transport('/api/v1/geo/workbench/onsite-tasks',{method:'POST',body:JSON.stringify({tenant_id:1,project_id:11})}),/SCOPE_MISMATCH/);
 assert.equal(f.calls.length,4);
});
test('GEO late responses are discarded when the canonical session scope changes',async()=>{
 const f=fixture();await f.host.initialize();let release;f.hold(new Promise(r=>release=r));
 const pending=f.host.transport('/api/v1/geo/workbench/onsite-tasks?tenant_id=1&project_id=10');
 await new Promise(r=>setImmediate(r));f.setSession({projectId:11,revision:2});release();
 await assert.rejects(()=>pending,/CONTEXT_CHANGED/);assert.equal(f.host.getContext().connected,false);
});
test('GEO customer cannot inject a write even after read authorization',async()=>{
 const f=fixture();f.setRole('view');await f.host.initialize();
 await assert.rejects(()=>f.host.transport('/api/v1/geo/workbench/onsite-tasks',{method:'POST',body:JSON.stringify({tenant_id:1,project_id:10})}),/PERMISSION_DENIED/);
 assert.equal(f.calls.length,4);
});
test('onsite client binds the read revision and consumes uncertain writes without resending',async()=>{
 let context={connected:true,tenantId:1,projectId:10,userId:7,revision:1},calls=[],loss=false;
 const row={id:20,module:'geo',tenant_id:1,scope_id:10,workflow:{module:'geo',revision:3,items:[]},allowed_actions:['approve']};
 const client=createOnsiteClient({module:'geo',getContext:()=>context,transport:async(path,options)=>{
  calls.push({path,options});if(loss)throw Error('lost');return {ok:true,status:200,json:async()=>options.method==='GET'?{module:'geo',tenant_id:1,scope_id:10,can_create:true,items:[row]}:row};
 }});
 await client.list();loss=true;
 await assert.rejects(()=>client.act(20,'approve',{note:'审核'}),/WRITE_OUTCOME_UNKNOWN/);
 const body=JSON.parse(calls[1].options.body);assert.equal(body.expected_revision,3);assert.equal(body.project_id,10);
 await assert.rejects(()=>client.act(20,'approve',{note:'重发'}),/ACTION_EXPIRED/);
 assert.equal(calls.length,2);
});

