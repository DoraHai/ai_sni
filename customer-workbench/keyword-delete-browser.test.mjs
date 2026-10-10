import test from 'node:test';import assert from 'node:assert/strict';import puppeteer from 'puppeteer-core';
import {startFixtureServer} from './tests/fixture-server.mjs';
const edge=process.env.EDGE_BINARY||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const idle=p=>p.waitForFunction(()=>document.querySelector('#connected-message')?.textContent==='');
const deleted=f=>f.state.calls.filter(c=>c.method==='DELETE'&&c.path.includes('/keywords/'));
async function setup(role='advisor'){
  const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true,args:['--no-sandbox']}),p=await browser.newPage();
  await p.goto(f.origin+'/fixture.html');await idle(p);
  if(role==='advisor'){await p.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('advisor'));await idle(p);}
  await p.click('.navigation [data-page="数据"]');await idle(p);
  await p.evaluate(()=>{const summary=[...document.querySelectorAll('summary')].find(e=>e.textContent.includes('顾问关键词维护'));if(summary)summary.parentElement.open=true;});
  return {f,p,close:async()=>{await browser.close();await f.close();}};
}
test('advisor cancels without writes, confirms once with the historical deletion warning, and refreshes the remaining list',async()=>{
  const {f,p,close}=await setup();try{
    const id=f.state.keywords.get(1)[0].id;let warning='';
    p.once('dialog',d=>{warning=d.message();void d.dismiss();});await p.click(`[data-action="keyword-delete"][data-id="${id}"]`);
    assert.match(warning,/排名历史和搜索结果/);assert.match(warning,/文章与网站页面会保留/);assert.equal(deleted(f).length,0);
    p.once('dialog',d=>d.accept());await p.click(`[data-action="keyword-delete"][data-id="${id}"]`);await idle(p);
    assert.equal(deleted(f).length,1);assert.equal(deleted(f)[0].query.site_id,'9');assert.equal(f.state.keywords.get(1).some(v=>v.id===id),false);
    assert.equal(await p.$(`[data-action="keyword-delete"][data-id="${id}"]`),null);
    await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  }finally{await close();}
});
test('customer has no deletion controls and injected actions cannot dispatch deletes',async()=>{
  const {f,p,close}=await setup('customer');try{
    assert.equal(await p.$('[data-action="keyword-delete"]'),null);
    await p.evaluate(()=>{const b=document.createElement('button');b.dataset.action='keyword-delete';b.dataset.id='1001';document.querySelector('#page').append(b);b.click();});
    assert.equal(deleted(f).length,0);
  }finally{await close();}
});
test('revoked advisor assignment prevents deletion after confirmation and clears the action',async()=>{
  const {f,p,close}=await setup();try{
    f.state.planDenied=true;p.once('dialog',d=>d.accept());await p.click('[data-action="keyword-delete"]');
    await p.waitForFunction(()=>document.querySelector('#connected-message').textContent.includes('未取得'));
    assert.equal(deleted(f).length,0);assert.equal(await p.$('[data-action="keyword-delete"]'),null);
  }finally{await close();}
});
test('lost success receipt does not resend; explicit reread reconciles the already deleted record',async()=>{
  const {f,p,close}=await setup();try{
    const id=f.state.keywords.get(1)[0].id;f.state.keywordDeleteDropOnce=true;
    p.once('dialog',d=>d.accept());await p.click(`[data-action="keyword-delete"][data-id="${id}"]`);
    await p.waitForFunction(()=>document.querySelector('#connected-message').textContent.includes('删除结果未知'));
    assert.equal(deleted(f).length,1);assert.equal(await p.$('[data-action="keyword-delete"]'),null);
    await p.click('[data-action="refresh"]');await idle(p);assert.equal(deleted(f).length,1);
    assert.equal(await p.$(`[data-action="keyword-delete"][data-id="${id}"]`),null);
  }finally{await close();}
});
test('deleting the only item on the last page returns to the last valid page',async()=>{
  const {f,p,close}=await setup();try{
    f.state.keywords.set(1,f.state.keywords.get(1).slice(0,21));await p.click('[data-action="refresh"]');await idle(p);
    await p.click('[data-action="data-page"][data-number="2"]');await idle(p);
    await p.evaluate(()=>{[...document.querySelectorAll('summary')].find(e=>e.textContent.includes('顾问关键词维护')).parentElement.open=true;});
    p.once('dialog',d=>d.accept());await p.click('[data-action="keyword-delete"]');await idle(p);
    assert.equal(deleted(f).length,1);assert.equal(f.state.keywords.get(1).length,20);
    assert.equal(await p.$eval('[data-action="data-page"][data-number="0"]',e=>e.disabled),true);
  }finally{await close();}
});
