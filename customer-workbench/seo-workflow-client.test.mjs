import test from 'node:test';import assert from 'node:assert/strict';
import {createSeoWorkflowClient} from './js/seo-workflow-client.mjs';
import {contentDeliveryView,serviceStatusView} from './js/seo-contract-view.mjs';
const fixture=()=>({content:{id:88,tenant_id:1,site_id:9,version_count:3,payload_hash:'a'.repeat(64),status:'ready'},workflow_status:'awaiting_customer_confirmation',confirmation:{status:'pending',latest:null,approval_is_publication:false},allowed_actions:{confirm_as_customer:true,confirm_as_advisor_proxy:true,reject_as_customer:true,reject_as_advisor_proxy:true,review:true},permission_basis:{active_site_advisor_assignment:true},result_basis:{publication_status:'not_loaded'}});
const ctx=()=>({connected:true,tenantId:1,siteId:9,userId:7,revision:1});
function setup(handler){const context=ctx(),calls=[];const client=createSeoWorkflowClient({getContext:()=>context,transport:async(path,options)=>{calls.push({path,options,body:options.body&&JSON.parse(options.body)});return handler(path,options);}});return {client,context,calls};}
const ok=data=>({ok:true,status:200,json:async()=>data});
test('unconnected host never sends requests',async()=>{let sent=0;const client=createSeoWorkflowClient({getContext:()=>null,transport:async()=>{sent++;}});await assert.rejects(client.delivery(88),/NOT_CONNECTED/);assert.equal(sent,0);});
test('customer approval and advisor proxy use exact server version/hash and real response actor',async()=>{
  for(const actorMode of ['customer_direct','advisor_proxy']){
    const s=setup((path,options)=>{const data=fixture();if(options.method==='POST'){data.confirmation={...data.confirmation,status:'approved',latest:{actor_mode:actorMode,actor_user_id:7,actor_name:'接口夹具顾问',content_version:3}};data.workflow_status='approved_waiting_publication';}return ok(data);});
    await s.client.delivery(88);const result=await s.client.confirm(88,{actorMode});
    assert.equal(s.calls[1].path,'/api/v1/seo/workbench/content-assets/88/confirmations?tenant_id=1');
    assert.deepEqual(s.calls[1].body,{version_count:3,payload_hash:'a'.repeat(64),decision:'approve',actor_mode:actorMode,note:null});
    assert.equal(result.confirmation.latest.actor_user_id,7);assert.equal(result.result_basis.publication_status,'not_loaded');
  }
});
test('server denied actions and missing rejection note prevent writes; reject sends note',async()=>{
  const denied=setup(()=>ok({...fixture(),allowed_actions:{confirm_as_advisor_proxy:false}}));await denied.client.delivery(88);await assert.rejects(denied.client.confirm(88,{actorMode:'advisor_proxy'}),/ACTION_NOT_ALLOWED/);assert.equal(denied.calls.length,1);
  const s=setup(()=>ok(fixture()));await s.client.delivery(88);await assert.rejects(s.client.confirm(88,{decision:'reject'}),/REJECTION_NOTE_REQUIRED/);await s.client.confirm(88,{decision:'reject',note:'请核实事实'});assert.equal(s.calls[1].body.decision,'reject');
});
test('409 conflict and 503 missing migration invalidate snapshot; never mock success',async()=>{
  for(const [status,code] of [[409,'content_version_conflict'],[503,'content_confirmation_schema_unavailable'],[403,'permission_denied']]){
    const s=setup((path,options)=>options.method==='GET'?ok(fixture()):{ok:false,status,json:async()=>({detail:{code,current_version:4}})});await s.client.delivery(88);await assert.rejects(s.client.confirm(88),e=>e.code===code&&e.status===status);await assert.rejects(s.client.confirm(88),/DELIVERY_REQUIRED/);
  }
});
test('review includes exact version and discards old delivery after write',async()=>{const s=setup(()=>ok(fixture()));await s.client.delivery(88);await s.client.review(88,{decision:'approve'});assert.deepEqual(s.calls[1].body,{version_count:3,decision:'approve',note:null});await assert.rejects(s.client.confirm(88),/DELIVERY_REQUIRED/);});
test('plan read preserves revision; absent server write eligibility stays disabled even with host flag',async()=>{
  const s=setup(()=>ok({tenant_id:1,site_id:9,revision:2,status:'active'}));const plan=await s.client.servicePlan();assert.equal(plan.revision,2);await assert.rejects(s.client.saveServicePlan({optimizationDirections:['技术SEO']}),/PLAN_UPDATE_NOT_ALLOWED/);s.context.canWriteServicePlan=true;await assert.rejects(s.client.saveServicePlan({optimizationDirections:['技术SEO'],contentTopics:['选型']}),/PLAN_UPDATE_NOT_ALLOWED/);assert.equal(s.calls.length,1);
});
test('service status preserves phase vocabulary; ready is not completed',async()=>{const s=setup(()=>ok({tenant_id:1,site_id:9,read_only:true,phases:{'SEO-A02':{state:'ready',blockers:[],facts:{pages:1},as_of:null}}}));const result=await s.client.serviceStatus();assert.equal(result.phases['SEO-A02'].state,'ready');assert.equal(result.phases['SEO-A02'].workflow_status,undefined);});
test('context change and uncertain write never resend automatically',async()=>{
  const s=setup((path,options)=>{if(options.method==='POST')throw Error('timeout');return ok(fixture());});await s.client.delivery(88);await assert.rejects(s.client.confirm(88),/WRITE_OUTCOME_UNKNOWN/);assert.equal(s.calls.length,2);await assert.rejects(s.client.confirm(88),/DELIVERY_REQUIRED/);
  const t=setup(()=>ok(fixture()));await t.client.delivery(88);t.context.userId=8;await assert.rejects(t.client.confirm(88),/CONTEXT_CHANGED/);assert.equal(t.calls.length,1);
});
test('display mapping keeps server allowed actions, actual proxy actor and unavailable schema',()=>{
  const data=fixture();data.allowed_actions={confirm_as_customer:false,confirm_as_advisor_proxy:true};data.confirmation={...data.confirmation,status:'unavailable',latest:{actor_user_id:77,actor_name:'顾问张某',actor_role_name:'consultant',actor_mode:'advisor_proxy',content_version:2,created_at:'2026-10-07T12:00:00Z'}};
  data.workflow_status='confirmation_unavailable';data.allowed_actions.start_publication=true;
  const view=contentDeliveryView(data);assert.deepEqual(view.actions,[]);assert.equal(view.workflowStatus,'confirmation_unavailable');assert.equal(view.confirmation.actorId,77);assert.equal(view.confirmation.label,'顾问代确认');assert.equal(view.approvalIsPublication,false);assert(view.capabilityMessage);
});
test('phase view never invents missing workflow owners or history',()=>{const phases=serviceStatusView({phases:{'SEO-A03':{state:'ready',blockers:[],facts:{rank_observations:5},as_of:null}}});assert.equal(phases[0].label,'事实就绪');assert.equal(phases[0].workflowStatus,null);assert.equal(phases[0].history,null);assert.equal(phases[0].completionEvidence,null);});
test('malformed confirmation response invalidates snapshot',async()=>{
  const t=setup((path,options)=>ok(options.method==='GET'?fixture():{content:{id:99}}));await t.client.delivery(88);await assert.rejects(t.client.confirm(88),/CONTRACT_MISMATCH/);await assert.rejects(t.client.confirm(88),/DELIVERY_REQUIRED/);
});
test('0104 unavailable prevents confirm even if a malformed response advertises an action',async()=>{
  const s=setup(()=>ok({...fixture(),workflow_status:'confirmation_unavailable',confirmation:{status:'unavailable',latest:null,approval_is_publication:false}}));
  await s.client.delivery(88);await assert.rejects(s.client.confirm(88),/CONFIRMATION_UNAVAILABLE/);assert.equal(s.calls.length,1);
});
