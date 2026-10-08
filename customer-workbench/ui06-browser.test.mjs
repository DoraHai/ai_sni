import test from 'node:test';import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';import fs from 'node:fs';import {createHash} from 'node:crypto';
import {startFixtureServer} from './tests/fixture-server.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
const waitReady=page=>page.waitForFunction(()=>document.querySelector('[data-action="delivery"]')&&!document.querySelector('[data-action="delivery"]').disabled);
const text=page=>page.$eval('body',e=>e.textContent);

test('UI-06 pagination, read retries, no write replay, scope reset and three-module combinations',async()=>{
  const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true,args:['--no-first-run']});
  try{
    fixture.state.contentTotals.set(1,53);
    const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(fixture.origin+'/fixture.html');await waitReady(page);
    assert.match(await text(page),/第1页 \/ 共2页/);assert.equal(await page.$$eval('[data-action="delivery"]',nodes=>nodes.length),50);
    await page.click('[data-action="list-page"][data-number="2"]');await waitReady(page);
    assert.match(await text(page),/客户1第51篇稿件/);assert.equal(await page.$$eval('[data-action="delivery"]',nodes=>nodes.length),3);
    assert.equal(await page.$eval('[data-action="list-page"][data-number="3"]',e=>e.disabled),true);
    fixture.state.forceError={path:'/content-assets',status:500};await page.click('[data-action="refresh"]');
    await page.waitForFunction(()=>document.body.textContent.includes('读取失败'));assert(!(await text(page)).includes('客户1第51篇稿件'));
    await page.click('[data-action="refresh"]');await waitReady(page);assert.match(await text(page),/第2页 \/ 共2页/);
    fixture.state.contentTotals.set(1,0);await page.click('[data-action="refresh"]');await page.waitForFunction(()=>document.body.textContent.includes('列表已变化'));
    assert.equal(await page.$eval('[data-action="list-page"][data-number="1"]',e=>e.disabled),false);
    fixture.state.contentTotals.set(1,53);await page.click('[data-action="list-page"][data-number="1"]');await waitReady(page);
    fixture.state.forceError={path:'/delivery',status:503};await page.click('[data-action="delivery"]');await page.waitForFunction(()=>document.body.textContent.includes('服务能力尚未启用'));
    await page.click('[data-action="delivery"]');await page.waitForSelector('#delivery-body');
    fixture.state.forceError={path:'/confirmations',status:503};await page.click('[data-action="confirm"][data-mode="customer_direct"]');await page.waitForFunction(()=>document.body.textContent.includes('服务能力尚未启用'));
    const writes=fixture.state.calls.filter(c=>c.method==='POST').length;await page.click('[data-action="delivery"]');await page.waitForSelector('#delivery-body');assert.equal(fixture.state.calls.filter(c=>c.method==='POST').length,writes);
    await page.click('[data-action="page"][data-page="数据"]');await page.waitForFunction(()=>document.querySelector('.phase-row'));
    fixture.state.forceError={path:'/service-status',status:500};await page.click('[data-action="refresh"]');await page.waitForFunction(()=>document.body.textContent.includes('请求未完成'));
    assert(!(await text(page)).includes('fixture_count'));await page.click('[data-action="refresh"]');await page.waitForFunction(()=>document.querySelector('.phase-row'));
    await page.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('advisor'));await waitReady(page);await page.click('[data-action="list-page"][data-number="2"]');await waitReady(page);
    await page.evaluate(()=>WORKBENCH_TEST_HOST.selectTenant(2));await waitReady(page);assert.match(await text(page),/第1页 \/ 共1页/);assert(!(await text(page)).includes('客户1第51篇'));
    for(const modules of [['seo'],['sem'],['geo'],['sem','seo'],['seo','geo'],['sem','geo'],['sem','seo','geo']]){
      fixture.state.modules=modules;await page.reload();await page.waitForFunction(()=>!document.querySelector('[data-module="seo"]').textContent.includes('待核验'));
      for(const code of ['sem','geo']){
        assert.equal(await page.$eval(`[data-module="${code}"]`,e=>e.disabled),true);
        assert.match(await page.$eval(`[data-module="${code}"]`,e=>e.textContent),modules.includes(code)?/已开通 · 待接入/:/未开通/);
      }
      if(modules.includes('seo'))await waitReady(page);else assert.match(await text(page),/当前未开通SEO/);
    }
    await page.setViewport({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);assert(fixture.state.calls.some(c=>c.query.page==='2'));assert(fixture.state.calls.every(c=>!/^\/api\/v1\/(sem|geo)\//.test(c.path)));
  }finally{await browser.close();await fixture.close();}
});

test('UI-06 built artifact uses canonical session storage and dedicated same-origin login',async()=>{
  const manifest=JSON.parse(fs.readFileSync(new URL('./dist/customer-workbench/release-manifest.json',import.meta.url),'utf8'));
  for(const [name,meta] of Object.entries(manifest.files))assert.equal(createHash('sha256').update(fs.readFileSync(new URL('./dist/customer-workbench/'+name,import.meta.url))).digest('hex'),meta.sha256);
  assert.deepEqual(Object.keys(manifest.canonicalSources).sort(),['src/store/session.js','src/store/sessionStorage.js']);
  const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true,args:['--no-first-run']});
  try{
    const page=await browser.newPage(),external=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
    const origin='https://workbench.test';
    await page.setRequestInterception(true);
    page.on('request',async request=>{
      const url=new URL(request.url());
      if(url.origin!==origin){external.push(url.href);await request.abort();return;}
      if(url.pathname==='/login'){await request.respond({status:200,contentType:'text/html',body:'Existing login fixture'});return;}
      try {const response=await fetch(fixture.origin+url.pathname+url.search,{method:request.method(),headers:request.headers(),body:request.postData()});await request.respond({status:response.status,contentType:response.headers.get('content-type'),body:Buffer.from(await response.arrayBuffer())});}catch {await request.abort();}
    });
    const entry=origin+'/customer-workbench/?tenant_id=1&site_id=9';
    await page.goto(entry);await page.waitForSelector('#entry-login');assert.equal(fixture.state.calls.length,0);
    assert.equal(new URL(page.url()).origin,origin);assert.equal(new URL(page.url()).pathname,'/customer-workbench/');
    // Seed only the existing session envelope, with fixture identities. No new credential store.
    await page.evaluate(()=>sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token:'fixture-customer',user:{id:12,tenant_id:1,display_name:'夹具用户',permissions:{'seo.content':'view','seo.site':'view'}}})));
    await page.goto(entry);await waitReady(page);assert.match(await text(page),/契约服务器客户1稿件/);
    assert.equal(await page.evaluate(()=>typeof DEV_ADAPTER),'undefined');assert(!(await text(page)).includes('独立演示模式'));
    assert.deepEqual(await page.evaluate(()=>Object.keys(sessionStorage).sort()),['sem_auth_v1','sem_tenant_id']);assert.deepEqual(await page.evaluate(()=>Object.keys(localStorage)),[]);
    await page.goto(origin+'/customer-workbench/');await waitReady(page);assert.equal(new URL(page.url()).searchParams.get('site_id'),'9');assert(!await page.$('a[href="/workspace/cockpit"]'));
    await page.goto(entry);await waitReady(page);fixture.state.forceError={path:'/content-assets',status:401};await Promise.all([page.waitForNavigation(),page.click('.navigation [data-page="内容"]')]);
    assert.equal(new URL(page.url()).pathname,'/customer-workbench/');assert.equal(new URL(page.url()).searchParams.get('login'),'1');assert.equal(new URL(page.url()).searchParams.get('site_id'),'9');assert.equal(await page.evaluate(()=>sessionStorage.getItem('sem_auth_v1')),null);
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  }finally{await browser.close();await fixture.close();}
});
