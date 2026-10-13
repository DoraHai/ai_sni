'use strict';
// Companion launcher. The original frozen executor and its credential store stay intact.
const {app,BrowserWindow,Menu,dialog,clipboard}=require('electron');
const path=require('node:path'),fs=require('node:fs');
const {pathToFileURL}=require('node:url');
const {spawn}=require('node:child_process');
const packageRoot=path.resolve(process.argv[2]),parent=path.resolve(process.argv[3]);
if(process.argv.length!==4)throw Error('PACKAGE_AND_PARENT_REQUIRED');
const entry=path.join(packageRoot,'out/remote-executor/device-pairing.cjs');
const trustedPage=pathToFileURL(path.join(packageRoot,'out/remote-executor/device-pairing.html')).href;
const origin='https://gsnipers.snipers.com.cn';
let pairing=null,login=null,latest=null,synced=false,syncBusy=false,host=null,registered=false;
const info=message=>dialog.showMessageBox({type:'info',title:'诺德首次接入',message});
const validOfficial=url=>{try{const u=new URL(url);return u.protocol==='https:'&&u.hostname==='mp.weixin.qq.com'&&!u.username&&!u.password;}catch{return false;}};
async function pastePairing(){
  if(!pairing||pairing.isDestroyed()||pairing.webContents.getURL()!==trustedPage)return;
  let code=clipboard.readText().trim();
  if(!/^[A-Za-z0-9_-]{32}$/.test(code)){code='';await info('请先在管理台点击“复制短期码”，再点击本窗口的“从管理台复制的配对码继续”。不用输入地址或参数。');return;}
  const answer=await dialog.showMessageBox(pairing,{type:'question',message:'确认将这台电脑接入诺德生产任务？',detail:'服务器地址已配置。此操作只领取设备凭据，不创建或发表文章。',buttons:['确认配对','取消'],defaultId:0,cancelId:1});
  if(answer.response!==0){code='';return;}
  await pairing.webContents.executeJavaScript(`(()=>{const f=document.getElementById('form');if(f.hidden||document.getElementById('pair').disabled)return;document.getElementById('origin').value=${JSON.stringify(origin)};document.getElementById('code').value=${JSON.stringify(code)};f.requestSubmit();})()`);code='';
}
async function openLogin(){
  if(login&&!login.isDestroyed()){login.show();login.focus();return;}
  login=new BrowserWindow({width:1150,height:850,title:'诺德公众号 · 扫码登录',webPreferences:{partition:'persist:nord-first-publisher',sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true}});
  login.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  login.webContents.on('will-navigate',(event,url)=>{if(!validOfficial(url))event.preventDefault();});
  login.webContents.session.setPermissionRequestHandler((_wc,_p,callback)=>callback(false));
  login.webContents.session.on('will-download',event=>event.preventDefault());
  await login.loadURL('https://mp.weixin.qq.com/');
}
async function observeAccount(){
  if(!login||login.isDestroyed()||!validOfficial(login.webContents.getURL())){await info('请先扫码登录公众号，再进入“设置与开发 → 公众号设置”的账号信息页。');return;}
  // Only visible text on the official account information page; never read cookies or tokens.
  const observation=await login.webContents.executeJavaScript(`(()=>{if(location.hostname!=='mp.weixin.qq.com'||!location.pathname.startsWith('/cgi-bin/'))return null;const texts=[document.body.innerText];for(const frame of document.querySelectorAll('iframe')){try{const doc=frame.contentDocument;if(doc&&frame.getBoundingClientRect().width>0)texts.push(doc.body.innerText);}catch{}}const text=texts.join('\\n');if(!/原始\\s*ID|公众号\\s*ID/i.test(text))return null;const ids=[...new Set(text.match(/\\bgh_[a-f0-9]{12}\\b/g)||[])];return ids.length===1?{account:ids[0]}:null;})()`);
  if(!observation){await info('还没有读到唯一的公众号原始 ID。请在已登录的公众号中打开“设置与开发 → 公众号设置”，再点“确认账号并复制接入信息”。无需填写账号参数。');return;}
  const recordPath=path.join(parent,'gsnipers-distribution-agent/remote-executor/device-pairing.json');
  let record;try{record=JSON.parse(fs.readFileSync(recordPath,'utf8'));}catch{await info('请先完成这台电脑的配对，再确认账号。');return;}
  if(record.origin!==origin||!/^[a-f0-9-]{36}$/.test(record.device_id))throw Error('PAIRING_RECORD_MISMATCH');
  const answer=await dialog.showMessageBox(login,{type:'question',message:'确认这个账号可用于诺德发文？',detail:'公众号原始 ID：'+observation.account+'\n确认后只复制账号接入信息，不保存密码或验证码，也不会发表文章。',buttons:['确认并复制','取消'],defaultId:1,cancelId:1});
  if(answer.response!==0)return;
  latest={schema:1,kind:'nord-local-account-observation',module:'seo',tenant_id:1,scope_id:1,platform:'wechat-article',device_id:record.device_id,external_account_id:observation.account,observed_at:Date.now(),human_confirmed:true};synced=false;
  clipboard.writeText(JSON.stringify(latest));
  fs.writeFileSync(path.join(parent,'nord-account-observation.json'),JSON.stringify(latest,null,2)+'\n',{mode:0o600});
  await info('账号接入信息已复制。回到管理台点击“读取本机已确认账号”，核对后点击“确认此账号可用于诺德，并完成接入配置”。');
}
function sdk(action){
  return spawn(process.execPath,[path.join(packageRoot,'out/production/production-entry.mjs'),action,parent],{windowsHide:true,env:{...process.env,ELECTRON_RUN_AS_NODE:'1',NODE_TLS_REJECT_UNAUTHORIZED:'1'},stdio:['ignore','pipe','ignore']});
}
async function startReceiver(){
  if(host)return;
  host=sdk('start');
  let output='';
  host.stdout.on('data',chunk=>{
    output+=chunk.toString();if(output.length>16384){output='';return;}
    if(!output.includes('production-manual-host-running'))return;
    const register=sdk('capability-register');let response='';
    register.stdout.on('data',b=>{response+=b.toString();if(response.length>65536)response='';});
    register.once('exit',code=>{
      registered=code===0;
      fs.writeFileSync(path.join(parent,'nord-receiver-state.json'),JSON.stringify({device_id:latest.device_id,configured:true,capability_registration_process_ok:registered,automatic_submit:false,observed_at:Date.now()},null,2)+'\n');
    });
    host.stdout.removeAllListeners('data');host.stdout.resume();
  });
  host.once('exit',()=>{host=null;});
}
async function syncBinding(silent=false){
  if(syncBusy||synced)return;
  if(!pairing||pairing.isDestroyed()||!latest||Date.now()-latest.observed_at>900000){if(!silent)await info('请先完成账号确认和管理台绑定。');return;}
  syncBusy=true;
  try{
  const accountId='nord-wechat-'+latest.external_account_id.slice(3);
  const result=await pairing.webContents.executeJavaScript(`(async()=>{const r=await window.devicePairing.bindings();if(!r.ok)return false;const b=r.items.filter(v=>v.module==='seo'&&v.tenant_id===1&&v.scope_id===1&&v.platform==='wechat-article'&&v.device_id===${JSON.stringify(latest.device_id)}&&v.account_id===${JSON.stringify(accountId)});if(b.length!==1)return false;return (await window.devicePairing.configure(b[0].binding_id)).ok;})()`);
    if(result){synced=true;await startReceiver();await info('本机任务配置已同步。人工任务接收器正在启动并登记交接能力；实际状态以接入记录为准。账号登录和真实发布能力仍需首条任务核验。');}
    else if(!silent)await info('未读到唯一有效的诺德绑定，请先在管理台完成接入确认。');
  }finally{syncBusy=false;}
}
app.on('browser-window-created',(_event,window)=>{
  window.webContents.on('did-finish-load',()=>{
    if(window.webContents.getURL()!==trustedPage)return;
    pairing=window;window.setTitle('诺德执行电脑 · 首次接入');
    void window.webContents.executeJavaScript(`(()=>{document.querySelector('h1').textContent='诺德执行电脑接入';document.getElementById('origin').value=${JSON.stringify(origin)};document.getElementById('origin').readOnly=true;document.querySelector('p').textContent='连接地址已配置。请使用窗口上方的“诺德接入”菜单完成配对和扫码登录。';})()`);
    Menu.setApplicationMenu(Menu.buildFromTemplate([{label:'诺德接入',submenu:[{label:'① 从管理台复制的配对码继续',click:()=>void pastePairing().catch(()=>info('配对未完成，请核对本机窗口中的状态。'))},{label:'② 打开公众号扫码登录',click:()=>void openLogin().catch(()=>info('官方登录页未打开，请检查网络。'))},{label:'③ 确认账号并复制接入信息',click:()=>void observeAccount().catch(()=>info('账号接入信息未生成，请核对配对和账号信息页。'))},{label:'④ 同步已确认的诺德绑定',click:()=>void syncBinding().catch(()=>info('本机任务配置未同步，请核对管理台绑定。'))},{role:'quit'}]}]));
    void openLogin().catch(()=>info('官方扫码登录页未打开，可从“诺德接入”菜单重新打开。'));
    const timer=setInterval(()=>void syncBinding(true).catch(()=>{}),3000);timer.unref();
  });
});
// Preserve the frozen entry's exact argument contract and its IPC/TLS/DPAPI protections.
process.argv=[process.argv[0],entry,parent];require(entry);
