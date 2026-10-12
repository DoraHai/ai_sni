// Actual DOM -> actual loopback API. Private profile and narrowly pinned CA.
const {app,BrowserWindow,session}=require('electron');
const {readFileSync,mkdirSync,writeFileSync,realpathSync:portableRealpath}=require('node:fs');
const realpathSync=portableRealpath.native;
const {join,dirname,basename}=require('node:path');
const {X509Certificate,randomUUID,createHash}=require('node:crypto');
const suppliedRoot=process.argv[2],stage=process.argv[3]||'seo-review';
const moduleName=stage.startsWith('geo-')?'geo':'seo';
if(!suppliedRoot)throw Error('OWNED_ROOT_REQUIRED');
const root=realpathSync(suppliedRoot),temp=realpathSync(process.env.TEMP);
if(dirname(root).toLowerCase()!==temp.toLowerCase()||basename(root)!=='distribution-acceptance-full-flow-20261012')throw Error('OWNED_ROOT_REQUIRED');
const config=JSON.parse(readFileSync(join(root,'environment.json'),'utf8'));
const expectedHeads={seo:'b4d8387123355348f79e26ea2838585c5106a4b9',geo:'46dacbd805afc00f37eba344306fde004039efed'};
if(config.production!==false||realpathSync(config.root).toLowerCase()!==root.toLowerCase()||JSON.stringify(config.ports)!==JSON.stringify({pg:55473,seo:55851,geo:55852})||Object.entries(expectedHeads).some(([key,value])=>config.native_heads[key]!==value)||realpathSync(config.central_root).toLowerCase()!==realpathSync(join(__dirname,'..')).toLowerCase())throw Error('ACCEPTANCE_CONFIG_REQUIRED');
for(const[key,directory]of Object.entries({seo:'seo-review-response-acceptance-20261012',geo:'geo-manual-channel-acceptance-20261012'}))if(realpathSync(config.native_roots[key]).toLowerCase()!==realpathSync(join(config.central_root,'..',directory)).toLowerCase())throw Error('ACCEPTANCE_NATIVE_ROOT_REQUIRED');
const profile=join(root,'central-ui-profile-'+randomUUID());mkdirSync(profile);
app.setPath('userData',profile);
const authority=new X509Certificate(readFileSync(join(root,'loopback.pem')));
const password=JSON.parse(readFileSync(join(root,'secrets.json'),'utf8')).password;
const checks=[];let window,paintSerial=0;
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function dom(code){return window.webContents.executeJavaScript(code);}
async function wait(code){for(let i=0;i<100;i++){if(await dom(code))return;await pause(100);}throw Error('DOM_EXPECTATION_TIMEOUT');}
async function click(id){await wait(`!document.getElementById(${JSON.stringify(id)}).disabled`);await dom(`document.getElementById(${JSON.stringify(id)}).click()`);}
async function login(name){
 await dom(`document.getElementById('username').value=${JSON.stringify(name)};document.getElementById('password').value=${JSON.stringify(password)};document.getElementById('login').click()`);
 await wait(`!document.getElementById('workspace').hidden && document.getElementById('actor').textContent.includes(${JSON.stringify(name)}) && document.getElementById('status').textContent.includes('登录完成')`);
 checks.push('actual native login '+name);
}
async function switchActor(name){await click('logout');await login(name);}
async function confirmChecked(){await dom("document.getElementById('checked').checked=true;document.getElementById('checked').dispatchEvent(new Event('change',{bubbles:true}))");}
async function shot(name){
 await dom('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))');
 const serial=paintSerial;window.webContents.invalidate();
 for(let i=0;i<40&&paintSerial===serial;i++)await pause(50);
 if(paintSerial===serial)throw Error('CURRENT_DOM_PAINT_REQUIRED');
 const image=await window.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true});const bytes=image.toPNG();writeFileSync(join(root,name+'.png'),bytes);return{file:name+'.png',sha256:createHash('sha256').update(bytes).digest('hex'),freshPaint:true};
}
app.whenReady().then(async()=>{
 const s=session.fromPartition('acceptance-'+randomUUID(),{cache:false});
 s.setCertificateVerifyProc((request,callback)=>{
  try{const leaf=new X509Certificate(request.certificate.data);const now=Date.now();callback(request.hostname==='127.0.0.1'&&leaf.fingerprint256===authority.fingerprint256&&leaf.checkIP('127.0.0.1')&&leaf.verify(authority.publicKey)&&now>=Date.parse(leaf.validFrom)&&now<Date.parse(leaf.validTo)?0:-3);}catch{callback(-3);}
 });
 s.webRequest.onBeforeRequest((details,callback)=>{try{const u=new URL(details.url);callback({cancel:u.protocol!=='https:'||u.hostname!=='127.0.0.1'||!['55851','55852'].includes(u.port)});}catch{callback({cancel:true});}});
 window=new BrowserWindow({show:false,width:1320,height:1000,webPreferences:{session:s,nodeIntegration:false,contextIsolation:true,sandbox:true,backgroundThrottling:false,offscreen:true}});
 window.webContents.on('paint',()=>{paintSerial++});
 let failed=false;
 try{
  const module=moduleName;
  await window.loadURL('https://127.0.0.1:'+config.ports[module]+'/acceptance/');
  await login('acceptance-advisor');
  const initial=await shot(module+'-advisor-initial');
  if(stage==='seo-review'){
   if(await dom("!document.getElementById('clone').disabled")){await click('clone');await wait("document.getElementById('local-state').textContent.includes('drafting')");checks.push('DOM clone creates native draft');}
   else checks.push('reuse persisted native draft; no duplicate clone');
   await click('submit-master');await wait("document.getElementById('local-state').textContent.includes('review /')");checks.push('DOM submit invokes native review state machine');
   await switchActor('acceptance-reviewer');await confirmChecked();await click('approve-master');await wait("document.getElementById('local-state').textContent.includes('ready /')");checks.push('native local test reviewer approves new master');
   await switchActor('acceptance-advisor');await confirmChecked();await click('confirm');await wait("document.getElementById('local-state').textContent.includes('确认 approved')");checks.push('native advisor-proxy exact-version confirmation');
   await click('adapt');await wait("document.getElementById('local-state').textContent.includes('渠道稿 pending_review')");checks.push('native non-AI adaptation and new pending channel variant');
   await switchActor('acceptance-reviewer');await confirmChecked();await click('approve-variant');await wait("document.getElementById('local-state').textContent.includes('渠道稿 approved')");checks.push('native local test reviewer approves exact new channel variant');
   await switchActor('acceptance-advisor');
   const approved=await shot('seo-advisor-approved-paused');
   // Keep MHT's sole GUI executor stopped until coordinator receives task tuple.
   writeFileSync(join(root,'seo-ui-review-evidence.json'),JSON.stringify({stage,checks,screenshots:[initial,approved],actualDOM:true,actualAPI:true,publicationVerified:false,project:'paused',approval:'native local test accounts; not real customer approval',TLS:'exact self-signed acceptance CA, IP/SAN/signature/date validation; no global ignore'},null,2));
  }else if(stage==='seo-read'){
   await wait("!document.getElementById('workspace').hidden&&document.getElementById('actor').textContent.includes('acceptance-advisor')&&document.getElementById('local-state').textContent.includes('ready / 确认 approved / 渠道稿 approved')&&document.getElementById('project-state').textContent.includes('paused')&&!document.getElementById('resume').disabled");
   const state=await dom("({actor:document.getElementById('actor').textContent,state:document.getElementById('local-state').textContent,project:document.getElementById('project-state').textContent,workspaceVisible:!document.getElementById('workspace').hidden})");
   checks.push('current approved workspace read-only; no review replay');
   writeFileSync(join(root,'seo-ui-current-read-evidence.json'),JSON.stringify({stage,checks,state,screenshot:await shot('seo-advisor-current-approved-paused'),actualDOM:true,actualAPI:true,publicationVerified:false,corrects:'first hidden-window screenshot painted previous login panel; initial API/DOM actions remain recorded separately'},null,2));
  }else if(stage==='session-race'){
   const delay=()=>writeFileSync(join(root,'ui-delay-seo.json'),JSON.stringify({remaining:1,delay_ms:1500}));
   async function received(){for(let i=0;i<50;i++){if(JSON.parse(readFileSync(join(root,'ui-delay-seo.json'),'utf8')).remaining===0)return;await pause(100);}throw Error('REAL_API_DELAY_NOT_RECEIVED');}
   delay();await click('refresh');await received();await click('logout');await pause(1800);
   if(!await dom("document.getElementById('workspace').hidden&&document.getElementById('original-body').value===''&&document.getElementById('local-body').value===''&&document.getElementById('local-state').textContent===''&&document.getElementById('approve-master').disabled&&document.getElementById('status').textContent==='已退出'"))throw Error('STALE_LOGOUT_DOM');
   checks.push('real delayed original response after logout cannot restore body or actions');
   const logoutShot=await shot('seo-ui-session-logout-safe');
   // Deliberately make this one real read uncancelable to exercise epoch checks.
   // Response bytes and server auth remain real, with the same pinned TLS.
   await dom("const realFetch=window.fetch;window.fetch=(url,options)=>String(url).includes('/acceptance/original')?realFetch(url,{...options,signal:undefined}):realFetch(url,options);void 0");
   delay();await dom(`document.getElementById('username').value='acceptance-advisor';document.getElementById('password').value=${JSON.stringify(password)};document.getElementById('login').click()`);await received();
   await dom(`document.getElementById('username').value='acceptance-customer-1';document.getElementById('password').value=${JSON.stringify(password)};document.getElementById('login').click()`);
   await wait("document.getElementById('status').textContent.includes('登录未完成')");await pause(1800);
   if(!await dom("document.getElementById('workspace').hidden&&document.getElementById('original-body').value===''&&document.getElementById('local-body').value===''&&document.getElementById('actor').textContent===''&&document.getElementById('approve-master').disabled"))throw Error('STALE_FOREIGN_IDENTITY_DOM');
   checks.push('uncancelable real delayed advisor read cannot reveal body after foreign customer login');
   await login('acceptance-advisor');delay();await click('refresh');await received();await click('logout');await login('acceptance-customer-15');await pause(1800);
   if(!await dom("document.getElementById('actor').textContent.includes('acceptance-customer-15')&&document.getElementById('actions').hidden&&document.getElementById('approve-master').disabled&&document.getElementById('confirm').disabled"))throw Error('STALE_REVIEW_PERMISSION');
   checks.push('real delayed response cannot replace current customer identity or enable review');
   writeFileSync(join(root,'seo-ui-session-evidence.json'),JSON.stringify({stage,checks,screenshots:[logoutShot,await shot('seo-ui-session-customer-safe')],actualDOM:true,actualAPI:true,responseDelay:'actual native original response delayed 1500ms; payload unchanged',uncancelableRead:'one frontend test wrapper drops AbortSignal to exercise epoch, response not mocked',publicationVerified:false},null,2));
  }else if(stage==='seo-start'||stage==='geo-start'){
   if(module==='geo')await wait("document.getElementById('local-state').textContent.includes('客户审核 approved / 人工定版 approved')");
   await click('resume');await wait("document.getElementById('project-state').textContent.includes('running')");checks.push('DOM resume current revision enables central worker');
   writeFileSync(join(root,module+'-ui-start-evidence.json'),JSON.stringify({stage,checks,screenshot:await shot(module+'-advisor-running'),actualDOM:true,actualAPI:true,publicationVerified:false},null,2));
  }else if(stage==='seo-pause'||stage==='geo-pause'){
   await click('pause');await wait("document.getElementById('project-state').textContent.includes('paused')&&!document.getElementById('resume').disabled");checks.push('DOM pause current revision stops future central advancement');
   writeFileSync(join(root,module+'-ui-pause-evidence.json'),JSON.stringify({stage,checks,screenshot:await shot(module+'-advisor-paused-final'),actualDOM:true,actualAPI:true,publicationVerified:false},null,2));
  }else if(stage==='seo-customer'||stage==='geo-customer'){
   await switchActor('acceptance-customer-'+(module==='seo'?'15':'1'));
   await wait("!document.getElementById('workspace').hidden&&document.getElementById('actions').hidden&&document.getElementById('pause').disabled&&document.getElementById('resume').disabled&&document.getElementById('approve-master').disabled&&document.getElementById('confirm').disabled");
   const state=await dom("({actor:document.getElementById('actor').textContent,localState:document.getElementById('local-state').textContent,ledger:document.getElementById('tasks').textContent,actionsHidden:document.getElementById('actions').hidden})");
   if(!state.ledger.includes('HUMAN_HANDOFF_ACCEPTED'))throw Error('CURRENT_CUSTOMER_HANDOFF_REQUIRED');
   checks.push('actual current customer delivery shows accepted handoff and no project/review controls');
   writeFileSync(join(root,module+'-ui-customer-evidence.json'),JSON.stringify({stage,checks,state,screenshot:await shot(module+'-customer-handoff-readonly'),actualDOM:true,actualAPI:true,actualNativeVue:false,publicationVerified:false},null,2));
  }else throw Error('UNSUPPORTED_STAGE');
  process.stdout.write(JSON.stringify({stage,passed:checks.length,actualDOM:true,actualAPI:true,publicationVerified:false})+'\n');
 }catch(error){failed=true;await shot(moduleName+'-ui-failure');writeFileSync(join(root,moduleName+'-ui-error.json'),JSON.stringify({stage,code:String(error.message),checks,visibleStatus:await dom("document.getElementById('status').textContent")},null,2));}
 finally{window.destroy();app.exit(failed?1:0);}
}).catch(()=>{process.exitCode=1;app.quit();});
