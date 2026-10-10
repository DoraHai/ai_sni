import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {startFixtureServer} from './tests/fixture-server.mjs';
import os from 'node:os';
import path from 'node:path';
const edge=process.env.EDGE_BINARY||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
test('advisor production UI isolates modules, paginates, clears revoked sessions and renders on desktop/mobile',async()=>{
 const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
 const origin='https://advisor.test',calls=[],errors=[],permissions={'seo.site':'edit','seo.content':'edit','seo.keywords':'edit','geo.assets':'edit','geo.content':'edit'};
 let moduleStatus={seo:200,geo:404},held=null;
 const row=(module,id)=>({id,module,tenant_id:2,scope_id:module==='seo'?19:10,title:'实际任务 '+id,workflow:{module,revision:2,phase:id===77?'review':'implementation',month:'2026-10',owner_name:'实施人员',items:[],ai_proposal:{summary:'核实产品规格',missing_information:['规格依据']},history:[]},allowed_actions:['approve'],next_action:'人工核实',blocker:'待审核',capabilities:{website_execution:{enabled:false}}});
 try{
  const p=await browser.newPage();p.on('pageerror',e=>errors.push(e.message));await p.setViewport({width:1440,height:1000});
  await p.evaluateOnNewDocument(permissions=>sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token:'fixture-advisor',user:{id:7,tenant_id:null,display_name:'顾问',permissions}})),permissions);
  await p.setRequestInterception(true);p.on('request',async req=>{
   const url=new URL(req.url());if(url.protocol==='data:')return req.continue();if(url.origin!==origin)return req.abort();
   const send=(data,status=200)=>req.respond({status,contentType:'application/json',body:JSON.stringify(data)});
   if(url.pathname.startsWith('/api/'))calls.push({path:url.pathname,query:Object.fromEntries(url.searchParams),method:req.method()});
   if(url.pathname==='/api/v1/auth/login')return send({token:'fixture-advisor',user:{id:7,tenant_id:null,display_name:'顾问',permissions}});
   if(url.pathname==='/api/v1/auth/me')return send({user:{id:7,tenant_id:null,display_name:'顾问',permissions}});
   if(url.pathname==='/api/v1/auth/modules')return send({tenant_id:null,modules:['seo','geo'].map(module_code=>({module_code,available:true}))});
   if(url.pathname.endsWith('/advisor-tasks')){const module=url.pathname.includes('/geo/')?'geo':'seo';if(held&&module==='seo')await held;const id=url.searchParams.has('before_id')?76:77;return send({schema:1,module,items:[row(module,id)],next_before_id:id===77?77:null},moduleStatus[module]);}
   try{const r=await fetch(f.origin+url.pathname+url.search,{method:req.method(),headers:req.headers(),body:req.postData()});await req.respond({status:r.status,contentType:r.headers.get('content-type'),body:Buffer.from(await r.arrayBuffer())});}catch{await req.abort().catch(()=>{});}
  });
  await p.goto(origin+'/customer-workbench/?console=advisor');await p.waitForSelector('.advisor-task');await p.waitForFunction(()=>document.body.textContent.includes('未接入'));
  assert.equal(await p.$$eval('.advisor-task',v=>v.length),1);assert(!calls.some(c=>c.path.includes('/tenants')));
  assert.equal(await p.$eval('.advisor-task a',v=>v.getAttribute('href')),'/customer-workbench/?tenant_id=2&site_id=19&onsite_task_id=77');
  assert.match(await p.$eval('.advisor-task',e=>e.textContent),/核实产品规格/);
  await p.click('[data-advisor=next][data-module=seo]');await p.waitForFunction(()=>document.body.textContent.includes('实际任务 76'));
  assert(calls.some(c=>c.query.before_id==='77'&&c.query.limit==='25'));assert(!await p.$('[data-advisor=next][data-module=seo]'));
  await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await p.screenshot({path:path.join(os.tmpdir(),'advisor-workbench-mobile-20261010.png'),fullPage:true});
  moduleStatus.geo=200;await p.click('[data-advisor=refresh]');await p.waitForFunction(()=>document.querySelectorAll('.advisor-task').length===2);
  await p.select('#advisor-module','geo');assert.equal(await p.$$eval('.advisor-module',e=>e.length),1);assert.equal(await p.$eval('.advisor-task a',e=>e.getAttribute('href')),'/customer-workbench/?module=geo&tenant_id=2&project_id=10&onsite_task_id=77');
  await p.select('#advisor-module','all');moduleStatus.geo=403;await p.click('[data-advisor=refresh]');await p.waitForFunction(()=>document.body.textContent.includes('全部列表已清除'));assert(!await p.$('.advisor-task'));
  moduleStatus.geo=200;await p.click('[data-advisor=refresh]');await p.waitForSelector('.advisor-task');
  let release;held=new Promise(r=>release=r);await p.click('[data-advisor=latest][data-module=seo]');await p.click('[data-advisor=logout]');release();held=null;
  await p.waitForFunction(()=>document.body.textContent.includes('已退出'));assert(!await p.$('.advisor-task'));assert.equal(await p.evaluate(()=>sessionStorage.getItem('sem_auth_v1')),null);
  assert(calls.every(c=>c.method==='GET'));
  await p.goto(origin+'/customer-workbench/?console=advisor&login=1');await p.waitForSelector('#entry-login');await p.type('#entry-username','advisor');await p.type('#entry-password','fixture-only');await p.$eval('#entry-captcha',e=>e.value=document.querySelector('[data-entry=captcha]').textContent);await p.click('#entry-login [type=submit]');await p.waitForSelector('.advisor-task');assert.equal(new URL(p.url()).searchParams.get('console'),'advisor');
  permissions['seo.site']='view';permissions['geo.assets']='view';await p.reload();await p.waitForFunction(()=>document.body.textContent.includes('没有可用的顾问模块入口'));assert(!await p.$('.advisor-module'));assert(!calls.some(c=>c.method!=='GET'&&c.path!=='/api/v1/auth/login'));assert.deepEqual(errors,[]);
 }finally{await browser.close();await f.close();}
});
