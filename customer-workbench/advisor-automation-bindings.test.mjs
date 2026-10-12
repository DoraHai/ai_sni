import test from 'node:test';
import assert from 'node:assert/strict';
import {createAdvisorAutomationPanel} from './js/advisor-automation-panel.mjs';
import {automationTargetKey} from './js/advisor-automation-contract.mjs';
import {project,requestId} from './tests/advisor-automation-fixture.mjs';

test('mixed capabilities keep exact source bindings and remove patrol-only inputs with the last patrol target',async()=>{
  const hash='a'.repeat(64),shared=[{kind:'project_prompt_set',object_id:19,revision:1,sha256:hash},{kind:'project_scope_registry',object_id:19,revision:1,sha256:hash}],patrol={kind:'tenant_patrol_settings',object_id:2,revision:0,sha256:hash};
  const periodicTarget={operation:'periodic_workflow',object_type:'project',object_id:19,source_revision:1,source_hash:hash,variant:null};
  const patrolTarget={operation:'visibility_patrol',object_type:'prompt',object_id:10,source_revision:0,source_hash:hash,variant:'deepseek'};
  const session={token:'synthetic-geo',user:{id:7,tenant_id:null,permissions:{'geo.assets':'edit','geo.content':'edit'}},authRevision:1,logout(){}},writes=[];
  let current=project({module:'geo',capabilities:{schema_state:'ready',can_configure:true,can_control:true,available_operations:['periodic_workflow','visibility_patrol']}});
  const browser={document:{hidden:false},crypto:{randomUUID:()=>requestId},setTimeout(){return 1;},clearTimeout(){}};
  const panel=createAdvisorAutomationPanel({session,browser,onChange(){},onDenied(){},fetchImpl:async(path,options)=>{
    let data;
    if(path.endsWith('/me'))data={user:session.user};else if(path.endsWith('/modules'))data={tenant_id:null,modules:[{module_code:'geo',available:true}]};
    else if(path.includes('/configuration-basis?')){const operation=new URL(path,'https://local.invalid').searchParams.get('operation');data={schema:1,module:'geo',tenant_id:2,scope_id:19,contract_version:2,state:'ready',service_plan:{revision:1,sha256:hash},source_bindings:operation==='visibility_patrol'?[patrol,...shared]:shared,available_operations:current.capabilities.available_operations,targets:[operation==='visibility_patrol'?patrolTarget:periodicTarget],next_before_object_id:null};}
    else if(options.method==='PUT'){writes.push(JSON.parse(options.body));current={...current,version:current.version+1,configuration:writes.at(-1).configuration};data=current;}
    else if(path.includes('/control?'))data=current;else data={schema:1,module:'geo',items:[current],next_before_scope_id:null};
    return {ok:true,status:200,json:async()=>structuredClone(data)};
  }});
  const form={dataset:{automationKey:'geo:2:19',contractVersion:'2'},elements:{operation:{value:'periodic_workflow'},max_dispatches:{value:'2'},max_external_calls:{value:'3'},cycle_mode:{value:'once'},cycle_enabled:{checked:false}},matches:()=>true};
  const click=(action,target=null)=>panel.click({target:{closest:()=>({disabled:false,dataset:{automationKey:'geo:2:19',automationAction:action,automationTarget:target&&automationTargetKey(target)},closest:()=>form})}});
  const settle=async()=>{for(let i=0;i<10;i++)await new Promise(resolve=>setImmediate(resolve));};
  try{
    await panel.initialize(['geo']);click('basis');await settle();click('choose-target',periodicTarget);
    form.elements.operation.value='visibility_patrol';click('basis');await settle();click('choose-target',patrolTarget);
    assert.match(panel.html(),/已选择 2 个目标/);panel.submit({target:form,preventDefault(){}});await settle();
    assert.equal(writes[0].configuration.source_bindings.length,3);assert.deepEqual(new Set(writes[0].configuration.operations),new Set(['periodic_workflow','visibility_patrol']));
    // Re-read the remaining operation to get its own minimal binding set.
    form.elements.operation.value='periodic_workflow';click('basis');await settle();click('remove-target',patrolTarget);
    panel.submit({target:form,preventDefault(){}});await settle();
    assert.deepEqual(writes[1].configuration.targets,[periodicTarget]);assert.deepEqual(writes[1].configuration.source_bindings,shared);
    assert(!Object.hasOwn(writes[1].configuration,'operationBindings'));
  }finally{panel.dispose();}
});
