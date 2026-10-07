// Preparation only until SEO delivers the verified isolated backend and coordinator authorization applies.
import assert from 'node:assert/strict';import fs from 'node:fs/promises';import {existsSync} from 'node:fs';import path from 'node:path';import os from 'node:os';import puppeteer from 'puppeteer-core';
import {startLocalBackendHost} from './local-backend-host.mjs';
if(process.env.UI12_REAL_API_AUTHORIZED!=='true')throw Error('Coordinator authorization and verified backend handoff required');
const config=JSON.parse(await fs.readFile(process.env.UI12_CONFIG_FILE,'utf8')),mode=process.argv[2]||'workflow',positive=n=>Number.isSafeInteger(n)&&n>0;
assert(config.environment_kind==='isolated-local-pg'&&config.database&&config.schema&&config.external_operations_disabled===true,'Verified isolated environment with external operations disabled required');
assert([config.tenant_id,config.site_id].every(positive),'Synthetic scope required');assert(['workflow','revoked','observe','inspect-inputs','verify-feedback'].includes(mode),'Unknown scenario mode');
const seed=config.scenarios??{};
if(mode==='workflow'){
  assert([seed.draft_content_id,seed.proxy_content_id].every(positive)&&seed.draft_content_id!==seed.proxy_content_id,'Separate drafting and ready content seeds required');
  assert(Array.isArray(seed.task_ids)&&seed.task_ids.length>0&&seed.task_ids.every(positive),'Known synthetic task IDs required');
  assert(config.publication?.synthetic===true&&config.publication.page_url&&config.publication.published_local_time,'Explicit simulated publication fact required');
}else if(mode==='revoked')assert(positive(seed.revocation_content_id),'Unpublished ready content required for revoked advisor check');
const output=await fs.mkdtemp(path.join(os.tmpdir(),'workbench-ui12-scenarios-'));
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
async function edit(page,id,note){
  const before=await openContent(page,id);assert(['planned','drafting'].includes(before.content.status),'Expected editable seeded draft');
  await click(page,selector('edit-content'));const text=await page.$eval('#content-body',e=>e.value);await set(page,'#content-body',text+'\n'+note);
  const saved=await responseAction(page,selector('save-content'),'PATCH',`/api/v1/seo/content-assets/${id}`);assert.equal(saved.version_count,before.content.version_count+1);return saved;
}
async function review(page,id){
  const submitted=await responseAction(page,selector('submit-review'),'POST',`/api/v1/seo/content-assets/${id}/submit-review`);assert.equal(submitted.status,'review');
  const approved=await responseAction(page,selector('review'),'POST',`/api/v1/seo/content-assets/${id}/review`);assert.equal(approved.status,'ready');return approved;
}
async function confirm(page,id,actorMode){
  const data=await responseAction(page,`[data-action="confirm"][data-mode="${actorMode}"]`,'POST',`/api/v1/seo/workbench/content-assets/${id}/confirmations`);
  assert.equal(data.confirmation.status,'approved');assert.equal(data.confirmation.latest.actor_mode,actorMode);assert.equal(data.confirmation.latest.content_version,data.content.version_count);assert.equal(data.confirmation.latest.payload_hash,data.content.payload_hash);return data;
}
async function manualForm(page){
  await click(page,'[data-action="manual-open"]:not([data-id])');await set(page,'#manual-platform',config.publication.platform_name||'UI12合成发布事实');await set(page,'#manual-url',config.publication.page_url);await set(page,'#manual-time',config.publication.published_local_time);await page.click('#manual-verified');
}
try{
  browser=await puppeteer.launch({executablePath:edge,headless:true,args:[`--ignore-certificate-errors-spki-list=${host.spki}`]});
  const advisor=await login('advisor');
  if(mode==='verify-feedback'){
    const customer=await login('customer'),data=await openContent(customer,seed.draft_content_id);assert.equal(data.confirmation.status,'stale');assert.equal(data.confirmation.latest.decision,'reject');
    const text=await customer.$eval('#page',e=>e.textContent);assert.match(text,/客户本人退回/);assert.match(text,/对应旧版本，当前版本尚未确认/);assert.equal((await customer.$$('.confirmed')).length,0);await capture(customer,'customer-historical-rejection-corrected');
    await customer.setViewport({width:390,height:844});await capture(customer,'customer-historical-rejection-corrected-mobile');
    assert(host.calls.every(c=>c.method==='GET'||c.path==='/api/v1/auth/login'));report.cases.push({name:'historical_rejection_label_and_neutral_color',contentId:data.content.id,currentVersion:data.content.version_count,historicalVersion:data.confirmation.latest.content_version,result:'passed'});
  }else if(mode==='inspect-inputs'){
    let dialogs=0;advisor.on('dialog',async dialog=>{dialogs++;await dialog.dismiss();});
    await nav(advisor,'数据');for(const level of ['L1','L2','L3']){await click(advisor,`[data-action="level"][data-level="${level}"]`);await capture(advisor,'advisor-data-'+level);}
    await nav(advisor,'服务计划');const originalPlan=await advisor.$eval('#plan-note',e=>e.value),marker='UI12仅浏览器未保存输入';await set(advisor,'#plan-note',marker);await capture(advisor,'plan-unsaved-before-navigation');
    await nav(advisor,'进度');await nav(advisor,'服务计划');const afterPlan=await advisor.$eval('#plan-note',e=>e.value);await capture(advisor,'plan-after-navigation');report.cases.push({name:'unsaved_plan_navigation',retained:afterPlan===marker,restoredServerValue:afterPlan===originalPlan,dialogs,result:'observed'});
    await openContent(advisor,seed.draft_content_id);await click(advisor,selector('edit-content'));const originalBody=await advisor.$eval('#content-body',e=>e.value);await set(advisor,'#content-body',originalBody+'\n'+marker);await capture(advisor,'draft-unsaved-before-navigation');
    await nav(advisor,'进度');await openContent(advisor,seed.draft_content_id);await click(advisor,selector('edit-content'));const afterBody=await advisor.$eval('#content-body',e=>e.value);await capture(advisor,'draft-after-navigation');report.cases.push({name:'unsaved_draft_navigation',retained:afterBody.includes(marker),restoredServerValue:afterBody===originalBody,dialogs,result:'observed'});
    assert(host.calls.every(c=>c.method==='GET'||c.path==='/api/v1/auth/login'),'Inspection must not write business data');
  }else if(mode==='observe'){
    for(const [role,page] of [['advisor',advisor],['customer',await login('customer')]]){
      for(const [name,label] of [['首页','home'],['内容','content-list'],['服务计划','plan'],['进度','progress-list'],['数据','data']]){await nav(page,name);await capture(page,role+'-'+label);}
      const content=await openContent(page,seed.draft_content_id);await capture(page,role+'-current-content');report.cases.push({name:'read_current_content',role,contentId:content.content.id,version:content.content.version_count,status:content.content.status,confirmation:content.confirmation.status,result:'observed'});
      if(role==='advisor'){
        await openContent(page,seed.proxy_content_id);const records=await responseAction(page,selector('publications'),'GET','/api/v1/seo/content-distribution/publications');await capture(page,'advisor-publication-readback');report.cases.push({name:'read_publications_after_unknown_write',ids:records.items.map(v=>v.id),items:records.items.map(v=>({id:v.id,status:v.status,source_version:v.source_version})),result:'observed'});
        for(const taskId of seed.task_ids){await nav(page,'进度');const task=await responseAction(page,`[data-action="execution-detail"][data-id="${taskId}"]`,'GET',`/api/v1/seo/workbench/executions/${taskId}`);await capture(page,'advisor-task-'+taskId);report.cases.push({name:'read_task',taskId,status:task.status,phase:task.params?.phase,result:'observed'});}
      }else{await page.setViewport({width:390,height:844});await capture(page,'customer-content-mobile');report.cases.push({name:'mobile_horizontal_overflow',overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),result:'observed'});}
    }
    assert(host.calls.every(c=>c.method==='GET'||c.path==='/api/v1/auth/login'),'Observe mode must not write business data');
  }else if(mode==='revoked'){
    const data=await openContent(advisor,seed.revocation_content_id);assert.equal(data.content.status,'ready');assert.equal(data.permission_basis.active_site_advisor_assignment,false);assert.equal(data.allowed_actions.confirm_as_advisor_proxy,false);
    for(const css of ['[data-action="confirm"][data-mode="advisor_proxy"]',selector('edit-content'),'[data-action="manual-open"]:not([data-id])'])assert.equal(await advisor.$eval(css,e=>e.disabled),true);
    assert(host.calls.every(c=>c.method==='GET'||c.path==='/api/v1/auth/login'));await capture(advisor,'revoked-advisor');report.cases.push({name:'revoked_assignment_after_reload',contentId:data.content.id,result:'passed',limit:'No in-flight revocation race asserted; assignment revoked by SEO before this invocation.'});
  }else{
    const customer=await login('customer'),id=seed.draft_content_id;
    const saved=await edit(advisor,id,'UI12合成联调：顾问轻改');await review(advisor,id);await openContent(customer,id);
    assert.equal(await customer.$eval(selector('edit-content'),e=>e.disabled),true);assert.equal(await customer.$eval('[data-action="confirm"][data-mode="advisor_proxy"]',e=>e.disabled),true);
    const approved=await confirm(customer,id,'customer_direct');assert.equal(approved.content.version_count,saved.version_count);await capture(customer,'customer-confirmed');
    report.cases.push({name:'advisor_edit_review_customer_confirm',contentId:id,version:saved.version_count,hash:approved.content.payload_hash,actor:approved.confirmation.latest.actor_user_id,result:'passed'});
    await openContent(advisor,seed.proxy_content_id);const proxy=await confirm(advisor,seed.proxy_content_id,'advisor_proxy');
    report.cases.push({name:'advisor_proxy_confirmation',contentId:seed.proxy_content_id,version:proxy.content.version_count,actor:proxy.confirmation.latest.actor_user_id,result:'passed'});
    // Leave an exact-version manual registration form open, then change the version through legal UI actions.
    await openContent(advisor,id);const beforeRecords=await responseAction(advisor,selector('publications'),'GET','/api/v1/seo/content-distribution/publications');await manualForm(advisor);await capture(advisor,'manual-form-exact-version');const editor=await login('advisor');
    await set(customer,'#decision-note','UI12合成联调：退回后验证旧登记版本冲突');await responseAction(customer,'[data-action="reject"][data-mode="customer_direct"]','POST',`/api/v1/seo/workbench/content-assets/${id}/confirmations`);
    const changed=await edit(editor,id,'UI12合成联调：并发新版本');assert(changed.version_count>saved.version_count);
    const conflict=await responseAction(advisor,selector('manual-save'),'POST','/api/v1/seo/content-distribution/publications/manual',409);assert.equal(conflict.detail?.code,'content_version_conflict');
    await advisor.waitForFunction(()=>document.querySelector('#connected-message')?.textContent.includes('稿件版本已变化'),{polling:50});assert.equal(await advisor.$('#manual-url'),null);await capture(advisor,'manual-version-conflict');
    const writeCount=host.calls.filter(c=>c.path.endsWith('/publications/manual')).length;await openContent(advisor,id);const afterRecords=await responseAction(advisor,selector('publications'),'GET','/api/v1/seo/content-distribution/publications');assert.deepEqual(afterRecords.items.map(v=>v.id),beforeRecords.items.map(v=>v.id));
    assert.equal(host.calls.filter(c=>c.path.endsWith('/publications/manual')).length,writeCount);report.cases.push({name:'manual_registration_version_conflict_no_replay',contentId:id,oldVersion:saved.version_count,currentVersion:changed.version_count,status:409,result:'passed'});
    await openContent(advisor,seed.proxy_content_id);await manualForm(advisor);
    const receipt=await responseAction(advisor,selector('manual-save'),'POST','/api/v1/seo/content-distribution/publications/manual');assert.equal(receipt.source_version,proxy.content.version_count);assert.equal(receipt.status,'published');await capture(advisor,'manual-registration-result');
    report.cases.push({name:'manual_registration_simulated_external_fact',contentId:receipt.content_id,publicationId:receipt.id,version:receipt.source_version,pageVerification:receipt.page_verification,result:'passed'});
    for(const taskId of seed.task_ids){await nav(advisor,'进度');const task=await responseAction(advisor,`[data-action="execution-detail"][data-id="${taskId}"]`,'GET',`/api/v1/seo/workbench/executions/${taskId}`);await capture(advisor,'task-'+taskId+'-progress');report.cases.push({name:'persisted_task_detail',taskId,status:task.status,phase:task.params?.phase,completionBasis:task.completion_evidence?.completion_basis??null,result:'passed'});}
  }
  assert.equal(errors.length,0,'Browser JS errors');assert.equal(external.length,0,'Unexpected external browser requests');report.result='passed';
}catch(error){report.error=error.name==='TimeoutError'?'Timed out waiting for scenario UI/API; inspect method/path/status trace':error.message;process.exitCode=1;}
finally{
  if(report.result!=='passed'&&browser)for(const [index,page] of (await browser.pages()).entries())if(await page.$('#page'))await capture(page,'failure-page-'+index).catch(()=>{});
  report.apiCalls=host.calls;report.browserErrors=errors;report.externalOrigins=external;await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
  if(browser)await browser.close();await host.close();console.log(JSON.stringify({result:report.result,report:path.join(output,'report.json')},null,2));
}
