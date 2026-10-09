import test from 'node:test';import assert from 'node:assert/strict';import puppeteer from 'puppeteer-core';
import {startFixtureServer} from './tests/fixture-server.mjs';
const idle=p=>p.waitForFunction(()=>document.querySelector('#connected-message')?.textContent==='');
const ready=p=>p.waitForFunction(()=>document.querySelector('[data-assistant-action=ask]')?.textContent==='发送给 AI');
test('workspace AI: followup, selected article, escaped response, same request recovery, errors and scope clearing',async()=>{
 const f=await startFixtureServer(),b=await puppeteer.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{
  const p=await b.newPage();await p.setViewport({width:1440,height:1000});await p.goto(f.origin+'/fixture.html');await idle(p);
  f.state.aiAnswer='<img src=x onerror="window.AI_UNSAFE=true">这是AI解释，未执行发布。';
  await p.type('#workspace-question','SEO和SEM有什么区别？');await p.click('[data-assistant-action=ask]');await p.waitForSelector('.assistant-ai-answer');await ready(p);
  assert.equal(await p.$('.assistant-ai-answer img'),null);assert.match(await p.$eval('.assistant-ai-answer',e=>e.textContent),/这是AI解释/);assert.equal(await p.evaluate(()=>window.AI_UNSAFE),undefined);
  await p.type('#workspace-question','那我下一步做什么？');await p.click('[data-assistant-action=ask]');await p.waitForFunction(()=>document.querySelectorAll('.assistant-ai-answer').length===2);
  const calls=()=>f.state.calls.filter(c=>c.path.endsWith('/assistant/chat'));
  assert.equal(calls()[1].body.history.length,2);assert.match(calls()[1].body.history[0].content,/SEO和SEM/);
  await p.click('.navigation [data-page=内容]');await idle(p);await p.click('[data-action=delivery]');await idle(p);
  await p.type('#workspace-question','这篇稿件怎么改？');await p.click('[data-assistant-action=ask]');await p.waitForFunction(()=>document.querySelectorAll('.assistant-ai-answer').length===3);
  assert.equal(calls()[2].body.content_id,88);
  f.state.aiDropOnce=true;await p.type('#workspace-question','网络中断仍保留');await p.click('[data-assistant-action=ask]');await p.waitForSelector('[data-assistant-action=retry-ai]');
  assert.equal(await p.$eval('#workspace-question',e=>e.value),'网络中断仍保留');const failed=calls().at(-1).body;
  await p.click('[data-assistant-action=retry-ai]');await p.waitForFunction(()=>document.querySelectorAll('.assistant-ai-answer').length===4);
  assert.deepEqual(calls().at(-1).body,failed);assert.equal(f.state.aiResults.size,4);
  f.state.forceError={path:'/assistant/chat',status:503};await p.type('#workspace-question','服务失败保留问题');await p.click('[data-assistant-action=ask]');await p.waitForFunction(()=>document.querySelector('.assistant-feedback')?.textContent.includes('暂时不可用'));
  assert.equal(await p.$eval('#workspace-question',e=>e.value),'服务失败保留问题');assert.equal(await p.$$('.assistant-ai-answer').then(a=>a.length),4);
  await p.setViewport({width:390,height:844});await p.click('[data-assistant-action=fullscreen]');assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await p.click('[data-assistant-action=fullscreen]');
  await p.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('advisor'));await idle(p);assert.equal(await p.$eval('#workspace-question',e=>e.value),'');assert.equal(await p.$$('.assistant-ai-answer').then(a=>a.length),0);
  f.state.holdNext='/assistant/chat';await p.type('#workspace-question','旧客户回答必须丢弃');await p.click('[data-assistant-action=ask]');await p.waitForFunction(()=>document.querySelector('.assistant-feedback')?.textContent.includes('正在回答'));
  while(!f.state.held.length)await new Promise(r=>setTimeout(r,20));
  await p.evaluate(()=>WORKBENCH_TEST_HOST.selectTenant(2));f.state.held.shift()();await idle(p);
  assert.equal(await p.$$('.assistant-ai-answer').then(a=>a.length),0);assert.equal(await p.$eval('#workspace-question',e=>e.value),'');
  f.state.forceError={path:'/assistant/chat',status:403};await p.type('#workspace-question','撤权清空');await p.click('[data-assistant-action=ask]');await p.waitForFunction(()=>document.querySelector('#connected-content')?.textContent.includes('无权'));
  assert.equal(await p.$$('.assistant-ai-answer').then(a=>a.length),0);assert.equal(await p.$eval('#workspace-question',e=>e.value),'');
  assert.equal(f.state.calls.filter(c=>c.method!=='GET'&&!c.path.endsWith('/assistant/chat')).length,0);
 }finally{await b.close();await f.close();}
});
