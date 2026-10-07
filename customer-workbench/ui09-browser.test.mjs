import test from 'node:test';import assert from 'node:assert/strict';import puppeteer from 'puppeteer-core';import fs from 'node:fs';
import {startFixtureServer} from './tests/fixture-server.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
const ready=page=>page.waitForFunction(()=>document.querySelector('[data-action="delivery"]')&&!document.querySelector('[data-action="delivery"]').disabled);
const idle=page=>page.waitForFunction(()=>document.querySelector('#connected-message')?.textContent==='');
const click=async(page,action)=>{await page.click(`[data-action="${action}"]`);await idle(page);};
const text=page=>page.$eval('body',e=>e.textContent);
async function enter(page,origin){await page.goto(origin+'/fixture.html');await ready(page);await page.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('advisor'));await ready(page);await click(page,'delivery');}
test('UI09 draft edit, review return, resubmit, proxy confirmation and read-only manual records',async()=>{
  const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
  try{
    const content=f.state.contents.get(1);Object.assign(content,{status:'drafting',draft:'旧底稿',humanized_content:'当前正文',body:'当前正文',keyword_ids:[21]});
    f.state.confirmations.set(1,{content_version:2,payload_hash:'b'.repeat(64),decision:'approve',actor_mode:'advisor_proxy',actor_user_id:7});
    const page=await browser.newPage(),errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url())&&new URL(r.url()).origin!==f.origin)external.push(r.url());});
    await page.goto(f.origin+'/fixture.html');await ready(page);await click(page,'delivery');assert.equal(await page.$eval('[data-action="edit-content"]',e=>e.disabled),true);assert.equal(await page.$$('a[href^="/seo/"]').then(a=>a.length),0);
    await page.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('advisor'));await ready(page);await click(page,'delivery');await click(page,'edit-content');assert.equal(await page.$eval('#content-body',e=>e.value),'当前正文');
    await page.$eval('#content-body',e=>{e.value='校对后的正文';e.dispatchEvent(new Event('input',{bubbles:true}));});await click(page,'publications');assert.equal(await page.$eval('#content-body',e=>e.value),'校对后的正文');
    await click(page,'save-content');assert.equal(content.version_count,4);assert.equal(content.draft,'旧底稿');assert.equal(content.humanized_content,'校对后的正文');assert.match(await text(page),/stale/);
    await click(page,'submit-review');assert.equal(content.status,'review');assert.equal(await page.$eval('[data-action="edit-content"]',e=>e.disabled),true);
    await page.type('#decision-note','请补充来源');await click(page,'review-reject');assert.equal(content.status,'drafting');await click(page,'submit-review');await click(page,'review');assert.equal(content.status,'ready');
    await page.click('[data-action="confirm"][data-mode="advisor_proxy"]');await idle(page);assert.equal(f.state.confirmations.get(1).content_version,4);assert.match(await text(page),/顾问代确认/);
    await click(page,'publications');await click(page,'publication-attempts');assert.match(await text(page),/结果未知，需要人工/);assert.match(await text(page),/与当前稿件版本不同/);assert.match(await text(page),/人工登记回填（资格待接入）/);assert.equal(await page.$$('a[href^="/seo/"]').then(a=>a.length),0);
    assert(f.state.calls.filter(c=>c.path.includes('content-distribution')).every(c=>c.method==='GET'));assert(f.state.calls.filter(c=>['PATCH','POST'].includes(c.method)).every(c=>c.body.version_count>=3));assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    await page.setViewport({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  }finally{await browser.close();await f.close();}
});
test('UI09 stale save and unavailable publication read clear data and require explicit re-read',async()=>{
  const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
  try{
    f.state.contents.get(1).status='drafting';const page=await browser.newPage();await enter(page,f.origin);await click(page,'edit-content');f.state.contents.get(1).version_count++;
    await page.click('[data-action="save-content"]');await page.waitForFunction(()=>document.body.textContent.includes('内容状态或版本已变化'));assert.equal(await page.$$('#content-body').then(a=>a.length),0);assert.equal(f.state.calls.filter(c=>c.method==='PATCH').length,1);
    await click(page,'delivery');f.state.forceError={path:'/content-distribution/publications',status:503};await page.click('[data-action="publications"]');await page.waitForFunction(()=>document.body.textContent.includes('服务能力尚未启用'));assert.equal(await page.$$('[data-action="publication-attempts"]').then(a=>a.length),0);
    await click(page,'delivery');await click(page,'edit-content');f.state.forceError={path:'/content-assets/88',status:403};await page.click('[data-action="save-content"]');await page.waitForFunction(()=>document.body.textContent.includes('当前身份无权'));assert.equal(await page.$$('#content-body').then(a=>a.length),0);
  }finally{await browser.close();await f.close();}
});
