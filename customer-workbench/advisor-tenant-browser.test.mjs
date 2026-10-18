import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {startFixtureServer} from './tests/fixture-server.mjs';
import path from 'node:path';
import fs from 'node:fs/promises';
const edge=process.env.EDGE_BINARY||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const jwt=claims=>`e30.${Buffer.from(JSON.stringify({sub:'7',...claims})).toString('base64url')}.fixture`;
const identity=jwt({scope_kind:'advisor_identity',aud:'advisor-session'});
const business=tid=>jwt({scope_kind:'advisor_tenant',aud:'advisor-business',tid,gid:tid+100});
const permissions={'seo.site':'edit','seo.content':'edit'};
const user={id:7,tenant_id:1,is_advisor:true,display_name:'顾问',permissions};

test('advisor selects authorized customers, clears old data, rejects foreign URLs and survives revocation',async()=>{
  const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true,args:['--no-sandbox']});
  const origin='https://advisor.test',calls=[],errors=[];
  let tenantRows=[{id:1,name:'客户甲'},{id:2,name:'客户乙'}],revoked=false,hold=null;
  const shots=process.env.ADVISOR_SHOTS_DIR;
  try{
    const p=await browser.newPage();p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept());
    await p.evaluateOnNewDocument(({identity,user})=>{if(!sessionStorage.getItem('sem_auth_v1'))sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token:identity,user}));},{identity,user});
    await p.setRequestInterception(true);p.on('request',async req=>{
      const url=new URL(req.url());if(url.protocol==='data:')return req.continue();if(url.origin!==origin)return req.abort();
      const token=req.headers().authorization?.slice(7),tid=token===business(2)?2:1;
      const send=(data,status=200)=>req.respond({status,contentType:'application/json',body:JSON.stringify(data)}).catch(()=>{});
      if(url.pathname.startsWith('/api/'))calls.push({path:url.pathname,method:req.method(),token,body:req.postData()});
      if(url.pathname==='/api/v1/auth/tenants')return send(tenantRows);
      if(url.pathname==='/api/v1/auth/select-tenant'){
        const id=JSON.parse(req.postData()).tenant_id;
        if(!tenantRows.some(t=>t.id===id))return send({detail:{code:'ADVISOR_TENANT_NOT_GRANTED'}},403);
        return send({access_token:business(id),token_type:'bearer',tenant_id:id,tenant_name:tenantRows.find(t=>t.id===id).name,expires_at:'2099-01-01T00:00:00Z'});
      }
      if(url.pathname==='/api/v1/auth/me')return send({user});
      if(url.pathname==='/api/v1/auth/modules')return send({tenant_id:tid,modules:[{module_code:'seo',available:true}]});
      if(url.pathname.endsWith('/advisor-tasks')){
        if(hold)await hold;
        if(revoked)return send({detail:{code:'ADVISOR_GRANT_REVOKED'}},401);
        return send({schema:1,module:'seo',items:[{id:77,module:'seo',tenant_id:tid,scope_id:19,title:`客户${tid===1?'甲':'乙'}专属任务`,workflow:{module:'seo',revision:1,phase:'draft',items:[]},allowed_actions:[]}],next_before_id:null});
      }
      if(url.pathname.startsWith('/api/'))return send({detail:{code:'not_integrated'}},404);
      try{const r=await fetch(fixture.origin+url.pathname+url.search);await req.respond({status:r.status,contentType:r.headers.get('content-type'),body:Buffer.from(await r.arrayBuffer())});}catch{await req.abort().catch(()=>{});}
    });
    const screenshot=async(name)=>{if(!shots)return;await fs.mkdir(shots,{recursive:true});for(const [suffix,width,height] of [['desktop',1440,900],['mobile',390,844]]){await p.setViewport({width,height});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await p.screenshot({path:path.join(shots,`${name}-${suffix}.png`)});}};
    await p.goto(origin+'/customer-workbench/?console=advisor');await p.waitForSelector('.advisor-tenant-picker details');
    assert(!await p.$('.advisor-task'));assert(!calls.some(c=>c.path.endsWith('/modules')));
    await p.click('.advisor-tenant-picker summary');await screenshot('mt-switch');
    await p.click('[data-tenant="1"]');await p.waitForSelector('.advisor-task');
    assert((await p.$eval('.advisor-task',e=>e.textContent)).includes('客户甲专属任务'));
    await p.evaluate(()=>{sessionStorage.setItem('seo_pending_rewrite_source','客户甲草稿');sessionStorage.setItem('sem_builder_handoff_1','客户甲筛选');});
    let release;hold=new Promise(r=>release=r);await p.click('[data-advisor=latest]');
    await p.click('.advisor-tenant-picker summary');await p.click('[data-tenant="2"]');
    await p.waitForFunction(()=>document.querySelector('.advisor-tenant-picker')?.textContent.includes('当前客户：客户乙'));
    hold=null;release();await p.waitForFunction(()=>document.querySelector('.advisor-task')?.textContent.includes('客户乙专属任务'));
    assert.equal(await p.evaluate(()=>sessionStorage.getItem('seo_pending_rewrite_source')),null);
    assert.equal(await p.evaluate(()=>sessionStorage.getItem('sem_builder_handoff_1')),null);
    assert(!(await p.$eval('body',e=>e.textContent)).includes('客户甲专属任务'));
    assert(!await p.$('#advisor-account'));
    revoked=true;tenantRows=[{id:1,name:'客户甲'}];await p.click('[data-advisor=refresh]');
    await p.waitForFunction(()=>document.body.textContent.includes('可能已被收回'));
    assert(!await p.$('.advisor-task'));assert(!await p.$('.advisor-automation'));assert(!await p.$('.distribution-task'));
    await screenshot('mt-denied');
    revoked=false;await p.click('[data-tenant="1"]');await p.waitForSelector('.advisor-task');
    assert(!await p.$('.advisor-tenant-picker details'));
    await p.goto(origin+'/customer-workbench/?console=advisor&tenant_id=3');await p.waitForFunction(()=>document.body.textContent.includes('可能已被收回'));
    assert(!await p.$('.advisor-task'));
    tenantRows=[];await p.click('[data-advisor=refresh]');await p.waitForFunction(()=>document.body.textContent.includes('你还没有被分配客户'));
    assert(!await p.$('.advisor-task'));assert(!await p.$('.advisor-tenant-picker details'));
    assert(!calls.some(c=>c.path.includes('switch-account')||c.path.includes('linked-accounts')));
    assert.deepEqual(errors,[]);
  }finally{await browser.close();await fixture.close();}
});
