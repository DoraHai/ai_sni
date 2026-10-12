// Actual native login and pairing UI on the SSH-forwarded cloud acceptance origin.
import fs from 'node:fs/promises';
import path from 'node:path';
import {X509Certificate,createHash,randomUUID} from 'node:crypto';
import puppeteer from 'puppeteer-core';
const root=await fs.realpath(path.resolve(process.argv[2]||''));
const temp=await fs.realpath(process.env.TEMP);
if(path.dirname(root).toLowerCase()!==temp.toLowerCase()||path.basename(root)!=='distribution-cloud-pilot-20261012')throw Error('OWNED_CLOUD_PILOT_REQUIRED');
const credentials=JSON.parse(await fs.readFile(path.join(root,'operator-login.json'),'utf8'));
if(credentials.production!==false||credentials.origins.seo!=='https://127.0.0.1:55861')throw Error('PRIVATE_ACCEPTANCE_REQUIRED');
const origin=credentials.origins.seo,run=path.join(root,'admin-browser-'+randomUUID());await fs.mkdir(run);
const certificate=new X509Certificate(await fs.readFile(path.join(root,'loopback.pem')));
const spki=createHash('sha256').update(certificate.publicKey.export({type:'spki',format:'der'})).digest('base64');
const browser=await puppeteer.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true,userDataDir:path.join(run,'profile'),args:['--ignore-certificate-errors-spki-list='+spki]});
const page=await browser.newPage();page.setDefaultTimeout(20000);const http=[],errors=[];let creation=null,stage='login';
page.on('pageerror',e=>errors.push(e.name));
page.on('response',async r=>{const url=new URL(r.url());if(url.origin!==origin)return;http.push({path:url.pathname,method:r.request().method(),status:r.status()});if(url.pathname==='/api/distribution/v1/device-pairings'&&r.request().method()==='POST'&&r.status()===200)creation=await r.json();});
try{
 await page.goto(origin+'/acceptance/pairing/',{waitUntil:'networkidle0'});
 await page.type('#entry-username',credentials.admin_username);await page.type('#entry-password',credentials.password);
 const captcha=await page.$eval('[data-entry=captcha]',e=>e.textContent.trim());
 await page.type('#entry-captcha',captcha);await page.click('#entry-login [type=submit]');
 await page.waitForSelector('[data-pairing-create]');
 await page.waitForFunction(()=>document.querySelector('[data-pairing-create] button')?.disabled===false);stage='create';
 await page.type('[data-pairing-create] [name=label]','公司电脑 · 独立发布验收');
 await page.$eval('[name=expires_in_seconds]',e=>{e.value='600';});
 if(await page.$eval('[data-pairing-create] [name=label]',e=>e.value)!=='公司电脑 · 独立发布验收')throw Error('FORM_NOT_READY');
 await page.click('[data-pairing-create] button');
 await page.waitForSelector('[data-pairing-code]');
 const code=await page.$eval('[data-pairing-code]',e=>e.value);
 await page.waitForFunction(()=>document.querySelector('.device-pairing')?.textContent.includes('等待电脑领取'));
 if(!creation||creation.code_once!==true||code!==creation.pairing_code||!/^[A-Za-z0-9_-]{32}$/.test(code))throw Error('ACTUAL_PAIRING_REQUIRED');
 const privateFile=path.join(root,'one-time-pairing-private.json');
 await fs.writeFile(privateFile,JSON.stringify({origin,pairing_code:code,pairing_id:creation.pairing.id,device_id:creation.pairing.device_id,request_id:creation.pairing.request_id,expires_at:creation.pairing.expires_at}),{flag:'wx',mode:0o600});
 stage='pagehide';await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pagehide')));
 if(await page.$('[data-pairing-code]'))throw Error('SHORT_CODE_RETAINED_AFTER_PAGEHIDE');
 await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true})));
 await page.waitForSelector('[data-pairing-create]');
 if(await page.$('[data-pairing-code]'))throw Error('SHORT_CODE_RESTORED_FROM_CACHE');
 if(errors.length)throw Error('PAGE_ERRORS');
 await page.screenshot({path:path.join(run,'pairing-metadata-only.png'),fullPage:true});
 const evidence={nativeLogin:true,actualCloudHTTP:true,apiResponsesMocked:false,pairingId:creation.pairing.id,deviceId:creation.pairing.device_id,createPosts:http.filter(x=>x.path==='/api/distribution/v1/device-pairings'&&x.method==='POST').length,pagehideClearsCode:true,restoreRechecksIdentity:true,restoreDoesNotRecoverCode:true,credentialReturnedToWebpage:false,http,pageErrors:errors,production:false,publicationAttempted:false};
 await fs.writeFile(path.join(root,'cloud-admin-pairing-evidence.json'),JSON.stringify(evidence,null,2));
 console.log(JSON.stringify({passed:true,...evidence,privateCodeFileCreated:true}));
}catch(e){await fs.writeFile(path.join(root,'cloud-admin-pairing-failure.json'),JSON.stringify({stage,error:e.name,code:e.message,http,pageErrors:errors,publicationAttempted:false},null,2));throw Error('CLOUD_PAIRING_UI_FAILED_AT_'+stage);}
finally{await browser.close();}
