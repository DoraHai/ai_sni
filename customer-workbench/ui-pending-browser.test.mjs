import scanFixtures from './tests/pending-scan-fixtures.json' with {type:'json'};
import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {existsSync} from 'node:fs';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {pendingAdmin as admin,pendingSnapshot,pendingGovernance} from './tests/pending-page-fixture.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
test('production-shaped pending controls remain visible at 1440 and 390, even when governance GET succeeds',async()=>{
 const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
 const errors=[],writes=[],external=[],automationReads=[];let governance=pendingGovernance(),snapshot=pendingSnapshot();
 try{for(const width of [1440,390]){
  const p=await browser.newPage();await p.setViewport({width,height:width===390?844:900,isMobile:width===390,hasTouch:width===390});
  await p.evaluateOnNewDocument(user=>sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token:'fixture-admin',user})),admin);
  p.on('pageerror',e=>errors.push(e.message));await p.setRequestInterception(true);
  p.on('request',async r=>{
   const u=new URL(r.url());if(u.protocol==='data:')return r.continue();if(u.origin!==f.origin){external.push(u.href);return r.abort();}
   if(!u.pathname.startsWith('/api/'))return r.continue();
   if(r.method()!=='GET'){writes.push(u.pathname);return r.abort();}
   const send=(data,status=200)=>r.respond({status,contentType:'application/json',body:JSON.stringify(data)});
   if(u.pathname.endsWith('/auth/me'))return send({user:admin});
   if(u.pathname.endsWith('/snapshot'))return send(snapshot);
   if(u.pathname.endsWith('/ai-governance'))return send(governance);
   if(u.pathname.endsWith('/automation-health')){automationReads.push(u.pathname);return send({},404);}
   return send({},404);
  });
  await p.goto(f.origin+'/customer-workbench/?console=platform');await p.waitForSelector('.pc-kpis');
  const open=async page=>{await p.waitForNetworkIdle({idleTime:100});await p.locator(`.pc-sidebar [data-pc-page="${page}"]`).click();await p.waitForFunction(id=>document.querySelector('.pc-sidebar .active')?.dataset.pcPage===id,{},page);await p.waitForNetworkIdle({idleTime:100});};
  for(const [page,text] of [['ai-governance','治理策略编辑暂未接入'],['controls','管理功能等待启用'],['config','配置管理尚未启用'],['alerts','处理记录等待数据库审核启用']]){
   await open(page);await p.waitForFunction(text=>document.querySelector('.pc-content')?.textContent.includes(text),{},text);
   assert.equal(await p.$$eval('.pc-main > .pc-pending',els=>els.length),page==='controls'?1:0,`${page} ${width}`);
   assert(await p.$$eval('.pc-content .pending-badge',els=>els.length)>0,`${page} has a capability badge`);
   if(page==='controls')assert(await p.$eval('.pc-pending',e=>e.nextElementSibling.classList.contains('pc-kpis')));
  }
  await open('ai-governance');assert.match(await p.$eval('.pc-content',e=>e.textContent),/等待数据库人工审核启用/);
  assert(await p.$$eval('.pc-content button',els=>els.find(e=>e.textContent==='治理策略编辑暂未接入').disabled));
  await open('automation-ops');
  assert.equal(await p.$eval('.pc-content [role=status]',e=>e.textContent),'项目自动运行功能还没上线，目前没有运行记录可查，也不需要你启用。顾问请到顾问工作台的「我的站内交付任务」处理站内任务。');
  assert(!await p.$('[data-pc=automation-refresh]'));assert(!await p.$('.pc-content a'));assert.deepEqual(automationReads,[]);
  // A page outside the target set must not inherit a pending badge from the sidebar.
  await open('overview');assert.equal(await p.$$eval('.pc-pending',els=>els.length),0);

  // Every supervisor menu: recorded c880be02 response shape, with no page-key allowlist in production.
  for(const key of await p.$$eval('.pc-sidebar [data-pc-page]',es=>es.map(e=>e.dataset.pcPage))){
   await open(key);await new Promise(r=>setTimeout(r,150));
   if(key==='automation-ops')await p.waitForFunction(()=>document.querySelector('.pc-content').textContent.includes('项目自动运行功能还没上线'));
   assert.equal(await p.$$eval('.pc-main > .pc-pending',es=>es.length),key==='controls'?1:0,`full-menu ${key} ${width}`);
   if(['apis','ai-governance','controls','config','alerts','tasks','security'].includes(key))assert(await p.$$eval('.pc-content .pending-badge',es=>es.length)>0,`block ${key} ${width}`);
   const target=scanFixtures.find(row=>row.area==='supervisor'&&row.page===key);const titles=await p.$$eval('.pc-content .pending-badge',es=>es.map(e=>e.parentElement.textContent));for(const feature of target.expected_pending_features)assert(titles.some(t=>t.includes(feature)),`scanned block ${key}: ${feature}`);
  }
  await p.close();
 }}finally{await browser.close();await f.close();}
 assert.deepEqual({errors,writes,external,automationReads},{errors:[],writes:[],external:[],automationReads:[]});
});
