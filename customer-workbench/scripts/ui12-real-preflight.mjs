// Run only after coordinator grants this host access to SEO's isolated schema.
import fs from 'node:fs/promises';import os from 'node:os';import path from 'node:path';import puppeteer from 'puppeteer-core';import {existsSync} from 'node:fs';
import {startLocalBackendHost} from './local-backend-host.mjs';
if(process.env.UI12_REAL_API_AUTHORIZED!=='true')throw Error('Real API login requires coordinator authorization; preparation alone does not grant DB access');
const config=JSON.parse(await fs.readFile(process.env.UI12_CONFIG_FILE,'utf8'));
if(config.environment_kind!=='isolated-local-pg'||!config.database||!config.schema||![config.tenant_id,config.site_id].every(n=>Number.isSafeInteger(n)&&n>0))throw Error('Explicit isolated database/schema and synthetic scope required');
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
const host=await startLocalBackendHost({backendOrigin:config.backend_origin}),report={scope:'UI12 real login + read-only business preflight; not full workflow acceptance',backend:config.backend_origin,database:config.database,schema:config.schema,backendCommit:config.backend_commit??null,buildCommit:host.manifest.upstreamCommit,externalAdapters:config.external_adapters??'not supplied',roles:[],result:'failed'};let browser;
const output=await fs.mkdtemp(path.join(os.tmpdir(),'workbench-ui12-preflight-'));
try{
  browser=await puppeteer.launch({executablePath:edge,headless:true,args:[`--ignore-certificate-errors-spki-list=${host.spki}`]});
  for(const role of ['advisor','customer']){
    const account=config[role];if(!account?.username||!account?.password)throw Error('Synthetic role credentials missing: '+role);
    const context=await browser.createBrowserContext(),page=await context.newPage(),errors=[],unexpected=[];
    page.on('pageerror',e=>errors.push(e.message));await page.setRequestInterception(true);
    page.on('request',async request=>{const url=new URL(request.url());if(['http:','https:'].includes(url.protocol)&&url.origin!==host.origin){unexpected.push(url.origin);await request.abort();}else await request.continue();});
    const entry=host.origin+`/customer-workbench/?tenant_id=${config.tenant_id}&site_id=${config.site_id}`;
    try{
      await page.goto(entry);await page.waitForSelector('[data-action="login"]');await Promise.all([page.waitForNavigation(),page.click('[data-action="login"]')]);
      await page.type('[name="username"]',account.username);await page.type('[name="password"]',account.password);await Promise.all([page.waitForNavigation(),page.click('form button')]);
      await page.waitForSelector('#pagination-summary',{timeout:20000});
      for(const name of ['服务计划','进度','数据']){
        await page.waitForFunction(label=>{const node=document.querySelector(`.navigation [data-page="${label}"]`);return node&&!node.disabled;},{polling:50},name);
        await page.click(`.navigation [data-page="${name}"]`);await page.waitForFunction(()=>document.querySelector('#connected-message')?.textContent==='',{polling:50,timeout:20000});
      }
      const writes=host.calls.filter(c=>!['GET','HEAD'].includes(c.method)&&c.path!=='/api/v1/auth/login');if(writes.length)throw Error('Unexpected business write in preflight');
      if(errors.length||unexpected.length)throw Error('Browser error or external request');
      report.roles.push({role,result:'passed',pages:['首页','服务计划','进度','数据'],storage:'canonical session.setAuth; transient sessionStorage'});
    }finally{await context.close();}
  }
  report.result='passed';
}catch(error){report.error=error.name==='TimeoutError'?'Timed out waiting for expected page; inspect API status trace':error.message;process.exitCode=1;}
finally{
  report.apiCalls=host.calls;await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
  if(browser)await browser.close();await host.close();console.log(JSON.stringify({result:report.result,report:path.join(output,'report.json')},null,2));
}
