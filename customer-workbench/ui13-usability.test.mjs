import test from 'node:test';import assert from 'node:assert/strict';import puppeteer from 'puppeteer-core';
import {startFixtureServer} from './tests/fixture-server.mjs';
const edge='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const idle=p=>p.waitForFunction(()=>document.querySelector('#connected-message')?.textContent==='');
const click=async(p,action)=>{await p.click(`[data-action="${action}"]`);await idle(p);};
const set=(p,id,text)=>p.$eval('#'+id,(e,v)=>{e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}));},text);
const nav=async(p,name)=>{await p.click(`.navigation [data-page="${name}"]`);await idle(p);};
async function setup(role='advisor'){
  const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true}),p=await browser.newPage();
  await p.goto(f.origin+'/fixture.html');await idle(p);if(role==='advisor'){await p.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('advisor'));await idle(p);}return {f,browser,p,close:async()=>{await browser.close();await f.close();}};
}
test('UI13 unsaved plan/draft navigation and failed 409/500 saves retain text until explicit restore; scope clears',async()=>{
  const {f,p,close}=await setup();let dialogs=0;const rejectDialog=d=>{dialogs++;void d.dismiss();};p.on('dialog',rejectDialog);
  try{
    await nav(p,'服务计划');await set(p,'plan-note','未保存的计划意见');await nav(p,'进度');assert.equal(dialogs,1);assert.equal(await p.$eval('#plan-note',e=>e.value),'未保存的计划意见');
    f.state.plans.get(1).revision++;await p.click('[data-action="save-plan"]');await p.waitForSelector('#input-recovery');assert.equal(f.state.calls.filter(c=>c.method==='PUT').length,1);
    await click(p,'refresh-plan');assert.equal(dialogs,1);assert(await p.$('#input-recovery'));await click(p,'restore-input');assert.equal(await p.$eval('#plan-note',e=>e.value),'未保存的计划意见');
    p.off('dialog',rejectDialog);p.once('dialog',d=>d.accept());await nav(p,'内容');f.state.contents.get(1).status='drafting';await click(p,'delivery');await click(p,'edit-content');await set(p,'content-body','失败后保留的正文');
    p.on('dialog',rejectDialog);await nav(p,'进度');assert.equal(await p.$eval('#content-body',e=>e.value),'失败后保留的正文');
    f.state.forceError={path:'/content-assets/88',status:500};await p.click('[data-action="save-content"]');await p.waitForSelector('#input-recovery');assert.equal(f.state.calls.filter(c=>c.method==='PATCH').length,1);assert.equal(await p.$('[data-action="save-content"]'),null);
    await click(p,'delivery');await click(p,'edit-content');await click(p,'restore-input');assert.equal(await p.$eval('#content-body',e=>e.value),'失败后保留的正文');assert.equal(f.state.calls.filter(c=>c.method==='PATCH').length,1);
    await p.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('customer'));await idle(p);assert.equal(await p.$('#input-recovery'),null);assert(!(await p.$eval('body',e=>e.textContent)).includes('失败后保留的正文'));
  }finally{await close();}
});
test('UI13 customer sees safe formatted content and a read-only business plan, without advisor forms',async()=>{
  const {f,p,close}=await setup('customer');try{
    f.state.contents.get(1).body='<h2>正文小标题</h2><p>可读<strong>正文</strong></p><img src="https://bad.invalid/pixel" onerror="window.hacked=true"><script>window.hacked=true</script><a href="javascript:window.hacked=true">链接</a><svg onload="window.hacked=true"></svg>';
    await click(p,'delivery');assert.equal(await p.$eval('#delivery-body h2',e=>e.textContent),'正文小标题');assert.equal(await p.$('#delivery-body img'),null);assert.equal(await p.$('#delivery-body script'),null);assert.equal(await p.$eval('#delivery-body a',e=>e.hasAttribute('href')),false);assert.equal(await p.evaluate(()=>window.hacked),undefined);assert.match(await p.$eval('#delivery-body',e=>e.textContent),/1 张图片/);
    for(const action of ['edit-content','review','manual-open','submit-review'])assert.equal(await p.$(`[data-action="${action}"]`),null);
    await nav(p,'服务计划');assert.equal(await p.$('#plan-note'),null);assert.equal(await p.$('[data-action="save-plan"]'),null);assert.match(await p.$eval('#page',e=>e.textContent),/优化方向/);assert.equal(await p.$eval('.compact-chat',e=>e.open),false);
    await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  }finally{await close();}
});
test('UI13 manual failure recovery requires reread and unchecks verification; 403 erases retained text',async()=>{
  const {f,p,close}=await setup();try{
    const content=f.state.contents.get(1);f.state.confirmations.set(1,{content_version:content.version_count,payload_hash:content.payload_hash,decision:'approve',actor_mode:'advisor_proxy',actor_user_id:7});
    await click(p,'delivery');await click(p,'manual-open');await set(p,'manual-platform','本地验证平台');await set(p,'manual-url','https://fixture.invalid/actual');await set(p,'manual-time','2026-10-08T10:00');await p.click('#manual-verified');
    f.state.forceError={path:'/publications/manual',status:500};await p.click('[data-action="manual-save"]');await p.waitForSelector('#input-recovery');await click(p,'delivery');await click(p,'manual-open');await click(p,'restore-input');assert.equal(await p.$eval('#manual-url',e=>e.value),'https://fixture.invalid/actual');assert.equal(await p.$eval('#manual-verified',e=>e.checked),false);assert.equal(f.state.calls.filter(c=>c.method==='POST').length,1);
    await p.click('#manual-verified');f.state.forceError={path:'/publications/manual',status:403};await p.click('[data-action="manual-save"]');await p.waitForFunction(()=>document.body.textContent.includes('当前身份无权'));assert.equal(await p.$('#input-recovery'),null);assert(!(await p.$eval('body',e=>e.textContent)).includes('fixture.invalid/actual'));
  }finally{await close();}
});
test('UI13 advisor can build an empty keyword list and maintain facts; 409 recovers and assignment loss clears',async()=>{
  const {f,p,close}=await setup();try{
    f.state.keywords.set(1,[]);await nav(p,'数据');await click(p,'maintenance-open');await set(p,'maint-keyword','新建测试词');await set(p,'maint-landing_page','https://fixture.invalid/target');await click(p,'maintenance-save');assert.equal(f.state.keywords.get(1).length,1);assert.equal(f.state.keywords.get(1)[0].keyword,'新建测试词');
    await p.click('[data-action="data-kind"][data-kind="facts"]');await idle(p);await click(p,'maintenance-open');await set(p,'maint-title','新资料');await set(p,'maint-statement','可核对的资料');await set(p,'maint-source_name','合成来源');await click(p,'maintenance-save');const fact=f.state.facts.get(1)[0];assert.equal(fact.title,'新资料');
    await p.click(`[data-action="maintenance-open"][data-id="${fact.id}"]`);await idle(p);await set(p,'maint-statement','冲突后保留的资料');fact.version++;await p.click('[data-action="maintenance-save"]');await p.waitForSelector('#input-recovery');await click(p,'maintenance-reload');await click(p,'restore-input');assert.equal(await p.$eval('#maint-statement',e=>e.value),'冲突后保留的资料');
    f.state.planDenied=true;const before=f.state.calls.filter(c=>c.method==='PATCH').length;await p.click('[data-action="maintenance-save"]');await p.waitForFunction(()=>document.body.textContent.includes('当前身份未取得'));assert.equal(await p.$('#input-recovery'),null);assert.equal(await p.$('#maint-statement'),null);assert.equal(f.state.calls.filter(c=>c.method==='PATCH').length,before);
    await p.evaluate(()=>WORKBENCH_TEST_HOST.setIdentity('customer'));await idle(p);await nav(p,'数据');assert.equal(await p.$('[data-action="maintenance-open"]'),null);
  }finally{await close();}
});
