// Delay the real initial metadata request; never mock its response or create a ticket.
import fs from 'node:fs/promises';
import path from 'node:path';
import {X509Certificate,createHash,randomUUID} from 'node:crypto';
import puppeteer from 'puppeteer-core';
const root=await fs.realpath(path.resolve(process.argv[2]||''));
const temp=await fs.realpath(process.env.TEMP);
if(path.dirname(root).toLowerCase()!==temp.toLowerCase()||path.basename(root)!=='distribution-cloud-pilot-20261012')throw Error('OWNED_CLOUD_PILOT_REQUIRED');
const config=JSON.parse(await fs.readFile(path.join(root,'operator-login.json'),'utf8'));
const origin=config.origins.seo;
if(config.production!==false||origin!=='https://127.0.0.1:55861')throw Error('PRIVATE_ACCEPTANCE_REQUIRED');
const certificate=new X509Certificate(await fs.readFile(path.join(root,'loopback.pem')));
const spki=createHash('sha256').update(certificate.publicKey.export({type:'spki',format:'der'})).digest('base64');
const run=path.join(root,'draft-browser-'+randomUUID());await fs.mkdir(run);
const browser=await puppeteer.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true,userDataDir:path.join(run,'profile'),args:['--ignore-certificate-errors-spki-list='+spki]});
const page=await browser.newPage();page.setDefaultTimeout(20000);
const http=[],errors=[];let held=null,released=false,stage='login';
await page.setRequestInterception(true);
page.on('request',request=>{
 const u=new URL(request.url());
 if(u.origin===origin&&u.pathname==='/api/distribution/v1/device-pairings'&&request.method()==='GET'&&!released){held=request;return;}
 void request.continue();
});
page.on('response',response=>{const u=new URL(response.url());if(u.origin===origin)http.push({path:u.pathname,method:response.request().method(),status:response.status()});});
page.on('pageerror',e=>errors.push(e.name));
try{
 await page.goto(origin+'/acceptance/pairing/',{waitUntil:'networkidle0'});
 await page.type('#entry-username',config.admin_username);await page.type('#entry-password',config.password);
 await page.type('#entry-captcha',await page.$eval('[data-entry=captcha]',e=>e.textContent.trim()));
 await page.click('#entry-login [type=submit]');await page.waitForSelector('[data-pairing-create]');stage='draft';
 await page.waitForFunction(()=>document.querySelector('[data-pairing-create] button')?.disabled===true);
 await page.type('[data-pairing-create] [name=label]','慢网输入保留验收');
 await page.$eval('[name=expires_in_seconds]',e=>{e.value='420';e.dispatchEvent(new Event('input',{bubbles:true}));});
 if(!held)throw Error('ACTUAL_METADATA_REQUEST_NOT_HELD');
 released=true;await held.continue();held=null;
 await page.waitForFunction(()=>document.querySelector('[data-pairing-create] button')?.disabled===false);
 const values=await page.$eval('[data-pairing-create]',f=>({label:f.elements.label.value,ttl:f.elements.expires_in_seconds.value}));
 if(values.label!=='慢网输入保留验收'||values.ttl!=='420')throw Error('DRAFT_ERASED_BY_ACTUAL_READ');
 stage='pagehide';await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pagehide')));
 if(await page.$('[data-pairing-create]'))throw Error('DRAFT_DOM_RETAINED');
 await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true})));
 await page.waitForFunction(()=>document.querySelector('[data-pairing-create] button')?.disabled===false);
 const restored=await page.$eval('[data-pairing-create]',f=>({label:f.elements.label.value,ttl:f.elements.expires_in_seconds.value}));
 if(restored.label!==''||restored.ttl!=='300')throw Error('DRAFT_RESTORED_FROM_CACHE');
 if(errors.length||http.some(x=>x.path==='/api/distribution/v1/device-pairings'&&x.method==='POST'))throw Error('READ_ONLY_BROWSER_CHECK_REQUIRED');
 const evidence={nativeLogin:true,actualCloudHTTP:true,responsesMocked:false,realRequestHeldUntilInput:true,
  draftSurvivesActualRead:true,pagehideClearsDraft:true,cacheRestoreDoesNotRecoverDraft:true,
  pairingCreated:false,publicationAttempted:false,production:false,http,pageErrors:errors};
 await fs.writeFile(path.join(root,'cloud-pairing-draft-browser-evidence.json'),JSON.stringify(evidence,null,2));
 console.log(JSON.stringify({passed:true,...evidence}));
}catch(e){await fs.writeFile(path.join(run,'failure.json'),JSON.stringify({stage,error:e.name,code:e.message,http,pageErrors:errors}));throw Error('CLOUD_DRAFT_BROWSER_FAILED_AT_'+stage);}
finally{if(held)await held.abort();await browser.close();}
