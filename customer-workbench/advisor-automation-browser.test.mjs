import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {startFixtureServer} from './tests/fixture-server.mjs';
import os from 'node:os';
import path from 'node:path';
import {project,run,eventPage,configuration,runId} from './tests/advisor-automation-fixture.mjs';
const edge=process.env.EDGE_BINARY||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';

test('native advisor UI explicitly configures and controls a scoped run, preserves pause receipts and never repeats an uncertain write',async()=>{
  const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
  const origin='https://advisor-automation.test',requests=[],errors=[],permissions={'seo.site':'edit','seo.content':'edit','seo.keywords':'view'};
  let current=project({scope_name:'客户官网',tenant_name:'测试客户'}),lost=false,revoke=false;
  let currentRun=run().run,events=eventPage(),eventAfter=false;
  const oldRunId='cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  try{
    const page=await browser.newPage();page.on('pageerror',error=>errors.push(error.message));await page.setViewport({width:1440,height:1000});
    await page.evaluateOnNewDocument(permissions=>sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token:'fixture-advisor',user:{id:7,tenant_id:null,display_name:'顾问',permissions}})),permissions);
    await page.setRequestInterception(true);page.on('request',async request=>{
      const url=new URL(request.url());if(url.protocol==='data:')return request.continue();if(url.origin!==origin)return request.abort();
      const send=(data,status=200)=>request.respond({status,contentType:'application/json',body:JSON.stringify(data)});
      if(url.pathname.startsWith('/api/'))requests.push({path:url.pathname,method:request.method(),query:Object.fromEntries(url.searchParams),body:request.postData()?JSON.parse(request.postData()):null});
      if(url.pathname==='/api/v1/auth/me')return send({user:{id:7,tenant_id:null,display_name:'顾问',permissions:revoke?{'seo.site':'view'}:permissions}});
      if(url.pathname==='/api/v1/auth/modules')return send({tenant_id:null,modules:[{module_code:'seo',available:true}]});
      if(url.pathname.endsWith('/advisor-tasks'))return send({schema:1,module:'seo',items:[78,77].map(id=>({id,module:'seo',tenant_id:2,scope_id:id===77?19:20,title:id===77?'官网 TDK 建议':'其他网站任务',workflow:{module:'seo',revision:1,phase:'draft',items:[],ai_proposal:null},allowed_actions:['save_proposal']})),next_before_id:null});
      if(url.pathname.endsWith('/automation-projects'))return send({schema:1,module:'seo',items:[current],next_before_scope_id:null});
      if(url.pathname.endsWith('/control')){
        if(request.method()==='GET')return send(current);
        const body=JSON.parse(request.postData());if(lost)return request.abort();
        assert.equal(body.tenant_id,2);assert.equal(body.expected_version,current.version);
        if(request.method()==='PUT')current={...current,version:current.version+1,configuration:body.configuration,allowed_actions:['start']};
        else if(body.action==='start'){current={...current,version:current.version+1,state:'active',current_run_id:runId,allowed_actions:['pause','takeover','end'],capabilities:{...current.capabilities,can_configure:false}};}
        else if(body.action==='pause'){current={...current,version:current.version+1,generation:current.generation+1,state:'pausing',allowed_actions:['takeover','end']};currentRun={...currentRun,state:'pausing',stop_requested:true};}
        else if(body.action==='takeover'){current={...current,version:current.version+1,generation:current.generation+1,state:'taking_over',allowed_actions:['end']};currentRun={...currentRun,state:'taking_over',stop_requested:true};}
        else if(body.action==='end'){current={...current,version:current.version+1,generation:current.generation+1,state:'ending',allowed_actions:[]};currentRun={...currentRun,state:'ending',stop_requested:true};}
        else if(body.action==='disable_cycle')current={...current,version:current.version+1,cycle_enabled:false,next_due_at:null,allowed_actions:current.allowed_actions.filter(action=>action!=='disable_cycle')};
        else if(body.action==='resume'){current={...current,version:current.version+1,generation:current.generation+1,state:'active',allowed_actions:['pause','takeover','end']};currentRun={...currentRun,state:'queued',stop_requested:false};}
        return send(current);
      }
      if(url.pathname.endsWith('/runs'))return send({schema:1,module:'seo',tenant_id:2,scope_id:19,items:[{id:oldRunId,state:'ended',started_at:'2026-10-10T00:00:00Z',finished_at:'2026-10-10T00:00:10Z'}],next_before_run_id:null});
      if(url.pathname.endsWith('/events')){
        if(!url.pathname.includes('/runs/'))return send({...events,run_id:null,items:[{...events.items[0],run_id:null,actor_kind:'human',actor_user_id:7,code:'project_configure',fee_state:'not_called'}],next_after_id:null});
        if(url.pathname.includes(oldRunId))return send({...events,run_id:oldRunId,items:[{...events.items[0],run_id:oldRunId,code:'run_ended'}],next_after_id:null});
        if(url.searchParams.get('after_id')==='1'){eventAfter=true;return send({...events,items:[{...events.items[0],id:2,code:'stop_requested'}],next_after_id:null});}
        return send({...events,next_after_id:1});
      }
      if(url.pathname.includes('/runs/'))return send({schema:1,module:'seo',tenant_id:2,scope_id:19,run:url.pathname.includes(oldRunId)?{...currentRun,id:oldRunId,state:'ended'}:currentRun});
      try{const response=await fetch(fixture.origin+url.pathname+url.search,{method:request.method(),headers:request.headers(),body:request.postData()});await request.respond({status:response.status,contentType:response.headers.get('content-type'),body:Buffer.from(await response.arrayBuffer())});}catch{await request.abort().catch(()=>{});}
    });
    await page.goto(origin+'/customer-workbench/?console=advisor');await page.waitForSelector('[data-automation-project="seo:2:19"]');
    await page.waitForSelector('.advisor-task');
    assert(requests.every(request=>request.method==='GET'));assert(!await page.$('[data-automation-action=start]'));
    assert.match(await page.$eval('.advisor-automation',element=>element.textContent),/尚未接入控制：渠道发布、官网修改/);
    await page.click('[data-automation-action=project-logs]');await page.waitForFunction(()=>document.querySelector('.advisor-events')?.textContent.includes('顾问保存运行配置'));
    assert.equal(requests.filter(request=>request.method!=='GET').length,0);
    await page.click('.advisor-automation details summary');assert.equal(await page.$$eval('[data-automation-action=choose-task]',elements=>elements.length),1);
    await page.click('[data-automation-action=choose-task]');assert.equal(await page.$eval('[name=task_ids]',element=>element.value),'77');await page.click('.advisor-automation-config button:not([type=button])');
    await page.waitForSelector('[data-automation-action=start]');assert.equal(requests.filter(request=>request.method==='PUT').length,1);assert.equal(requests.filter(request=>request.method==='POST').length,0);
    assert.deepEqual(requests.find(request=>request.method==='PUT').body.configuration,configuration);
    await page.click('[data-automation-action=start]');await page.waitForFunction(()=>document.querySelector('.advisor-automation strong')?.textContent==='自动推进中');
    await page.waitForSelector('.advisor-run');await page.waitForFunction(()=>!document.querySelector('[data-automation-action=logs]')?.disabled);
    assert.match(await page.$eval('.advisor-run',element=>element.textContent),/费用尚未核实/);assert.match(await page.$eval('.advisor-run',element=>element.textContent),/不代表业务交付完成/);
    assert.equal(await page.$eval('.advisor-steps a',element=>element.getAttribute('href')),'/customer-workbench/?tenant_id=2&site_id=19&onsite_task_id=77');
    await page.click('[data-automation-action=next-logs]');await page.waitForFunction(()=>document.querySelector('.advisor-events')?.textContent.includes('stop_requested'));assert(eventAfter);
    await page.waitForFunction(()=>!document.querySelector('[data-automation-action=pause]')?.disabled);
    await page.click('[data-automation-action=pause]');await page.waitForFunction(()=>document.querySelector('.advisor-automation strong')?.textContent==='暂停收尾中');
    await page.waitForFunction(()=>!document.querySelector('[data-automation-action=takeover]')?.disabled);
    assert(!await page.$('[data-automation-action=resume]'));
    await page.click('[data-automation-action=takeover]');await page.waitForFunction(()=>document.querySelector('.advisor-automation strong')?.textContent==='人工接管收尾中');
    await page.waitForFunction(()=>!document.querySelector('[data-automation-action=end]')?.disabled);
    await page.click('[data-automation-action=end]');await page.waitForFunction(()=>document.querySelector('.advisor-automation strong')?.textContent==='结束收尾中');
    await page.waitForFunction(()=>!document.querySelector('[data-automation-action=read]')?.disabled);assert(!await page.$('[data-automation-action=start]'));
    current={...current,version:current.version+1,state:'idle',allowed_actions:['start'],capabilities:{...current.capabilities,can_configure:true}};
    currentRun={...currentRun,state:'ended',finished_at:'2026-10-11T00:00:10Z',progress:{total_steps:1,terminal_steps:1,running_steps:0,waiting_steps:0},steps:currentRun.steps.map(step=>({...step,status:'stale',waiting_for:'advisor',finished_at:'2026-10-11T00:00:10Z',fee_state:'unknown_charge'}))};
    await page.click('[data-automation-action=read]');await page.waitForFunction(()=>document.querySelector('.advisor-automation strong')?.textContent==='当前无自动运行');
    await page.waitForFunction(()=>document.querySelector('.advisor-run')?.textContent.includes('本次已结束'));
    assert.match(await page.$eval('.advisor-run',element=>element.textContent),/尚无成果结论/);
    await page.waitForFunction(()=>!document.querySelector('[data-automation-action=history]')?.disabled);await page.click('[data-automation-action=history]');await page.waitForSelector('[data-automation-action=open-run]');
    await page.click('[data-automation-action=open-run]');await page.waitForFunction(()=>document.querySelector('.advisor-automation')?.textContent.includes('正在查看历史运行'));
    assert.equal(await page.$eval('[data-automation-action=start]',button=>button.disabled),true);const beforeHistoryPosts=requests.filter(request=>request.method==='POST').length;
    await page.$eval('[data-automation-action=start]',button=>button.dispatchEvent(new MouseEvent('click',{bubbles:true})));assert.equal(requests.filter(request=>request.method==='POST').length,beforeHistoryPosts);
    await page.click('[data-automation-action=current-run]');await page.waitForFunction(()=>!document.querySelector('.advisor-automation')?.textContent.includes('正在查看历史运行'));
    await page.waitForFunction(()=>!document.querySelector('[data-automation-action=start]')?.disabled);
    await page.setViewport({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:path.join(os.tmpdir(),'advisor-automation-mobile-20261011.png'),fullPage:true});
    lost=true;await page.click('[data-automation-action=start]');await page.waitForFunction(()=>document.querySelector('.advisor-automation')?.textContent.includes('写入结果尚未确认'));
    const posts=requests.filter(request=>request.method==='POST').length;
    await page.$eval('[data-automation-action=start]',button=>button.dispatchEvent(new MouseEvent('click',{bubbles:true})));await new Promise(resolve=>setTimeout(resolve,50));
    assert.equal(requests.filter(request=>request.method==='POST').length,posts);assert.equal(await page.$eval('[data-automation-action=start]',button=>button.disabled),true);
    revoke=true;await page.click('[data-automation-action=read]');await page.waitForFunction(()=>document.body.textContent.includes('已读取当前项目状态'));
    await page.click('[data-automation-action=start]');await page.waitForFunction(()=>!document.querySelector('.advisor-automation'));
    assert.equal(requests.filter(request=>request.method==='POST').length,posts);assert.deepEqual(errors,[]);
    lost=false;revoke=false;current=project({version:10,state:'paused',configuration:{...configuration,cycle:{mode:'daily',enabled:true}},cycle_enabled:true,current_run_id:runId,allowed_actions:['resume','takeover','end','disable_cycle'],capabilities:{schema_state:'ready',can_configure:false,can_control:true,available_operations:['onsite_ai']}});currentRun={...currentRun,state:'paused'};
    await page.reload();await page.waitForSelector('[data-automation-action=disable_cycle]');const generationBefore=current.generation;
    await page.click('[data-automation-action=disable_cycle]');await page.waitForFunction(()=>document.querySelector('.advisor-automation')?.textContent.includes('后续周期：未启用'));
    await page.waitForFunction(()=>!document.querySelector('[data-automation-action=resume]')?.disabled);assert.equal(current.generation,generationBefore);assert.equal(current.state,'paused');
    await page.click('[data-automation-action=resume]');await page.waitForFunction(()=>document.querySelector('.advisor-automation strong')?.textContent==='自动推进中');
    assert.equal(requests.filter(request=>request.body?.action==='resume').length,1);assert.equal(requests.filter(request=>request.body?.action==='disable_cycle').length,1);assert.deepEqual(errors,[]);
  }finally{await browser.close();await fixture.close();}
});
