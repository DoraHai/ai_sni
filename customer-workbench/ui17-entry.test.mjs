import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {existsSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {entryScope,workbenchPath,workbenchLoginPath} from './js/workbench-entry.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
test('entry parameters cannot supply an external return, duplicate scope or invalid IDs',()=>{
  for(const q of ['?tenant_id=1','?tenant_id=1&site_id=0','?tenant_id=1&site_id=9&site_id=19','?tenant_id=1&tenant_id=2&site_id=9','?tenant_id=9007199254740992&site_id=1'])assert.equal(entryScope(q).invalid,true);
  assert.equal(entryScope('?redirect=https://example.invalid').invalid,false);
  assert.equal(workbenchPath(1,9),'/customer-workbench/?tenant_id=1&site_id=9');
  assert.equal(workbenchLoginPath(),'/customer-workbench/?login=1');
});
test('dedicated entry logs in, chooses authorized scope, survives expiry and never sends business writes',async()=>{
  const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
  const origin='https://workbench.test',loginCalls=[],external=[],errors=[];
  let mode='customer',denyLogin=false,denySites=false,emptySites=false,heldSite=null;
  try{
    const p=await browser.newPage();await p.setViewport({width:1440,height:1000});
    p.on('pageerror',e=>errors.push(e.message));await p.setRequestInterception(true);
    p.on('request',async request=>{
      const url=new URL(request.url());if(url.protocol==='data:')return request.continue();if(url.origin!==origin){external.push(url.href);return request.abort();}
      if(url.pathname==='/api/v1/auth/login'){
        loginCalls.push(JSON.parse(request.postData()));
        return request.respond({status:denyLogin?401:200,contentType:'application/json',body:JSON.stringify(denyLogin?{detail:'denied'}:{token:'fixture-'+mode,user:{id:mode==='customer'?12:7,tenant_id:mode==='customer'?1:null,display_name:'测试身份',permissions:{'seo.content':'view','seo.site':'view'}}})});
      }
      if(url.pathname.endsWith('/workbench/sites')){
        if(denySites)return request.respond({status:403,contentType:'application/json',body:'{}'});
        if(emptySites)return request.respond({status:200,contentType:'application/json',body:JSON.stringify({tenant_id:Number(url.searchParams.get('tenant_id')),sites:[],selection_policy:{selectable_statuses:['active']}})});
        if(heldSite&&url.searchParams.get('tenant_id')==='1')await heldSite;
      }
      try{const r=await fetch(f.origin+url.pathname+url.search,{method:request.method(),headers:request.headers(),body:request.postData()});await request.respond({status:r.status,contentType:r.headers.get('content-type'),body:Buffer.from(await r.arrayBuffer())});}catch{await request.abort().catch(()=>{});}
    });
    const submit=async()=>{await p.$eval('#entry-captcha',el=>el.value=document.querySelector('[data-entry=captcha]').textContent);await p.click('#entry-login [type=submit]');};
    const fill=async()=>{await p.type('#entry-username','fixture-user');await p.type('#entry-password','fixture-password');};
    await p.goto(origin+'/customer-workbench/?redirect=https://example.invalid');await p.waitForSelector('#entry-login');
    await p.screenshot({path:path.join(os.tmpdir(),'workbench-independent-login-20261009.png'),fullPage:true});
    await fill();await p.type('#entry-captcha','WRNG');await p.click('#entry-login [type=submit]');assert.equal(loginCalls.length,0);
    denyLogin=true;await submit();await p.waitForFunction(()=>document.querySelector('[role=status]')?.textContent.includes('用户名或密码'));
    assert.equal(await p.$eval('#entry-password',e=>e.value),'');assert.equal(await p.evaluate(()=>sessionStorage.getItem('sem_auth_v1')),null);
    denyLogin=false;await p.type('#entry-password','fixture-password');await submit();await p.waitForSelector('.summary-grid');
    assert.equal(new URL(p.url()).pathname,'/customer-workbench/');assert.equal(new URL(p.url()).searchParams.get('site_id'),'9');
    assert.equal(await p.evaluate(()=>localStorage.getItem('sem_auth_v1')),null);
    assert(!await p.$('a[href="/workspace/cockpit"]'));
    await p.click('[data-action=logout]');await p.waitForSelector('#entry-login');assert.equal(await p.evaluate(()=>sessionStorage.getItem('sem_auth_v1')),null);
    mode='advisor';await fill();await submit();await p.waitForSelector('#entry-tenant');
    assert.equal(await p.$$eval('#entry-tenant option',e=>e.length),3);assert.equal(await p.$eval('[data-entry=enter]',e=>e.disabled),true);
    await p.select('#entry-tenant','2');await p.waitForFunction(()=>!document.querySelector('[data-entry=enter]').disabled);
    await p.click('[data-entry=enter]');await p.waitForSelector('.summary-grid');assert.match(await p.$eval('#identity',e=>e.textContent),/契约客户2/);
    await p.click('[data-action=select-space]');await p.waitForSelector('#entry-tenant');
    // A slow old tenant response cannot repopulate the current selection.
    let release;heldSite=new Promise(r=>release=r);await p.select('#entry-tenant','1');await p.select('#entry-tenant','2');
    await p.waitForFunction(()=>document.querySelector('#entry-site')?.value==='19');release();heldSite=null;
    assert.equal(await p.$eval('#entry-tenant',e=>e.value),'2');
    emptySites=true;await p.select('#entry-tenant','1');await p.waitForFunction(()=>document.body.textContent.includes('暂时没有可用网站'));assert.equal(await p.$eval('[data-entry=enter]',e=>e.disabled),true);
    emptySites=false;denySites=true;await p.select('#entry-tenant','2');await p.waitForFunction(()=>document.body.textContent.includes('没有访问权限'));assert.equal(await p.$eval('[data-entry=enter]',e=>e.disabled),true);denySites=false;
    await p.select('#entry-tenant','1');await p.waitForFunction(()=>!document.querySelector('[data-entry=enter]').disabled);await p.click('[data-entry=enter]');await p.waitForSelector('.summary-grid');
    f.state.forceError={path:'/content-assets',status:401};await p.click('.navigation [data-page="内容"]');await p.waitForSelector('#entry-login');assert.equal(new URL(p.url()).searchParams.get('site_id'),'9');assert(!await p.$('.summary-grid'));
    await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await p.screenshot({path:path.join(os.tmpdir(),'workbench-independent-login-mobile-20261009.png'),fullPage:true});
    assert.deepEqual(external,[]);assert.deepEqual(errors,[]);assert.equal(f.state.calls.filter(c=>c.method!=='GET').length,0);
    assert.equal(loginCalls.length,3);
  }finally{await browser.close();await f.close();}
});
