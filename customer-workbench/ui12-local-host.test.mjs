import test from 'node:test';import assert from 'node:assert/strict';import http from 'node:http';import https from 'node:https';import fs from 'node:fs';import puppeteer from 'puppeteer-core';
import {loopbackBackend,startLocalBackendHost} from './scripts/local-backend-host.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
test('local host rejects non-loopback upstreams and credentials',()=>{
  for(const origin of ['https://example.com','http://localhost:8000','http://0.0.0.0:8000','http://127.0.0.1:8000/api','http://user:secret@127.0.0.1:8000','http://127.0.0.1:8000/?token=x'])assert.throws(()=>loopbackBackend(origin));
  assert.equal(loopbackBackend('http://127.0.0.1:8000').origin,'http://127.0.0.1:8000');
});
function request(origin,path,options={}){return new Promise((resolve,reject)=>{
  const req=https.request(origin+path,{rejectUnauthorized:false,...options},res=>{const chunks=[];res.on('data',chunk=>chunks.push(chunk));res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(chunks).toString()}));});req.on('error',reject);req.end(options.body);
});}
test('TLS proxy preserves upstream status/body/ETag and compiled login uses original session bootstrap (transport stub only)',async()=>{
  const upstreamCalls=[];
  const upstream=http.createServer(async(req,res)=>{
    let body='';for await(const chunk of req)body+=chunk;upstreamCalls.push({method:req.method,path:req.url,body,headers:req.headers});
    const json=(status,value)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(value));};
    if(req.url==='/api/v1/auth/login')return json(200,{token:'ui12-transport-only-token',user:{id:17,tenant_id:11,permissions:{'seo.content':'view','seo.site':'view'}}});
    if(req.url==='/api/v1/auth/tenants')return json(200,{tenants:[{id:11,name:'transport-only'}]});
    if(req.url==='/api/v1/auth/me')return json(503,{detail:'Deliberate transport stub: business backend absent'});
    res.writeHead(409,{'Content-Type':'application/json',ETag:'"test-etag"','Set-Cookie':'must-not-store=1','Location':'https://example.invalid'});res.end('{"detail":{"code":"probe_conflict"}}');
  });
  await new Promise(resolve=>upstream.listen(0,'127.0.0.1',resolve));let host,browser;
  try{
    host=await startLocalBackendHost({backendOrigin:`http://127.0.0.1:${upstream.address().port}`});
    const probe=await request(host.origin,'/api/v1/seo/probe',{method:'POST',headers:{Origin:host.origin,Authorization:'Bearer transport-probe','Content-Type':'application/json'},body:'{"version_count":7}'});
    assert.equal(probe.status,409);assert.equal(probe.headers.etag,'"test-etag"');assert.equal(probe.body,'{"detail":{"code":"probe_conflict"}}');assert.equal(probe.headers['set-cookie'],undefined);assert.equal(probe.headers.location,undefined);
    assert.equal(upstreamCalls[0].body,'{"version_count":7}');assert.equal(upstreamCalls[0].headers.authorization,'Bearer transport-probe');
    const count=upstreamCalls.length;assert.equal((await request(host.origin,'/api/v1/seo/probe',{method:'POST',headers:{Origin:'https://example.invalid'}})).status,403);assert.equal((await request(host.origin,'/api/v1/sem/probe')).status,404);assert.equal(upstreamCalls.length,count);
    assert.equal((await request(host.origin,'/customer-workbench/')).status,200);assert.equal((await request(host.origin,'/tests/fixture-host.mjs')).status,404);
    browser=await puppeteer.launch({executablePath:edge,headless:true,args:[`--ignore-certificate-errors-spki-list=${host.spki}`]});
    const page=await browser.newPage(),errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
    await page.setRequestInterception(true);page.on('request',async req=>{const url=new URL(req.url());if(['http:','https:'].includes(url.protocol)&&url.origin!==host.origin){external.push(url.origin);await req.abort();}else await req.continue();});
    const entry=host.origin+'/customer-workbench/?tenant_id=11&site_id=19';await page.goto(entry);await page.waitForSelector('[data-action="login"]');
    assert.match(await page.$eval('body',e=>e.textContent),/尚未登录/);
    await Promise.all([page.waitForNavigation(),page.click('[data-action="login"]')]);assert.equal(new URL(page.url()).pathname,'/login');
    await page.type('[name="username"]','transport-only');await page.type('[name="password"]','synthetic-local-only');await Promise.all([page.waitForNavigation(),page.click('form button')]);
    await page.waitForFunction(()=>document.querySelector('#connected-message')?.textContent.includes('服务能力尚未启用'),{polling:50});
    assert.equal(page.url(),entry);assert.deepEqual(await page.evaluate(()=>({keys:Object.keys(sessionStorage).sort(),local:Object.keys(localStorage),userId:JSON.parse(sessionStorage.getItem('sem_auth_v1')).user.id})),{keys:['sem_auth_v1','sem_tenant_id','sem_token','sem_user'],local:[],userId:17});
    assert.equal(upstreamCalls.find(c=>c.path==='/api/v1/auth/me').headers.authorization,'Bearer ui12-transport-only-token');
    assert(!host.calls.some(c=>JSON.stringify(c).includes('token')));assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  }finally{if(browser)await browser.close();if(host)await host.close();await new Promise(resolve=>{upstream.close(resolve);upstream.closeAllConnections();});}
});
