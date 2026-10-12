import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {existsSync} from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {healthFixture} from './tests/platform-automation-fixture.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
const admin={id:7,username:'fixture-admin',display_name:'运维测试管理员',tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
const snapshot={schema:1,mode:'read_only_inventory',generated_at:'2026-10-11T02:00:10Z',sources:{},
  costs:{actual_amount:null,usage:[],date:'2026-10-11'},calls:{total:null},alerts:[],coverage:{}};

test('built operations page handles independent module failures, fresh authorization, visibility, late data and exact scope links',async()=>{
  const server=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
  const origin='https://ops.workbench.test',calls=[],errors=[],external=[];
  let user=admin,readCount=0,held=null;
  const status={seo:200,geo:200},data={seo:healthFixture('seo'),geo:healthFixture('geo')};
  const refreshFixtures=()=>{for(const d of Object.values(data)){d.as_of=new Date().toISOString();d.worker.last_tick_at=new Date(Date.now()-1000).toISOString();}};
  refreshFixtures();data.geo.counts.unknown_cost=3;data.geo.rows[0].tenant_id=2;data.geo.rows[0].scope_id=19;data.geo.rows[0].unknown_cost=3;
  try{
    const p=await browser.newPage();await p.setViewport({width:1440,height:1000});
    p.on('pageerror',e=>errors.push(e.message));
    await p.evaluateOnNewDocument(()=>{const native=window.setInterval;window.setInterval=(fn,ms,...args)=>{
      if(ms===60000)window.__automationPoll=fn;return native(fn,ms,...args);
    };});
    await p.setRequestInterception(true);
    p.on('request',async r=>{
      const u=new URL(r.url());if(u.protocol==='data:')return r.continue();
      if(u.origin!==origin){external.push(u.href);return r.abort();}
      if(u.pathname.startsWith('/api/')){
        calls.push({path:u.pathname,method:r.method(),query:u.search,headers:r.headers()});
        if(u.pathname.endsWith('/automation-health')){
          const module=u.pathname.includes('/seo/')?'seo':'geo';readCount++;
          const code=status[module],body=JSON.stringify(data[module]);if(module==='seo'&&held)await held;
          return r.respond({status:code,contentType:'application/json',body}).catch(()=>{});
        }
        const code=u.pathname.endsWith('/ai-governance')?404:200;
        const body=u.pathname.endsWith('/me')?{user}:u.pathname.endsWith('/login')?{token:'fixture-admin',user}:snapshot;
        return r.respond({status:code,contentType:'application/json',body:JSON.stringify(body)});
      }
      const response=await fetch(server.origin+u.pathname+u.search);
      return r.respond({status:response.status,contentType:response.headers.get('content-type'),body:Buffer.from(await response.arrayBuffer())});
    });
    const body=()=>p.$eval('.pc-content',e=>e.textContent);
    const idle=()=>p.waitForFunction(()=>document.querySelector('[data-pc=automation-refresh]')?.disabled===false);
    await p.goto(origin+'/customer-workbench/?console=platform');await p.waitForSelector('#pc-login');
    await p.type('[name=username]','fixture-admin');await p.type('[name=password]','fixture-password');await p.click('#pc-login button');await p.waitForSelector('.pc-kpis');
    await p.click('.pc-sidebar [data-pc-page=automation-ops]');await idle();
    assert.match(await body(),/SEM 本轮未接入 AI 接管/);assert.match(await body(),/采样时当前进程有心跳/);
    assert.match(await body(),/待人工/);assert.match(await body(),/费用未知/);assert.match(await body(),/未知/);
    assert(!await p.$('.pc-content form'));assert.equal(await p.$$eval('.pc-content button',els=>els.length),1);
    assert.deepEqual(await p.$$eval('.pc-content a',els=>els.map(e=>e.getAttribute('href'))),
      ['/customer-workbench/?tenant_id=1&site_id=9','/customer-workbench/?module=geo&tenant_id=2&project_id=19']);
    assert.match(await p.$eval('.pc-right',e=>e.textContent),/GEO 费用未知步骤 3 项/);
    await p.screenshot({path:path.join(os.tmpdir(),'platform-automation-ops-20261011.png'),fullPage:true});
    await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await p.setViewport({width:1440,height:1000});
    const beforeHidden=readCount;await p.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});window.__automationPoll();delete document.visibilityState;});
    assert.equal(readCount,beforeHidden);
    // Background health polling updates hints without destroying another page's unsaved input or focus.
    await p.click('.pc-sidebar [data-pc-page=customers]');await p.type('#pc-search','未提交筛选');
    await p.evaluate(()=>window.__searchNode=document.querySelector('#pc-search'));
    const responses=['seo','geo'].map(m=>p.waitForResponse(r=>r.url().includes('/'+m+'/workbench/automation-health')));
    await p.evaluate(()=>window.__automationPoll());await Promise.all(responses);
    await p.waitForFunction(()=>document.querySelector('.pc-right')?.textContent.includes('GEO 费用未知步骤 3 项'));
    assert.equal(await p.evaluate(()=>document.querySelector('#pc-search')===window.__searchNode),true);
    assert.equal(await p.$eval('#pc-search',e=>e.value),'未提交筛选');
    await p.click('.pc-sidebar [data-pc-page=automation-ops]');await idle();
    status.geo=404;await p.evaluate(()=>window.__automationPoll());await idle();assert.match(await body(),/接口未部署/);
    assert.doesNotMatch(await p.$eval('.pc-right',e=>e.textContent),/GEO 费用未知/);
    data.seo={...data.seo,state:'schema_pending'};await p.click('[data-pc=automation-refresh]');await idle();assert.match(await body(),/执行结构尚未就绪/);
    data.seo=healthFixture();data.seo.scope.tenant_id=3;await p.click('[data-pc=automation-refresh]');await idle();assert.match(await body(),/响应或范围未通过核验/);assert.equal(await p.$('.pc-content a'),null);
    data.seo=healthFixture();refreshFixtures();status.geo=200;
    await p.click('[data-pc=automation-refresh]');await idle();assert.match(await body(),/客户 1/);
    // Revocation clears all private UI, even when another module request is in flight.
    status.geo=403;let release;held=new Promise(r=>release=r);await p.click('[data-pc=automation-refresh]');
    await p.waitForFunction(()=>document.body.textContent.includes('无法读取自动执行运维'));
    assert.equal(await p.$('.pc-kpis'),null);assert.doesNotMatch(await p.evaluate(()=>document.body.textContent),/客户 1|费用未知步骤 3/);
    release();held=null;await new Promise(r=>setTimeout(r,100));assert.equal(await p.$('.pc-kpis'),null);
    status.geo=200;user={...admin,tenant_id:2};const before=readCount;await p.click('[data-pc=refresh]');
    await p.waitForFunction(()=>document.body.textContent.includes('此账号无法进入超管工作台'));assert.equal(readCount,before);
    user=admin;await p.click('[data-pc=refresh]');await p.waitForSelector('.pc-kpis');await idle();
    let releaseLate;held=new Promise(r=>releaseLate=r);await p.click('[data-pc=automation-refresh]');
    await p.waitForFunction(()=>document.querySelector('[data-pc=automation-refresh]')?.disabled===true);
    await p.click('[data-pc=logout]');await p.waitForSelector('#pc-login');releaseLate();held=null;
    await new Promise(r=>setTimeout(r,100));assert.equal(await p.$('.pc-kpis'),null);assert.equal(await p.$('.pc-content'),null);
    const healthCalls=calls.filter(c=>c.path.endsWith('/automation-health'));
    assert(healthCalls.length>0);for(const c of healthCalls){assert.equal(c.method,'GET');assert.equal(c.query,'');assert.equal(c.headers.authorization,'Bearer fixture-admin');}
    assert.equal(calls.filter(c=>c.method!=='GET'&&!c.path.endsWith('/login')).length,0);
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  }finally{await browser.close();await server.close();}
});
