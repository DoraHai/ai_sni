import assert from 'node:assert/strict';import fs from 'node:fs/promises';import {existsSync} from 'node:fs';import path from 'node:path';import os from 'node:os';import puppeteer from 'puppeteer-core';
import {startLocalBackendHost} from './local-backend-host.mjs';
assert.equal(process.env.UI15_REAL_API_AUTHORIZED,'true','Explicit isolated-message acceptance authorization required');
const config=JSON.parse(await fs.readFile(process.env.UI12_CONFIG_FILE,'utf8')),contentId=Number(process.env.UI15_CONTENT_ID),secondarySite=Number(process.env.UI15_SECONDARY_SITE_ID);
assert(config.environment_kind==='isolated-local-pg'&&config.external_operations_disabled===true);assert(Number.isSafeInteger(contentId)&&contentId>0,'Use only the content ID in the UI15 backend handoff');
const output=await fs.mkdtemp(path.join(os.tmpdir(),'workbench-ui15-real-')),host=await startLocalBackendHost({backendOrigin:config.backend_origin});
const readOnly=process.env.UI15_READ_ONLY==='true';
const report={result:'failed',mode:readOnly?'read-only':'messages',backendCommit:config.backend_commit,buildCommit:host.manifest.upstreamCommit,sourceTreeClean:host.manifest.sourceTreeClean,contentId,cases:[],screenshots:[],messageWrites:[]};
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync),errors=[],external=[];let browser;
const stem=`/api/v1/seo/workbench/content-assets/${contentId}/conversation`,tag='UI15 browser '+new Date().toISOString();
const idle=page=>page.waitForFunction(()=>{const b=document.querySelector('[data-chat-action=refresh]');return b&&!b.disabled;},{timeout:20000});
const screenshot=async(page,name)=>{const file=path.join(output,name+'.png');await page.screenshot({path:file,fullPage:true});report.screenshots.push({name,path:file});};
async function openContent(page){
  await page.waitForSelector('.navigation');await page.click('.navigation [data-page="内容"]');await page.waitForFunction(()=>document.querySelector('#connected-message')?.textContent==='');
  for(let i=0;i<10;i++){
    const button=await page.$(`[data-action=delivery][data-id="${contentId}"]`);if(button){await button.click();await idle(page);return;}
    const next=await page.$('[data-action=list-page]:nth-child(2)');if(!next||await next.evaluate(e=>e.disabled))break;
    await next.click();await page.waitForFunction(()=>document.querySelector('#connected-message')?.textContent==='');
  }throw Error('Authorized UI15 content not found through actual list');
}
async function login(role){
  const context=await browser.createBrowserContext(),page=await context.newPage();page.setDefaultTimeout(20000);await page.setViewport({width:1440,height:1000});page.on('pageerror',error=>errors.push(error.message));
  await page.evaluateOnNewDocument(()=>{const original=window.fetch;window.fetch=async(url,options)=>{const response=await original(url,options);if(window.__ui15LoseSendResponse&&options?.method==='POST'&&new URL(url,location.href).pathname.endsWith('/conversation/messages')){window.__ui15LoseSendResponse=false;await response.clone().json();throw TypeError('Synthetic loss after server response');}return response;};});
  await page.setRequestInterception(true);page.on('request',async request=>{const url=new URL(request.url());if(['data:','blob:'].includes(url.protocol)){await request.continue();return;}if(url.origin!==host.origin){external.push(url.href);await request.abort();return;}if(request.method()==='POST'&&url.pathname.endsWith('/conversation/messages')){const body=JSON.parse(request.postData());report.messageWrites.push({role,requestId:body.request_id,text:body.body});}await request.continue();});
  await page.goto(host.origin+'/customer-workbench/?'+new URLSearchParams({tenant_id:config.tenant_id,site_id:config.site_id}));await page.waitForSelector('[data-action=login]');await Promise.all([page.waitForNavigation(),page.click('[data-action=login]')]);
  await page.type('[name=username]',config[role].username);await page.type('[name=password]',config[role].password);await Promise.all([page.waitForNavigation(),page.click('form button')]);await page.waitForSelector('.summary-grid');await openContent(page);return page;
}
async function send(page,text,lose=false){await page.type('#conversation-draft',text);if(lose)await page.evaluate(()=>window.__ui15LoseSendResponse=true);await page.click('[data-chat-action=send]');await idle(page);}
async function refresh(page){await page.click('[data-chat-action=refresh]');await idle(page);}
async function signalWait(name){const file=path.join(output,name);const until=Date.now()+300000;while(Date.now()<until){if(existsSync(file))return;await new Promise(r=>setTimeout(r,500));}throw Error('Timed out awaiting SEO handoff '+name);}
try{
  browser=await puppeteer.launch({executablePath:edge,headless:true,args:[`--ignore-certificate-errors-spki-list=${host.spki}`]});
  const customer=await login('customer'),advisor=await login('advisor');
  assert.equal(await customer.$eval('.conversation',e=>e.open),false);assert.equal(host.calls.filter(c=>c.path.endsWith('/conversation/read')).length,0);await screenshot(customer,'customer-folded');
  for(const page of [customer,advisor])await page.click('.conversation summary');
  const initial=await customer.$$eval('.conversation-message',els=>els.map(e=>Number(e.dataset.messageId)));
  assert.equal(initial.length,20,'SEO handoff should provide more than one page');assert.equal(await customer.$eval('[data-chat-action=older]',e=>e.disabled),false);await customer.click('[data-chat-action=older]');await idle(customer);assert((await customer.$$('.conversation-message')).length>20);assert.equal(host.calls.filter(c=>c.path.endsWith('/conversation/read')).length,0);report.cases.push('history paging and no automatic read');
  if(!readOnly){
  await send(customer,tag+' 客户意见');assert.equal(await customer.$eval('#conversation-draft',e=>e.value),'');await refresh(advisor);assert.match(await advisor.$eval('.conversation-messages',e=>e.textContent),new RegExp(tag+' 客户意见'));
  await send(advisor,tag+' 顾问回复');await refresh(customer);assert((await customer.$eval('.conversation-messages',e=>e.textContent)).includes(tag+' 顾问回复'));report.cases.push('both real identities send and receive');
  await send(customer,tag+' 幂等恢复',true);assert.equal(await customer.$eval('#conversation-draft',e=>e.value),tag+' 幂等恢复');assert.match(await customer.$eval('.conversation-feedback',e=>e.textContent),/结果未确认/);await screenshot(customer,'customer-retained-failure');
  await customer.click('[data-chat-action=send]');await idle(customer);assert.equal(await customer.$eval('#conversation-draft',e=>e.value),'');
  assert.equal(await customer.$$eval('.conversation-message p',(els,text)=>els.filter(e=>e.textContent===text).length,tag+' 幂等恢复'),1);
  const retry=report.messageWrites.filter(w=>w.text===tag+' 幂等恢复');assert.equal(retry.length,2);assert.equal(retry[0].requestId,retry[1].requestId);report.cases.push('lost successful response recovered with same key and one rendered record');
  await customer.click('[data-chat-action=read]');await idle(customer);assert(!await customer.$eval('.conversation summary',e=>e.textContent.includes('未读')));report.cases.push('explicit user read only');
  }
  const expected=process.env.UI15_EXPECTED_TEXT||tag+' 幂等恢复';
  await customer.reload();await customer.waitForSelector('.summary-grid');await openContent(customer);await customer.click('.conversation summary');assert((await customer.$eval('.conversation-messages',e=>e.textContent)).includes(expected));await customer.waitForFunction(()=>{const e=document.querySelector('.conversation-messages');return e&&Math.abs(e.scrollHeight-e.clientHeight-e.scrollTop)<3;});await screenshot(customer,'customer-durable-desktop');
  await customer.setViewport({width:390,height:844});await refresh(customer);assert.equal(await customer.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await screenshot(customer,'customer-durable-mobile');report.cases.push('reload persistence and 390px layout');
  if(Number.isSafeInteger(secondarySite)&&secondarySite>0){
    await advisor.type('#conversation-draft','UI15切范围必须清除');advisor.once('dialog',d=>d.accept());await advisor.goto(host.origin+'/customer-workbench/?'+new URLSearchParams({tenant_id:config.tenant_id,site_id:secondarySite}));await advisor.waitForFunction(()=>document.querySelector('.summary-grid')||document.body.textContent.includes('当前身份无权'));assert(!await advisor.$('#conversation-draft'));assert(!await advisor.$('.conversation-message'));await screenshot(advisor,'advisor-other-scope');
    await advisor.goto(host.origin+'/customer-workbench/?'+new URLSearchParams({tenant_id:config.tenant_id,site_id:config.site_id}));await advisor.waitForSelector('.summary-grid');await openContent(advisor);await advisor.click('.conversation summary');assert.equal(await advisor.$eval('#conversation-draft',e=>e.value),'');report.cases.push('scope navigation clears prior message input');
  }
  if(!readOnly&&process.env.UI15_REVOKE_HANDSHAKE==='true'){
    await advisor.type('#conversation-draft','UI15撤权必须清除');await fs.writeFile(path.join(output,'revocation-ready.json'),JSON.stringify({contentId,tenantId:config.tenant_id,siteId:config.site_id}));console.log(JSON.stringify({phase:'ready-for-seo-revoke',output}));
    await signalWait('revoked.json');await advisor.click('[data-chat-action=refresh]');await advisor.waitForFunction(()=>document.body.textContent.includes('权限已失效'));assert(!await advisor.$('#conversation-draft'));assert(!await advisor.$('.conversation-message'));await screenshot(advisor,'advisor-revoked');
    await fs.writeFile(path.join(output,'revocation-tested.json'),'{}');console.log(JSON.stringify({phase:'ready-for-seo-restore',output}));await signalWait('restored.json');await advisor.reload();await advisor.waitForSelector('.summary-grid');await openContent(advisor);report.cases.push('real advisor revocation clears text and history, restored session reads again');
  }
  if(readOnly)assert(host.calls.every(c=>c.method==='GET'||c.path==='/api/v1/auth/login'),'Read-only follow-up cannot replay messages/read');
  assert(host.calls.every(c=>c.method==='GET'||c.path==='/api/v1/auth/login'||c.method==='POST'&&[stem+'/messages',stem+'/read'].includes(c.path)),'Only authorized message actions and login may write');assert.deepEqual(external,[]);assert.deepEqual(errors,[]);report.result='passed';
}catch(error){report.error=error.message;if(browser)for(const page of await browser.pages())if(new URL(page.url()).pathname==='/customer-workbench/')await screenshot(page,'failure-'+report.screenshots.length);throw error;}
finally{report.calls=host.calls;await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({output,result:report.result,error:report.error}));await browser?.close();await host.close();}
