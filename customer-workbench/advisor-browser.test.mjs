import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {startFixtureServer} from './tests/fixture-server.mjs';
import os from 'node:os';
import path from 'node:path';
import {createAdvisorAutomationPanel} from './js/advisor-automation-panel.mjs';
const edge=process.env.EDGE_BINARY||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
test('advisor production UI isolates modules, paginates, clears revoked sessions and renders on desktop/mobile',async()=>{
 const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
 const origin='https://advisor.test',calls=[],errors=[],permissions={'seo.site':'edit','seo.content':'edit','seo.keywords':'edit','geo.assets':'edit','geo.content':'edit'};
 let moduleStatus={seo:200,geo:404},moduleCode={},empty=false,held=null;
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
   if(url.pathname.endsWith('/automation-projects'))return send({detail:{code:'not_integrated'}},404);
   if(url.pathname.endsWith('/advisor-tasks')){const module=url.pathname.includes('/geo/')?'geo':'seo';if(held&&module==='seo')await held;const id=url.searchParams.has('before_id')?76:77;return send(moduleStatus[module]!==200?{detail:{code:moduleCode[module]||'ADVISOR_ROUTE_UNAVAILABLE'}}:{schema:1,module,items:empty?[]:[row(module,id)],next_before_id:!empty&&id===77?77:null},moduleStatus[module]);}
   try{const r=await fetch(f.origin+url.pathname+url.search,{method:req.method(),headers:req.headers(),body:req.postData()});await req.respond({status:r.status,contentType:r.headers.get('content-type'),body:Buffer.from(await r.arrayBuffer())});}catch{await req.abort().catch(()=>{});}
  });
  await p.goto(origin+'/customer-workbench/?console=advisor');await p.waitForSelector('.advisor-task');
  assert(await p.$('.advisor-remote-host [data-remote-action="open"]'));
  assert(await p.$('.advisor-remote-host [data-remote-action="verify"]'));
  await p.waitForFunction(()=>document.body.textContent.includes('GEO 站内任务暂时读不到，其他模块不受影响')).catch(async error=>{error.message+=' · '+JSON.stringify({body:(await p.$eval('body',e=>e.textContent)).slice(0,1800),errors,calls});throw error;});
  await p.waitForFunction(()=>document.querySelector('.advisor-automation-section')?.textContent.includes('项目自动运行功能还没上线'));
  assert.equal(await p.$eval('.advisor-automation-section p',e=>e.textContent),'项目自动运行功能还没上线，目前不需要你操作。站内任务请看上面的「我的站内交付任务」。');
  assert(!await p.$('.advisor-automation-section button'));assert(!await p.$('.advisor-automation-section a'));
  assert.equal(await p.$$eval('.pc-pending',es=>es.length),0);
  assert.equal(await p.$$eval('.advisor-task',v=>v.length),1);assert(!calls.some(c=>c.path.includes('/tenants')));
  assert.equal(await p.$eval('.advisor-task a',v=>v.getAttribute('href')),'/customer-workbench/?tenant_id=2&site_id=19&onsite_task_id=77');
  assert.match(await p.$eval('.advisor-task',e=>e.textContent),/核实产品规格/);
  await p.click('[data-advisor=next][data-module=seo]');await p.waitForFunction(()=>document.body.textContent.includes('实际任务 76'));
  assert(calls.some(c=>c.query.before_id==='77'&&c.query.limit==='25'));assert(!await p.$('[data-advisor=next][data-module=seo]'));
  await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await p.screenshot({path:path.join(os.tmpdir(),'advisor-workbench-mobile-20261010.png'),fullPage:true});
  moduleStatus.geo=200;await p.click('[data-advisor=refresh]');await p.waitForFunction(()=>document.querySelectorAll('.advisor-task').length===2);
  await p.select('#advisor-module','geo');assert.equal(await p.$$eval('.pc-pending',es=>es.length),0);assert.equal(await p.$$eval('.advisor-automation-section',es=>es.length),1);assert.equal(await p.$$eval('.advisor-module',e=>e.length),1);assert.equal(await p.$eval('.advisor-task a',e=>e.getAttribute('href')),'/customer-workbench/?module=geo&tenant_id=2&project_id=10&onsite_task_id=77');
  await p.select('#advisor-module','all');moduleStatus.geo=403;await p.click('[data-advisor=refresh]');await p.waitForFunction(()=>document.body.textContent.includes('GEO 站内任务暂时读不到，其他模块不受影响'));await p.waitForSelector('[data-module=seo] .advisor-task');assert(await p.$('.advisor-automation-section'));
  moduleStatus.geo=200;moduleStatus.seo=403;await p.click('[data-advisor=refresh]');await p.waitForFunction(()=>document.body.textContent.includes('SEO 站内任务暂时读不到，其他模块不受影响'));await p.waitForSelector('[data-module=geo] .advisor-task');
  moduleStatus.seo=503;await p.click('[data-advisor=latest][data-module=seo]');await p.waitForFunction(()=>document.body.textContent.includes('SEO 站内任务暂时读不到，其他模块不受影响'));assert(await p.$('[data-module=geo] .advisor-task'));
  moduleStatus.seo=200;empty=true;await p.locator('[data-advisor=refresh]').click();await p.waitForFunction(()=>document.querySelectorAll('.advisor-module').length===2&&[...document.querySelectorAll('.advisor-module')].every(e=>e.textContent.includes('这个客户还没有分配给你的站内任务')));assert(!await p.$('.advisor-task'));empty=false;
  for(const [status,code] of [[403,'ADVISOR_GRANT_REVOKED'],[403,'ADVISOR_ROLE_CHANGED'],[401,null]]){
   moduleStatus.geo=200;await p.locator('[data-advisor=refresh]').click();await p.waitForFunction(()=>document.querySelectorAll('.advisor-task').length===2);
   moduleStatus.geo=status;moduleCode.geo=code;await p.locator('[data-advisor=latest][data-module=geo]').click();await p.waitForFunction(()=>document.body.textContent.includes('你的客户授权已变化，请重新选择客户'));assert(!await p.$('.advisor-task'));assert(!await p.$('.advisor-automation-section'));
   // Restore only the isolated browser fixture after the expired-session case.
   if(status===401)await p.evaluate(permissions=>sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token:'fixture-advisor',user:{id:7,tenant_id:null,display_name:'顾问',permissions}})),permissions);
  }
  moduleCode={};moduleStatus.geo=200;await p.reload();await p.waitForFunction(()=>document.querySelectorAll('.advisor-task').length===2);
  let release;held=new Promise(r=>release=r);await p.click('[data-advisor=latest][data-module=seo]');await p.click('[data-advisor=logout]');release();held=null;
  await p.waitForFunction(()=>document.body.textContent.includes('已退出'));assert(!await p.$('.advisor-task'));assert.equal(await p.evaluate(()=>sessionStorage.getItem('sem_auth_v1')),null);
  assert(calls.every(c=>c.method==='GET'));
  await p.goto(origin+'/customer-workbench/?console=advisor&login=1');await p.waitForSelector('#entry-login');await p.type('#entry-username','advisor');await p.type('#entry-password','fixture-only');await p.$eval('#entry-captcha',e=>e.value=document.querySelector('[data-entry=captcha]').textContent);await p.click('#entry-login [type=submit]');await p.waitForSelector('.advisor-task');assert.equal(new URL(p.url()).searchParams.get('console'),'advisor');
  permissions['seo.site']='view';permissions['geo.assets']='view';await p.reload();await p.waitForFunction(()=>document.body.textContent.includes('没有可用的顾问模块入口'));assert(!await p.$('.advisor-module'));assert(!calls.some(c=>c.method!=='GET'&&c.path!=='/api/v1/auth/login'));assert.deepEqual(errors,[]);
  assert(!await p.$('.advisor-automation-section'));assert(!calls.some(c=>c.path.includes('/automation-projects')));
 }finally{await browser.close();await f.close();}
});

test('automation notice waits for verified module access and clears on context change',async()=>{
 const paths=[],user={id:7,tenant_id:null,permissions:{'seo.site':'edit','seo.content':'edit','seo.keywords':'edit','geo.assets':'edit','geo.content':'edit'}};
 const session={user,token:'fixture-only',authRevision:0,logout(){}},listeners=[];
 let release,denied=0;
 const panel=createAdvisorAutomationPanel({session,subscribeSession:fn=>{listeners.push(fn);return()=>{};},browser:{clearTimeout(){}},onChange(){},onDenied(){denied++;},fetchImpl:async path=>{
  paths.push(path);
  if(path.endsWith('/me'))await new Promise(r=>release=r);
  return {ok:true,status:200,json:async()=>path.endsWith('/me')?{user}:{tenant_id:null,modules:[{module_code:'seo',available:true}]}};
 }});
 try{
  const loading=panel.initialize(['seo','geo']);assert.equal(panel.html(),'');release();await loading;
  assert.match(panel.html('seo'),/项目自动运行功能还没上线/);assert.equal(panel.html('geo'),'');assert.deepEqual(panel.assignedScopes(),[]);
  panel.click({target:{closest:()=>({dataset:{automationList:'seo'}})}});
  assert.deepEqual(paths,['/api/v1/auth/me','/api/v1/auth/modules']);
  session.authRevision++;listeners.forEach(fn=>fn());assert.equal(panel.html(),'');assert.equal(denied,1);
 }finally{panel.dispose();}
});
