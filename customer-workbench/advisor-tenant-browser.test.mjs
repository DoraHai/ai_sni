import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {startFixtureServer} from './tests/fixture-server.mjs';
import path from 'node:path';
import fs from 'node:fs/promises';
import {workspaceSelectionPath} from './js/workbench-entry.mjs';
const edge=process.env.EDGE_BINARY||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const jwt=claims=>`e30.${Buffer.from(JSON.stringify({sub:'7',...claims})).toString('base64url')}.fixture`;
const identity=jwt({scope_kind:'advisor_identity',aud:'advisor-session'});
const business=tid=>jwt({scope_kind:'advisor_tenant',aud:'advisor-business',tid,gid:tid+100});
const permissions={'seo.site':'edit','seo.content':'edit','geo.assets':'edit','geo.content':'edit'};
const user={id:7,tenant_id:1,is_advisor:true,display_name:'顾问',permissions};

test('workspace selection uses the advisor session flag, not customer ID or edit permissions',()=>{
  assert.equal(workspaceSelectionPath({isAdvisorSession:true}),'/customer-workbench/?console=advisor');
  for(const session of [{},{isAdvisorSession:false,tenantId:15,user:{permissions}},{isAdvisorSession:'true'}]){
    assert.equal(workspaceSelectionPath(session),'/customer-workbench/');
  }
});

for(const [advisor,tenantId] of [[true,15],[true,17],[false,15]]){
  test(`GEO and SEO workspace returns preserve ${advisor?'advisor':'customer'} session for customer ${tenantId}`,async()=>{
    const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true,args:['--no-sandbox']});
    const origin='https://workspace.test',calls=[],errors=[],external=[],documents=[];
    const token=advisor?business(tenantId):'fixture-customer',name=tenantId===15?'Gsnipers':'SNIPERS';
    const account={...user,tenant_id:15,is_advisor:advisor},auth=JSON.stringify({version:1,token,user:account});
    const backup=JSON.stringify({token:identity,user:account});
    const expected=workspaceSelectionPath({isAdvisorSession:advisor});
    try{
      const p=await browser.newPage();p.on('pageerror',e=>errors.push(e.message));
      await p.setRequestInterception(true);p.on('request',async req=>{
        const url=new URL(req.url());if(url.protocol==='data:')return req.continue();
        if(url.origin!==origin){external.push(url.href);return req.abort();}
        if(req.isNavigationRequest())documents.push(url.pathname+url.search);
        const send=(data,status=200)=>req.respond({status,contentType:'application/json',body:JSON.stringify(data)}).catch(()=>{});
        if(url.pathname.startsWith('/api/')){
          calls.push({path:url.pathname,query:Object.fromEntries(url.searchParams),method:req.method(),token:req.headers().authorization?.slice(7)});
          if(url.pathname==='/api/v1/auth/me')return send({user:account});
          if(url.pathname==='/api/v1/auth/modules')return send({tenant_id:tenantId,modules:['seo','geo'].map(module_code=>({module_code,available:true}))});
          if(['/api/v1/auth/tenants','/api/v1/geo/tenants'].includes(url.pathname))return send({module:'seo',tenants:[{id:tenantId,name}]});
          if(url.pathname==='/api/v1/geo/projects')return send({projects:[{id:3,tenant_id:tenantId,name:'官网项目',status:'active'}]});
          if(url.pathname==='/api/v1/seo/workbench/sites')return send({tenant_id:tenantId,sites:[{id:6,name:'客户网站',status:'active'}],selection_policy:{selectable_statuses:['active']}});
          if(url.pathname==='/api/v1/geo/workbench/onsite-tasks')return send({module:'geo',tenant_id:tenantId,scope_id:3,can_create:false,items:[]});
          if(url.pathname==='/api/v1/seo/content-assets')return send({items:[],total:0,page:Number(url.searchParams.get('page')),page_size:Number(url.searchParams.get('page_size'))});
          if(url.pathname.endsWith('/advisor-tasks'))return send({schema:1,module:url.pathname.includes('/geo/')?'geo':'seo',items:[],next_before_id:null});
          return send({detail:{code:'not_integrated'}},404);
        }
        try{const r=await fetch(fixture.origin+url.pathname+url.search);await req.respond({status:r.status,contentType:r.headers.get('content-type'),body:Buffer.from(await r.arrayBuffer())});}catch{await req.abort().catch(()=>{});}
      });
      // Seed only synthetic auth once, then exercise full document navigation in one tab.
      await p.goto(origin+'/customer-workbench/?login=1');await p.waitForSelector('#entry-login');
      await p.evaluate(({auth,backup,tenantId,advisor})=>{
        sessionStorage.setItem('sem_auth_v1',auth);sessionStorage.setItem('sem_tenant_id',String(tenantId));
        if(advisor)sessionStorage.setItem('sem_advisor_identity_v1',backup);
      },{auth,backup,tenantId,advisor});
      const verifyReturn=async()=>{
        if(advisor){
          await p.waitForFunction(name=>document.querySelector('.advisor-tenant-picker')?.textContent.includes('当前客户：'+name),{},name);
          assert.equal(new URL(p.url()).search,'?console=advisor');
          assert(!documents.includes(`/customer-workbench/?tenant_id=${tenantId}&site_id=6`),'No automatic SEO redirect');
        }else{
          await p.waitForFunction(()=>document.querySelector('#identity')?.textContent.includes('客户网站'));
          assert.equal(new URL(p.url()).search,`?tenant_id=${tenantId}&site_id=6`);
          assert(documents.includes(expected),'Customer still returns through the original selector');
        }
        assert.equal(await p.evaluate(()=>JSON.parse(sessionStorage.getItem('sem_auth_v1')).token),token);
        assert.equal(await p.evaluate(()=>sessionStorage.getItem('sem_tenant_id')),String(tenantId));
        assert.equal(await p.evaluate(()=>sessionStorage.getItem('sem_advisor_identity_v1')),advisor?backup:null);
        assert.equal(await p.evaluate(()=>localStorage.getItem('sem_auth_v1')),null);
        assert(!(await p.$eval('body',e=>e.textContent)).includes('当前身份无权进入此客户空间'));
      };
      await p.goto(origin+`/customer-workbench/?module=geo&tenant_id=${tenantId}&project_id=3`);
      await p.waitForFunction(()=>document.querySelector('header small')?.textContent.includes('官网项目'));
      assert.equal(await p.$eval('header a',e=>e.getAttribute('href')),expected);
      const geoCalls=calls.length;
      await Promise.all([p.waitForNavigation(),p.click('header a')]);await verifyReturn();
      if(advisor)assert(!calls.slice(geoCalls).some(c=>c.path.endsWith('/sites')||c.path.endsWith('/projects')),'Return does not select a new business scope');
      documents.length=0;
      await p.goto(origin+`/customer-workbench/?tenant_id=${tenantId}&site_id=6`);
      await p.waitForFunction(()=>document.querySelector('#identity')?.textContent.includes('客户网站'));
      documents.length=0;
      await Promise.all([p.waitForNavigation(),p.click('[data-action=select-space]')]);await verifyReturn();
      // The existing SEO error-page anchor is also covered without editing connected-workbench.
      await p.goto(origin+`/customer-workbench/?tenant_id=${tenantId}&site_id=7`);
      await p.waitForFunction(()=>document.body.textContent.includes('当前身份无权进入此客户空间'));
      documents.length=0;
      await Promise.all([p.waitForNavigation(),p.click('.connected-state a')]);await verifyReturn();
      if(advisor){
        for(const entry of ['/customer-workbench/','/customer-workbench/?module=geo']){
          documents.length=0;const before=calls.length;await p.goto(origin+entry);await verifyReturn();
          assert(!calls.slice(before).some(c=>c.path.endsWith('/sites')||c.path.endsWith('/projects')));
        }
        await p.goto(origin+`/customer-workbench/?tenant_id=${tenantId}`);await p.waitForSelector('[data-entry=choose]');
        documents.length=0;await Promise.all([p.waitForNavigation(),p.click('[data-entry=choose]')]);await verifyReturn();
        await p.goto(origin+`/customer-workbench/?module=geo&tenant_id=${tenantId}&project_id=3&onsite_task_id=77&login=1`);
        await p.waitForSelector('[data-entry=continue]');documents.length=0;
        await Promise.all([p.waitForNavigation(),p.click('[data-entry=continue]')]);await verifyReturn();
      }
      assert(calls.every(c=>c.method==='GET'&&c.token===token),'Returns reuse the current session without selecting or restoring auth');
      assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
    }finally{await browser.close();await fixture.close();}
  });
}

test('advisor selects authorized customers, clears old data, rejects foreign URLs and survives revocation',async()=>{
  const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true,args:['--no-sandbox']});
  const origin='https://advisor.test',calls=[],errors=[];
  let tenantRows=[{id:1,name:'客户甲'},{id:2,name:'客户乙'}],revoked=false,hold=null,tenantsDenied=false,bareExpired=false,connectedDenied=false;
  const shots=process.env.ADVISOR_SHOTS_DIR;
  try{
    const p=await browser.newPage();p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept());
    await p.evaluateOnNewDocument(({identity,user})=>{if(!sessionStorage.getItem('sem_auth_v1'))sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token:identity,user}));},{identity,user});
    await p.setRequestInterception(true);p.on('request',async req=>{
      const url=new URL(req.url());if(url.protocol==='data:')return req.continue();if(url.origin!==origin)return req.abort();
      const token=req.headers().authorization?.slice(7),tid=token===business(2)?2:1;
      const send=(data,status=200)=>req.respond({status,contentType:'application/json',body:JSON.stringify(data)}).catch(()=>{});
      if(url.pathname.startsWith('/api/'))calls.push({path:url.pathname,query:Object.fromEntries(url.searchParams),method:req.method(),token,body:req.postData()});
      if(url.pathname==='/api/v1/auth/tenants')return tenantsDenied?send({detail:{code:'ADVISOR_NO_TENANT'}},403):send(tenantRows);
      if(url.pathname==='/api/v1/auth/select-tenant'){
        const id=JSON.parse(req.postData()).tenant_id;
        if(!tenantRows.some(t=>t.id===id))return send({detail:{code:'ADVISOR_TENANT_NOT_GRANTED'}},403);
        return send({access_token:business(id),token_type:'bearer',tenant_id:id,tenant_name:tenantRows.find(t=>t.id===id).name,expires_at:'2099-01-01T00:00:00Z'});
      }
      if(url.pathname==='/api/v1/auth/me')return connectedDenied&&token!==identity?send({detail:{code:'ADVISOR_GRANT_REVOKED'}},401):send({user});
      if(url.pathname==='/api/v1/auth/modules')return send({tenant_id:tid,modules:['seo','geo'].map(module_code=>({module_code,available:true}))});
      if(url.pathname.endsWith('/advisor-tasks')){
        if(token===identity)return send({detail:{code:'ADVISOR_TENANT_SELECTION_REQUIRED'}},409);
        if(!url.searchParams.has('tenant_id'))return send({detail:{code:'ADVISOR_TENANT_REQUIRED'}},403);
        if(Number(url.searchParams.get('tenant_id'))!==tid)return send({detail:{code:'ADVISOR_TENANT_NOT_GRANTED'}},403);
        if(hold)await hold;
        if(bareExpired)return send({},401);
        if(revoked)return send({detail:{code:'ADVISOR_GRANT_REVOKED'}},401);
        const module=url.pathname.includes('/geo/')?'geo':'seo',id=url.searchParams.has('before_id')?76:77;
        return send({schema:1,module,items:[{id,module,tenant_id:tid,scope_id:19,title:`客户${tid===1?'甲':'乙'}专属任务`,workflow:{module,revision:1,phase:'draft',items:[]},allowed_actions:[]}],next_before_id:id===77?77:null});
      }
      if(url.pathname.startsWith('/api/'))return send({detail:{code:'not_integrated'}},404);
      try{const r=await fetch(fixture.origin+url.pathname+url.search);await req.respond({status:r.status,contentType:r.headers.get('content-type'),body:Buffer.from(await r.arrayBuffer())});}catch{await req.abort().catch(()=>{});}
    });
    const screenshot=async(name)=>{if(!shots)return;await fs.mkdir(shots,{recursive:true});for(const [suffix,width,height] of [['desktop',1440,900],['mobile',390,844]]){await p.setViewport({width,height});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await p.screenshot({path:path.join(shots,`${name}-${suffix}.png`)});}};
    await p.goto(origin+'/customer-workbench/?console=advisor');await p.waitForSelector('.advisor-tenant-picker details');
    assert(!await p.$('.advisor-task'));assert(!calls.some(c=>c.path.endsWith('/modules')));
    assert.equal(await p.$eval('.advisor-module [role=status]',e=>e.textContent),'请先在上方选择客户，再查看站内任务');
    await p.click('[data-advisor=refresh]');await p.waitForNetworkIdle({idleTime:100});
    await p.waitForFunction(()=>document.querySelector('.advisor-tenant-picker')?.textContent.includes('请先选择客户'));
    assert(!calls.some(c=>c.path.endsWith('/advisor-tasks')));
    await p.locator('.advisor-tenant-picker summary').click();
    await p.locator('[data-tenant="1"]').click();await p.waitForSelector('.advisor-task');
    assert((await p.$eval('.advisor-task',e=>e.textContent)).includes('客户甲专属任务'));
    await p.waitForFunction(()=>document.querySelectorAll('.advisor-task').length===2);
    for(const module of ['seo','geo']){
      const taskCall=calls.find(c=>c.path===`/api/v1/${module}/workbench/advisor-tasks`);
      assert.equal(taskCall.query.tenant_id,'1');assert.equal(taskCall.token,business(1));
      await p.click(`[data-advisor=next][data-module=${module}]`);
      await p.waitForFunction(module=>document.querySelector(`.advisor-module[data-module=${module}] .advisor-task h4`)?.textContent.includes('#76'),{},module);
      assert(calls.some(c=>c.path===taskCall.path&&c.query.before_id==='77'&&c.query.tenant_id==='1'));
    }
    for(const module of ['geo','seo']){
      const selector=`.entry-header a[href="/customer-workbench/?console=advisor&module=${module}"]`;
      await Promise.all([p.waitForNavigation(),p.click(selector)]);await p.waitForSelector(`.advisor-module[data-module=${module}] .advisor-task`);
      assert.equal(new URL(p.url()).searchParams.get('console'),'advisor');
      assert.equal(await p.$eval('#advisor-module',e=>e.value),module);
      assert.equal(await p.$$eval('.advisor-module',es=>es.length),1);
      assert(!(await p.$eval('body',e=>e.textContent)).includes('当前身份无权进入此客户空间'));
    }
    await p.select('#advisor-module','all');
    await p.click('.advisor-tenant-picker summary');await screenshot('mt-switch');
    await p.evaluate(()=>{sessionStorage.setItem('seo_pending_rewrite_source','客户甲草稿');sessionStorage.setItem('sem_builder_handoff_1','客户甲筛选');});
    let release;hold=new Promise(r=>release=r);await p.click('[data-advisor=latest][data-module=seo]');
    await p.click('.advisor-tenant-picker summary');await p.click('[data-tenant="2"]');
    await p.waitForFunction(()=>document.querySelector('.advisor-tenant-picker')?.textContent.includes('当前客户：客户乙'));
    hold=null;release();await p.waitForFunction(()=>document.querySelector('.advisor-task')?.textContent.includes('客户乙专属任务'));
    assert.equal(await p.evaluate(()=>sessionStorage.getItem('seo_pending_rewrite_source')),null);
    assert.equal(await p.evaluate(()=>sessionStorage.getItem('sem_builder_handoff_1')),null);
    assert(!(await p.$eval('body',e=>e.textContent)).includes('客户甲专属任务'));
    assert(!await p.$('#advisor-account'));
    bareExpired=true;await p.click('[data-advisor=latest]');
    await p.waitForFunction(()=>document.body.textContent.includes('当前客户会话已过期'));
    assert(!await p.$('.advisor-task'));
    await p.waitForFunction(()=>document.querySelectorAll('[data-tenant]').length===2);
    bareExpired=false;await p.click('.advisor-tenant-picker summary');await p.click('[data-tenant="2"]');
    await p.waitForFunction(()=>document.querySelector('.advisor-task')?.textContent.includes('客户乙专属任务'));
    revoked=true;tenantRows=[{id:1,name:'客户甲'}];await p.click('[data-advisor=refresh]');
    await p.waitForFunction(()=>document.body.textContent.includes('可能已被收回'));
    assert(!await p.$('.advisor-task'));assert(!await p.$('.advisor-automation'));assert(!await p.$('.distribution-task'));
    await screenshot('mt-denied');
    revoked=false;await p.waitForFunction(()=>document.querySelectorAll('[data-tenant]').length===1);
    await p.click('.advisor-tenant-picker summary');await p.click('[data-tenant="1"]');
    await p.waitForSelector('.advisor-task').catch(async e=>{e.message+=' '+await p.$eval('body',e=>e.textContent);throw e;});
    assert(!await p.$('.advisor-tenant-picker details'));
    connectedDenied=true;await p.goto(origin+'/customer-workbench/?tenant_id=1&site_id=19');
    await p.waitForFunction(()=>document.body.textContent.includes('可能已被收回'));
    assert(!await p.$('.advisor-task'));
    assert(!new URL(p.url()).searchParams.has('advisor_notice'));
    connectedDenied=false;await p.waitForFunction(()=>document.querySelectorAll('[data-tenant]').length===1);
    await p.click('.advisor-tenant-picker summary');await p.click('[data-tenant="1"]');await p.waitForSelector('.advisor-task');
    await p.goto(origin+'/customer-workbench/?console=advisor&tenant_id=3');await p.waitForFunction(()=>document.body.textContent.includes('可能已被收回'));
    assert(!await p.$('.advisor-task'));
    tenantRows=[];await p.click('[data-advisor=refresh]');await p.waitForFunction(()=>document.body.textContent.includes('你还没有被分配客户'));
    assert(!await p.$('.advisor-task'));assert(!await p.$('.advisor-tenant-picker details'));
    const taskCalls=calls.filter(c=>c.path.endsWith('/advisor-tasks'));
    assert(taskCalls.every(c=>c.query.tenant_id===String(c.token===business(2)?2:1)&&c.token!==identity));
    tenantsDenied=true;
    const beforeDenied=calls.filter(c=>c.path==='/api/v1/auth/tenants').length;
    await p.click('[data-advisor=refresh]');
    await p.waitForFunction(()=>document.body.textContent.includes('你还没有被分配客户'));
    await new Promise(r=>setTimeout(r,200));
    assert.equal(calls.filter(c=>c.path==='/api/v1/auth/tenants').length,beforeDenied+1);
    assert(!await p.$('.advisor-task'));assert(!await p.$('.advisor-tenant-picker details'));
    assert(!calls.some(c=>c.path.includes('switch-account')||c.path.includes('linked-accounts')));
    assert.deepEqual(errors,[]);
  }finally{await browser.close();await fixture.close();}
});
