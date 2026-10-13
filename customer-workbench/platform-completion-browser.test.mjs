import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {existsSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {billingObservations} from './tests/platform-billing-fixture.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
const admin={id:7,username:'fixture-admin',display_name:'超管验证',tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
const snapshot={schema:1,mode:'read_only_inventory',generated_at:new Date().toISOString(),sources:{},costs:{actual_amount:null,usage:[],date:'2026-10-12'},calls:{total:null},alerts:[],coverage:{}};
test('global balance hints, dated package display, audit pagination/export and revocation work without resetting unsaved forms',async()=>{
  const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
  const origin='https://complete.workbench.test',calls=[],errors=[];let balanceStatus=200,auditStatus=200,balanceReads=0,held=null,user=admin;
  try{
    const p=await browser.newPage();await p.setViewport({width:1440,height:1000});p.on('pageerror',e=>errors.push(e.message));
    await p.evaluateOnNewDocument(()=>{const original=window.setInterval;window.setInterval=(fn,ms,...args)=>{if(ms===300000)window.__balancePoll=fn;return original(fn,ms,...args);};});
    await p.setRequestInterception(true);
    p.on('request',async r=>{
      const u=new URL(r.url());if(u.origin!==origin)return r.abort();
      if(u.pathname.startsWith('/api/')){
        calls.push({path:u.pathname,method:r.method(),query:u.search});let status=200,body={};
        if(u.pathname.endsWith('/automation-health')||u.pathname.endsWith('/ai-governance'))status=404;
        else if(u.pathname.endsWith('/balances')){
          balanceReads++;status=balanceStatus;
          body={schema:1,state:'available',observations:{...billingObservations,freshness:'needs_recheck'},rows:[{id:'aliyun',name:'百炼账户',tenant_id:null,provider:'aliyun',state:'available',warning:'low',queried_at:new Date().toISOString(),balances:[{currency:'CNY',available:'27.34',cash:'27.34'}]}]};
        }else if(u.pathname.endsWith('/audit/export'))return r.respond({status:auditStatus,contentType:'text/csv',body:'\ufeffid,actor_id\nfixture,7\n'});
        else if(u.pathname.endsWith('/audit')){
          status=auditStatus;if(held)await held;
          body={schema:1,state:'available',rows:[{id:u.searchParams.has('cursor')?'older':'first',actor_id:7,action:'credential.update',resource_kind:'credential',recorded_fields:['revision'],created_at:new Date().toISOString(),after_value:'NEVER_RENDER'}],next_cursor:u.searchParams.has('cursor')?null:'next',as_of:new Date().toISOString()};
        }else body=u.pathname.endsWith('/me')?{user}:u.pathname.endsWith('/login')?{token:'fixture-token',user}:snapshot;
        return r.respond({status,contentType:'application/json',body:JSON.stringify(body)}).catch(()=>{});
      }
      const response=await fetch(f.origin+u.pathname+u.search);return r.respond({status:response.status,contentType:response.headers.get('content-type'),body:Buffer.from(await response.arrayBuffer())});
    });
    await p.goto(origin+'/customer-workbench/?console=platform');await p.waitForSelector('#pc-login');
    await p.type('[name=username]','fixture-admin');await p.type('[name=password]','fixture-password');await p.click('#pc-login button');
    await p.waitForFunction(()=>document.querySelector('.pc-right')?.textContent.includes('百炼账户 余额低于'));
    assert(balanceReads>0);assert.match(await p.$eval('.pc-right',e=>e.textContent),/套餐余量需重新核对/);
    await p.click('.pc-sidebar [data-pc-page=security]');await p.waitForSelector('#pc-audit-query');await p.type('[name=actor_id]','7');
    await p.evaluate(()=>window.__auditField=document.querySelector('#pc-audit-query [name=actor_id]'));
    const done=p.waitForResponse(r=>r.url().includes('/balances'));await p.evaluate(()=>window.__balancePoll());await done;
    assert.equal(await p.evaluate(()=>window.__auditField===document.querySelector('#pc-audit-query [name=actor_id]')),true);
    assert.equal(await p.$eval('#pc-audit-query [name=actor_id]',e=>e.value),'7');
    await p.click('#pc-audit-query button');await p.waitForFunction(()=>document.querySelector('.pc-content')?.textContent.includes('first'));
    assert.doesNotMatch(await p.$eval('.pc-content',e=>e.textContent),/NEVER_RENDER/);
    await p.click('[data-pc=audit-next]');await p.waitForFunction(()=>document.querySelector('.pc-content')?.textContent.includes('older'));
    await p.click('[data-pc=audit-export]');await p.waitForFunction(()=>document.body.textContent.includes('已导出管理审计元数据'));
    await p.click('.pc-sidebar [data-pc-page=balances]');await p.waitForFunction(()=>document.body.textContent.includes('站长之家账户与套餐余量'));
    assert.match(await p.$eval('.pc-content',e=>e.textContent),/247/);assert.match(await p.$eval('.pc-content',e=>e.textContent),/核验时余量正常/);
    await p.click('.pc-sidebar [data-pc-page=inventory]');assert.match(await p.$eval('.pc-content',e=>e.textContent),/当前接入与剩余条件/);
    await p.screenshot({path:path.join(os.tmpdir(),'platform-completion-20261012.png'),fullPage:true});
    balanceStatus=404;const failed=p.waitForResponse(r=>r.url().includes('/balances'));await p.evaluate(()=>window.__balancePoll());await failed;
    await p.waitForFunction(()=>document.querySelector('.pc-right')?.textContent.includes('余额查询接口未部署'));
    assert.doesNotMatch(await p.$eval('.pc-right',e=>e.textContent),/百炼账户 余额低于/);
    await p.click('.pc-sidebar [data-pc-page=security]');auditStatus=403;await p.click('#pc-audit-query button');
    await p.waitForFunction(()=>document.body.textContent.includes('无法读取管理审计'));assert.equal(await p.$('.pc-kpis'),null);
    assert(calls.filter(c=>c.path.includes('/audit')).every(c=>c.method==='GET'));
    assert.deepEqual(errors,[]);
  }finally{await browser.close();await f.close();}
});
