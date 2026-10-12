// Real compiled advisor UI -> native JWT -> owned HTTPS broker -> separate MHT.
// No intercepted API responses, injected auth, fixture host, or platform login.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash,X509Certificate,randomUUID} from 'node:crypto';
import https from 'node:https';
import puppeteer from 'puppeteer-core';

const root=await fs.realpath(path.resolve(process.argv[2]||''));
const temp=await fs.realpath(process.env.TEMP);
if(path.dirname(root).toLowerCase()!==temp.toLowerCase()||path.basename(root)!=='distribution-server-pilot-20261012')throw Error('OWNED_PILOT_REQUIRED');
const read=async name=>JSON.parse(await fs.readFile(path.join(root,name),'utf8'));
const config=await read('environment.json'),pairing=await read('seo-pairing.json'),secret=await read('secrets.json');
if(config.production!==false||config.ports.seo!==55861||config.ports.pg!==55483||pairing.scope.module!=='seo'||pairing.scope.tenant_id!==15||pairing.scope.scope_id!==6)throw Error('EXACT_PILOT_REQUIRED');
const origin='https://127.0.0.1:55861',run=path.join(root,'advisor-browser-'+randomUUID());
await fs.mkdir(run);
const ca=new X509Certificate(await fs.readFile(path.join(root,'loopback.pem')));
const spki=createHash('sha256').update(ca.publicKey.export({type:'spki',format:'der'})).digest('base64');
const browser=await puppeteer.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true,userDataDir:path.join(run,'profile'),args:['--ignore-certificate-errors-spki-list='+spki],defaultViewport:{width:1440,height:1050}});
const journal=[],errors=[],pending=new Set();let remoteSession=null,page=null,stage='launch',operatorToken=null;
try{
 page=await browser.newPage();page.setDefaultTimeout(20000);
 page.on('pageerror',e=>errors.push(e.name));
 await page.setRequestInterception(true);
 page.on('request',req=>{const u=new URL(req.url());return ['blob:','data:'].includes(u.protocol)||u.origin===origin?req.continue():req.abort();});
 page.on('response',response=>{
   const work=(async()=>{
    const u=new URL(response.url());if(u.origin!==origin||!u.pathname.startsWith('/api/'))return;
    journal.push({method:response.request().method(),path:u.pathname,status:response.status()});
    if(u.pathname==='/api/v1/auth/login'&&response.status()===200)operatorToken=(await response.json()).token;
    if(u.pathname.endsWith('/remote/sessions')&&response.request().method()==='POST'&&response.status()===200){
      const body=await response.json();remoteSession={id:body.session.id,state:body.session.state,
       controller_user_id:body.session.controller_user_id,binding_id:body.session.binding_id,
       automatic_submit:body.session.automatic_submit,publication_verified:body.session.publication_verified};
    }
   })().catch(()=>{errors.push('RESPONSE_READ_FAILED');});pending.add(work);void work.finally(()=>pending.delete(work));
 });
 stage='login';await page.goto(origin+'/customer-workbench/?console=advisor',{waitUntil:'networkidle0'});
 await page.type('#entry-username','acceptance-advisor');await page.type('#entry-password',secret.password);
 const challenge=await page.$eval('[data-entry=captcha]',e=>e.textContent);
 await page.type('#entry-captcha',challenge);await page.click('#entry-login [type=submit]');
 stage='scope';await page.waitForSelector('select[name=distribution_scope]');
 await page.select('select[name=distribution_scope]','seo:15:6');
 await page.waitForFunction(binding=>[...document.querySelectorAll('select[name=distribution_binding] option')].some(e=>e.value===binding),{},pairing.bindingIds[0]);
 await page.select('select[name=distribution_binding]',pairing.bindingIds[0]);
 await page.waitForFunction(()=>{const b=document.querySelector('[data-remote-action=open]');return b&&!b.disabled;});
 stage='open';await page.click('[data-remote-action=open]');
 stage='first-frame';
 await page.waitForFunction(()=>{const e=document.querySelector('.advisor-remote-frame');return e&&e.complete&&e.naturalWidth===1024&&!document.querySelector('[data-remote-text]').disabled;});
 if(remoteSession?.controller_user_id!==100007||remoteSession.binding_id!==pairing.bindingIds[0]||remoteSession.automatic_submit!==false||remoteSession.publication_verified!==false)throw Error('REAL_SESSION_BINDING_FAILED');
 const frame=await page.$eval('.advisor-remote-frame',e=>({src:e.src,width:e.naturalWidth,height:e.naturalHeight}));
 if(!frame.src.startsWith('blob:')||frame.height!==768)throw Error('REAL_FRAME_REQUIRED');
 await page.screenshot({path:path.join(run,'advisor-connected.png'),fullPage:true});
 await page.$eval('.advisor-remote-frame',e=>e.scrollIntoView({block:'center'}));
 const box=await page.$eval('.advisor-remote-frame',e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};});
 stage='mouse';await page.mouse.click(box.x+155*box.width/1024,box.y+215*box.height/768);
 await page.waitForFunction(()=>document.querySelector('.advisor-remote')?.textContent.includes('最近命令：applied'));
 await page.waitForFunction(()=>!document.querySelector('[data-remote-text]').disabled);
 stage='text';await page.type('[data-remote-text]','TEST-7391');await page.click('[data-remote-action=text]');
 await page.waitForFunction(()=>document.querySelector('.advisor-remote')?.textContent.includes('最近命令：applied')&&!document.querySelector('[data-remote-text]').disabled);
 if(await page.$eval('[data-remote-text]',e=>e.value)!=='')throw Error('INPUT_NOT_CLEARED');
 await page.screenshot({path:path.join(run,'advisor-input-applied.png'),fullPage:true});
 // Independently capture a current native-JWT PNG while control is still open.
 await new Promise(r=>setTimeout(r,1100));await Promise.allSettled([...pending]);
 if(!operatorToken)throw Error('REAL_NATIVE_TOKEN_REQUIRED');
 const raw=await new Promise((resolve,reject)=>{
  const req=https.get(origin+'/api/distribution/v1/remote/sessions/'+remoteSession.id+'/frame',
   {ca:ca.toString(),headers:{Authorization:'Bearer '+operatorToken}},res=>{
    const chunks=[];let size=0;res.on('data',b=>{size+=b.length;if(size>2097152)req.destroy(Error('FRAME_LIMIT'));else chunks.push(b);});
    res.on('end',()=>{if(res.statusCode!==200)reject(Error('REAL_PNG_RESPONSE_REQUIRED'));else resolve(Buffer.concat(chunks));});res.on('error',reject);
   });req.setTimeout(5000,()=>req.destroy(Error('REAL_PNG_TIMEOUT')));req.on('error',reject);
 });
 if(raw.length<8||raw.subarray(0,8).toString('hex')!=='89504e470d0a1a0a')throw Error('REAL_PNG_RESPONSE_REQUIRED');
 journal.push({method:'GET',path:'/api/distribution/v1/remote/sessions/'+remoteSession.id+'/frame',status:200,evidence_capture:true});
 await fs.writeFile(path.join(run,'remote-input-applied.png'),raw);
 const noSecrets=await page.evaluate(()=>!document.body.innerHTML.includes('control_nonce')&&!document.body.innerHTML.includes('device.secret'));
 if(!noSecrets)throw Error('SECRET_IN_DOM');
 stage='close';await page.click('[data-remote-action=close]');await page.waitForFunction(()=>!document.querySelector('.advisor-remote-frame')&&document.querySelector('.advisor-remote')?.textContent.includes('会话已关闭'));
 const remoteReadsBeforeLogout=journal.filter(r=>r.path.includes('/remote/')).length;
 stage='logout';await page.click('[data-advisor=logout]');await new Promise(r=>setTimeout(r,1500));
 if(journal.filter(r=>r.path.includes('/remote/')).length!==remoteReadsBeforeLogout)throw Error('READ_AFTER_LOGOUT');
 await Promise.allSettled([...pending]);
 if(errors.length)throw Error('BROWSER_RUNTIME_ERROR');
 if(journal.some(r=>r.path.includes('/remote/device/')))throw Error('DEVICE_API_IN_BROWSER');
 const report={actual_compiled_advisor:true,native_form_login:true,native_user_id:100007,
  scope:pairing.scope,binding_id:pairing.bindingIds[0],session:remoteSession,
  screenshot_dimensions:{width:frame.width,height:frame.height},mouse_ack_applied:true,text_ack_applied:true,
  close_released_control:true,logout_stops_reads:true,operator_only:true,
  synthetic_platform_page:true,real_platform_login:false,formal_publication:false,
  production_mutations:false,broker_port:55861,pg_port:55483,journal,errors,run_root:run};
 await fs.writeFile(path.join(root,'advisor-real-broker-evidence.json'),JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify({phase:'actual-advisor-broker-executor-passed',http_checks:journal.length,real_platform_login:false,formal_publication:false}));
}catch(e){
 let dom=null;
 if(page){await page.screenshot({path:path.join(run,'failure.png'),fullPage:true}).catch(()=>{});dom=await page.evaluate(()=>{const i=document.querySelector('.advisor-remote-frame'),t=document.querySelector('[data-remote-text]');return {frame:i?{complete:i.complete,width:i.naturalWidth,height:i.naturalHeight,src_prefix:i.src.slice(0,5)}:null,input_disabled:t?.disabled,remote_state:document.querySelector('.advisor-remote')?.textContent.slice(0,900),note:document.querySelector('[data-remote-note]')?.textContent};}).catch(()=>null);}
 await fs.writeFile(path.join(root,'advisor-real-broker-failure.json'),JSON.stringify({code:typeof e.message==='string'&&/^[A-Z_]+$/.test(e.message)?e.message:e.name,stage,dom,journal,errors,run_root:run},null,2)+'\n');
 console.error('Actual advisor pilot failed; inspect private status-only evidence.');process.exitCode=1;
}finally{
 if(page&&await page.$eval('[data-remote-action=close]',e=>!e.disabled).catch(()=>false)){
  const response=page.waitForResponse(r=>r.url().endsWith('/close')&&r.request().method()==='POST',{timeout:5000}).catch(()=>null);
  await page.$eval('[data-remote-action=close]',e=>e.click()).catch(()=>{});
  const result=await response;
  await fs.writeFile(path.join(run,'cleanup-control.json'),JSON.stringify({explicit_close_attempted:true,http_status:result?.status()??null})+'\n');
 }
 await browser.close();
}
