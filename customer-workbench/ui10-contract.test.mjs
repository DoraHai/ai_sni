import test from 'node:test';import assert from 'node:assert/strict';
import {startFixtureServer} from './tests/fixture-server.mjs';import {createHostSessionAdapter} from './js/host-session-adapter.mjs';import {createSeoWorkflowClient} from './js/seo-workflow-client.mjs';import {createSeoTriggerClient} from './js/seo-trigger-client.mjs';
async function setup(){const server=await startFixtureServer();let session={token:'fixture-advisor',userId:7,tenantId:1,siteId:9,revision:1};const host=createHostSessionAdapter({origin:server.origin,allowLocalHttp:true,getSession:()=>session});await host.initialize();const input={transport:host.transport,getContext:host.getContext};return {server,host,client:createSeoWorkflowClient(input),trigger:createSeoTriggerClient(input),async switch(){session={...session,tenantId:2,siteId:19,revision:2};await host.initialize();},async close(){host.dispose();await server.close();}};}
const planInput={optimizationDirections:['依据核对资料'],contentTopics:['产品选型'],status:'active'};
async function approve(f){await f.client.delivery(88);return f.client.confirm(88,{actorMode:'advisor_proxy'});}
const manual=v=>({expectedVersion:v.content.version_count,expectedHash:v.content.payload_hash,platformName:'实际平台',pageUrl:'https://example.invalid/published',publishedAt:'2026-10-07T11:00:00+08:00',verified:true});
test('AI remains opt-in; only loaded current site facts and active keywords can be selected; permission loss still permits disabling',async()=>{
  const f=await setup();try{
    const p=await f.client.servicePlan();assert.equal(p.content_ai_enabled,false);await assert.rejects(f.client.saveServicePlan({...planInput,ai:{enabled:true,factIds:[31],keywordIds:[1001]}}),/AI_SELECTION_READ_REQUIRED/);
    const facts=await f.client.aiFacts();assert.equal(facts[1].current,false);await f.client.aiKeywords();await assert.rejects(f.client.saveServicePlan({...planInput,ai:{enabled:true,factIds:[41],keywordIds:[1001]}}),/AI_SELECTION_READ_REQUIRED/);
    await f.client.aiKeywords(2);const saved=await f.client.saveServicePlan({...planInput,ai:{enabled:true,factIds:[31],keywordIds:[1052]}});assert.equal(saved.content_ai_authorized_by,7);assert.deepEqual(saved.content_ai_keyword_ids,[1052]);assert(f.server.state.calls.filter(c=>c.method==='PUT').every(c=>!('content_ai_authorized_by' in c.body)));
    f.server.state.keywordLevel='none';await f.client.servicePlan();await f.client.saveServicePlan({...planInput,ai:{enabled:false}});assert.equal(f.server.state.plans.get(1).content_ai_enabled,false);
  }finally{await f.close();}
});
test('stale AI facts at save and mismatched scope or late response cannot be accepted',async()=>{
  const f=await setup();try{
    await f.client.servicePlan();await f.client.aiFacts();await f.client.aiKeywords();f.server.state.facts.get(1)[0].current=false;
    await assert.rejects(f.client.saveServicePlan({...planInput,ai:{enabled:true,factIds:[31],keywordIds:[1001]}}),e=>e.status===409);assert.equal(f.server.state.plans.get(1).content_ai_enabled,false);
    await f.client.servicePlan();f.server.state.facts.get(1)[0].site_id=19;await assert.rejects(f.client.aiFacts(),/CONTRACT_MISMATCH/);
    await f.client.servicePlan();f.server.state.holdNext='/qa/facts';const pending=f.client.aiFacts().catch(e=>e);while(!f.server.state.held.length)await new Promise(r=>setTimeout(r,5));await f.switch();f.server.state.held.shift()();assert.equal((await pending).code,'READ_TRANSPORT_FAILED');
  }finally{await f.close();}
});
test('all four triggers use independent capabilities and exact revisions; no update permission inference',async()=>{
  const f=await setup();try{
    const p=await f.client.servicePlan();assert.equal(p.allowed_actions.update_service_plan,true);await f.trigger.load();await assert.rejects(f.trigger.trigger('content'),/ACTION_NOT_ALLOWED/);assert.equal(f.server.state.calls.filter(c=>c.path.endsWith('/run')).length,0);
    f.server.state.executions.clear();for(const kind of ['content','website','monitoring','report']){await f.trigger.load();const result=await f.trigger.trigger(kind);assert(result.id>1000);const call=f.server.state.calls.findLast(c=>c.path.endsWith('/run'));assert.equal(call.body.expected_revision,2);assert.match(call.body.request_id,/^[a-f0-9-]{36}$/);assert.equal(call.body.kind,kind==='content'?undefined:kind);}
    assert.equal(f.server.state.calls.filter(c=>c.path.endsWith('/run')).length,4);await assert.rejects(f.trigger.load(1),e=>e.code==='service_plan_version_conflict');
  }finally{await f.close();}
});
test('unknown trigger retains UUID across rereads, never resends, and reconciles an existing task',async()=>{
  const f=await setup();try{
    f.server.state.executions.clear();await f.trigger.load();f.server.state.dropTriggerResponse=true;await assert.rejects(f.trigger.trigger('content'),/WRITE_OUTCOME_UNKNOWN/);const id=f.trigger.pending().content;assert(id);await f.trigger.load();await assert.rejects(f.trigger.trigger('content'),/TRIGGER_OUTCOME_UNRESOLVED/);assert.equal(f.server.state.calls.filter(c=>c.path.endsWith('/run')).length,1);
    f.trigger.reconcile([...f.server.state.executions.values()].map(v=>v.task));assert.equal(f.trigger.pending().content,undefined);
    f.server.state.executions.clear();await f.trigger.load();f.server.state.plans.get(1).revision++;await assert.rejects(f.trigger.trigger('website'),e=>e.status===409);assert.equal(f.server.state.calls.filter(c=>c.path.endsWith('/run')).length,2);
  }finally{await f.close();}
});
test('manual registration freezes version/hash and individual completion capability; no writes from denied or unavailable confirmation',async()=>{
  const f=await setup();try{
    let v=await f.client.delivery(88);await assert.rejects(f.client.recordPublication(88,manual(v)),/ACTION_NOT_ALLOWED/);v=await approve(f);await f.client.publications(88);
    const complete=await f.client.recordPublication(88,{...manual(v),publicationId:91});assert.equal(complete.page_verification.state,'queued');assert.equal(f.server.state.calls.at(-1).body.source_version,3);assert.equal(f.server.state.calls.at(-1).body.payload_hash,undefined);
    v=await f.client.delivery(88);await f.client.publications(88);await assert.rejects(f.client.recordPublication(88,{...manual(v),publicationId:91}),/ACTION_NOT_ALLOWED/);
    const result=await f.client.recordPublication(88,{...manual(v),pageUrl:'https://example.invalid/second'});assert.equal(result.status,'published');assert.equal(f.server.state.calls.at(-1).body.payload_hash,v.content.payload_hash);
    await f.client.delivery(88);f.server.state.confirmationUnavailable=true;v=await f.client.delivery(88);await assert.rejects(f.client.recordPublication(88,manual(v)),/CONFIRMATION_UNAVAILABLE/);
  }finally{await f.close();}
});
test('manual stale version, revoked permission and lost response never retry writes',async()=>{
  for(const scenario of ['stale','denied','unknown']){
    const f=await setup();try{const v=await approve(f);if(scenario==='stale')f.server.state.contents.get(1).version_count++;if(scenario==='denied')f.server.state.publicationDenied=true;if(scenario==='unknown')f.server.state.dropPublicationResponse=true;
      await assert.rejects(f.client.recordPublication(88,manual(v)));await assert.rejects(f.client.recordPublication(88,manual(v)));assert.equal(f.server.state.calls.filter(c=>c.path.endsWith('/publications/manual')).length,1);if(scenario==='unknown'){await f.client.delivery(88);assert.equal((await f.client.publications(88)).items.filter(v=>v.status==='published').length,1);}
    }finally{await f.close();}
  }
});
