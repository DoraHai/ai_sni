import test from 'node:test';
import assert from 'node:assert/strict';
import {createSeoWorkflowClient} from './js/seo-workflow-client.mjs';
import {createServicePlanController} from './js/service-plan-controller.mjs';
import {servicePlanView,serviceStatusView} from './js/seo-contract-view.mjs';

const input={optimizationDirections:['技术 SEO'],contentTopics:['产品选型'],serviceNote:'受控接口夹具',status:'active'};
const planFixture=(allowed=true)=>({tenant_id:1,site_id:9,revision:2,status:'active',optimization_directions:['技术 SEO'],content_topics:[],service_note:null,updated_by:null,updated_at:null,
  allowed_actions:{update_service_plan:allowed},permission_basis:{actor_user_id:7,schema_ready:true,seo_content_permission:'edit',seo_site_permission:'edit',active_site_advisor_assignment:allowed,update_denial_reason:allowed?null:'active_site_advisor_assignment_required'}});
const savedFixture=()=>({tenant_id:1,site_id:9,revision:3,status:'active',optimization_directions:input.optimizationDirections,content_topics:input.contentTopics,service_note:input.serviceNote,updated_by:7,updated_at:'2026-10-07T12:00:00Z'});
const ok=data=>({ok:true,status:200,json:async()=>data});
function setup(handler){
  const context={connected:true,tenantId:1,siteId:9,userId:7,revision:1},calls=[];
  const client=createSeoWorkflowClient({getContext:()=>context,transport:async(path,options)=>{const call={path,...options,body:options.body?JSON.parse(options.body):undefined};calls.push(call);return handler(call);}});
  return {context,calls,client,controller:createServicePlanController(client)};
}
test('server true enables exact PUT; only validated response displays saved; next edit rereads permission',async()=>{
  let finish;const s=setup(call=>call.method==='GET'?ok(planFixture()):new Promise(resolve=>{finish=resolve;}));
  await s.controller.load();assert.equal(s.controller.getState().canSave,true);
  const pending=s.controller.save(input);assert.equal(s.controller.getState().saved,false);assert.equal(s.controller.getState().phase,'saving');
  finish(ok(savedFixture()));await pending;
  assert.equal(s.calls[1].path,'/api/v1/seo/workbench/service-plan');
  assert.deepEqual(s.calls[1].body,{tenant_id:1,site_id:9,expected_revision:2,optimization_directions:input.optimizationDirections,content_topics:input.contentTopics,service_note:input.serviceNote,status:'active'});
  const state=s.controller.getState();assert.equal(state.saved,true);assert.equal(state.view.revision,3);assert.equal(state.view.updatedBy,7);assert.equal(state.canSave,false);
  await assert.rejects(s.client.saveServicePlan(input),/SERVICE_PLAN_REQUIRED/);
});
test('false, absent and non-boolean permission remain disabled; role and host flags cannot override',async()=>{
  for(const value of [false,undefined,'true',1]){
    const data=planFixture();data.allowed_actions=value===undefined?undefined:{update_service_plan:value};
    const s=setup(()=>ok(data));s.context.role='advisor';s.context.canWriteServicePlan=true;
    await s.controller.load();assert.equal(s.controller.getState().canSave,false);assert.equal(servicePlanView(data).canUpdate,false);
    await assert.rejects(s.controller.save(input),/PLAN_UPDATE_NOT_ALLOWED/);await assert.rejects(s.client.saveServicePlan(input),/PLAN_UPDATE_NOT_ALLOWED/);assert.equal(s.calls.length,1);
  }
});
test('409 conflict never displays saved and requires a fresh GET',async()=>{
  const s=setup(call=>call.method==='GET'?ok(planFixture()):{ok:false,status:409,json:async()=>({detail:{code:'service_plan_version_conflict',current_revision:3}})});
  await s.controller.load();await assert.rejects(s.controller.save(input),e=>e.code==='service_plan_version_conflict');
  const state=s.controller.getState();assert.equal(state.saved,false);assert.equal(state.canSave,false);assert.equal(state.view,null);assert.match(state.message,/版本已变化/);
  await assert.rejects(s.client.saveServicePlan(input),/SERVICE_PLAN_REQUIRED/);assert.equal(s.calls.length,2);
});
test('assignment revoked after GET causes 403; reread denial is displayed without save success',async()=>{
  let revoked=false;const s=setup(call=>{
    if(call.method==='GET')return ok(planFixture(!revoked));
    revoked=true;return {ok:false,status:403,json:async()=>({detail:'只有当前站点已分配的顾问可以维护服务计划'})};
  });
  await s.controller.load();await assert.rejects(s.controller.save(input),e=>e.status===403);assert.equal(s.controller.getState().saved,false);assert.match(s.controller.getState().message,/资格或权限已变化/);
  await s.controller.load();const state=s.controller.getState();assert.equal(state.canSave,false);assert.equal(state.saved,false);assert.equal(state.view.denialReason,'active_site_advisor_assignment_required');
});
test('503, uncertain PUT and malformed success do not produce saved state',async()=>{
  for(const kind of ['503','timeout','badRevision','badScope']){
    const s=setup(call=>{if(call.method==='GET')return ok(planFixture());
      if(kind==='503')return {ok:false,status:503,json:async()=>({detail:'顾问分配能力尚未完成数据库迁移'})};
      if(kind==='timeout')throw Error('timeout');
      return ok({...savedFixture(),...(kind==='badRevision'?{revision:2}:{site_id:10})});
    });
    await s.controller.load();await assert.rejects(s.controller.save(input));assert.equal(s.controller.getState().saved,false);assert.equal(s.controller.getState().canSave,false);assert.equal(s.calls.length,2);
  }
});
test('session changes or view invalidation discard late successful PUT without a success banner',async()=>{
  for(const change of ['session','view']){
    let finish;const s=setup(call=>call.method==='GET'?ok(planFixture()):new Promise(resolve=>{finish=resolve;}));await s.controller.load();const pending=s.controller.save(input);
    if(change==='session')s.context.revision++;else s.controller.invalidate();
    finish(ok(savedFixture()));await assert.rejects(pending);assert.equal(s.controller.getState().saved,false);assert.equal(s.controller.getState().canSave,false);
  }
});
test('no host remains explicitly disconnected',async()=>{
  const controller=createServicePlanController(createSeoWorkflowClient());await assert.rejects(controller.load(),/NOT_CONNECTED/);assert.equal(controller.getState().phase,'disconnected');assert.equal(controller.getState().saved,false);
});
test('semantics and server evidence references are preserved without creating workflow completion',()=>{
  const semantics={phase_state:'fact_readiness_only;not_task_completion',task_completion:'use_task_status_done_with_server_verified_completion_evidence'};
  const evidence={task_ledger:'/api/v1/seo/tasks',content_delivery_template:'/api/v1/seo/workbench/content-assets/{content_id}/delivery',publication_attempts_template:'/api/v1/seo/content-distribution/publications/{publication_id}/attempts'};
  const [view]=serviceStatusView({phases:{'SEO-A07':{state:'ready',blockers:[],facts:{recent_run_count:1},as_of:null}},semantics,evidence_endpoints:evidence});
  assert.deepEqual(view.semantics,semantics);assert.deepEqual(view.evidenceEndpoints,evidence);assert.equal(view.workflowStatus,null);assert.equal(view.completionEvidence,null);assert.equal(view.history,null);
});
