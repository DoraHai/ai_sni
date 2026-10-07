import test from 'node:test';import assert from 'node:assert/strict';import puppeteer from 'puppeteer-core';import fs from 'node:fs';
import {startFixtureServer} from './tests/fixture-server.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
const idle=p=>p.waitForFunction(()=>document.querySelector('#connected-message')?.textContent==='');
const ready=p=>p.waitForFunction(()=>document.querySelector('[data-action="delivery"]')&&!document.querySelector('[data-action="delivery"]').disabled);
const click=async(p,selector)=>{await p.click(selector);await idle(p);};
const nav=async(p,name)=>click(p,`.navigation [data-page="${name}"]`);
const val=async(p,id,value)=>p.$eval(id,(e,v)=>{e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}));},value);
async function advisor(p,f){await p.goto(f.origin+'/fixture.html');await ready(p);await p.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('advisor'));await ready(p);}
test('UI10 GET-only entry, explicit AI sources across keyword pages, real authorization and trigger result detail',async()=>{
  const f=await startFixtureServer(),b=await puppeteer.launch({executablePath:edge,headless:true});
  try{
    f.state.executions.clear();const p=await b.newPage(),errors=[],external=[];p.on('pageerror',e=>errors.push(e.message));p.on('request',r=>{if(/^https?:/.test(r.url())&&new URL(r.url()).origin!==f.origin)external.push(r.url());});
    await p.goto(f.origin+'/fixture.html');await ready(p);await nav(p,'服务计划');assert.equal(await p.$$eval('[data-action="trigger"]',els=>els.filter(e=>!e.disabled).length),0);assert.equal(await p.$eval('#ai-enabled',e=>e.disabled),true);
    await p.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('advisor'));await ready(p);await nav(p,'服务计划');assert.equal(await p.$eval('#ai-enabled',e=>e.checked),false);assert(f.state.calls.every(c=>c.method==='GET'));
    await val(p,'#plan-note','保留本次手工修改');await click(p,'[data-action="ai-materials"]');assert.equal(await p.$eval('#plan-note',e=>e.value),'保留本次手工修改');assert.equal(await p.$eval('[data-ai-fact="41"]',e=>e.disabled),true);
    await p.click('[data-ai-fact="31"]');await p.click('[data-ai-keyword="1001"]');await click(p,'[data-action="ai-keyword-page"][data-number="2"]');await p.click('[data-ai-keyword="1052"]');await p.click('#ai-enabled');await click(p,'[data-action="save-plan"]');assert.equal(f.state.plans.get(1).content_ai_enabled,true);assert.deepEqual(f.state.plans.get(1).content_ai_keyword_ids,[1001,1052]);assert.equal(f.state.plans.get(1).content_ai_authorized_by,7);assert.equal(f.state.calls.filter(c=>c.path.endsWith('/run')).length,0);
    await click(p,'[data-action="refresh-plan"]');await click(p,'[data-action="trigger"][data-kind="content"]');assert.equal(f.state.calls.filter(c=>c.path.endsWith('/run')).length,1);assert.match(await p.$eval('body',e=>e.textContent),/本次顾问触发/);
    const task=[...f.state.executions.values()][0].task;task.params.ai_draft={status:'succeeded',saved_version:4,authorized_by:7,fact_snapshots:[{title:'已保存来源',statement:'已核对事实'}],generated_by:'system'};task.params.phase='awaiting_internal_review';f.state.contents.get(1).status='drafting';await click(p,'[data-action="execution-detail"]');assert.match(await p.$eval('body',e=>e.textContent),/自动生成成功只得到草稿/);assert.equal(f.state.confirmations.size,0);assert.equal(await p.$$('#execution-publication[type="number"]').then(v=>v.length),0);
    await p.setViewport({width:390,height:844});await nav(p,'服务计划');await click(p,'[data-action="ai-materials"]');assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  }finally{await b.close();await f.close();}
});
test('UI10 manual completion and new registration remain version-bound facts with independent queued evidence',async()=>{
  const f=await startFixtureServer(),b=await puppeteer.launch({executablePath:edge,headless:true});
  try{
    const p=await b.newPage();await advisor(p,f);await click(p,'[data-action="delivery"]');assert.equal(await p.$eval('[data-action="manual-open"]',e=>e.disabled),true);await click(p,'[data-action="confirm"][data-mode="advisor_proxy"]');await click(p,'[data-action="publications"]');await click(p,'[data-action="manual-open"][data-id="91"]');
    await val(p,'#manual-url','https://example.invalid/existing');await val(p,'#manual-time','2026-10-07T10:30');await p.click('#manual-verified');await click(p,'[data-action="manual-save"]');assert.match(await p.$eval('body',e=>e.textContent),/人工登记已由服务器保存/);assert.match(await p.$eval('body',e=>e.textContent),/queued/);assert.equal(await p.$eval('[data-action="manual-open"][data-id="91"]',e=>e.disabled),true);
    await click(p,'[data-action="manual-open"]');await val(p,'#manual-platform','人工核对平台');await val(p,'#manual-url','https://example.invalid/new');await val(p,'#manual-time','2026-10-07T10:35');await p.click('#manual-verified');await click(p,'[data-action="manual-save"]');const call=f.state.calls.find(c=>c.path.endsWith('/publications/manual'));assert.equal(call.body.source_version,3);assert.equal(call.body.payload_hash,'1'.repeat(64));assert.equal(call.body.published_at,'2026-10-07T10:35:00+08:00');assert.equal(f.state.publications.get(1).length,2);
    await click(p,'[data-action="manual-open"]');await val(p,'#manual-platform','另一个平台');await val(p,'#manual-url','https://example.invalid/stale');await val(p,'#manual-time','2026-10-07T10:40');await p.click('#manual-verified');f.state.contents.get(1).version_count++;await p.click('[data-action="manual-save"]');await p.waitForFunction(()=>document.body.textContent.includes('稿件版本已变化'));assert.equal(await p.$$('#manual-url').then(a=>a.length),0);assert.equal(f.state.publications.get(1).length,2);assert.equal(await p.$$('a[href^="/seo/"]').then(a=>a.length),0);
  }finally{await b.close();await f.close();}
});
test('UI10 lost trigger response is read back without resend or new UUID',async()=>{
  const f=await startFixtureServer(),b=await puppeteer.launch({executablePath:edge,headless:true});
  try{
    f.state.executions.clear();const p=await b.newPage();await advisor(p,f);await nav(p,'服务计划');f.state.dropTriggerResponse=true;await p.click('[data-action="trigger"][data-kind="website"]');await p.waitForFunction(()=>document.body.textContent.includes('写入结果未知'));await click(p,'[data-action="refresh-triggers"]');assert.equal(await p.$eval('[data-action="trigger"][data-kind="website"]',e=>e.disabled),true);assert.match(await p.$eval('body',e=>e.textContent),/请求编号/);
    await nav(p,'进度');assert.match(await p.$eval('body',e=>e.textContent),/本次顾问触发 website/);assert.equal(f.state.calls.filter(c=>c.path.endsWith('/run')).length,1);await nav(p,'服务计划');assert.equal(await p.$eval('[data-action="trigger"][data-kind="website"]',e=>e.disabled),true);
  }finally{await b.close();await f.close();}
});
