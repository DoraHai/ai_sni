import test from 'node:test';import assert from 'node:assert/strict';import puppeteer from 'puppeteer-core';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {startFixtureServer} from './tests/fixture-server.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
const body=page=>page.$eval('body',e=>e.textContent);
async function nav(page,name){await page.click(`.navigation [data-page="${name}"]`);await page.waitForFunction(name=>!document.querySelector(`.navigation [data-page="${name}"]`)?.disabled,{},name);}
async function detail(page,id){await page.click(`[data-action="execution-detail"][data-id="${id}"]`);await page.waitForFunction(id=>document.querySelector('#page h2')?.textContent.includes(`#${id}`),{},id);}
const ready=page=>page.waitForFunction(()=>document.querySelector('[data-action="delivery"]')&&!document.querySelector('[data-action="delivery"]').disabled);
async function until(fn){const deadline=Date.now()+7000;while(!fn()){if(Date.now()>deadline)throw Error('Fixture timeout');await new Promise(r=>setTimeout(r,10));}}

test('SEO service automation buttons work in the mounted workbench without implicit writes',async()=>{
  const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
  try{
    const row=fixture.state.executions.get(104);
    row.task.params.report=null;row.task.params.month='2026-09';row.task.params.phase='report_needs_attention';row.task.params.blocker='analytics_source_requires_advisor';row.task.retrySources=['ga4'];
    row.task.notifications=[{id:'4c47a31b-a3aa-49f8-a846-2b2472b22184',task_id:104,title:row.task.title,phase:'report_needs_attention',waiting_for:'advisor',read:false}];
    const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(fixture.origin+'/fixture.html');await ready(page);await page.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('advisor'));await ready(page);await nav(page,'进度');
    assert.equal(fixture.state.calls.filter(c=>c.method!=='GET').length,0);
    await page.click('[data-action="execution-notification-read"]');await page.waitForFunction(()=>!document.querySelector('[data-action="execution-notification-read"]'));assert.equal(row.task.status,'in_progress');
    await detail(page,104);await page.click('[data-action="execution-retry_analytics"]');await page.waitForFunction(()=>document.body.textContent.includes('等待统计数据'));
    await page.click('[data-action="execution-incomplete_report"]');await page.waitForSelector('[data-action="execution-report"]');assert.equal(row.task.params.analytics_incomplete_ack.actor_user_id,7);
    await nav(page,'服务计划');await page.click('[data-cycle="analytics_cycle_enabled"]');await page.click('[data-cycle="website_incremental_enabled"]');await page.click('[data-action="save-plan"]');await page.waitForFunction(()=>document.querySelector('#plan-message')?.textContent.includes('已由服务器保存'));assert.equal(fixture.state.plans.get(1).analytics_cycle_enabled,true);assert.equal(fixture.state.plans.get(1).website_incremental_enabled,true);
    const scan=fixture.state.executions.get(102).task.params;
    scan.incremental={state:'complete',inventory:{added_page_ids:[10],inventory_count:3,inventory_limit_reached:false},selected_count:1,more_sitemaps_pending:true};
    scan.pages['10'].change='changed';scan.pages['10'].previous_snapshot_id=99;
    await nav(page,'进度');await detail(page,102);assert.match(await body(page),/站点地图仍有待发现页面/);assert.match(await body(page),/页面有变化/);assert.match(await body(page),/这里只证明诊断完成/);
    assert.deepEqual(errors,[]);
  }finally{await browser.close();await fixture.close();}
});
test('UI-08 mounted four execution kinds, frozen download, role actions and explicit cycle settings',async()=>{
  const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true}),downloads=fs.mkdtempSync(path.join(os.tmpdir(),'ui08-report-'));
  try{
    const page=await browser.newPage(),errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url())&&new URL(r.url()).origin!==fixture.origin)external.push(r.url());});
    await page.goto(fixture.origin+'/fixture.html');await ready(page);await nav(page,'进度');
    for(const label of ['内容交付','网站诊断与整改','监测异常','周期报告','keyword_inventory_required'])assert((await body(page)).includes(label));assert(fixture.state.calls.every(c=>c.method==='GET'));
    await detail(page,104);assert.equal((await page.$$('[data-action="execution-explain"]')).length,0);assert.match(await body(page),/冻结月报.*2026-09/s);assert.match(await body(page),/历史已截断/);
    const cdp=await page.createCDPSession();await cdp.send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:downloads});await page.click('[data-action="execution-report"]');await until(()=>fs.existsSync(path.join(downloads,'seo-report-104.html')));assert.match(fs.readFileSync(path.join(downloads,'seo-report-104.html'),'utf8'),/冻结HTML月报/);assert.equal(await page.$$('iframe').then(n=>n.length),0);
    await page.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('advisor'));await ready(page);await nav(page,'服务计划');
    assert.equal(await page.$$eval('[data-cycle$="_enabled"]',els=>els.filter(e=>e.checked).length),0);assert.equal(fixture.state.calls.filter(c=>c.method==='PUT').length,0);
    await page.click('[data-cycle="website_cycle_enabled"]');await page.$eval('[data-cycle="website_max_pages"]',e=>e.value='3');await page.click('[data-action="save-plan"]');await page.waitForFunction(()=>document.querySelector('#plan-message')?.textContent.includes('已由服务器保存'));assert.equal(fixture.state.plans.get(1).website_cycle_enabled,true);assert.equal(fixture.state.plans.get(1).report_cycle_enabled,false);
    await nav(page,'进度');await detail(page,102);assert.match(await body(page),/child_task_ids/);await page.click('[data-action="execution-retry"][data-page-id="10"]');await page.waitForFunction(()=>document.body.textContent.includes('105'));assert.equal(fixture.state.executions.get(102).task.params.pages['10'].state,'observed');
    await nav(page,'进度');await detail(page,101);await page.click('[data-action="execution-publications"]');await page.waitForSelector('#execution-publication option[value="91"]');await page.select('#execution-publication','91');await page.click('[data-action="execution-advance"]');await page.waitForFunction(()=>document.body.textContent.includes('待选择渠道并发布'));assert(fixture.state.calls.some(c=>c.path.includes('/content-workflows/101/advance')));
    await nav(page,'进度');await detail(page,104);await page.type('#execution-explanation','本月统计缺失，不能判断流量变化。');await page.click('[data-action="execution-explain"]');await page.waitForFunction(()=>document.body.textContent.includes('已完成（附服务端证据）'));assert.match(await body(page),/actor_user_id/);assert.match(await body(page),/not_evaluated/);
    fixture.state.plans.get(1).status='paused';await nav(page,'进度');await detail(page,103);assert.equal((await page.$$('[data-action="execution-advance"]')).length,0);await page.click('[data-action="execution-cancel"]');await page.waitForFunction(()=>document.body.textContent.includes('已取消'));
    await page.setViewport({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert(fixture.state.calls.every(c=>!c.path.endsWith('/run')));
  }finally{await browser.close();await fixture.close();for(const file of fs.readdirSync(downloads))fs.unlinkSync(path.join(downloads,file));fs.rmdirSync(downloads);}
});
test('UI-08 errors, revoked permission, list pagination and late scope changes clear execution data',async()=>{
  const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
  try{
    for(let id=120;id<141;id++)fixture.state.executions.set(id,{...structuredClone(fixture.state.executions.get(102)),task:{...structuredClone(fixture.state.executions.get(102).task),id,title:`分页任务${id}`}});
    const page=await browser.newPage();await page.goto(fixture.origin+'/fixture.html');await ready(page);await page.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('advisor'));await ready(page);await nav(page,'进度');assert.match(await body(page),/共25项/);
    await page.click('[data-action="execution-page"][data-number="2"]');await page.waitForFunction(()=>document.querySelector('#execution-count')?.textContent.includes('第2页'));await detail(page,104);
    fixture.state.forceError={path:'/executions/104/advance',status:409,detail:{code:'report_version_conflict'}};await page.type('#execution-explanation','新说明');await page.click('[data-action="execution-explain"]');await page.waitForFunction(()=>document.body.textContent.includes('报告版本已变化'));assert.equal(await page.$$('[data-action="execution-explain"]').then(v=>v.length),0);
    await detail(page,104);fixture.state.executionDenied=true;await page.click('[data-action="execution-advance"]');await page.waitForFunction(()=>document.body.textContent.includes('当前身份无权'));assert(!(await body(page)).includes('客户1执行任务104'));
    await page.click('[data-action="connect"]');await ready(page);fixture.state.executionDenied=false;await nav(page,'进度');fixture.state.holdNext='/executions/140';await page.click('[data-action="execution-detail"][data-id="140"]');await until(()=>fixture.state.held.length===1);await page.evaluate(()=>WORKBENCH_TEST_HOST.selectTenant(2));await ready(page);fixture.state.held.shift()();await nav(page,'进度');assert.match(await body(page),/客户2执行任务/);assert(!(await body(page)).includes('分页任务140'));
    fixture.state.forceError={path:'/executions',status:503};await page.click('[data-action="execution-refresh"]');await page.waitForFunction(()=>document.body.textContent.includes('服务能力尚未启用'));assert(!(await body(page)).includes('客户2执行任务'));await page.click('[data-action="execution-refresh"]');await page.waitForSelector('#execution-count');
    await detail(page,204);fixture.state.executions.get(204).task.params.report=null;await page.click('[data-action="execution-report"]');await page.waitForFunction(()=>document.body.textContent.includes('HTTP_ERROR'));assert.equal(await page.$$('[data-action="execution-report"]').then(v=>v.length),0);
    assert.equal(fixture.state.calls.filter(c=>c.path.endsWith('/104/advance')).length,2);
  }finally{await browser.close();await fixture.close();}
});
