import test from 'node:test';import assert from 'node:assert/strict';import puppeteer from 'puppeteer-core';import {existsSync} from 'node:fs';
import {startFixtureServer} from './tests/fixture-server.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
const idle=p=>p.waitForFunction(()=>document.querySelector('.navigation')&&document.querySelector('#connected-message')?.textContent==='');
test('homepage confirmation entry clears old search and resets the existing ready-state list',async()=>{
 const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
 try{const p=await browser.newPage();await p.goto(f.origin+'/fixture.html');await idle(p);await p.click('.navigation [data-page="内容"]');await idle(p);
 await p.type('#content-query','旧搜索');await p.select('#content-status','published');await p.click('[data-action=content-search]');await idle(p);await p.click('.navigation [data-page="首页"]');await idle(p);
 await p.click('[data-action=home-data][data-kind=confirmations]');await idle(p);assert.equal(await p.$eval('#content-query',e=>e.value),'');assert.equal(await p.$eval('#content-status',e=>e.value),'ready');
 const call=f.state.calls.filter(c=>c.path==='/api/v1/seo/content-assets').at(-1);assert.equal(call.query.page,'1');assert.equal(call.query.status,'ready');assert(!call.query.q);assert(f.state.calls.every(c=>c.method==='GET'));
 }finally{await browser.close();await f.close();}
});
