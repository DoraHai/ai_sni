import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {distributionContentDigest} from './js/distribution-client.mjs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
const edge=process.env.EDGE_BINARY||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const base='/api/distribution/v1',origin='https://distribution.test';
const deviceId='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',bindingId='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const scope={module:'seo',tenant_id:4,scope_id:19};
const permissions={'seo.site':'edit','seo.content':'edit'};
const user={id:7,tenant_id:null,display_name:'合成顾问',permissions};
const content={version:'seo_variant_11_r1',title:'合成审核稿 <script>',body:'合成正文，等待人工执行。',assets:[]};
const source={schema:1,...scope,variant_id:11,platform:'wechat-article',source_revision:content.version,content,
  content_digest:await distributionContentDigest(content)};
const channel=()=>({platform:'wechat-article',content_type:'article',label:'公众号文章',mode:'manual',enabled:false,revision:0,executable:false,automated_publish:false,real_channel_verified:false,automatic_steps:['队列登记'],manual_steps:['正式发布','公开作品核验'],reason:'NOT_AUTHORIZED'});
const schedule=()=>({binding_id:bindingId,policy:{enabled:true,timezone:'Asia/Shanghai',min_interval_seconds:600,daily_limit:5,
  windows:[{start:0,end:1440}],revision:1,paused_reason:null},restriction:null,as_of:Date.now(),reason:'READY',next_allowed_at:Date.now(),
  available:true,system_used_today:0,system_remaining:5,platform_remaining:null,platform_quota_state:'unverified',
  reservation_task_id:null,effective_daily_limit:5,effective_interval_seconds:600});
async function pageHarness(user,consoleName,handler){
  const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
  const page=await browser.newPage(),errors=[],calls=[];
  page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>dialog.accept());
  await page.evaluateOnNewDocument(user=>sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token:'synthetic-browser',user})),user);
  await page.setRequestInterception(true);page.on('request',async req=>{
    const url=new URL(req.url());if(['data:','blob:'].includes(url.protocol))return req.continue();if(url.origin!==origin)return req.abort();
    if(url.pathname.startsWith('/api/')){
      const body=req.postData()?JSON.parse(req.postData()):null;calls.push({path:url.pathname,method:req.method(),body});
      assert.equal(req.headers().authorization,'Bearer synthetic-browser');
      let result=url.pathname===base+'/plans'?{value:{schema:1,...scope,automated_publish:false,items:[{id:deviceId,queue_id:deviceId,binding_id:bindingId,draft_version:'draft_1',source_revision:'rev_1',planned_at:1,checked_at:1,basis:'rules',state:'planned',reason:'AI_INVALID_OUTPUT'}],requests:[{id:deviceId,state:'failed',reason:'AI_INVALID_OUTPUT',attempts:1,retry_at:300000,updated_at:1}]}}:await handler(url,req.method(),body);
      if((!result||result.status===404)&&url.pathname===base+'/platform-directory')result={value:{schema:1,...scope,items:['wechat-official','wechat-channels','xiaohongshu','zhihu','bilibili','douyin','weibo','linkedin','toutiao','baijiahao','kuaishou','website'].map(platform_id=>({platform_id,label:platform_id,content_types:platform_id==='wechat-channels'?['video']:platform_id==='zhihu'?['answer']:['article'],v1_platform:null,native_intake:false,automatic_publish:false,real_channel_verified:false,status:platform_id==='website'?'reserved':'not-integrated',missing:['能力证明待接线']}))}};
      if((!result||result.status===404)&&url.pathname===base+'/execution-progress')result={value:{schema:1,...scope,automatic_publish:false,items:[],permissions:[],waits:[]}};
      return req.respond({status:result?.status||200,contentType:result?.mediaType||'application/json',body:result?.raw||JSON.stringify(result?.value||{})});
    }
    try{const response=await fetch(fixture.origin+url.pathname+url.search);await req.respond({status:response.status,
      contentType:response.headers.get('content-type'),body:Buffer.from(await response.arrayBuffer())});}catch{await req.abort().catch(()=>{});}
  });
  return {page,errors,calls,open:()=>page.goto(origin+'/customer-workbench/?console='+consoleName),
    close:async()=>{await browser.close();await fixture.close();}};
}

test('built advisor verifies a reported publication and retries only native writeback with explicit checks',async()=>{
  const taskId='cccccccc-cccc-4ccc-8ccc-cccccccccccc',checkId='dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  const image=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a17sAAAAASUVORK5CYII=','base64');
  const frozenContent={...content,assets:[{id:'reviewed_1',mediaType:'image/png',bytes:image.length,sha256:createHash('sha256').update(image).digest('hex')}]};
  const frozenSource={...source,content:frozenContent,content_digest:await distributionContentDigest(frozenContent)};
  let publication={check:null,writeback:null},denied=false,checks=0,retries=0,monitorReads=0;
  const task=()=>({id:taskId,...scope,binding_id:bindingId,device_id:deviceId,account_id:'synthetic-account',variant_id:11,
    platform:'wechat-article',source_revision:content.version,action:'publish',status:'succeeded',created_at:Date.now(),
    grant_expires_at:Date.now()+3600000,revoked:true,receipt:null,
    resolution:{outcome:'published',checked_at:Date.now(),public_url:'https://mp.weixin.qq.com/s/test'},publication});
  const f=await pageHarness(user,'advisor',async(url,method,body)=>{
    if(url.pathname==='/api/v1/auth/me')return {value:{user}};
    if(url.pathname==='/api/v1/auth/modules')return {value:{tenant_id:null,modules:[{module_code:'seo',available:true}]}};
    if(url.pathname.endsWith('/automation-projects'))return {status:404};
    if(url.pathname.endsWith('/advisor-tasks'))return {value:{schema:1,module:'seo',next_before_id:null,items:[{
      id:77,...scope,tenant_name:'合成客户',scope_name:'合成官网',title:'任务',workflow:{module:'seo',revision:1,phase:'review',items:[],history:[]},allowed_actions:[],capabilities:{website_execution:{enabled:false}}}]}};
    if(url.pathname.startsWith(base)&&denied)return {status:403};
    if(url.pathname===base+'/scope')return {value:{schema:1,...scope,project:{...scope,state:'paused',revision:2,owner_user_id:7},bindings:[{id:bindingId,
      device_id:deviceId,account_id:'synthetic-account',platform:'wechat-article',active:true,device_label:'合成设备',last_seen_at:null}],
      capabilities:{automated_publish:false,human_handoff:true,real_channel_verified:false}}};
    if(url.pathname===base+'/tasks')return {value:{schema:1,...scope,items:[task()]}};
    if(url.pathname===base+'/publication-source')return {value:{...frozenSource,task_id:taskId,external_account_id:'gh_test'}};
    if(url.pathname===base+'/publication-assets/'+taskId+'/reviewed_1')return {raw:image,mediaType:'image/png'};
    if(url.pathname===base+'/sources')return {value:{schema:1,...scope,platform:'wechat-article',items:[]}};
    if(url.pathname===base+'/events')return {value:{schema:1,...scope,items:[]}};
    if(url.pathname===base+'/account-schedules')return {value:{schema:1,...scope,items:[schedule()]}};
    if(url.pathname===base+'/publication-check'){
      assert.equal(body.expected_public_url,'https://mp.weixin.qq.com/s/test');checks++;
      publication.check={id:checkId,task_id:taskId,actor_id:7,mode:body.mode,public_url:body.expected_public_url,
        reported_at:Date.now(),checked_at:Date.now(),status:body.mode==='human'?'verified':'needs-human',
        code:body.mode==='human'?'ADVISOR_CONFIRMED_PUBLIC_CONTENT':'ACCOUNT_UNVERIFIED',verification:body.mode==='human'?'human-verified':null};
      if(body.mode==='human'){
        assert(body.confirm_public_access&&body.confirm_target_account&&body.confirm_approved_content);
        publication.writeback={event_id:checkId,state:'pending',attempts:1,updated_at:Date.now(),code:'WRITEBACK_UNAVAILABLE',result:null};
      }
      return {value:{schema:1,...scope,task_id:taskId,publication}};
    }
    if(url.pathname===base+'/publication-writeback'){
      retries++;assert.equal(body.event_id,checkId);publication.writeback={...publication.writeback,state:'written',attempts:2,
        code:'WRITEBACK_WRITTEN',result:{module:'seo',publication_id:55,monitor_state:'pending',verification:'human-verified',idempotent:false}};
      return {value:{schema:1,...scope,task_id:taskId,publication}};
    }
    if(url.pathname===base+'/publication-monitor'){
      assert.equal(method,'GET');monitorReads++;
      return {value:{schema:1,...scope,task_id:taskId,as_of:Date.now(),monitor:{module:'seo',publication_id:55,
        basis:'page-capture',state:monitorReads===1?'pending':'captured',evidence_source:monitorReads===1?'auto':'manual',
        observed_at:monitorReads===1?null:Date.now(),next_check_at:null,evidence_id:88,code:monitorReads===1?'CAPTURE_PENDING':'MANUAL_CAPTURE'}}};
    }
    return {status:404};
  });
  try{
    const p=f.page;await f.open();await p.waitForSelector('[data-publication]');
    const expand=()=>p.$eval('[data-publication]',e=>e.parentElement.open=true);await expand();
    assert.equal(await p.$eval('[data-distribution=check-human]',e=>e.disabled),true);assert.equal(checks,0);
    await p.click('[data-distribution=check-machine]');await p.waitForFunction(()=>document.querySelector('[data-distribution-panel]')?.textContent.includes('平台账号身份尚未核验'));
    await expand();await p.click('[data-distribution=publication-preview]');await p.waitForSelector('[data-distribution=check-human]:not([disabled])');
    await expand();await p.waitForFunction(()=>[...document.querySelectorAll('[data-publication] img')].some(i=>i.complete&&i.naturalWidth===1));
    const frozenImageUrl=await p.$eval('[data-publication] img',i=>i.src);
    await expand();await p.click('[data-distribution=check-human]');assert.equal(checks,1);await expand();
    await expand();for(const name of ['publication_public','publication_account','publication_content'])await p.click(`[name=${name}]`);
    await p.click('[data-distribution=check-human]');await p.waitForSelector('[data-distribution=retry-writeback]:not([disabled])');
    await expand();await p.click('[data-distribution=retry-writeback]');await p.waitForFunction(()=>document.querySelector('[data-distribution-panel]')?.textContent.includes('发布记录 #55'));
    assert.equal(checks,2);assert.equal(retries,1);assert(!f.calls.some(c=>c.method==='POST'&&c.path===base+'/tasks'));
    assert.equal(await p.evaluate(async url=>{try{await fetch(url);return true;}catch{return false;}},frozenImageUrl),false);
    await expand();await p.click('[data-distribution=monitor-status]');await p.waitForFunction(()=>document.querySelector('[data-distribution-panel]')?.textContent.includes('最新页面截图检查：等待检查'));
    await expand();await p.click('[data-distribution=monitor-status]');await p.waitForFunction(()=>document.querySelector('[data-distribution-panel]')?.textContent.includes('人工上传证据'));
    assert.equal(monitorReads,2);assert.equal(checks,2);assert.equal(retries,1);
    assert.match(await p.$eval('[data-distribution-panel]',e=>e.textContent),/首次登记：待原模块检查/);
    await p.setViewport({width:390,height:844});await expand();assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await p.screenshot({path:path.join(os.tmpdir(),'distribution-publication-advisor-mobile-20261011.png'),fullPage:true});
    denied=true;await p.click('[data-distribution=refresh]');await p.waitForFunction(()=>!document.querySelector('[data-publication]'));
    assert(!await p.$('[href="https://mp.weixin.qq.com/s/test"]'));assert.deepEqual(f.errors,[]);
    assert.doesNotMatch(await p.$eval('[data-distribution-panel]',e=>e.textContent),/人工上传证据/);
  }finally{await f.close();}
});

test('built advisor distribution reviews the approved draft, gates publication, pauses and clears revoked data',async()=>{
  let project={...scope,state:'paused',revision:0,owner_user_id:null},items=[],denied=false,unknownWrite=false,account=schedule(),selected=false,selectionRevision=0,handoffPermissions=[];
  const f=await pageHarness(user,'advisor',async(url,method,body)=>{
    const pathname=url.pathname;
    if(pathname==='/api/v1/auth/me')return {value:{user}};
    if(pathname==='/api/v1/auth/modules')return {value:{tenant_id:null,modules:[{module_code:'seo',available:true}]}};
    if(pathname.endsWith('/automation-projects'))return {status:404};
    if(pathname.endsWith('/advisor-tasks'))return {value:{schema:1,module:'seo',next_before_id:null,items:[{
      id:77,...scope,tenant_name:'合成客户',scope_name:'合成官网',title:'站内人工验收',workflow:{module:'seo',revision:1,phase:'review',items:[],history:[]},
      allowed_actions:[],capabilities:{website_execution:{enabled:false}}}]}};
    if(pathname.startsWith(base)&&denied)return {status:403};
    if(pathname===base+'/scope')return {value:{schema:1,...scope,project,bindings:[{id:bindingId,device_id:deviceId,
      account_id:'synthetic-account',platform:'wechat-article',active:true,device_label:'合成设备',last_seen_at:null}],
      capabilities:{automated_publish:false,human_handoff:true,real_channel_verified:false}}};
    if(pathname===base+'/execution-progress')return {value:{schema:1,...scope,automatic_publish:false,items:[],waits:[],permissions:handoffPermissions}};
    if(pathname===base+'/handoff-permission'){
      assert.equal(body.confirm_reviewed_handoff,true);assert.equal(body.stage,'handoff');assert(!('confirm_manual_publication' in body));
      handoffPermissions=[{binding_id:bindingId,enabled:body.enabled,stage:'handoff',revision:body.expected_revision+1}];return {value:{schema:1,permission:handoffPermissions[0]}};}
    if(pathname===base+'/sources')return {value:{schema:1,...scope,platform:'wechat-article',items:[{
      variant_id:11,source_revision:content.version,title:content.title,platform:'wechat-article'}]}};
    if(pathname===base+'/source')return {value:source};
    if(pathname===base+'/events')return {value:{schema:1,...scope,items:[]}};
    if(pathname===base+'/account-schedules')return {value:{schema:1,...scope,items:[account]}};
    if(pathname===base+'/project-channels')return {value:{schema:1,...scope,items:[{binding_id:bindingId,account_id:'synthetic-account',selected,revision:selectionRevision,capability:channel()}]}};
    if(pathname===base+'/project-channel'){
      assert.equal(body.binding_id,bindingId);assert.equal(body.expected_revision,selectionRevision);assert.equal(body.content_type,'article');
      selected=body.enabled;selectionRevision++;return {value:{schema:1,selection:{binding_id:bindingId,enabled:selected,revision:selectionRevision}}};}
    if(pathname===base+'/queue')return {value:{schema:1,...scope,completed_draft_events_connected:false,
      items:selected?[{id:deviceId,binding_id:bindingId,variant_id:11,draft_version:'draft_1',source_revision:null,platform:'wechat-article',state:'awaiting-review',reason:'geo_distribution_review_pending',next_allowed_at:null,created_at:Date.now(),checked_at:Date.now()}]:[],
      scans:[{binding_id:bindingId,state:'checked',reason:'SCANNED',checked_at:Date.now(),discovery:'completed-draft-polling'}]}};
    if(pathname===base+'/account-restriction'){
      assert.equal(body.daily_limit,2);assert.equal(body.min_interval_seconds,1200);
      account={...account,restriction:{revision:1,daily_limit:2,min_interval_seconds:1200},effective_daily_limit:2,effective_interval_seconds:1200};
      return {value:{schema:1,schedule:account}};
    }
    if(pathname==='/api/distribution/handoff/v1/advisor/resolution'){
      assert.equal(body.content_digest,source.content_digest);assert(body.confirm_platform_checked&&body.confirm_executor_stopped&&body.confirm_no_publication);
      items[0].status='failed';items[0].revoked=true;items[0].handoff_resolution={outcome:'not-published',checked_at:Date.now()};
      return {value:{handoffVersion:1,task_id:body.task_id,outcome:'not-published',checked_at:Date.now(),evidence:'advisor-reported',result:'HANDOFF_NOT_PUBLISHED',publicationVerified:false}};
    }
    if(pathname==='/api/distribution/handoff/v1/advisor/retry'){
      assert(body.confirm_executor_stopped&&body.confirm_no_publication);assert.equal(body.content_digest,source.content_digest);assert(!('confirm_manual_publication' in body));
      items.push({...items[0],id:crypto.randomUUID(),handoff_attempt:2,status:'queued',revoked:false,handoff_resolution:null});
      return {value:{handoffVersion:1,task_id:items.at(-1).id,previous_task_id:body.task_id,attempt:2,result:'HANDOFF_REDISPATCHED',publicationVerified:false}};
    }
    if(pathname===base+'/task-resolution'){
      assert.equal(body.confirm_platform_checked,true);assert.equal(body.confirm_executor_stopped,true);assert.equal(body.outcome,'not-published');
      items[0].status='failed';items[0].revoked=true;items[0].resolution={outcome:body.outcome,checked_at:Date.now(),public_url:null};
      return {value:{schema:1,task_id:body.task_id,...items[0].resolution,evidence:'advisor-reported'}};
    }
    if(pathname===base+'/control'){
      assert.equal(body.expected_revision,project.revision);
      project={...project,state:{start:'running',pause:'paused',resume:'running',end:'ended'}[body.action],revision:project.revision+1,owner_user_id:7};
      return {value:{schema:1,project}};
    }
    if(pathname===base+'/tasks'&&method==='POST'){
      assert.equal(body.expected_digest,source.content_digest);assert.equal(body.confirm_reviewed_content,true);
      if(body.action==='publish')assert.equal(body.confirm_manual_publication,true);
      assert(!('content' in body));
      if(unknownWrite)return {status:503};
      items.push({id:crypto.randomUUID(),...scope,binding_id:bindingId,device_id:deviceId,account_id:'synthetic-account',
        variant_id:11,platform:'wechat-article',source_revision:content.version,action:body.action,status:'queued',
        created_at:Date.now(),grant_expires_at:Date.now()+3600000,revoked:false,receipt:null});
      return {value:{schema:1,task:items.at(-1)}};
    }
    if(pathname===base+'/tasks')return {value:{schema:1,...scope,items}};
    return {status:404};
  });
  try{
    const p=f.page;await f.open();await p.waitForSelector('[data-distribution=start]:not([disabled])');
    assert.match(await p.$eval('[data-distribution-panel]',e=>e.textContent),/规则安排.*采用规则安排/s);
    assert(f.calls.some(c=>c.path===base+'/plans'&&c.method==='GET'));
    assert.match(await p.$eval('[name=distribution_scope]',e=>e.textContent),/合成客户.*合成官网/);
    assert(!f.calls.some(c=>c.method==='POST'));
    assert.match(await p.$eval('[data-distribution-panel]',e=>e.textContent),/人工发布.*系统步骤/s);
    await p.click('[data-distribution=channel-toggle]');await p.waitForFunction(()=>document.body.textContent.includes('停用项目渠道'));
    assert.match(await p.$eval('[data-distribution-panel]',e=>e.textContent),/等待原模块审核/);
    assert.match(await p.$eval('[data-distribution-panel]',e=>e.textContent),/公众号文章 · 账号 synthetic-account/);
    await p.screenshot({path:path.join(os.tmpdir(),'distribution-queue-advisor-20261012.png'),fullPage:true});
    assert.equal(f.calls.filter(c=>c.path===base+'/tasks'&&c.method==='POST').length,0);
    await p.click('[data-distribution=channel-toggle]');await p.waitForFunction(()=>document.body.textContent.includes('选择并启用排队'));
    await p.click('[data-distribution=start]');await p.waitForSelector('[data-distribution=pause]:not([disabled])');
    assert.match(await p.$eval('[data-distribution-panel]',e=>e.textContent),/wechat-channels.*zhihu.*kuaishou/s);
    await p.click('[data-distribution=handoff-toggle]');await p.waitForFunction(()=>document.body.textContent.includes('停用自动素材交接'));
    assert.equal(f.calls.filter(c=>c.path===base+'/handoff-permission'&&c.method==='POST').length,1);
    await p.$eval('[data-restriction]',e=>e.parentElement.open=true);
    for(const [name,value] of [['restriction_daily','2'],['restriction_interval','1200']])await p.$eval(`[name=${name}]`,(e,v)=>e.value=v,value);
    await p.click('[data-distribution=restrict]');await p.waitForFunction(()=>document.body.textContent.includes('最小间隔 1200 秒'));
    await p.click('[data-distribution=preview]');await p.waitForSelector('[name=distribution_reviewed]');
    assert.equal(await p.$eval('[data-distribution=publish]',e=>e.disabled),true);
    await p.click('[name=distribution_reviewed]');assert.equal(await p.$eval('[data-distribution=publish]',e=>e.disabled),true);
    await p.click('[data-distribution=preflight]');await p.waitForSelector('.distribution-task');
    await p.click('[data-distribution=preview]');await p.waitForSelector('[name=distribution_reviewed]');
    await p.click('[name=distribution_reviewed]');await p.click('[name=distribution_manual]');
    unknownWrite=true;await p.click('[data-distribution=publish]');await p.waitForFunction(()=>document.body.textContent.includes('操作结果待核查'));
    assert.equal(f.calls.filter(c=>c.path===base+'/tasks'&&c.body?.action==='publish').length,1);
    items[0].action='publish';items[0].status='unknown';
    await p.click('[data-distribution=refresh]');await p.waitForSelector('[data-distribution=pause]:not([disabled])');
    await p.$eval('[data-resolution]',e=>e.parentElement.open=true);
    await p.click('[data-distribution=resolve]');assert(!f.calls.some(c=>c.path===base+'/task-resolution'));
    await p.$eval('[data-resolution]',e=>e.parentElement.open=true);
    await p.select('[name=resolution_outcome]','not-published');await p.click('[name=resolution_checked]');await p.click('[name=resolution_stopped]');
    await p.click('[data-distribution=resolve]');await p.waitForFunction(()=>document.body.textContent.includes('确认未发布'));
    Object.assign(items[0],{action:'handoff',status:'unknown',content_digest:source.content_digest,handoff_attempt:1,resolution:null});
    await p.click('[data-distribution=refresh]');await p.waitForSelector('[data-handoff-investigation]');
    await p.$eval('[data-handoff-investigation]',e=>e.parentElement.open=true);
    await p.click('[data-distribution=handoff-investigate]');assert(!f.calls.some(c=>c.path==='/api/distribution/handoff/v1/advisor/resolution'));
    await p.$eval('[data-handoff-investigation]',e=>e.parentElement.open=true);
    for(const name of ['handoff_checked','handoff_stopped','handoff_unpublished'])await p.click(`[name=${name}]`);
    await p.click('[data-distribution=handoff-investigate]');await p.waitForSelector('[data-handoff-retry]');
    await p.$eval('[data-handoff-retry]',e=>e.parentElement.open=true);
    await p.click('[data-distribution=handoff-retry]');assert(!f.calls.some(c=>c.path==='/api/distribution/handoff/v1/advisor/retry'));
    await p.$eval('[data-handoff-retry]',e=>e.parentElement.open=true);
    await p.click('[name=retry_stopped]');await p.click('[name=retry_unpublished]');
    await p.click('[data-distribution=handoff-retry]');await p.waitForFunction(()=>document.querySelectorAll('.distribution-task').length===2);
    assert.equal(f.calls.filter(c=>c.path==='/api/distribution/handoff/v1/advisor/retry').length,1);
    await p.click('[data-distribution=pause]');await p.waitForSelector('[data-distribution=resume]:not([disabled])');
    await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await p.screenshot({path:path.join(os.tmpdir(),'distribution-advisor-mobile-20261011.png'),fullPage:true});
    denied=true;await p.click('[data-distribution=refresh]');await p.waitForFunction(()=>!document.querySelector('.distribution-task'));
    assert(!await p.$('[name=distribution_reviewed]'));assert.deepEqual(f.errors,[]);
  }finally{await f.close();}
});

test('built admin device secret is transient and individual account bindings can be revoked',async()=>{
  const admin={id:8,tenant_id:null,display_name:'合成超管',permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
  let devices=[],bindings=[],serverUser=admin,account=null,cap=channel();
  const f=await pageHarness(admin,'platform',async(url,method,body)=>{
    if(url.pathname==='/api/v1/auth/me')return {value:{user:serverUser}};
    if(url.pathname==='/api/v1/admin/console/snapshot')return {value:{schema:1,mode:'read_only_inventory',
      generated_at:'2026-10-11T00:00:00Z',sources:{
        tenants:{state:'available',total:1,rows:[{id:4,name:'合成客户'}]},
        seo_sites:{state:'available',total:1,rows:[{id:19,tenant_id:4,name:'合成官网'}]}},
      costs:{date:'2026-10-11',usage:[]},calls:{total:0},alerts:[],coverage:{}}};
    if(url.pathname===base+'/channel-catalog')return {value:{schema:1,items:[cap,{...channel(),platform:'website-article',label:'官网文章',mode:'not-integrated',reason:'NOT_INTEGRATED',automatic_steps:[],manual_steps:[]}]}};
    if(url.pathname===base+'/channel-permission'){
      assert.equal(body.expected_revision,cap.revision);cap={...cap,enabled:body.enabled,revision:cap.revision+1,reason:body.enabled?'REAL_CHANNEL_NOT_ACCEPTED':'NOT_AUTHORIZED'};
      return {value:{schema:1,capability:cap}};}
    if(url.pathname===base+'/devices'&&method==='GET')return {value:{schema:1,items:devices}};
    if(url.pathname===base+'/admin-events')return {value:{schema:1,items:[{id:1,at:Date.now(),actor:'8',action:'account_policy_saved',
      task_id:null,result:'POLICY_SAVED',target:{binding_id:bindingId}}]}};
    if(url.pathname===base+'/bindings'&&method==='GET')return {value:{schema:1,items:bindings}};
    if(url.pathname===base+'/account-policies')return {value:{schema:1,items:bindings.filter(b=>b.active).map(()=>account||{...schedule(),policy:null,reason:'POLICY_REQUIRED',available:false,next_allowed_at:null,system_remaining:null,effective_daily_limit:null,effective_interval_seconds:null})}};
    if(url.pathname===base+'/account-policy'){
      assert.deepEqual(body.windows,[{start:540,end:1080}]);assert.equal(body.enabled,true);assert.equal(body.expected_revision,0);
      account={...schedule(),policy:{...schedule().policy,revision:1,daily_limit:body.daily_limit,min_interval_seconds:body.min_interval_seconds,windows:body.windows},
        effective_daily_limit:body.daily_limit,effective_interval_seconds:body.min_interval_seconds};return {value:{schema:1,schedule:account}};
    }
    if(url.pathname===base+'/account-pause'){
      assert.equal(body.action,'pause');assert.equal(body.expected_revision,1);
      account={...account,policy:{...account.policy,revision:2,paused_reason:'ACCOUNT_PAUSED'},reason:'ACCOUNT_PAUSED',available:false,next_allowed_at:null};
      return {value:{schema:1,schedule:account}};
    }
    if(url.pathname===base+'/devices'){
      devices=[{id:deviceId,label:body.label,active:true,last_seen_at:null,created_at:Date.now()}];
      return {value:{schema:1,device:{id:deviceId,label:body.label,credential:'synthetic_'+ 'x'.repeat(48),credential_once:true}}};
    }
    if(url.pathname===base+'/bindings'){
      assert.equal(body.confirm_account_ownership,true);
      bindings=[{...body,id:bindingId,active:true,device_label:'合成设备',device_active:true}];
      return {value:{schema:1,binding:bindings[0]}};
    }
    if(url.pathname===base+'/bindings/'+bindingId+'/revoke'){
      bindings[0].active=false;return {value:{schema:1,id:bindingId,active:false}};
    }
    return {status:404};
  });
  try{
    const p=f.page;await f.open();await p.waitForSelector('[data-pc-page=distribution]');await p.click('[data-pc-page=distribution]');
    await p.waitForFunction(()=>document.querySelector('.distribution-panel [role=status]')?.textContent==='已更新。');
    assert.equal(await p.$eval('[data-platform=website-article]',e=>e.disabled),true);
    await p.click('[data-platform=wechat-article]');await p.waitForFunction(()=>document.body.textContent.includes('撤销全局排队授权'));
    assert.match(await p.$eval('.distribution-panel',e=>e.textContent),/实页发布与结果确认未验收/);
    await p.type('[data-distribution-admin=device] [name=label]','合成设备');await p.click('[data-distribution-admin=device] button');
    await p.waitForSelector('[aria-label=本次设备凭证]');
    assert.equal(await p.evaluate(()=>localStorage.getItem('distribution_device_token')),null);
    await p.click('[data-pc-page=accounts]');assert(!await p.$('[aria-label=本次设备凭证]'));
    await p.click('[data-pc-page=distribution]');await p.waitForFunction(()=>document.querySelector('.distribution-panel [role=status]')?.textContent==='已更新。');
    assert(!await p.$('[aria-label=本次设备凭证]'));
    assert.match(await p.$eval('.distribution-panel',e=>e.textContent),/最近分发操作日志/);
    assert.match(await p.$eval('[name=target_scope]',e=>e.textContent),/合成客户.*合成官网/);
    for(const [field,value] of Object.entries({account_id:'synthetic-local',external_account_id:'synthetic-official'}))
      await p.type(`[data-distribution-admin=binding] [name=${field}]`,value);
    await p.click('[name=confirm_account_ownership]');await p.click('[data-distribution-admin=binding] button');
    await p.waitForSelector('[data-distribution-admin=revoke-binding]:not([disabled])');
    await p.$eval('[data-distribution-admin=policy]',e=>e.parentElement.open=true);
    assert.equal(await p.$eval('[name=enabled]',e=>e.checked),false);
    assert.equal(await p.$eval('[name=daily_limit]',e=>e.value),'');
    await p.click('[name=enabled]');for(const [name,value] of [['daily_limit','3'],['min_interval_seconds','900'],['windows','09:00-18:00']])await p.type(`[name=${name}]`,value);
    await p.click('[data-distribution-admin=policy] button');await p.waitForSelector('[data-distribution-admin=account-pause]:not([disabled])');
    await p.$eval('[data-distribution-admin=policy]',e=>e.parentElement.open=true);
    await p.click('[data-distribution-admin=account-pause]');await p.waitForSelector('[data-distribution-admin=account-resume]:not([disabled])');
    await p.$eval('[data-distribution-admin=policy]',e=>e.parentElement.open=true);
    await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await p.screenshot({path:path.join(os.tmpdir(),'distribution-admin-scheduling-mobile-20261011.png'),fullPage:true});
    await p.click('[data-distribution-admin=revoke-binding]');await p.waitForFunction(()=>!document.querySelector('[data-distribution-admin=revoke-binding]'));
    serverUser={...admin,tenant_id:4};await p.click('[data-pc=refresh]');await p.waitForFunction(()=>!document.querySelector('.distribution-admin-host'));
    assert(!await p.$('[aria-label=本次设备凭证]'));assert.deepEqual(f.errors,[]);
  }finally{await f.close();}
});
