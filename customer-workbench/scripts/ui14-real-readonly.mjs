// Authorized, read-only UI14 checks against the isolated backend handoff.
import assert from 'node:assert/strict';import fs from 'node:fs/promises';import {existsSync} from 'node:fs';import path from 'node:path';import os from 'node:os';import puppeteer from 'puppeteer-core';
import {startLocalBackendHost} from './local-backend-host.mjs';
if(process.env.UI12_REAL_API_AUTHORIZED!=='true')throw Error('Coordinator authorization and verified backend handoff required');
const config=JSON.parse(await fs.readFile(process.env.UI12_CONFIG_FILE,'utf8')),mode='observe',positive=n=>Number.isSafeInteger(n)&&n>0;
assert(config.environment_kind==='isolated-local-pg'&&config.database&&config.schema&&config.external_operations_disabled===true,'Verified isolated environment with external operations disabled required');
assert([config.tenant_id,config.site_id].every(positive),'Synthetic scope required');assert(['workflow','revoked','observe','inspect-inputs','verify-feedback','publication-tail'].includes(mode),'Unknown scenario mode');
const imageId=Number(process.env.UI14_IMAGE_CONTENT_ID);assert(positive(imageId),'Use the image content ID from the SEO handoff');
const output=await fs.mkdtemp(path.join(os.tmpdir(),'workbench-ui14-readonly-'));
const report={mode,result:'failed',backend:config.backend_origin,database:config.database,schema:config.schema,backendCommit:config.backend_commit??null,externalAdapters:config.external_adapters??null,boundary:'Real browser business API requests; synthetic accounts/data. External publication fact simulated, no public AI/crawl/publish verification.',cases:[]};
const host=await startLocalBackendHost({backendOrigin:config.backend_origin});report.buildCommit=host.manifest.upstreamCommit;report.sourceTreeClean=host.manifest.sourceTreeClean;report.localSourceHashes=host.manifest.localSources;
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
const errors=[],external=[];let browser;report.screenshots=[];
async function capture(page,name){const target=path.join(output,name+'.png');await page.screenshot({path:target,fullPage:true});report.screenshots.push({name,path:target,viewport:page.viewport()});}
const selector=action=>`[data-action="${action}"]`,idle=page=>page.waitForFunction(()=>document.querySelector('#connected-message')?.textContent==='',{polling:50,timeout:20000});
async function click(page,css){await page.waitForFunction(s=>{const e=document.querySelector(s);return e&&!e.disabled;},{polling:50,timeout:20000},css);await page.click(css);await idle(page);}
const nav=(page,name)=>click(page,`.navigation [data-page="${name}"]`);
const set=(page,css,value)=>page.$eval(css,(e,v)=>{e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}));},value);
async function responseAction(page,css,method,pathname,expected=200){
  await page.waitForFunction(s=>{const e=document.querySelector(s);return e&&!e.disabled;},{polling:50,timeout:20000},css);
  const pending=page.waitForResponse(r=>r.request().method()===method&&new URL(r.url()).pathname===pathname,{timeout:20000});
  const [response]=await Promise.all([pending,page.click(css)]);assert.equal(response.status(),expected,`${method} ${pathname}`);
  const data=await response.json();if(expected<400)await idle(page);return data;
}
async function login(role){
  const account=config[role];assert(account?.username&&account?.password,'Synthetic credentials missing: '+role);
  const context=await browser.createBrowserContext(),page=await context.newPage();page.setDefaultTimeout(20000);await page.setViewport({width:1440,height:1000});
  page.on('pageerror',e=>errors.push(e.message));await page.setRequestInterception(true);
  page.on('request',async request=>{const url=new URL(request.url());if(['http:','https:'].includes(url.protocol)&&url.origin!==host.origin){external.push(url.origin);await request.abort();}else await request.continue();});
  await page.goto(host.origin+`/customer-workbench/?tenant_id=${config.tenant_id}&site_id=${config.site_id}`);await page.waitForSelector(selector('login'));
  await Promise.all([page.waitForNavigation(),page.click(selector('login'))]);await page.type('[name="username"]',account.username);await page.type('[name="password"]',account.password);
  await Promise.all([page.waitForNavigation(),page.click('form button')]);await page.waitForSelector('.summary-grid');await idle(page);return page;
}
async function openContent(page,id){
  await nav(page,'内容');let found=false;
  for(let attempt=0;attempt<20;attempt++){
    const current=await page.$eval('#pagination-summary',e=>Number(e.textContent.match(/第(\d+)页/)[1]));if(current===1)break;
    await click(page,`[data-action="list-page"][data-number="${current-1}"]`);
  }
  for(let attempt=0;attempt<20;attempt++){
    if(await page.$(`[data-action="delivery"][data-id="${id}"]`)){found=true;break;}
    // Use the server-backed rendered pagination; never add a synthetic row or internal-ID input.
    const current=await page.$eval('#pagination-summary',e=>Number(e.textContent.match(/第(\d+)页/)[1]));
    const candidates=await page.$$eval('[data-action="list-page"]',rows=>rows.filter(e=>!e.disabled).map(e=>Number(e.dataset.number)));
    const nextPage=candidates.find(n=>n===current+1);if(!nextPage)break;
    await click(page,`[data-action="list-page"][data-number="${nextPage}"]`);
  }
  assert(found,'Seed content not found in rendered authorized list: '+id);
  return responseAction(page,`[data-action="delivery"][data-id="${id}"]`,'GET',`/api/v1/seo/workbench/content-assets/${id}/delivery`);
}
try{
 browser=await puppeteer.launch({executablePath:edge,headless:true,args:[`--ignore-certificate-errors-spki-list=${host.spki}`]});
 for(const role of ['customer','advisor']){
  const page=await login(role);await capture(page,role+'-home-large');assert.match(await page.$eval('#page',e=>e.textContent),/还有稿件未核对/);assert.match(await page.$eval('.summary-grid',e=>e.textContent),/仅覆盖本次 8 篇/);
  await nav(page,'内容');await set(page,'#content-query','UI14-20261008');const first=await responseAction(page,selector('content-search'),'GET','/api/v1/seo/content-assets');assert.equal(first.total,60);assert.equal(first.items.length,50);const second=await responseAction(page,'[data-action="list-page"][data-number="2"]','GET','/api/v1/seo/content-assets');assert.equal(second.items.length,10);await capture(page,role+'-content-page2');
  const selected=second.items.find(v=>(v.humanized_content||v.draft||'').includes('<img'))||second.items[0];const css=`[data-action="delivery"][data-id="${selected.id}"]`;await page.$eval(css,e=>e.scrollIntoView({block:'center'}));const y=await page.evaluate(()=>scrollY);await click(page,css);await capture(page,role+'-content-detail');await click(page,selector('return-list'));assert.match(await page.$eval('#pagination-summary',e=>e.textContent),/第2页/);assert.equal(await page.$eval('#content-query',e=>e.value),'UI14-20261008');await new Promise(r=>setTimeout(r,80));assert(Math.abs(await page.evaluate(()=>scrollY)-y)<100,'Content return position');
  await nav(page,'数据');await set(page,'#data-q','UI14-20261008');await page.select('#data-status','');const keywordFirst=await responseAction(page,selector('data-search'),'GET','/api/v1/seo/keywords');assert.equal(keywordFirst.total,45);await click(page,'[data-action="data-page"][data-number="2"]');await capture(page,role+'-keywords-page2');const keywordButton=(await page.$$('[data-action="data-keyword-detail"]')).at(-1);await keywordButton.evaluate(e=>e.scrollIntoView({block:'center'}));const ky=await page.evaluate(()=>scrollY);await keywordButton.click();await idle(page);await click(page,selector('return-list'));assert.match(await page.$eval('.data-scope',e=>e.textContent),/第 2 页/);await new Promise(r=>setTimeout(r,80));assert(Math.abs(await page.evaluate(()=>scrollY)-ky)<100,'Keyword return position');
  await nav(page,'进度');await click(page,'[data-action="execution-page"][data-number="2"]');await capture(page,role+'-tasks-page2');await click(page,selector('execution-detail'));await click(page,selector('return-list'));assert.match(await page.$eval('#execution-count',e=>e.textContent),/第2页/);
  await nav(page,'内容');await set(page,'#content-query','UI14-20261008');await click(page,selector('content-search'));const found=[];for(let i=0;i<2;i++){const ids=await page.$$eval('[data-action="delivery"][data-id]',els=>els.map(e=>Number(e.dataset.id)));found.push(...ids);if(i===0)await click(page,'[data-action="list-page"][data-number="2"]');}
  // The authorized batch identifies its image-bearing content; no arbitrary ID input is exposed in the UI.
  assert(found.includes(imageId));await openContent(page,imageId);await page.waitForFunction(()=>document.querySelectorAll('[data-media-state=loaded]').length>=1&&document.querySelectorAll('[data-media-state=failed]').length>=1);await capture(page,role+'-images');await page.click('[data-media-action=open]');await capture(page,role+'-image-original');await page.click('[data-media-action=close]');await page.click('[data-media-action=retry]');await page.waitForFunction(()=>document.querySelector('[data-media-state=failed]'));await page.setViewport({width:390,height:844});await capture(page,role+'-images-mobile');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.click('[data-media-action=open]');await capture(page,role+'-image-original-mobile');await page.keyboard.press('Escape');
  report.cases.push({name:role+'-large-lists-return-and-media',contentTotal:60,keywordTotal:45,imageId,result:'passed'});
 }
 assert(host.calls.every(c=>c.method==='GET'||c.path==='/api/v1/auth/login'),'Read-only scenario');assert.deepEqual(errors,[]);assert.deepEqual(external,[]);report.result='passed';
}catch(error){report.error=error.message;report.browserErrors=errors;for(const page of await browser.pages()){if(new URL(page.url()).pathname==='/customer-workbench/'){report.failureText=await page.$eval('body',e=>e.textContent);await capture(page,'failure-'+report.screenshots.length);}}throw error;}finally{report.calls=host.calls;await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({output,result:report.result,error:report.error}));await browser?.close();await host.close();}
