import test from 'node:test';import assert from 'node:assert/strict';import puppeteer from 'puppeteer-core';import {existsSync} from 'node:fs';
import scanFixtures from './tests/pending-scan-fixtures.json' with {type:'json'};
import {startFixtureServer} from './tests/fixture-server.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
test('mobile homepage starts with navigation and business content; dialogue still opens',async()=>{
 const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
 try{for(const width of [390,1440]){const p=await browser.newPage();await p.setViewport({width,height:width===390?844:900,isMobile:width===390,hasTouch:width===390});if(width===390)await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1');await p.goto(f.origin+'/fixture.html');await p.waitForFunction(()=>document.querySelector('.navigation')&&document.querySelector('#connected-message')?.textContent==='');
 const values=await p.evaluate(()=>({expanded:document.querySelector('[data-assistant-action=collapse]').getAttribute('aria-expanded'),main:document.querySelector('.connected-main').getBoundingClientRect().top,chat:document.querySelector('.workbench-dialogue').getBoundingClientRect().top,nav:document.querySelector('.navigation').getBoundingClientRect().top,overflow:document.documentElement.scrollWidth>innerWidth}));
 assert.equal(values.overflow,false);assert.equal(values.expanded,width===390?'false':'true');if(width===390){assert(values.chat>values.main);assert(values.nav<844);await p.click('[data-assistant-action=collapse]');assert.equal(await p.$eval('.assistant-expanded',e=>e.hidden),false);}await p.close();}
 }finally{await browser.close();await f.close();}
});

test('each scanned customer tab keeps useful content usable and marks only unavailable capabilities',async()=>{
 const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
 try{const p=await browser.newPage();await p.goto(f.origin+'/fixture.html');await p.waitForFunction(()=>document.querySelector('.navigation')&&!document.querySelector('#connected-message')?.textContent.includes('正在'));
 for(const row of scanFixtures.filter(x=>x.area==='customer')){
  const target=row.page.startsWith('data-')?'数据':row.page==='seo-evidence-open'?'SEO工作':row.page;
  await p.click(`.navigation [data-page="${target}"]`);await p.waitForFunction(()=>!document.querySelector('#connected-message')?.textContent.includes('正在'));
  if(row.page.startsWith('data-')){await p.click(`[data-action=data-kind][data-kind="${row.page.slice(5)}"]`);await p.waitForFunction(()=>!document.querySelector('#connected-message')?.textContent.includes('正在'));}
  assert.equal(await p.$$eval('.pc-pending',es=>es.length),0,`scanned ${row.page}: no whole-page badge`);
  if(row.page==='站内优化')assert.match(await p.$eval('.pending-feature',e=>e.textContent),/官网自动修改.*待启用/s);
  if(row.page==='服务计划')assert.equal(await p.$$eval('.pending-feature',es=>es.length),0,'customer sees the usable read-only plan, without editor-only pending features');
 }
 await p.close();}finally{await browser.close();await f.close();}
});
