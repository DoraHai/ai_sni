import test from 'node:test';
import assert from 'node:assert/strict';
import {validateAutomationConfiguration,validateAutomationBasis,validateAutomationChanges,validateAutomationRun,validateAutomationExport,automationTargetKey,validateAutomationProject} from './js/advisor-automation-contract.mjs';
import {createAdvisorAutomationClient} from './js/advisor-automation-client.mjs';
import {createAdvisorAutomationPanel} from './js/advisor-automation-panel.mjs';
import {automationWindowCsv} from './js/advisor-automation-export.mjs';
import {advisorRunView} from './js/advisor-run-view.mjs';
import {project,run,eventPage,scope,runId,requestId} from './tests/advisor-automation-fixture.mjs';
const sha='a'.repeat(64),plan={revision:2,sha256:sha};
const target=(extra={})=>({operation:'ranking_collect',object_type:'keyword',object_id:10,source_revision:2,source_hash:sha,variant:'baidu_pc',...extra});
const binding={kind:'project_scope_registry',object_id:19,revision:2,sha256:sha};
const config=()=>({contract_version:2,operations:['ranking_collect'],targets:[target()],service_plan:{...plan},source_bindings:[{...binding}],cycle:{mode:'once',enabled:false},limits:{max_dispatches_per_run:2,max_external_calls_per_run:3},stop_condition:'drafts_ready_or_blocked',owner_user_id:7});
const basis=(extra={})=>({schema:1,module:'seo',tenant_id:2,scope_id:19,contract_version:2,state:'ready',service_plan:{...plan},source_bindings:[{...binding}],available_operations:['ranking_collect'],targets:[target({label:'排名关键词'})],next_before_object_id:null,...extra});
const current=(extra={})=>project({capabilities:{schema_state:'ready',can_configure:true,can_control:true,available_operations:['ranking_collect']},coverage:{controlled:['ranking_collect'],not_controlled:['website_mutation']},...extra});
const session=()=>({token:'fixture-v2',user:{id:7,tenant_id:null,permissions:{'seo.site':'edit','seo.content':'edit','seo.keywords':'view'}},authRevision:1,logout(){this.token='';}});
const settle=async()=>{for(let i=0;i<10;i++)await new Promise(resolve=>setImmediate(resolve));};

test('v2 accepts independently bound variants and rejects forged fields, limits and unused operations',()=>{
  const value=config();value.targets.push(target({variant:'baidu_mobile'}));
  assert.equal(validateAutomationConfiguration(value).targets.length,2);
  for(const mutate of [c=>c.targets.push(target()),c=>c.targets[0].source_hash='not-a-hash',c=>c.targets[0].api_key='secret',c=>c.operations.push('onsite_ai'),c=>c.limits.max_external_calls_per_run=101,c=>c.source_bindings.push(binding),c=>c.service_plan.prompt='secret',c=>c.cycle.enabled=true]){
    const bad=config();mutate(bad);assert.throws(()=>validateAutomationConfiguration(bad),/CONTRACT/);
  }
});
test('basis pagination groups variants by object and rejects cross-scope, repeated or unbounded targets',()=>{
  const rows=[target(),target({variant:'baidu_mobile'}),target({object_id:9})];
  assert.equal(validateAutomationBasis(basis({targets:rows,next_before_object_id:9}),scope,{operation:'ranking_collect',limit:2}).targets.length,3);
  for(const page of [basis({tenant_id:3}),basis({targets:[target(),target()]}),basis({next_before_object_id:8}),basis({targets:[target({source_hash:'bad'})]})])assert.throws(()=>validateAutomationBasis(page,scope,{operation:'ranking_collect'}),/CONTRACT/);
  assert.throws(()=>validateAutomationBasis(basis(),scope,{operation:'ranking_collect',beforeObjectId:10}),/CONTRACT/);
  assert.throws(()=>validateAutomationBasis(basis({targets:rows}),scope,{operation:'ranking_collect',limit:1}),/CONTRACT/);
  assert.equal(validateAutomationBasis(basis({state:'schema_pending',service_plan:null,source_bindings:[],available_operations:[],targets:[]}),scope,{operation:'ranking_collect'}).state,'schema_pending');
});
test('ended projects cannot expose start/resume and audit fields exclude credentials or raw prompts',()=>{
  const ended=current({state:'idle',ended_at:'2026-10-11T00:01:00Z',configuration:config(),allowed_actions:[]});
  assert.equal(validateAutomationProject(ended,scope).ended_at,ended.ended_at);
  assert.throws(()=>validateAutomationProject({...ended,allowed_actions:['start']},scope),/CONTRACT/);
  const changes=[{path:'cycle_enabled',before:true,after:false},{path:'configuration.targets',before:null,after:config().targets}];
  assert.equal(validateAutomationChanges(changes).length,2);
  for(const change of [{path:'configuration.api_key',before:null,after:'secret'},{path:'configuration.service_plan',before:null,after:{...plan,prompt:'secret'}},{path:'state',after:'idle'},{path:'configuration.targets',before:null,after:[target({token:'secret'})]}])assert.throws(()=>validateAutomationChanges([change]),/CONTRACT/);
});
test('typed steps distinguish external admissions, receipts and unknown costs without pretending success',()=>{
  const typed=run();typed.run.steps[0]={...typed.run.steps[0],kind:'ranking_collect',operation:'ranking_collect',task_id:null,target:target(),calls:[{call_key:'rank:10:baidu_pc',kind:'provider',state:'unknown',admitted_at:'2026-10-11T00:00:00Z',finished_at:null,fee_state:'unknown_charge',evidence_refs:[]}]};
  assert.equal(validateAutomationRun(typed,scope,runId).run.steps[0].calls[0].state,'unknown');
  const duplicate=structuredClone(typed);duplicate.run.steps[0].calls.push(duplicate.run.steps[0].calls[0]);assert.throws(()=>validateAutomationRun(duplicate,scope,runId),/CONTRACT/);
  const wrong=structuredClone(typed);wrong.run.steps[0].task_id=10;assert.throws(()=>validateAutomationRun(wrong,scope,runId),/CONTRACT/);
  wrong.run.steps[0].task_id=null;wrong.run.steps[0].calls[0].call_key='https://arbitrary.example';assert.throws(()=>validateAutomationRun(wrong,scope,runId),/CONTRACT/);
});
test('fixed historical windows reject scope or upper-bound drift and explicitly export only one batch',()=>{
  const page={...eventPage(),snapshot_upper_id:10,next_after_id:1};
  assert.equal(validateAutomationExport(page,scope).snapshot_upper_id,10);
  assert.throws(()=>validateAutomationExport(page,scope,{throughId:9}),/CONTRACT/);
  assert.throws(()=>validateAutomationExport({...page,snapshot_upper_id:0},scope),/CONTRACT/);
  assert.throws(()=>validateAutomationExport({...page,items:[{...page.items[0],scope_id:20}]},scope),/CONTRACT/);
  const csv=automationWindowCsv(page,scope);assert.match(csv.contents,/历史窗口的本批记录/);assert.match(csv.contents,/窗口上界/);assert.match(csv.filename,/window-10-after-0/);
});
test('client uses only authorized fixed basis/export routes and fresh capability gates before configuration',async()=>{
  const user=session(),calls=[];let item=current();
  const client=createAdvisorAutomationClient({session:user,fetchImpl:async(path,options)=>{
    calls.push({path,method:options.method});let data;
    if(path.endsWith('/me'))data={user:user.user};else if(path.endsWith('/modules'))data={tenant_id:null,modules:[{module_code:'seo',available:true}]};
    else if(path.includes('/configuration-basis?'))data=basis();else if(path.includes('/events/export?'))data={...eventPage(),snapshot_upper_id:1};else data=item;
    return {ok:true,status:200,json:async()=>structuredClone(data)};
  }});
  try{
    await client.initialize();await client.basis(scope,{operation:'ranking_collect'});await client.exportWindow(scope,{throughId:1});
    assert(calls.every(call=>call.method==='GET'));assert(calls.some(call=>call.path.includes('format=json')));
    await assert.rejects(()=>client.basis(scope,{operation:'../sem'}),/QUERY_DENIED/);
    const old=item;item={...item,capabilities:{...item.capabilities,available_operations:['onsite_ai']}};
    await assert.rejects(()=>client.saveConfiguration(scope,old,config(),requestId),/INVALID_WRITE/);assert(!calls.some(call=>call.method==='PUT'));
  }finally{client.dispose();}
});
test('basis picker saves server hashes, never starts on read/save and clears targets when source versions change',async()=>{
  const user=session(),requests=[],browser={document:{hidden:false},crypto:{randomUUID:()=>requestId},setTimeout(){return 1;},clearTimeout(){}};
  let item=current(),source=basis();
  const panel=createAdvisorAutomationPanel({session:user,browser,onChange(){},onDenied(){},fetchImpl:async(path,options)=>{
    requests.push({path,method:options.method,body:options.body&&JSON.parse(options.body)});let data;
    if(path.endsWith('/me'))data={user:user.user};else if(path.endsWith('/modules'))data={tenant_id:null,modules:[{module_code:'seo',available:true}]};
    else if(path.includes('/configuration-basis?'))data=source;
    else if(options.method==='PUT'){item={...item,version:item.version+1,configuration:JSON.parse(options.body).configuration,allowed_actions:['start','end_project']};data=item;}
    else if(path.includes('/control?'))data=item;else data={schema:1,module:'seo',items:[item],next_before_scope_id:null};
    return {ok:true,status:200,json:async()=>structuredClone(data)};
  }});
  const form={dataset:{automationKey:'seo:2:19',contractVersion:'1'},elements:{operation:{value:'ranking_collect'},task_ids:{value:''},max_dispatches:{value:'2'},max_external_calls:{value:'3'},cycle_mode:{value:'once'},cycle_enabled:{checked:false}},matches:()=>true};
  const click=(action,extra={})=>panel.click({target:{closest:()=>({disabled:false,dataset:{automationKey:'seo:2:19',automationAction:action,...extra},closest:()=>form})}});
  try{
    await panel.initialize(['seo']);click('basis');await settle();click('choose-target',{automationTarget:automationTargetKey(target())});
    form.dataset.contractVersion='2';delete form.elements.task_ids;
    assert.match(panel.html(),/已选择 1 个目标/);assert(!panel.html().includes('name="source_hash"'));
    panel.submit({target:form,preventDefault(){}});await settle();
    assert.deepEqual(requests.find(row=>row.method==='PUT').body.configuration,config());assert(!requests.some(row=>row.method==='POST'));
    click('basis');await settle();click('choose-target',{automationTarget:automationTargetKey(target())});
    source=basis({service_plan:{revision:3,sha256:'b'.repeat(64)}});click('basis');await settle();
    assert.match(panel.html(),/已清除旧目标/);assert.match(panel.html(),/已选择 0 个目标/);
  }finally{panel.dispose();}
});
test('view exposes project end boundary, safe before/after and unknown request evidence',()=>{
  const html=advisorRunView({project:{module:'seo',tenantId:2,scopeId:19,name:'官网',revision:2,state:'idle',endedAt:'2026-10-11T00:00:00Z',available:true,cycleEnabled:false,allowedActions:[],coverage:['排名采集']},events:{items:[{seq:1,actor:'human',action:'结束项目',safeChanges:[{path:'cycle_enabled',before:true,after:false}]}]},run:{id:runId,state:'ended',dispatchCount:1,externalCount:1,steps:[{label:'排名采集',status:'unknown',actor:'system',calls:[{call_key:'rank:10',kind:'provider',state:'unknown',feeLabel:'供应商扣费结果待核实',evidence_refs:['meter:1']}]}]}});
  assert.match(html,/项目已结束/);assert.match(html,/重新开启需重新保存/);assert.match(html,/修改前：true/);assert.match(html,/修改后：false/);assert.match(html,/请求结果待核实/);assert.match(html,/不代表业务成功/);assert(!html.includes('data-automation-action="start"'));
});
