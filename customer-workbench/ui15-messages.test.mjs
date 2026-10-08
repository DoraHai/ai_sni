import test from 'node:test';import assert from 'node:assert/strict';import puppeteer from 'puppeteer-core';import {existsSync} from 'node:fs';import {startFixtureServer} from './tests/fixture-server.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
const idle=p=>p.waitForFunction(()=>{const b=document.querySelector('[data-chat-action=refresh]');return b&&!b.disabled;});
test('folded content conversation preserves failed text, pages history, explicit read, and clears on scope or permission loss',async()=>{
  const f=await startFixtureServer(),b=await puppeteer.launch({executablePath:edge,headless:true});
  f.state.messages=new Map([[1,Array.from({length:25},(_,i)=>({id:i+1,conversation_id:1,body:i===24?'<img src=x onerror=alert(1)>原样文本':'历史消息'+(i+1),sender:{id:7,name:'顾问实名',kind:'advisor'},created_at:'2026-10-08T12:00:00Z'}))]]);
  try{
    const p=await b.newPage(),errors=[];p.on('pageerror',e=>errors.push(e.message));await p.goto(f.origin+'/fixture.html');await p.waitForSelector('.summary-grid');await p.click('[data-action=delivery]');await idle(p);
    assert.equal(await p.$eval('.conversation',e=>e.open),false);assert.match(await p.$eval('.conversation summary',e=>e.textContent),/25 条未读/);assert.equal(f.state.calls.filter(c=>c.path.endsWith('/read')).length,0);
    await p.click('.conversation summary');assert.equal(await p.$$('.conversation-message img').then(v=>v.length),0);await p.click('[data-chat-action=older]');await idle(p);assert.equal(await p.$$('.conversation-message').then(v=>v.length),25);assert.equal(f.state.calls.filter(c=>c.path.endsWith('/read')).length,0);
    await p.click('[data-chat-action=read]');await idle(p);assert(!await p.$eval('.conversation summary',e=>e.textContent.includes('未读')));
    await p.type('#conversation-draft','网络中断仍保留的消息');f.state.messageDropOnce='status';await p.click('[data-chat-action=send]');await idle(p);assert.equal(await p.$eval('#conversation-draft',e=>e.value),'网络中断仍保留的消息');assert.match(await p.$eval('.conversation-feedback',e=>e.textContent),/结果未确认/);
    await p.click('[data-chat-action=send]');await idle(p);assert.equal(await p.$eval('#conversation-draft',e=>e.value),'');assert.equal(f.state.messages.get(1).filter(m=>m.body==='网络中断仍保留的消息').length,1);assert.equal(f.state.confirmations.size,0);
    await p.type('#conversation-draft','切换身份必须清除');await p.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('advisor'));await p.waitForSelector('.summary-grid');assert(!await p.$('#conversation-draft'));await p.click('[data-action=delivery]');await idle(p);await p.click('.conversation summary');assert.equal(await p.$eval('#conversation-draft',e=>e.value),'');
    await p.type('#conversation-draft','切客户必须清除');await p.evaluate(()=>WORKBENCH_TEST_HOST.selectTenant(2));await p.waitForFunction(()=>document.querySelector('#identity')?.textContent.includes('契约客户2'));assert(!await p.$('#conversation-draft'));await p.waitForSelector('[data-action=delivery]');await p.click('[data-action=delivery]');await idle(p);await p.click('.conversation summary');assert.equal(await p.$eval('#conversation-draft',e=>e.value),'');
    await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await p.type('#conversation-draft','撤权必须清除');f.state.messageDenied=true;await p.click('[data-chat-action=refresh]');await p.waitForFunction(()=>document.body.textContent.includes('权限已失效'));assert(!await p.$('#conversation-draft'));assert(!await p.$('.conversation-message'));assert.deepEqual(errors,[]);
  }finally{await b.close();await f.close();}
});
