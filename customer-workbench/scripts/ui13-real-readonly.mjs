// Preparation only until SEO delivers the verified isolated backend and coordinator authorization applies.
import assert from 'node:assert/strict';import fs from 'node:fs/promises';import {existsSync} from 'node:fs';import path from 'node:path';import os from 'node:os';import puppeteer from 'puppeteer-core';
import {startLocalBackendHost} from './local-backend-host.mjs';
if(process.env.UI12_REAL_API_AUTHORIZED!=='true')throw Error('Coordinator authorization and verified backend handoff required');
const config=JSON.parse(await fs.readFile(process.env.UI12_CONFIG_FILE,'utf8')),mode='observe',positive=n=>Number.isSafeInteger(n)&&n>0;
assert(config.environment_kind==='isolated-local-pg'&&config.database&&config.schema&&config.external_operations_disabled===true,'Verified isolated environment with external operations disabled required');
assert([config.tenant_id,config.site_id].every(positive),'Synthetic scope required');assert(['workflow','revoked','observe','inspect-inputs','verify-feedback','publication-tail'].includes(mode),'Unknown scenario mode');
const seed=config.scenarios??{};
if(['workflow','publication-tail'].includes(mode)){
  assert([seed.draft_content_id,seed.proxy_content_id].every(positive)&&seed.draft_content_id!==seed.proxy_content_id,'Separate drafting and ready content seeds required');
  assert(Array.isArray(seed.task_ids)&&seed.task_ids.length>0&&seed.task_ids.every(positive),'Known synthetic task IDs required');
  assert(config.publication?.synthetic===true&&config.publication.page_url&&config.publication.published_local_time,'Explicit simulated publication fact required');
}else if(mode==='revoked')assert(positive(seed.revocation_content_id),'Unpublished ready content required for revoked advisor check');
const output=await fs.mkdtemp(path.join(os.tmpdir(),'workbench-ui13-readonly-'));
const report={mode,result:'failed',backend:config.backend_origin,database:config.database,schema:config.schema,backendCommit:config.backend_commit??null,externalAdapters:config.external_adapters??null,boundary:'Real browser business API requests; synthetic accounts/data. External publication fact simulated, no public AI/crawl/publish verification.',cases:[]};
const host=await startLocalBackendHost({backendOrigin:config.backend_origin});report.buildCommit=host.manifest.upstreamCommit;
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
  await Promise.all([page.waitForNavigation(),page.click('form button')]);await page.waitForSelector('#pagination-summary');return page;
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
    const page=await login(role);
    await nav(page,'服务计划');await capture(page,role+'-plan');
    await openContent(page,seed.draft_content_id);await capture(page,role+'-draft');
    await openContent(page,seed.proxy_content_id);await click(page,selector('publications'));await capture(page,role+'-publication');
    if(role==='customer'){
      assert.equal(await page.$('[data-action="edit-content"]'),null);assert.equal(await page.$('[data-action="manual-open"]'),null);
      await page.setViewport({width:390,height:844});await capture(page,'customer-publication-mobile');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await nav(page,'服务计划');await capture(page,'customer-plan-mobile');
    }else{
      await nav(page,'服务计划');await set(page,'#plan-note','UI13只修改浏览器输入，不提交');let dialogs=0;page.on('dialog',d=>{dialogs++;void d.dismiss();});await nav(page,'进度');assert.equal(dialogs,1);assert.equal(await page.$eval('#plan-note',e=>e.value),'UI13只修改浏览器输入，不提交');await capture(page,'advisor-unsaved-plan-retained');
    }
    report.cases.push({name:role+'-readonly-role-layout',result:'passed'});
  }
  assert(host.calls.every(c=>c.method==='GET'||c.path==='/api/v1/auth/login'),'No business writes');assert.deepEqual(errors,[]);assert.deepEqual(external,[]);report.result='passed';
}catch(error){report.error=error.message;throw error;}finally{report.calls=host.calls;await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({output,result:report.result,error:report.error}));await browser?.close();await host.close();}
