import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {existsSync} from 'node:fs';
import {startFixtureServer} from './tests/fixture-server.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
test('link form selection, UUID validation, error and successful submit use fixture data only',{skip:!edge},async()=>{
  const server=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true,args:['--no-sandbox']});
  try{
    const page=await browser.newPage();
    await page.setRequestInterception(true);
    page.on('request',r=>r.url().endsWith('/link-test')?r.respond({status:200,contentType:'text/html',body:'<main id="panel"></main>'}):r.continue());
    await page.goto(server.origin+'/link-test');
    await page.evaluate(async()=>{
      const {createAdvisorLinksPanel}=await import('/js/platform-advisor-links.mjs');
      const root=document.querySelector('#panel'),admin={id:1,tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
      window.writes=[];window.linkStatus=409;
      const panel=createAdvisorLinksPanel({session:{token:'fixture',user:admin},onChange:()=>root.innerHTML=panel.html(),fetchImpl:async(path,options)=>{
        const data=path.endsWith('/me')?{user:admin}:path.endsWith('/users')?{users:[{id:10,username:'<img src=x>',tenant_id:1,is_active:true,role_id:2},{id:11,username:'顾问B',tenant_id:2,is_active:true,role_id:2}]}:path.endsWith('/roles')?{roles:[{id:2,permissions:{'seo.site':'edit','seo.content':'edit'}}]}:{group_id:'12345678-1234-1234-1234-123456789abc',user_ids:[10,11]};
        if(options.method==='POST')window.writes.push(JSON.parse(options.body));
        return {ok:options.method!=='POST'||window.linkStatus===200,status:options.method==='POST'?window.linkStatus:200,json:async()=>data};
      }});
      root.addEventListener('click',panel.click);root.addEventListener('change',panel.change);root.addEventListener('input',panel.input);root.addEventListener('submit',e=>void panel.submit(e));root.innerHTML=panel.html();
    });
    await page.click('[data-pc=advisor-links-open]');await page.waitForSelector('input[value="10"]');
    assert.equal(await page.$('img'),null);
    await page.click('input[value="10"]');assert.equal(await page.$eval('button[type=submit]',b=>b.disabled),true);
    await page.click('input[value="11"]');assert.equal(await page.$eval('button[type=submit]',b=>b.disabled),false);
    await page.type('[name=group_id]','invalid');assert.equal(await page.$eval('button[type=submit]',b=>b.disabled),true);
    await page.$eval('[name=group_id]',e=>{e.value='';e.dispatchEvent(new Event('input',{bubbles:true}));});
    await page.click('button[type=submit]');await page.waitForFunction("document.querySelector('[role=status]').textContent.includes('已有关联组')");
    await page.evaluate(()=>window.linkStatus=200);
    await page.type('[name=group_id]','12345678-1234-1234-1234-123456789abc');
    await page.click('button[type=submit]');await page.waitForFunction("document.querySelector('#panel').textContent.includes('操作成功')");
    const writes=await page.evaluate(()=>window.writes);
    assert.deepEqual(writes,[{user_ids:[10,11]},{user_ids:[10,11],group_id:'12345678-1234-1234-1234-123456789abc'}]);
    assert.equal(await page.$eval('button[type=submit]',b=>b.disabled),true);
  }finally{await browser.close();await server.close();}
});
