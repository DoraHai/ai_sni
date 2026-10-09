import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {startFixtureServer} from './tests/fixture-server.mjs';
const edge='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const idle=p=>p.waitForFunction(()=>document.querySelector('#connected-message')?.textContent==='');
test('R12 home: real scoped reads, persistent dialogue, drilldown, missing data, responsive and identity clearing',async()=>{
 const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
 try{
  const p=await browser.newPage();await p.setViewport({width:1440,height:1000});
  f.state.keywords.get(1).forEach((r,i)=>Object.assign(r,{keyword:['工业齿轮箱','减速电机选型','输送设备驱动'][i%3]+(i+1),latest_rank:i%4===0?null:i+1,rank_delta:i%3-1,rank_checked_at:'2026-10-08T08:00:00Z',rank_is_stale:i===1}));
  let pagesFail=false;const writes=[];
  await p.setRequestInterception(true);p.on('request',r=>{
   const u=new URL(r.url());if(!u.pathname.startsWith('/api/')){void r.continue();return;}
   if(r.method()!=='GET')writes.push(u.pathname);
   const tenant=Number(u.searchParams.get('tenant_id')),site=Number(u.searchParams.get('site_id'));
   let value=null;
   if(u.pathname==='/api/v1/seo/site-pages'){
    if(pagesFail){void r.respond({status:503,contentType:'application/json',body:'{}'});return;}
    value={items:[{id:11,tenant_id:tenant,site_id:site,title:'产品选型与应用指南',status:'needs_fix',last_checked_at:'2026-10-08T08:00:00Z'}],total:1,page:1,page_size:20};
   }
   if(u.pathname==='/api/v1/seo/workbench/publication-page-evidence')value={tenant_id:tenant,site_id:site,read_only:true,items:[],total:0,page:1,page_size:20};
   if(value)void r.respond({status:200,contentType:'application/json',body:JSON.stringify(value)});else void r.continue();
  });
  await p.goto(f.origin+'/fixture.html');await idle(p);await p.waitForSelector('.home-kpis');
  await p.click('[data-assistant-action=mode-guide]');
  assert.equal(await p.$$('.home-metric').then(a=>a.length),6);
  assert.equal(await p.$eval('.workspace',e=>getComputedStyle(e).display),'grid');
  const positions=await p.evaluate(()=>({main:document.querySelector('.connected-main').getBoundingClientRect().right,chat:document.querySelector('.workbench-dialogue').getBoundingClientRect().left}));
  assert(positions.chat>positions.main,'Dialogue is alongside the main workspace');
  assert(await p.$('#workspace-question'));assert.match(await p.$eval('.home-page',e=>e.textContent),/关键词表现/);
  const panelWidth=()=>p.$eval('.workbench-dialogue',e=>e.getBoundingClientRect().width);
  assert.equal(await panelWidth(),440);
  const handle=await p.$eval('.assistant-resizer',e=>{const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+24};});
  await p.mouse.move(handle.x,handle.y);await p.mouse.down();await p.mouse.move(handle.x-100,handle.y,{steps:5});await p.mouse.up();
  assert.equal(await panelWidth(),540);
  await p.focus('.assistant-resizer');await p.keyboard.press('ArrowRight');assert.equal(await panelWidth(),516);
  await p.type('#workspace-question','草稿保留\n'.repeat(20));
  assert.equal(await p.$eval('#workspace-question',e=>e.getBoundingClientRect().height),200);
  const draft=await p.$eval('#workspace-question',e=>e.value);
  await p.click('[data-assistant-action=fullscreen]');
  assert(await p.$('.assistant-fullscreen'));assert((await panelWidth())>1400);
  assert.equal(await p.$eval('#workspace-question',e=>e.value),draft);
  await p.keyboard.press('Escape');assert.equal(await panelWidth(),516);
  await p.click('[data-assistant-action=fullscreen]');await p.click('[data-assistant-action=fullscreen]');assert.equal(await panelWidth(),516);
  await p.evaluate(()=>{const t=document.querySelector('#workspace-question');t.value='';t.dispatchEvent(new Event('input',{bubbles:true}));});
  assert.match(await p.$eval('.home-page',e=>e.textContent),/非全量状态统计/);
  assert.equal(await p.$eval('.home-metric[data-kind=keywords] strong',e=>e.textContent),'52');
  assert.equal(await p.$eval('.home-metric[data-page=交付记录] strong',e=>e.textContent),'0');
  await p.screenshot({path:path.join(tmpdir(),'workbench-r12-home-20261009.png'),fullPage:true});
  await p.click('[data-assistant-prompt="关键词表现怎么样？"]');assert.match(await p.$eval('.assistant-messages',e=>e.textContent),/52 个关键词/);
  await p.click('.assistant-messages [data-action=home-data]');await idle(p);
  assert.match(await p.$eval('#page',e=>e.textContent),/关键词排名/);
  assert(await p.$('#workspace-question'),'Dialogue survives page navigation');
  await p.click('.navigation [data-page=首页]');await idle(p);
  await p.click('[data-action=delivery]');await p.waitForSelector('.conversation');
  assert(await p.$('#workspace-question'));assert(await p.$('#conversation-draft'),'Existing advisor messaging remains available');
  await p.click('.navigation [data-page=首页]');await idle(p);
  await p.type('#workspace-question','不要泄露的本地未发送问题');
  await p.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('advisor'));await idle(p);
  assert.equal(await p.$eval('#workspace-question',e=>e.value),'');
  assert.equal(await p.$$('.assistant-messages .user').then(a=>a.length),0);
  pagesFail=true;await p.click('[data-action=refresh]');await idle(p);
  assert.match(await p.$eval('.home-alert',e=>e.textContent),/网站页面读取失败/);
  assert.equal(await p.$eval('.home-metric[data-kind=pages] strong',e=>e.textContent),'—','Missing page count must not become zero');
  assert.equal(await p.$eval('.home-metric[data-kind=keywords] strong',e=>e.textContent),'52','A failed block must not erase independent successful reads');
  await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await p.click('[data-assistant-action=fullscreen]');assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await p.click('[data-assistant-action=fullscreen]');
  await p.click('[data-assistant-action=collapse]');assert.equal(await p.$eval('.assistant-expanded',e=>e.hidden),true);
  await p.screenshot({path:path.join(tmpdir(),'workbench-r12-mobile-20261009.png'),fullPage:true});
  assert.equal(writes.length,0,'Browsing and local guide must never write business data');
 }finally{await browser.close();await f.close();}
});
