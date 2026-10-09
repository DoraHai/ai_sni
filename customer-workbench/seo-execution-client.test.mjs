import test from 'node:test';import assert from 'node:assert/strict';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {createHostSessionAdapter} from './js/host-session-adapter.mjs';
import {createSeoExecutionClient} from './js/seo-execution-client.mjs';
import {createSeoWorkflowClient} from './js/seo-workflow-client.mjs';
async function setup(role='advisor'){
  const server=await startFixtureServer();let session={token:`fixture-${role}`,userId:role==='advisor'?7:12,tenantId:1,siteId:9,revision:1};
  const host=createHostSessionAdapter({origin:server.origin,allowLocalHttp:true,getSession:()=>session});await host.initialize();
  const client=createSeoExecutionClient({transport:host.transport,getContext:host.getContext});
  return {server,host,client,change(){session={...session,tenantId:2,siteId:19,revision:2};host.getContext();},async close(){host.dispose();await server.close();}};
}
test('execution GET is read-only, scoped and server-action gated; keyword permission filters counts',async()=>{
  const f=await setup('customer');try{
    assert.equal((await f.client.list()).total,4);await assert.rejects(f.client.act(102,'advance'),/ACTION_NOT_ALLOWED/);
    assert(f.server.state.calls.every(c=>c.method==='GET'));
    f.server.state.keywordLevel='none';assert.equal((await f.client.list()).total,3);
    await assert.rejects(f.host.transport('/api/v1/seo/workbench/executions/102/advance',{method:'POST',body:JSON.stringify({tenant_id:2,site_id:19})}),/SCOPE_MISMATCH/);
    await assert.rejects(f.host.transport('/api/v1/seo/workbench/executions/102?tenant_id=1&site_id=9',{method:'DELETE',body:'{}'}),/BODY_DENIED/);
  }finally{await f.close();}
});
test('content advance uses SEO-08; failed page retry, paused cancellation, and post-write re-read use current capabilities',async()=>{
  const f=await setup();try{
    await f.client.detail(101);await f.client.publicationOptions(101);await f.client.act(101,'advance',{publicationId:91});assert(f.server.state.calls.some(c=>c.path.endsWith('/content-workflows/101/advance')&&c.body.publication_id===91));
    await f.client.detail(102);await assert.rejects(f.client.act(102,'retry',{pageId:99}),/ACTION_NOT_ALLOWED/);
    await f.client.detail(102);const changed=await f.client.act(102,'retry',{pageId:10});assert.equal(changed.params.pages['10'].snapshot_id,105);assert.deepEqual(changed.allowed_actions.retry_page_ids,[]);
    f.server.state.plans.get(1).status='paused';await f.client.detail(103);await assert.rejects(f.client.act(103,'advance'),/ACTION_NOT_ALLOWED/);
    await f.client.detail(103);assert.equal((await f.client.act(103,'cancel')).status,'cancelled');
  }finally{await f.close();}
});
test('frozen report checks ETag and bytes, explanation binds read hash; 409 never retries',async()=>{
  const f=await setup();try{
    const task=await f.client.detail(104),report=await f.client.report(104);assert.equal(report.sha256,task.params.report.sha256);assert.match(new TextDecoder().decode(report.bytes),/冻结HTML/);
    f.server.state.executions.get(104).html+='changed';await assert.rejects(f.client.report(104),/REPORT_VERSION_MISMATCH/);
    await f.client.detail(104);f.server.state.executions.get(104).task.params.report.sha256='b'.repeat(64);
    await assert.rejects(f.client.act(104,'explain',{explanation:'缺统计，不判断流量变化'}),e=>e.code==='report_version_conflict'&&e.status===409);
    assert.equal(f.server.state.calls.filter(c=>c.method==='POST').length,1);await assert.rejects(f.client.act(104,'explain',{explanation:'再试'}),/EXECUTION_REQUIRED/);
    await f.client.detail(104);const result=await f.client.act(104,'explain',{explanation:'缺统计，不判断流量变化'});assert.equal(result.params.explanation.actor_user_id,7);assert.equal(result.status,'done');
  }finally{await f.close();}
});
test('scope changes discard held details; unexpected links and uncertain writes cannot become success',async()=>{
  const f=await setup();try{
    f.server.state.holdNext='/executions/102';const pending=f.client.detail(102);const observed=pending.catch(e=>e);
    while(!f.server.state.held.length)await new Promise(r=>setTimeout(r,5));f.change();f.server.state.held.shift()();assert(await observed instanceof Error);
    await f.host.initialize();const task=await f.client.detail(202);
    const wrong=createSeoExecutionClient({getContext:f.host.getContext,transport:async()=>({ok:true,json:async()=>({...task,links:{...task.links,detail:'/api/v1/seo/workbench/executions/202?tenant_id=1&site_id=9'}})})});await assert.rejects(wrong.detail(202),/CONTRACT_MISMATCH/);
    let writes=0;const unknown=createSeoExecutionClient({getContext:f.host.getContext,transport:async(path,options)=>{if(options.method!=='GET'){writes++;throw Error('network unavailable');}return {ok:true,json:async()=>task};}});
    await unknown.detail(202);await assert.rejects(unknown.act(202,'advance'),/WRITE_OUTCOME_UNKNOWN/);assert.equal(writes,1);await assert.rejects(unknown.act(202,'advance'),/EXECUTION_REQUIRED/);
  }finally{await f.close();}
});
test('cycle settings default off, changes are explicit and bounded; server response must preserve submitted settings',async()=>{
  const f=await setup();try{
    const plans=createSeoWorkflowClient({transport:f.host.transport,getContext:f.host.getContext});const first=await plans.servicePlan();assert.equal(first.website_cycle_enabled,false);assert.equal(f.server.state.calls.filter(c=>c.method==='PUT').length,0);
    const input={optimizationDirections:['SEO'],contentTopics:['选型'],status:'active'};
    await assert.rejects(plans.saveServicePlan({...input,cycles:{website_max_pages:11}}),/INVALID_CYCLE_CONFIG/);
    await plans.servicePlan();const saved=await plans.saveServicePlan({...input,cycles:{website_cycle_enabled:true,website_interval_days:7,website_max_pages:3,report_cycle_enabled:false}});assert.equal(saved.website_max_pages,3);assert.equal(saved.monitoring_cycle_enabled,false);
    const call=f.server.state.calls.find(c=>c.method==='PUT');assert.equal(call.body.expected_revision,2);assert.equal(call.body.website_cycle_enabled,true);assert.equal(call.body.monitoring_cycle_enabled,undefined);
  }finally{await f.close();}
});

test('analytics recovery and incomplete report require current server actions; reading a notice never completes a task',async()=>{
  const f=await setup();try{
    const row=f.server.state.executions.get(104),eventId='4c47a31b-a3aa-49f8-a846-2b2472b22184';
    row.task.params.report=null;row.task.params.month='2026-09';row.task.params.blocker='analytics_source_requires_advisor';row.task.retrySources=['ga4'];
    row.task.notifications=[{id:eventId,task_id:104,title:row.task.title,phase:'report_needs_attention',waiting_for:'advisor',read:false}];
    await f.client.list();await f.client.readNotification(104,eventId);assert.equal(row.task.notifications[0].read,true);assert.equal(row.task.status,'in_progress');
    await assert.rejects(f.client.readNotification(104,eventId),/EXECUTION_REQUIRED/);
    await f.client.detail(104);await assert.rejects(f.client.act(104,'retry_analytics',{source:'baidu_tongji'}),/ACTION_NOT_ALLOWED/);
    await f.client.detail(104);await f.client.act(104,'retry_analytics',{source:'ga4'});assert.equal(row.task.params.phase,'awaiting_analytics_collection');
    await f.client.act(104,'incomplete_report');assert.equal(row.task.params.analytics_incomplete_ack.actor_user_id,7);assert(row.task.params.report.missing.includes('site_analytics_missing'));
    await assert.rejects(f.client.act(104,'incomplete_report'),/ACTION_NOT_ALLOWED/);
    for(const body of [{tenant_id:2,site_id:19,task_id:104,event_id:eventId},{tenant_id:1,site_id:9,task_id:104,event_id:eventId,actor_id:7}])await assert.rejects(f.host.transport('/api/v1/seo/workbench/notifications/read',{method:'POST',body:JSON.stringify(body)}),/SCOPE_MISMATCH|BODY_DENIED/);
  }finally{await f.close();}
});
