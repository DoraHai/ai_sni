import test from 'node:test';
import assert from 'node:assert/strict';
import {createAdvisorAutomationClient} from './js/advisor-automation-client.mjs';
import {validateAutomationProject,validateAutomationRun,validateAutomationEvents,validateAutomationProjects,validateAutomationHistory} from './js/advisor-automation-contract.mjs';
import {advisorRunView,automationTaskLink} from './js/advisor-run-view.mjs';
import {createAdvisorAutomationPanel} from './js/advisor-automation-panel.mjs';

import {runId,requestId,scope,configuration,project,run,eventPage} from './tests/advisor-automation-fixture.mjs';
function fixture(){
  const session={token:'fixture-token',user:{id:7,tenant_id:null,permissions:{'seo.site':'edit','seo.content':'edit','seo.keywords':'view'}},authRevision:1,logout(){this.token='';this.user=null;this.authRevision++;}},calls=[];
  let currentProject=project({configuration,allowed_actions:['start']}),lost=false,status=200;
  const client=createAdvisorAutomationClient({session,fetchImpl:async(path,options)=>{
    calls.push({path,options});let data;
    if(path.endsWith('/auth/me'))data={user:structuredClone(session.user)};
    else if(path.endsWith('/auth/modules'))data={tenant_id:session.user.tenant_id,modules:[{module_code:'seo',available:true}]};
    else if(options.method!=='GET'){if(lost)throw Error('lost response');currentProject={...currentProject,version:currentProject.version+1};data=currentProject;}
    else if(path.includes('/events?'))data=eventPage();
    else if(path.includes('/runs/'))data=run();
    else if(path.includes('/runs?'))data={schema:1,module:'seo',tenant_id:2,scope_id:19,items:[{id:runId,state:'running',started_at:'2026-10-11T00:00:00Z',finished_at:null}],next_before_run_id:null};
    else if(path.includes('/control?'))data=currentProject;
    else data={schema:1,module:'seo',items:[currentProject],next_before_scope_id:null};
    return {ok:status===200,status,json:async()=>structuredClone(data)};
  }});
  return {client,session,calls,project:()=>structuredClone(currentProject),setProject:value=>currentProject=value,lose:()=>lost=true,status:value=>status=value};
}
test('scope, model operations, schema capability and event cursor failures reject cross-project data',()=>{
  assert.throws(()=>validateAutomationProject(project({tenant_id:3}),scope),/CONTRACT/);
  assert.throws(()=>validateAutomationProject(project({state:'schema_pending'}),scope),/CONTRACT/);
  assert.throws(()=>validateAutomationProject(project({configuration:{...configuration,operations:['publish']}}),scope),/CONTRACT/);
  assert.throws(()=>validateAutomationRun({...run(),scope_id:20},scope,runId),/CONTRACT/);
  assert.throws(()=>validateAutomationRun(run({steps:[...run().run.steps,...run().run.steps]}),scope,runId),/CONTRACT/);
  assert.throws(()=>validateAutomationEvents({...eventPage(),next_after_id:2},scope,runId),/CONTRACT/);
  assert.throws(()=>validateAutomationEvents(eventPage(),scope,runId,{afterId:1}),/CONTRACT/);
  assert.throws(()=>validateAutomationEvents({...eventPage(),items:[{...eventPage().items[0],tenant_id:3}]},scope,runId),/CONTRACT/);
  assert.throws(()=>validateAutomationEvents({...eventPage(),items:[{...eventPage().items[0],scope_id:20}]},scope,runId),/CONTRACT/);
  assert.throws(()=>validateAutomationProjects({schema:1,module:'seo',items:[project()],next_before_scope_id:18},'seo'),/CONTRACT/);
});
test('reading progress and logs never starts AI and uses fixed same-origin scoped GETs',async()=>{
  const f=fixture();await f.client.initialize();await f.client.list('seo');await f.client.readControl(scope);await f.client.run(scope,runId);await f.client.events(scope,runId);await f.client.history(scope);await f.client.projectEvents(scope);
  assert(f.calls.every(call=>call.options.method==='GET'&&call.options.credentials==='omit'&&call.options.cache==='no-store'&&call.options.redirect==='error'));
  assert(f.calls.slice(3).every(call=>call.path.includes('tenant_id=2')));
  for(const badScope of [{...scope,module:'sem'},{...scope,scopeId:0},{...scope,tenantId:-1}])await assert.rejects(()=>f.client.readControl(badScope));
  await assert.rejects(()=>f.client.events(scope,runId,{afterId:-1}));assert(!f.calls.some(call=>call.path.includes('/tenants')));f.client.dispose();
});
test('project-wide configuration audit remains visible without a run and history cursors remain scoped',()=>{
  const pending=project({state:'schema_pending',capabilities:{schema_state:'pending',can_configure:false,can_control:false,available_operations:[]}});
  assert.equal(validateAutomationProject(pending,scope).state,'schema_pending');
  const configEvent={...eventPage(),run_id:null,items:[{...eventPage().items[0],run_id:null,code:'configuration_saved'}]};
  assert.equal(validateAutomationEvents(configEvent,scope,null).items[0].run_id,null);
  const history={schema:1,module:'seo',tenant_id:2,scope_id:19,items:[{id:runId,state:'ended',started_at:'2026-10-11T00:00:00Z',finished_at:'2026-10-11T00:01:00Z'}],next_before_run_id:null};
  assert.equal(validateAutomationHistory(history,scope).items[0].id,runId);
  assert.throws(()=>validateAutomationHistory({...history,tenant_id:3},scope),/CONTRACT/);
  assert.throws(()=>validateAutomationHistory(history,scope,{beforeRunId:runId}),/CONTRACT/);
});
test('control rereads the exact version and real permission, refusing stale or revoked writes before POST',async()=>{
  const f=fixture();await f.client.initialize();const original=f.project();f.setProject({...original,version:2});
  await assert.rejects(()=>f.client.act(scope,original,'start',requestId),/AUTOMATION_CONFLICT/);assert(!f.calls.some(call=>call.options.method==='POST'));
  f.session.user.permissions['seo.site']='view';await assert.rejects(()=>f.client.act(scope,f.project(),'start',requestId));assert(!f.calls.some(call=>call.options.method==='POST'));f.client.dispose();
});
test('a lost control receipt is uncertain and identical submissions never issue another POST',async()=>{
  const f=fixture();await f.client.initialize();f.lose();const original=f.project();
  await assert.rejects(()=>f.client.act(scope,original,'start',requestId),/AUTOMATION_WRITE_UNKNOWN/);
  await assert.rejects(()=>f.client.act(scope,original,'start',requestId),/AUTOMATION_WRITE_UNKNOWN/);
  assert.equal(f.calls.filter(call=>call.options.method==='POST').length,1);f.client.dispose();
});
test('configuration owner and finite dispatch count cannot be replaced by caller fields',async()=>{
  const f=fixture();await f.client.initialize();
  assert.throws(()=>f.client.saveConfiguration(scope,f.project(),{...configuration,owner_user_id:8},requestId));
  assert.throws(()=>f.client.saveConfiguration(scope,f.project(),{...configuration,limits:{max_dispatches_per_run:21}},requestId));
  assert.throws(()=>f.client.saveConfiguration(scope,f.project(),{...configuration,api_key:'forged'},requestId));
  await f.client.saveConfiguration(scope,f.project(),configuration,requestId);
  const write=f.calls.find(call=>call.options.method==='PUT'),body=JSON.parse(write.options.body);
  assert.equal(body.tenant_id,2);assert.equal(body.expected_version,1);assert.equal(body.configuration.owner_user_id,7);assert(!('Authorization' in body));f.client.dispose();
});
test('an identity switch between auth preflight stages cannot authorize an old user',async()=>{
  const f=fixture();let release,ready;const started=new Promise(resolve=>ready=resolve),held=new Promise(resolve=>release=resolve);
  const client=createAdvisorAutomationClient({session:f.session,fetchImpl:async(path)=>({ok:true,status:200,json:async()=>{
    if(path.endsWith('/me'))return {user:structuredClone(f.session.user)};
    ready();await held;return {tenant_id:null,modules:[{module_code:'seo',available:true}]};
  }})});
  const pending=client.initialize();await started;f.session.user={...f.session.user,id:8};f.session.authRevision++;release();
  await assert.rejects(()=>pending,/CONTEXT_CHANGED/);await assert.rejects(()=>client.list('seo'),/PERMISSION_DENIED/);client.dispose();f.client.dispose();
});
test('SEO execution requires content edit and keyword view permissions before reading controls',async()=>{
  for(const permission of ['seo.content','seo.keywords']){
    const f=fixture();delete f.session.user.permissions[permission];assert.deepEqual((await f.client.initialize()).modules,[]);
    await assert.rejects(()=>f.client.list('seo'),/PERMISSION_DENIED/);assert.equal(f.calls.length,2);assert(!f.calls.some(call=>call.path.includes('/automation-projects')));f.client.dispose();
  }
});
test('progress preserves pending and human boundaries, escapes logs and creates only exact task links',()=>{
  const html=advisorRunView({project:{module:'seo',tenantId:2,scopeId:19,name:'<img src=x>',revision:1,state:'pausing',cycleEnabled:false,available:true,allowedActions:['pause'],coverage:['站内 AI'],uncovered:['渠道发布'],pendingCalls:1},events:{items:[{seq:1,at:'2026-10-11T00:00:00Z',actor:'human',action:'<script>evil</script>',summary:'<img onerror=x>'}]},blocked:true});
  assert.match(html,/暂停收尾中/);assert.match(html,/不能撤回/);assert.match(html,/尚未接入控制/);assert.match(html,/不会自动重发/);assert(!html.includes('<script>'));assert(!html.includes('<img'));
  assert.equal(automationTaskLink(scope,77),'/customer-workbench/?tenant_id=2&site_id=19&onsite_task_id=77');assert.equal(automationTaskLink({...scope,module:'sem'},77),null);
});
test('panel stays idle until an explicit start, stops reads for human work and bounds failed progress refreshes',async()=>{
  const session={token:'fixture-panel',user:{id:7,tenant_id:null,permissions:{'seo.site':'edit','seo.content':'edit','seo.keywords':'view'}},authRevision:1,logout(){}},calls=[],timers=new Map();
  let nextTimer=0,current=project({configuration,allowed_actions:['start']}),runState='waiting_human',detailFailure=false;
  const browser={document:{hidden:false},crypto:{randomUUID:()=>requestId},setTimeout(fn){const id=++nextTimer;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);}};
  const panel=createAdvisorAutomationPanel({session,browser,onChange(){},onDenied(){},fetchImpl:async(path,options)=>{
    calls.push({path,method:options.method});let data,status=200;
    if(path.endsWith('/auth/me'))data={user:session.user};
    else if(path.endsWith('/auth/modules'))data={tenant_id:null,modules:[{module_code:'seo',available:true}]};
    else if(options.method==='POST'){current={...current,version:current.version+1,state:'active',current_run_id:runId,allowed_actions:['pause','takeover','end']};data=current;}
    else if(path.includes('/control?'))data=current;
    else if(path.includes('/events?'))data=eventPage();
    else if(path.includes('/runs/')){data=run({state:runState});if(detailFailure)status=500;}
    else data={schema:1,module:'seo',items:[current],next_before_scope_id:null};
    return {ok:status===200,status,json:async()=>structuredClone(data)};
  }});
  const click=action=>panel.click({target:{closest:()=>({disabled:false,dataset:{automationKey:'seo:2:19',automationAction:action}})}});
  const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
  const tick=async()=>{const [id,fn]=timers.entries().next().value;timers.delete(id);fn();await settle();};
  try{
    await panel.initialize(['seo']);assert.equal(timers.size,0);assert(calls.every(call=>call.method==='GET'));
    click('start');await settle();assert.equal(calls.filter(call=>call.method==='POST').length,1);assert.match(panel.html(),/等待人工（自动运行已开启）/);assert.equal(timers.size,0);
    runState='running';click('logs');await settle();assert.equal(timers.size,1);
    browser.document.hidden=true;const beforeHidden=calls.length;await tick();assert.equal(calls.length,beforeHidden);browser.document.hidden=false;
    detailFailure=true;await tick();assert.equal(timers.size,1);await tick();assert.equal(timers.size,1);await tick();assert.equal(timers.size,0);assert.match(panel.html(),/已停止自动刷新/);
    assert.equal(calls.filter(call=>call.method==='POST').length,1);assert(!calls.some(call=>/ai-proposal|\/chat|\/completions/.test(call.path)));
  }finally{panel.dispose();assert.equal(timers.size,0);}
});
