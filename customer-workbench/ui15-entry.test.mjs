import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {existsSync} from 'node:fs';
import {startFixtureServer} from './tests/fixture-server.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);

test('production entry keeps canonical login return scope and rejects absent, ambiguous or unauthorized scope',async()=>{
  const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
  try{
    const page=await browser.newPage(),origin='https://workbench.test',errors=[],external=[];
    page.on('pageerror',e=>errors.push(e.message));await page.setRequestInterception(true);
    page.on('request',async request=>{
      const url=new URL(request.url());if(url.origin!==origin){external.push(url.href);return request.abort();}
      if(['/login','/workspace/cockpit'].includes(url.pathname))return request.respond({status:200,contentType:'text/html',body:'Existing host fixture'});
      try{const response=await fetch(fixture.origin+url.pathname+url.search,{method:request.method(),headers:request.headers(),body:request.postData()});await request.respond({status:response.status,contentType:response.headers.get('content-type'),body:Buffer.from(await response.arrayBuffer())});}catch{await request.abort();}
    });
    const entry='/customer-workbench/?tenant_id=1&site_id=9';
    await page.goto(origin+entry);await page.waitForSelector('[data-action=login]');assert.equal(fixture.state.calls.length,0);
    await Promise.all([page.waitForNavigation(),page.click('[data-action=login]')]);assert.equal(new URL(page.url()).searchParams.get('redirect'),entry);
    await page.evaluate(()=>sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token:'fixture-customer',user:{id:12,tenant_id:1,display_name:'客户',permissions:{'seo.content':'view','seo.site':'view'}}})));
    await page.goto(origin+entry);await page.waitForSelector('.summary-grid');assert.match(await page.$eval('#identity',e=>e.textContent),/站点9/);
    for(const query of ['', '?tenant_id=1','?tenant_id=1&tenant_id=2&site_id=9','?tenant_id=1&site_id=9&site_id=19','?tenant_id=1&site_id=0','?tenant_id=2&site_id=19']){
      const before=fixture.state.calls.length;await page.goto(origin+'/customer-workbench/'+query);await page.waitForFunction(()=>document.body.textContent.includes('请在宿主选择'));
      assert.equal(fixture.state.calls.length,before,'Invalid candidate scope sends no business requests');assert(await page.$('a[href="/workspace/cockpit"]'));
      assert.equal(await page.evaluate(()=>sessionStorage.getItem('sem_tenant_id')),'1','Customer binding is preserved');
    }
    await page.goto(origin+'/customer-workbench/?tenant_id=1&site_id=19');await page.waitForFunction(()=>document.body.textContent.includes('当前身份无权'));
    assert(!fixture.state.calls.some(c=>c.query.site_id==='19'));
    await page.goto(origin+entry);await page.waitForSelector('.summary-grid');fixture.state.forceError={path:'/content-assets',status:401};
    await Promise.all([page.waitForNavigation(),page.click('.navigation [data-page="内容"]')]);assert.equal(new URL(page.url()).pathname,'/login');assert.equal(new URL(page.url()).searchParams.get('redirect'),entry);assert.equal(await page.evaluate(()=>sessionStorage.getItem('sem_auth_v1')),null);
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  }finally{await browser.close();await fixture.close();}
});
