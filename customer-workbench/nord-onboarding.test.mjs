import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {existsSync} from 'node:fs';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {readNordIdentity,nordBindingMatches} from './js/nord-onboarding.mjs';
const device='11111111-1111-4111-8111-111111111111';
const receipt=()=>({schema:1,kind:'nord-local-account-observation',module:'seo',tenant_id:1,scope_id:1,platform:'wechat-article',device_id:device,external_account_id:'gh_123456789abc',observed_at:Date.now(),human_confirmed:true});
test('account transfer rejects foreign scopes, stale observations and unconfirmed identity',()=>{
  const source=receipt(),valid=readNordIdentity(JSON.stringify(source));
  assert.equal(valid.account_id,'nord-wechat-123456789abc');
  for(const delta of [{tenant_id:2},{scope_id:2},{module:'geo'},{human_confirmed:false},{observed_at:0},{external_account_id:'some-account'},{device_id:'unknown'},{token:'must-not-transfer'}])assert.throws(()=>readNordIdentity(JSON.stringify({...source,...delta})));
  const binding={...valid,active:true,device_active:true};assert(nordBindingMatches(binding,valid));
  for(const delta of [{active:false},{device_active:false},{device_id:'different'},{external_account_id:'gh_000000000000'},{tenant_id:2}])assert(!nordBindingMatches({...binding,...delta},valid));
});
test('the simplified browser flow writes only after confirmation and preserves existing rules',async()=>{
  const fixture=await startFixtureServer(),edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
  const browser=await puppeteer.launch({executablePath:edge,headless:true});
  try{
    const page=await browser.newPage();await page.goto(fixture.origin+'/js/nord-onboarding.mjs');
    await page.evaluate(async({receipt,device})=>{
      document.body.innerHTML='<div id="root"></div>';
      const {mountDistributionAdmin}=await import('/js/distribution-panel.mjs');
      window.writes=[];window.prepared=false;window.binding=null;window.policy=null;window.clip=JSON.stringify(receipt);
      const bindingId='22222222-2222-4222-8222-222222222222';
      const schedule=()=>({binding_id:bindingId,as_of:Date.now(),reason:window.policy?'READY':'POLICY_REQUIRED',available:!!window.policy,system_used_today:0,system_remaining:window.policy?1:null,platform_remaining:null,platform_quota_state:'unverified',next_allowed_at:null,reservation_task_id:null,effective_daily_limit:window.policy?.daily_limit??null,effective_interval_seconds:window.policy?.min_interval_seconds??null,policy:window.policy,restriction:null});
      const fetchImpl=async(path,options)=>{
        const p=new URL(path,location.origin).pathname,method=options.method||'GET',body=options.body?JSON.parse(options.body):null;
        if(method==='POST'){window.writes.push({p,body});if(p.endsWith('/preparation'))window.prepared=true;if(p.endsWith('/bindings'))window.binding={...body,id:bindingId,active:true,device_active:true,device_label:'本机'};if(p.endsWith('/account-policy'))window.policy={...body,revision:1,paused_reason:null};}
        let data;
        if(p.endsWith('/device-pairings'))data={schema:1,items:[],as_of:Date.now()};
        else if(p.endsWith('/devices'))data={schema:1,items:[{id:device,label:'本机',active:true}]};
        else if(p.endsWith('/bindings'))data=method==='POST'?{schema:1,binding:window.binding}:{schema:1,items:window.binding?[window.binding]:[]};
        else if(p.endsWith('/account-policies'))data={schema:1,items:window.binding?[schedule()]:[]};
        else if(p.endsWith('/account-policy'))data={schema:1,schedule:schedule()};
        else if(p.endsWith('/preparation'))data={schema:1,module:'seo',tenant_id:1,scope_id:1,external_account_id:receipt.external_account_id,advisor_user_id:7,advisor_assigned:window.prepared,connection_id:window.prepared?8:null,automatic_publish:false,publication_verified:false};
        else data={schema:1,items:[]};
        return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
      };
      const session={token:'isolated-test-session',user:{id:7,tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}},logout(){}};
      const localBrowser={...window,document,navigator:{clipboard:{readText:async()=>window.clip}},setInterval:window.setInterval.bind(window),clearInterval:window.clearInterval.bind(window),crypto:window.crypto,FormData:window.FormData};
      window.mount=mountDistributionAdmin({root:document.getElementById('root'),session,fetchImpl,browser:localBrowser,catalog:[{module:'seo',tenant_id:1,scope_id:1,tenant_name:'诺德',scope_name:'www.nord.cn'}]});
    },{receipt:receipt(),device});
    await page.waitForFunction(()=>document.body.innerText.includes('已更新。'));
    assert.equal(await page.$eval('[name=label]',e=>e.value),'诺德首条执行电脑（本机）');
    assert.equal(await page.$eval('[name=expires_in_seconds]',e=>e.value),'600');
    await page.click('[data-distribution-admin=nord-import]');await page.waitForSelector('[data-distribution-admin=nord-confirm]');
    assert.equal(await page.evaluate(()=>writes.length),0);
    await page.click('[data-distribution-admin=nord-confirm]');await page.waitForFunction(()=>window.writes.length===3&&document.body.innerText.includes('已更新。'),{timeout:5000}).catch(async e=>{console.log(await page.evaluate(()=>({writes,body:document.body.innerText})));throw e;});
    const writes=await page.evaluate(()=>window.writes);assert.deepEqual(writes.map(w=>w.p),['/api/distribution/nord/v1/preparation','/api/distribution/v1/bindings','/api/distribution/v1/account-policy']);
    assert.equal(writes[2].body.daily_limit,1);assert.equal(writes[2].body.min_interval_seconds,3600);assert.deepEqual(writes[2].body.windows,[{start:0,end:1440}]);
    await page.evaluate(()=>{window.policy.daily_limit=3;});
    await page.click('[data-distribution-admin=nord-confirm]');await page.waitForFunction(()=>document.body.innerText.includes('已更新。'));
    assert.equal(await page.evaluate(()=>writes.length),3);assert.equal(await page.evaluate(()=>policy.daily_limit),3);
    await page.evaluate(()=>{window.clip=JSON.stringify({...JSON.parse(window.clip),tenant_id:2});});
    await page.click('[data-distribution-admin=nord-import]');await page.waitForFunction(()=>document.body.innerText.includes('未读取到有效接入信息'));
    assert.equal(await page.$('[data-distribution-admin=nord-confirm]'),null);assert.equal(await page.evaluate(()=>writes.length),3);
    await page.evaluate(()=>mount.dispose());
  }finally{await browser.close();await fixture.close();}
});
