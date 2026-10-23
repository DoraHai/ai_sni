import test from 'node:test';
import assert from 'node:assert/strict';
import {createPlatformConsoleClient,isPlatformAdmin} from './js/platform-console-client.mjs';
const admin={id:7,tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
const snapshot={schema:1,mode:'read_only_inventory',sources:{},costs:{actual_amount:null}};
const response=(body,status=200)=>({ok:status===200,status,json:async()=>body});
const session=user=>({user,token:'test-token',authRevision:0,refreshUser(u){this.user=u;this.authRevision++;},logout(){this.token='';this.user=null;this.authRevision++;}});

test('unlaunched automation skips missing health routes and still checks administrator permission',async()=>{
 const paths=[],s=session(admin);let permitted=true;
 const client=createPlatformConsoleClient({session:s,fetchImpl:async path=>{paths.push(path);return response(path.endsWith('/me')?{user:permitted?admin:{...admin,tenant_id:1}}:snapshot);}});
 await assert.rejects(client.automationHealth('seo'),{code:'CONSOLE_NOT_AUTHORIZED'});assert.deepEqual(paths,[]);
 await client.initialize();
 for(const module of ['seo','geo'])await assert.rejects(client.automationHealth(module),{code:'CONSOLE_AUTOMATION_NOT_LAUNCHED'});
 assert.deepEqual(paths,['/api/v1/auth/me','/api/v1/admin/console/snapshot','/api/v1/auth/me','/api/v1/auth/me']);
 permitted=false;await assert.rejects(client.automationHealth('seo'),{code:'CONSOLE_FORBIDDEN'});assert.equal(client.getIdentity(),null);
 assert(!paths.some(path=>path.endsWith('/automation-health')));
});

test('console requires an unbound named identity with both management permissions',()=>{
  assert(isPlatformAdmin(admin));
  for(const u of [null,{...admin,id:null},{...admin,tenant_id:1},{...admin,tenant_id:undefined},
    {...admin,permissions:{'settings.accounts':'edit'}},{...admin,permissions:{'settings.accounts':'view','settings.customers':'edit'}}])assert(!isPlatformAdmin(u));
});
test('server identity is checked before fetching the global snapshot',async()=>{
  const paths=[],s=session(admin);
  const client=createPlatformConsoleClient({session:s,fetchImpl:async path=>{paths.push(path);return response({user:{...admin,tenant_id:1}});}});
  await assert.rejects(client.initialize(),{code:'CONSOLE_FORBIDDEN'});
  assert.deepEqual(paths,['/api/v1/auth/me']);
});
test('reads only the fixed global snapshot and account catalog routes and authenticates without keys',async()=>{
  const calls=[],s=session(admin);
  const client=createPlatformConsoleClient({session:s,fetchImpl:async(path,o)=>{calls.push({path,o});return response(path.endsWith('/me')?{user:admin}:snapshot);}});
  assert.equal((await client.initialize()).data,snapshot);
  assert.deepEqual(calls.map(c=>c.path),['/api/v1/auth/me','/api/v1/admin/console/snapshot']);
  for(const {o} of calls){assert.equal(o.method,'GET');assert.equal(o.cache,'no-store');assert.equal(o.credentials,'omit');assert.equal(o.redirect,'error');assert.equal(o.headers.Authorization,'Bearer test-token');assert(!('X-API-Key' in o.headers));}
});
test('late global data is rejected after session changes, including body parsing',async()=>{
  const s=session(admin);let release;
  const client=createPlatformConsoleClient({session:s,fetchImpl:async path=>path.endsWith('/me')?response({user:admin}):
    {ok:true,status:200,json:()=>new Promise(r=>release=r)}});
  const pending=client.initialize();while(!release)await new Promise(r=>setTimeout(r,1));
  s.token='different-token';release(snapshot);
  await assert.rejects(pending,{code:'CONSOLE_STALE'});
});
test('expiry clears the canonical session and permission denial invalidates authorization',async()=>{
  for(const status of [401,403]){
    const s=session(admin);let expired=0;
    const client=createPlatformConsoleClient({session:s,onExpired:()=>expired++,fetchImpl:async path=>path.endsWith('/me')?response({user:admin}):response({},status)});
    await assert.rejects(client.initialize(),{code:status===401?'CONSOLE_EXPIRED':'CONSOLE_FORBIDDEN'});
    assert.equal(client.getIdentity(),null);assert.equal(expired,status===401?1:0);
    if(status===401)assert.equal(s.token,'');
  }
});

test('configuration writes have fresh permission preflight and one fixed authenticated route',async()=>{
  const s=session(admin),calls=[];let permitted=true;
  const client=createPlatformConsoleClient({session:s,fetchImpl:async(path,o)=>{
    calls.push({path,o});return response(path.endsWith('/me')?{user:permitted?admin:{...admin,tenant_id:1}}:path.endsWith('/controls')?{revision:1}:snapshot);
  }});
  await client.initialize();
  const data={request_id:'id',kind:'provider',key:'provider:test',expected_revision:0,value:{enabled:false}};
  assert.equal((await client.change(data)).revision,1);
  assert.deepEqual(calls.slice(-2).map(c=>[c.path,c.o.method]),[['/api/v1/auth/me','GET'],['/api/v1/admin/console/controls','POST']]);
  const write=calls.at(-1).o;assert.equal(write.credentials,'omit');assert.equal(write.headers.Authorization,'Bearer test-token');
  assert.deepEqual(JSON.parse(write.body),data);
  permitted=false;const before=calls.length;
  await assert.rejects(client.change(data),{code:'CONSOLE_FORBIDDEN'});
  assert.equal(calls.length,before+1);assert.equal(client.getIdentity(),null);
});

test('identity changes during write preflight cancel the write',async()=>{
  const s=session(admin);let change=false,writes=0;
  const client=createPlatformConsoleClient({session:s,fetchImpl:async(path,o)=>{
    if(o.method==='POST')writes++;
    if(change&&path.endsWith('/me'))s.token='new-token';
    return response(path.endsWith('/me')?{user:admin}:snapshot);
  }});
  await client.initialize();change=true;
  await assert.rejects(client.change({}),{code:'CONSOLE_STALE'});assert.equal(writes,0);
});

test('history filters stay on fixed routes and CSV export checks current permission',async()=>{
  const s=session(admin),calls=[];let permitted=true;
  const client=createPlatformConsoleClient({session:s,fetchImpl:async(path,o)=>{
    calls.push({path,o});
    if(path.endsWith('/me'))return response({user:permitted?admin:{...admin,tenant_id:1}});
    if(path.includes('/usage/export'))return new Response('\ufeffid,estimated_amount\nfixture,\n',{headers:{'Content-Type':'text/csv; charset=utf-8'}});
    if(path.includes('/usage?'))return response({state:'available',rows:[],total:0});
    return response(snapshot);
  }});
  await client.initialize();
  assert.equal((await client.usage({tenant_id:1,endpoint:'provider.test/v1?name=value'})).total,0);
  const query=calls.at(-1).path;assert.equal(new URL(query,'https://test').searchParams.get('endpoint'),'provider.test/v1?name=value');
  assert.equal(new URL(query,'https://test').pathname,'/api/v1/admin/console/usage');
  await assert.rejects(client.usage({url:'https://outside.test'}),{code:'CONSOLE_INVALID_QUERY'});
  const csv=await client.exportUsage({from:'2026-10-01',to:'2026-10-10'});
  assert.match(await csv.text(),/fixture,/);
  assert.deepEqual(calls.slice(-2).map(c=>c.path.split('?')[0]),['/api/v1/auth/me','/api/v1/admin/console/usage/export']);
  permitted=false;const before=calls.length;
  await assert.rejects(client.exportUsage({}),{code:'CONSOLE_FORBIDDEN'});assert.equal(calls.length,before+1);
});

test('incident and supplier writes require fresh identity and discard stale downloads',async()=>{
  const s=session(admin);let permitted=true,hold=false,release;const writes=[];
  const client=createPlatformConsoleClient({session:s,fetchImpl:async(path,o)=>{
    if(path.endsWith('/me'))return response({user:permitted?admin:{...admin,tenant_id:1}});
    if(path.endsWith('/operations')){writes.push(JSON.parse(o.body));return response({revision:1});}
    if(path.includes('/usage/export'))return {ok:true,status:200,headers:new Headers({'Content-Type':'text/csv'}),blob:()=>new Promise(r=>release=r)};
    return response(snapshot);
  }});
  await client.initialize();await client.operation({kind:'alert',key:'fixture'});assert.equal(writes.length,1);
  const download=client.exportUsage({});while(!release)await new Promise(r=>setTimeout(r,1));
  client.invalidate();release(new Blob(['private-history']));await assert.rejects(download,{code:'CONSOLE_STALE'});
  await client.initialize();permitted=false;
  await assert.rejects(client.operation({kind:'supplier'}),{code:'CONSOLE_FORBIDDEN'});assert.equal(writes.length,1);
});

test('manual usage review checks fresh admin identity and coalesces a lost submission without retry',async()=>{
 const s=session(admin),calls=[];let permitted=true;
 const client=createPlatformConsoleClient({session:s,fetchImpl:async(path,o)=>{
  calls.push({path,o});
  if(path.endsWith('/me'))return response({user:permitted?admin:{...admin,tenant_id:1}});
  if(/^\/api\/v1\/admin\/console\/usage\/[0-9a-f-]+\/review$/.test(path))return response({schema:1,state:'available',row:{id:data.event_id,review_version:data.expected_version,state:data.expected_state,can_review:true}});
  if(path.endsWith('/usage/review'))throw Error('response lost');
  return response(snapshot);
 }});
 await client.initialize();
 const data={request_id:crypto.randomUUID(),event_id:crypto.randomUUID(),expected_version:0,expected_state:'unknown'};
 await assert.rejects(client.reviewUsage(data),{code:'CONSOLE_REVIEW_OUTCOME_UNKNOWN'});
 await assert.rejects(client.reviewUsage(data),{code:'CONSOLE_REVIEW_OUTCOME_UNKNOWN'});
 assert.equal(calls.filter(c=>c.o.method==='POST').length,1);
 assert.equal(calls.at(-1).path,'/api/v1/admin/console/usage/review');
 assert.equal(calls.at(-1).o.headers.Authorization,'Bearer test-token');
 assert.deepEqual(JSON.parse(calls.at(-1).o.body),data);
 permitted=false;const before=calls.length;
 await assert.rejects(client.reviewUsage({...data,request_id:crypto.randomUUID()}),{code:'CONSOLE_FORBIDDEN'});
 assert.equal(calls.length,before+1);assert.equal(client.getIdentity(),null);
});

test('late or mismatched review receipts cannot be shown as a confirmed settlement',async()=>{
 const s=session(admin),event_id=crypto.randomUUID();let hold=false,release;
 const client=createPlatformConsoleClient({session:s,fetchImpl:async(path)=>{
  if(path.endsWith('/me'))return response({user:admin});
  if(/^\/api\/v1\/admin\/console\/usage\/[0-9a-f-]+\/review$/.test(path))return response({schema:1,state:'available',row:{id:event_id,review_version:0,state:'unknown',can_review:true}});
  if(path.endsWith('/usage/review'))return hold?{ok:true,status:200,json:()=>new Promise(r=>release=r)}:
   response({schema:1,state:'available',row:{id:crypto.randomUUID(),review_version:1}});
  return response(snapshot);
 }});
 await client.initialize();
 const payload={request_id:crypto.randomUUID(),event_id,expected_version:0,expected_state:'unknown'};
 await assert.rejects(client.reviewUsage(payload),{code:'CONSOLE_REVIEW_OUTCOME_UNKNOWN'});
 hold=true;const pending=client.reviewUsage({...payload,request_id:crypto.randomUUID()});
 while(!release)await new Promise(r=>setTimeout(r,1));s.token='changed';
 release({schema:1,state:'available',row:{id:event_id,review_version:1}});
 await assert.rejects(pending,{code:'CONSOLE_STALE'});
});


test('account catalog enriches full authorized clients and fails closed on permission changes',async()=>{
  const snap={...snapshot,sources:{users:{rows:[{id:8,tenant_id:1}]}}};
  let denied=false;
  const client=createPlatformConsoleClient({session:session(admin),fetchImpl:async path=>response(path.endsWith('/me')?{user:admin}:path==='/api/v1/users'?(denied?{}:{users:[{id:8,is_advisor:true,tenant_ids:[1,2],default_tenant_id:2}]}):structuredClone(snap),denied&&path==='/api/v1/users'?403:200)});
  const result=await client.initialize();
  assert.deepEqual(result.data.sources.users.rows[0].tenant_ids,[1,2]);
  assert.equal(result.data.sources.users.rows[0].default_tenant_id,2);
  denied=true;await assert.rejects(client.initialize(),{code:'CONSOLE_FORBIDDEN'});
});

import {platformTime,moduleAvailability,accountScope} from './js/platform-display.mjs';
import {customerErrorLabel} from './js/customer-error.mjs';
test('trial services use expiry and truncated counts are explicitly current-list counts',()=>{
 const source={state:'available',truncated:false,rows:[{module_code:'seo',status:'trial',expires_at:'2026-10-24'},{module_code:'seo',status:'active',expires_at:null},{module_code:'seo',status:'trial',expires_at:'2026-10-23'},{module_code:'seo',status:'disabled'}]};
 assert.equal(moduleAvailability(source,'seo','2026-10-24'),'2');
 assert.equal(moduleAvailability({...source,truncated:true},'seo','2026-10-24'),'当前清单 2');
 assert.equal(moduleAvailability({...source,state:'unavailable'},'seo','2026-10-24'),'待接入');
});
test('account scope shows all grants and default or explicitly marks incomplete scope',()=>{
 const tenant=id=>({1:'客户甲',2:'客户乙'}[id]||'客户 '+id),user={is_advisor:true,tenant_id:1,tenant_ids:[1,2],default_tenant_id:2};
 assert.equal(accountScope(user,[],tenant),'客户甲、客户乙（默认：客户乙）');
 assert.match(accountScope({...user,tenant_ids:undefined},[],tenant),/授权范围未完整读取/);
});
test('platform timestamps are Beijing time for zoned and backend naive UTC values',()=>{
 for(const stamp of ['2026-10-23T16:05:00Z','2026-10-23T16:05:00','2026-10-24T00:05:00+08:00'])assert.equal(platformTime(stamp),'2026/10/24 00:05（北京时间）');
 assert.equal(platformTime(null),'暂无记录');assert.equal(platformTime('bad'),'时间待核对');
});
test('known customer error codes have Chinese guidance and safe diagnostic codes',()=>{
 assert.match(customerErrorLabel(Error('SCOPE_MISMATCH')),/超出当前客户或网站范围.*SCOPE_MISMATCH/);
 assert.match(customerErrorLabel({code:'AUTH_EXPIRED'}),/重新登录/);
 assert.equal(customerErrorLabel(Error('arbitrary response body')),'');
});

import {executionDetailView} from './js/seo-execution-view.mjs';
test('monthly report generation time crosses the Beijing calendar boundary',()=>{
 for(const stamp of ['2026-10-23T16:05:00Z','2026-10-23T16:05:00','2026-10-24T00:05:00+08:00']){
  const html=executionDetailView({id:104,action_type:'monthly_report',params:{report:{month:'2026-10',generated_at:stamp,missing:[]}},allowed_actions:{}},104,false);
  assert.match(html,/生成 2026\/10\/24 00:05（北京时间）/);
 }
 for(const [stamp,label] of [[null,'暂无记录'],['bad','时间待核对']]){
  const html=executionDetailView({id:104,action_type:'monthly_report',params:{report:{generated_at:stamp}},allowed_actions:{}},104,false);
  assert(html.includes('生成 '+label+' ·'));
 }
});

test('execution AI finish and history timestamps normalize backend UTC for customers',()=>{
 for(const stamp of ['2026-10-23T16:05:00Z','2026-10-23T16:05:00','2026-10-24T00:05:00+08:00']){
  const html=executionDetailView({id:101,action_type:'content_delivery',params:{ai_draft:{finished_at:stamp},history:[{at:stamp,phase:'awaiting_confirmation'}]},allowed_actions:{}},101,false);
  assert.match(html,/完成时间 2026\/10\/24 00:05（北京时间）/);
  assert.match(html,/<li>2026\/10\/24 00:05（北京时间） · 待准确版本确认/);
 }
});
