import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {project,run,eventPage,runId} from './tests/advisor-automation-fixture.mjs';
import os from 'node:os';
import path from 'node:path';
const edge=process.env.EDGE_BINARY||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';

test('native v2 advisor selects authorized variants, explicitly starts/ends and exports fixed authorized windows',async()=>{
  const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
  const origin='https://advisor-v2.test',requests=[],errors=[],permissions={'seo.site':'edit','seo.content':'edit','seo.keywords':'view'};
  const sha='a'.repeat(64),servicePlan={revision:2,sha256:sha};
  const targets=['baidu_pc','baidu_mobile'].map(variant=>({operation:'ranking_collect',object_type:'keyword',object_id:10,source_revision:2,source_hash:sha,variant,label:'本客户关键词'}));
  const sourceBindings=[{kind:'project_scope_registry',object_id:19,revision:2,sha256:sha}];
  let current=project({scope_name:'客户官网',capabilities:{schema_state:'ready',can_configure:true,can_control:true,available_operations:['ranking_collect']},coverage:{controlled:['ranking_collect'],not_controlled:['website_mutation','approval','acceptance']}}),revoked=false;
  let currentRun=run({state:'waiting_human'}).run;
  currentRun.steps=[{...currentRun.steps[0],step_key:'ranking_collect:10',kind:'ranking_collect',operation:'ranking_collect',task_id:null,target:(({label,...target})=>target)(targets[0]),status:'unknown',waiting_for:'advisor',fee_state:'unknown_charge',calls:[{call_key:'ranking:10:baidu_pc',kind:'provider',state:'unknown',admitted_at:'2026-10-11T00:00:00Z',finished_at:null,fee_state:'unknown_charge',evidence_refs:['meter:synthetic:1']}]}];
  currentRun.progress={total_steps:1,terminal_steps:1,running_steps:0,waiting_steps:0};
  const event={...eventPage().items[0],actor_kind:'human',actor_user_id:7,code:'project_end_project',fee_state:'not_called',safe_changes:[{path:'cycle_enabled',before:true,after:false}]};
  try{
    const page=await browser.newPage();page.on('pageerror',error=>errors.push(error.message));await page.setViewport({width:1440,height:1000});
    await page.evaluateOnNewDocument(permissions=>sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token:'fixture-v2',user:{id:7,tenant_id:null,display_name:'顾问',permissions}})),permissions);
    await page.setRequestInterception(true);page.on('request',async request=>{
      const url=new URL(request.url());if(url.protocol==='data:'||url.protocol==='blob:')return request.continue();if(url.origin!==origin)return request.abort();
      const send=(data,status=200)=>request.respond({status,contentType:'application/json',body:JSON.stringify(data)});
      if(url.pathname.startsWith('/api/'))requests.push({path:url.pathname,method:request.method(),query:Object.fromEntries(url.searchParams),body:request.postData()?JSON.parse(request.postData()):null});
      if(url.pathname==='/api/v1/auth/me')return send({user:{id:7,tenant_id:null,permissions}});
      if(url.pathname==='/api/v1/auth/modules')return send({tenant_id:null,modules:[{module_code:'seo',available:true}]});
      if(url.pathname.startsWith('/api/distribution/v1/'))return send({detail:{code:'distribution_unavailable'}},404);
      if(revoked&&url.pathname.includes('/automation-projects/'))return send({detail:'permission revoked'},403);
      if(url.pathname.endsWith('/advisor-tasks'))return send({schema:1,module:'seo',items:[],next_before_id:null});
      if(url.pathname.endsWith('/automation-projects'))return send({schema:1,module:'seo',items:[current],next_before_scope_id:null});
      if(url.pathname.endsWith('/configuration-basis'))return send({schema:1,module:'seo',tenant_id:2,scope_id:19,contract_version:2,state:'ready',service_plan:servicePlan,source_bindings:sourceBindings,available_operations:['ranking_collect'],targets,next_before_object_id:null});
      if(url.pathname.endsWith('/control')){
        if(request.method()==='GET')return send(current);
        const body=JSON.parse(request.postData());assert.equal(body.tenant_id,2);assert.equal(body.expected_version,current.version);
        if(request.method()==='PUT')current={...current,version:current.version+1,configuration:body.configuration,allowed_actions:['start','end_project']};
        else if(body.action==='start')current={...current,version:current.version+1,current_run_id:runId,state:'active',cycle_enabled:true,allowed_actions:['pause','takeover','end','end_project'],capabilities:{...current.capabilities,can_configure:false}};
        else if(body.action==='end_project'){current={...current,version:current.version+1,generation:current.generation+1,state:'idle',cycle_enabled:false,next_due_at:null,ended_at:'2026-10-11T00:01:00Z',allowed_actions:[],capabilities:{...current.capabilities,can_configure:true}};currentRun={...currentRun,state:'ended',stop_requested:true,finished_at:'2026-10-11T00:01:00Z'};}
        else assert.fail('unexpected action '+body.action);
        return send(current);
      }
      if(url.pathname.endsWith('/events/export'))return send({schema:1,module:'seo',tenant_id:2,scope_id:19,snapshot_upper_id:10,items:[{...event,id:url.searchParams.get('after_id')==='1'?10:1}],next_after_id:url.searchParams.get('after_id')==='1'?null:1});
      if(url.pathname.endsWith('/events'))return send({schema:1,module:'seo',tenant_id:2,scope_id:19,run_id:url.pathname.includes('/runs/')?runId:null,items:[event],next_after_id:null});
      if(url.pathname.includes('/runs/'))return send({schema:1,module:'seo',tenant_id:2,scope_id:19,run:currentRun});
      try{const response=await fetch(fixture.origin+url.pathname+url.search);await request.respond({status:response.status,contentType:response.headers.get('content-type'),body:Buffer.from(await response.arrayBuffer())});}catch{await request.abort().catch(()=>{});}
    });
    await page.goto(origin+'/customer-workbench/?console=advisor');await page.waitForSelector('[data-automation-project="seo:2:19"]');
    assert(requests.every(row=>row.method==='GET'));assert.match(await page.$eval('.advisor-boundary',element=>element.textContent),/SEM 本轮暂不接入 AI 接管/);
    await page.click('.advisor-automation details summary');await page.click('[data-automation-action=basis]');await page.waitForSelector('[data-automation-action=choose-target]');
    await page.click('[data-automation-action=choose-target]');await page.waitForSelector('[name=max_external_calls]');
    assert.equal(await page.$$eval('[data-automation-action=remove-target]',nodes=>nodes.length),1);
    await page.$eval('[name=max_external_calls]',input=>{input.value='2';input.dispatchEvent(new Event('input',{bubbles:true}));});
    await page.select('[name=cycle_mode]','daily');await page.click('[name=cycle_enabled]');
    await page.click('.advisor-automation-config button:not([type=button])');await page.waitForSelector('[data-automation-action=start]');
    const saved=requests.find(row=>row.method==='PUT').body.configuration;
    assert.equal(saved.contract_version,2);assert.equal(saved.targets.length,1);assert.equal(saved.targets[0].variant,'baidu_pc');assert.equal(saved.targets[0].source_hash,sha);assert.deepEqual(saved.source_bindings,sourceBindings);assert.equal(saved.limits.max_external_calls_per_run,2);assert(!('label' in saved.targets[0]));assert(!requests.some(row=>row.method==='POST'));
    await page.click('[data-automation-action=start]');await page.waitForSelector('.advisor-run');await page.waitForFunction(()=>!document.querySelector('[data-automation-action=end_project]')?.disabled);
    assert.match(await page.$eval('.advisor-run',element=>element.textContent),/请求结果待核实/);assert.match(await page.$eval('.advisor-run',element=>element.textContent),/供应商扣费结果待核实/);
    await page.click('[data-automation-action=end_project]');await page.waitForFunction(()=>document.querySelector('.advisor-automation strong')?.textContent==='项目已结束');
    await page.waitForFunction(()=>!document.querySelector('[data-automation-action=read]')?.disabled);
    assert(!await page.$('[data-automation-action=start]'));assert.match(await page.$eval('.advisor-automation',element=>element.textContent),/后续周期：未启用/);assert.match(await page.$eval('.advisor-events',element=>element.textContent),/修改前：true/);
    await page.click('[data-automation-action=export-window]');await page.waitForSelector('[data-automation-action=next-export-window]');
    await page.click('[data-automation-action=next-export-window]');await page.waitForFunction(()=>!document.querySelector('[data-automation-action=next-export-window]'));
    const chunks=requests.filter(row=>row.path.endsWith('/events/export'));assert.equal(chunks.length,2);assert.equal(chunks[1].query.through_id,'10');assert.equal(chunks[1].query.after_id,'1');
    await page.setViewport({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(os.tmpdir(),'advisor-automation-v2-mobile-20261011.png'),fullPage:true});
    revoked=true;await page.click('[data-automation-action=export-window]');await page.waitForFunction(()=>!document.querySelector('.advisor-automation'));
    assert(!requests.some(row=>row.path.includes('/sem/')||/completions|ai-proposal|\/chat/.test(row.path)));assert.equal(requests.filter(row=>row.method==='POST').length,2);assert.deepEqual(errors,[]);
  }finally{await browser.close();await fixture.close();}
});
