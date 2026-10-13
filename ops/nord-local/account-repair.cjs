'use strict';
// Read the account from the user's supplied settings screenshot; do not restart
// or inspect the existing logged-in browser session or its cookies.
const {app,dialog,clipboard}=require('electron');
const fs=require('node:fs'),path=require('node:path'),https=require('node:https');
const {spawn}=require('node:child_process');
const parent=path.resolve(process.argv[2]),packageRoot=path.resolve(process.argv[3]);
const account='gh_1864ed0c0506',origin='https://gsnipers.snipers.com.cn';
const root=path.join(parent,'gsnipers-distribution-agent/remote-executor');
app.setPath('userData',path.join(parent,'nord-account-repair-ui'));
let timer=null,done=false,busy=false,host=null;
const report=(state)=>fs.writeFileSync(path.join(parent,'nord-account-repair-state.json'),JSON.stringify({observed_at:Date.now(),...state},null,2)+'\n');
const uuid=v=>typeof v==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
function sdk(action){return spawn(path.join(packageRoot,'node_modules/electron/dist/electron.exe'),[path.join(packageRoot,'out/production/production-entry.mjs'),action,parent],{windowsHide:true,env:{...process.env,ELECTRON_RUN_AS_NODE:'1',NODE_TLS_REJECT_UNAUTHORIZED:'1'},stdio:['ignore','pipe','ignore']});}
async function getBindings(record){
  // Machine credential stays in this protected local helper; never print it.
  const credential=fs.readFileSync(path.join(root,'device.secret'),'utf8').trim();
  if(credential.length<40||/\s/.test(credential))throw Error('DEVICE_CREDENTIAL_REQUIRED');
  return new Promise((resolve,reject)=>{
    const body=JSON.stringify({device_id:record.device_id});
    const req=https.request(origin+'/api/distribution/v1/device/bindings',{method:'POST',rejectUnauthorized:true,headers:{'Content-Type':'application/json',Authorization:'Bearer '+credential}},res=>{
      let text='';res.on('data',b=>{text+=b;if(text.length>65536)req.destroy(Error('RESPONSE_LIMIT'));});res.on('end',()=>{if(res.statusCode!==200)return reject(Error('BINDINGS_UNAVAILABLE'));try{resolve(JSON.parse(text));}catch{reject(Error('INVALID_REPLY'));}});
    });req.setTimeout(10000,()=>req.destroy(Error('REQUEST_TIMEOUT')));req.on('error',reject);req.end(body);
  });
}
async function sync(record){
  if(busy||done)return;busy=true;
  try{
    const reply=await getBindings(record);
    if(reply.schema!==1||reply.device_id!==record.device_id||reply.automatic_submit!==false||!Array.isArray(reply.items)||reply.items.length>50||Math.abs(reply.as_of-Date.now())>5000||new Set(reply.items.map(b=>b.binding_id)).size!==reply.items.length)throw Error('INVALID_REPLY');
    const matches=reply.items.filter(b=>b.device_id===record.device_id&&b.module==='seo'&&b.tenant_id===1&&b.scope_id===1&&b.platform==='wechat-article'&&b.external_account_id===account&&b.account_id==='nord-wechat-'+account.slice(3));
    if(matches.length!==1)return;
    const b=matches[0];if(!uuid(b.binding_id))throw Error('INVALID_BINDING');
    const config={remote_version:1,origin,parent_root:parent,device_id:record.device_id,backend:'electron',page_mode:'official-login',allow_real_login:true,credential_file:path.join(root,'device.secret'),bindings:[{deviceId:b.device_id,bindingId:b.binding_id,accountId:b.account_id,platform:b.platform,customerId:'1',projectId:'seo-1',module:'seo',tenant_id:1,scope_id:1}]};
    const file=path.join(root,'executor.json');
    if(fs.existsSync(file)){const old=JSON.parse(fs.readFileSync(file,'utf8'));if(JSON.stringify(old)!==JSON.stringify(config))throw Error('EXISTING_CONFIG_DIFFERS');}
    else fs.writeFileSync(file,JSON.stringify(config,null,2)+'\n',{flag:'wx',mode:0o600});
    done=true;clearInterval(timer);report({phase:'configured',device_id:record.device_id,automatic_submit:false});
    host=sdk('start');let output='';
    host.stdout.on('data',chunk=>{output+=chunk.toString();if(output.length>16384)output='';if(!output.includes('production-manual-host-running'))return;host.stdout.removeAllListeners('data');host.stdout.resume();
      report({phase:'receiver_running',device_id:record.device_id,automatic_submit:false});const register=sdk('capability-register');register.stdout.resume();register.once('exit',code=>report({phase:code===0?'receiver_and_capability_ready':'capability_registration_needs_check',device_id:record.device_id,automatic_submit:false,registration_exit:code}));
    });host.once('exit',code=>report({phase:'receiver_stopped',exit_code:code,automatic_submit:false}));
  }catch{report({phase:done?'local_receiver_needs_check':'waiting_for_confirmed_server_binding',automatic_submit:false});}finally{busy=false;}
}
app.whenReady().then(async()=>{
  const record=JSON.parse(fs.readFileSync(path.join(root,'device-pairing.json'),'utf8'));
  if(record.origin!==origin||!uuid(record.device_id))throw Error('PAIRING_RECORD_MISMATCH');
  const answer=await dialog.showMessageBox({title:'诺德账号接入确认',type:'question',message:'已从你提供的公众号设置截图读到账号',detail:'公众号ID：'+account+'\n确认这个已扫码登录的公众号可以用于诺德首条发文？\n只接入账号和任务接收器，稿件审核及最终发表仍需确认。当前登录窗口会保留。',buttons:['确认此账号可用于诺德','暂不接入'],defaultId:1,cancelId:1});
  if(answer.response!==0){report({phase:'account_confirmation_not_given'});app.quit();return;}
  const observation={schema:1,kind:'nord-local-account-observation',module:'seo',tenant_id:1,scope_id:1,platform:'wechat-article',device_id:record.device_id,external_account_id:account,observed_at:Date.now(),human_confirmed:true};
  fs.writeFileSync(path.join(parent,'nord-account-observation.json'),JSON.stringify(observation,null,2)+'\n',{mode:0o600});clipboard.writeText(JSON.stringify(observation));report({phase:'account_confirmed_waiting_admin_import',device_id:record.device_id,automatic_submit:false});
  await dialog.showMessageBox({title:'诺德账号信息已复制',message:'回管理台点击“读取本机已确认账号”，再点击接入确认。无需填写参数，本机随后自动接收配置。'});
  timer=setInterval(()=>void sync(record),3000);void sync(record);
}).catch(()=>{report({phase:'account_repair_stopped'});app.quit();});
