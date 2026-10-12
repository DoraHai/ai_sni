import test from 'node:test';
import assert from 'node:assert/strict';
import {createPlatformConsoleClient} from './js/platform-console-client.mjs';
import {validateAutomationHealth,automationReadState} from './js/platform-automation-health.mjs';
import {renderAutomationOps,automationScopePath,automationNotifications} from './js/platform-automation-ops-view.mjs';
import {healthFixture} from './tests/platform-automation-fixture.mjs';
const admin={id:7,tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
const snapshot={schema:1,mode:'read_only_inventory',sources:{},costs:{}};
const response=(data,status=200)=>({ok:status===200,status,json:async()=>data});
function setup(overrides={}){
  const session={user:admin,token:'fixture-token',authRevision:0,refreshUser(u){this.user=u;this.authRevision++;},logout(){this.user=null;this.token='';this.authRevision++;}};
  const calls=[];let user=admin,healthStatus=200;
  const client=createPlatformConsoleClient({session,fetchImpl:async(path,options)=>{
    calls.push({path,options});
    if(path.endsWith('/me'))return response({user});
    if(path.endsWith('/automation-health'))return overrides.health?.(path,options,session)||response(healthFixture(path.includes('/seo/')?'seo':'geo'),healthStatus);
    return response(snapshot);
  }});
  return {session,calls,client,user(u){user=u;},status(s){healthStatus=s;}};
}
const helpers={card:(title,body,note='')=>`<h2>${title}</h2>${body}<p>${note}</p>`,
  table:(headers,rows)=>headers.join('|')+rows.flat().join('|'),time:s=>s||'暂无记录',
  tenant:id=>'客户 '+id,now:Date.parse('2026-10-11T02:00:11Z')};
const display=data=>renderAutomationOps({...helpers,state:{modules:{seo:{state:'available',data}}}});

test('health reads verify fresh global named identity and use only fixed same-origin GET routes',async()=>{
  const s=setup();await s.client.initialize();s.calls.length=0;
  for(const module of ['seo','geo'])assert.equal((await s.client.automationHealth(module)).module,module);
  assert.deepEqual(s.calls.map(c=>c.path),['/api/v1/auth/me','/api/v1/seo/workbench/automation-health','/api/v1/auth/me','/api/v1/geo/workbench/automation-health']);
  for(const {options:o} of s.calls){assert.equal(o.method,'GET');assert.equal(o.cache,'no-store');assert.equal(o.credentials,'omit');assert.equal(o.redirect,'error');assert.equal(o.headers.Authorization,'Bearer fixture-token');assert(!o.body);}
  for(const module of ['sem','https://outside.test','seo?tenant_id=2','__proto__',null])await assert.rejects(s.client.automationHealth(module),{code:'CONSOLE_INVALID_QUERY'});
  assert.equal(s.calls.length,4);
});
test('uninitialized and revoked identities cannot fetch global health',async()=>{
  const s=setup();await assert.rejects(s.client.automationHealth('seo'),{code:'CONSOLE_NOT_AUTHORIZED'});assert.equal(s.calls.length,0);
  for(const user of [{...admin,tenant_id:1},{...admin,id:8},{...admin,id:null},{...admin,permissions:{'settings.accounts':'view','settings.customers':'edit'}}]){
    s.user(admin);await s.client.initialize();s.calls.length=0;s.user(user);
    await assert.rejects(s.client.automationHealth('seo'),{code:'CONSOLE_FORBIDDEN'});
    assert.deepEqual(s.calls.map(c=>c.path),['/api/v1/auth/me']);assert.equal(s.client.getIdentity(),null);
  }
});
test('401 logs out and 403 invalidates platform identity',async()=>{
  for(const status of [401,403]){
    const s=setup();await s.client.initialize();s.status(status);
    await assert.rejects(s.client.automationHealth('seo'),{code:status===401?'CONSOLE_EXPIRED':'CONSOLE_FORBIDDEN'});
    assert.equal(s.client.getIdentity(),null);if(status===401)assert.equal(s.session.token,'');
  }
});
test('late health responses are rejected after logout, token or identity changes and invalidate',async()=>{
  for(const change of [s=>s.session.logout(),s=>s.session.token='changed',s=>s.session.user={...admin,tenant_id:2},s=>s.client.invalidate()]){
    let release;const s=setup({health:()=>({ok:true,status:200,json:()=>new Promise(r=>release=r)})});await s.client.initialize();
    const pending=s.client.automationHealth('seo');while(!release)await new Promise(r=>setImmediate(r));change(s);release(healthFixture());
    await assert.rejects(pending,{code:'CONSOLE_STALE'});
  }
});
test('missing endpoint and transport errors retain distinct states without fake zero counts',async()=>{
  const s=setup();await s.client.initialize();s.status(404);
  await assert.rejects(s.client.automationHealth('seo'),e=>automationReadState(e)==='not_deployed');
  for(const state of ['not_deployed','schema_pending','forbidden','invalid','unavailable','timeout','unknown']){
    const text=renderAutomationOps({...helpers,state:{modules:{seo:{state},geo:{state:'unknown'}}}});
    assert.match(text,/未知/);assert.doesNotMatch(text,/\|0\||全部服务正常/);
  }
  assert.equal(automationReadState({name:'TimeoutError'}),'timeout');
});
test('global module identity, schema and tenant boundaries are mandatory',()=>{
  for(const change of [d=>d.schema=2,d=>d.module='geo',d=>d.scope.kind='tenant',d=>d.scope.tenant_id=1,d=>delete d.scope.tenant_id,
    d=>d.as_of='yesterday',d=>d.counts.projects=-1,d=>d.counts.runs=true,d=>delete d.counts.unknown_cost,
    d=>d.rows[0].tenant_id=0,d=>d.rows[0].scope_id='9',d=>d.rows.push({...d.rows[0]}),d=>d.rows=Array(51).fill(d.rows[0])]){
    const d=healthFixture();change(d);assert.throws(()=>validateAutomationHealth(d,'seo'),{code:'CONSOLE_INVALID_AUTOMATION_HEALTH'});
  }
});
test('pending schema does not expose submitted bogus metrics or sensitive fields',()=>{
  const d={...healthFixture(),state:'schema_pending',api_key:'never-secret'};
  const safe=validateAutomationHealth(d,'seo');assert(!safe.counts);assert(!safe.rows);assert(!safe.api_key);
  assert.doesNotMatch(display(safe),/\|3\||never-secret/);assert.match(display(safe),/执行结构尚未就绪/);
});
test('null counts remain unknown, real zero stays visible and limited coverage stays explicit',()=>{
  const d=healthFixture();d.counts.projects=0;d.truncated=true;
  const text=display(validateAutomationHealth(d,'seo'));assert.match(text,/\|0\|4\|1\|未知/);assert.match(text,/前 50/);
  assert.match(text,/SEM 本轮未接入 AI 接管/);assert.doesNotMatch(text,/SEM.*线上.*关闭/);
});
test('fresh local worker evidence never claims fleet health or uses empty queue as heartbeat',()=>{
  const d=validateAutomationHealth(healthFixture(),'seo');assert.match(display(d),/采样时当前进程有心跳/);
  assert.match(display(d),/当前进程心跳不能证明全部服务正常/);
  for(const change of [d=>d.worker.verified=false,d=>d.worker.evidence=null,d=>d.worker.evidence.scope='fleet',
    d=>d.worker.last_tick_at='2026-10-11T01:00:00Z',d=>d.as_of='2026-10-11T01:00:10Z',d=>d.as_of='2026-10-12T01:00:10Z']){
    const copy=structuredClone(d);change(copy);copy.queue={state:'available',queued:0,running:0,unknown:0};
    assert.doesNotMatch(display(copy),/采样时当前进程有心跳/);assert.match(display(copy),/存活尚未验证/);
  }
});
test('scope links bind exact module, tenant and scope and never use returned URLs or arbitrary strings',()=>{
  const row={tenant_id:2,scope_id:19,url:'https://outside.test',href:'javascript:bad()'};
  assert.equal(automationScopePath('seo',row),'/customer-workbench/?tenant_id=2&site_id=19');
  assert.equal(automationScopePath('geo',row),'/customer-workbench/?module=geo&tenant_id=2&project_id=19');
  assert.equal(automationScopePath('seo',{...row,tenant_id:null}),null);assert.equal(automationScopePath('sem',row),null);
  const d=healthFixture();Object.assign(d.rows[0],{project_state:'<script>bad()</script>',message:'never-secret',url:row.url});
  const safe=validateAutomationHealth(d,'seo');assert.doesNotMatch(display(safe),/<script>|never-secret|outside.test/);
});
test('safe system hints are derived only from readable actual counts and do not acknowledge or retry',()=>{
  const d=validateAutomationHealth(healthFixture(),'seo');const notes=automationNotifications({modules:{seo:{state:'available',data:d}}});
  assert.equal(notes.length,1);assert.match(notes[0].message,/SEO 待人工项目 1 个/);
  assert.deepEqual(automationNotifications({modules:{seo:{state:'not_deployed',data:d}}}),[]);
  assert.doesNotMatch(display(d),/<form|data-pc="(?:start|pause|takeover|retry)"|已处理/);
});
test('confirmed schema1 accepts a null current run and does not turn unattached worker and queues into healthy zeros',()=>{
  const d=healthFixture();d.rows[0].run_state=null;d.queue={state:'not_connected',queued:0,running:0,unknown:0};
  d.worker={state:'unverified',verified:false,last_tick_at:null,evidence:null};d.overall='healthy';
  const text=display(validateAutomationHealth(d,'seo'));assert.match(text,/无本次运行/);assert.match(text,/未知 \/ 未知 \/ 未知/);
  assert.match(text,/存活尚未验证/);assert.doesNotMatch(text,/healthy|采样时当前进程有心跳/);
});
test('database 503 stays unavailable and provider or database diagnostic bodies never reach the UI',async()=>{
  const s=setup({health:()=>response({detail:{code:'database_unavailable',message:'never-secret'}},503)});await s.client.initialize();
  await assert.rejects(s.client.automationHealth('seo'),e=>automationReadState(e)==='unavailable'&&!e.message.includes('never-secret'));
  assert.doesNotMatch(renderAutomationOps({...helpers,tenant:()=>'<img src=x onerror=bad()>',state:{modules:{seo:{state:'available',data:healthFixture()}}}}),/<img/);
});
test('an invalid JSON health response is distinguished from a transport outage',async()=>{
  const s=setup({health:()=>({ok:true,status:200,json:async()=>{throw new SyntaxError('never-secret');}})});await s.client.initialize();
  await assert.rejects(s.client.automationHealth('seo'),e=>automationReadState(e)==='invalid'&&!e.message.includes('never-secret'));
});
