// Real pairing component and canonical login on the separate acceptance origin.
import {session} from '@existing-host/session';
import {watch} from 'vue';
import {mountWorkbenchEntry} from './workbench-entry.mjs';
import {createDevicePairingPanel} from './device-pairing-panel.mjs';
import {verifyPairingAdmin} from './device-pairing-acceptance-auth.mjs';
const root=document.querySelector('#app');
let panel=null,login=null,revision=0,applyingIdentity=false;
function dispose(){panel?.dispose();panel=null;login?.dispose();login=null;root.replaceChildren();}
async function connect(){
 const current=++revision;dispose();
 if(!session.token){
  login=mountWorkbenchEntry({root,session,search:'?console=advisor&login=1',navigate:()=>location.assign('/acceptance/pairing/')});
  return;
 }
 root.textContent='正在核验独立验收账号…';
 try{
  const user=await verifyPairingAdmin({session,isCurrent:()=>current===revision});
  if(current!==revision)return;
  applyingIdentity=true;try{session.refreshUser(user);}finally{applyingIdentity=false;}
  panel=createDevicePairingPanel({session,onChange:render});render();panel.refresh();
 }catch{if(current===revision){root.textContent='需要独立验收环境的全局超管账号。';const exit=document.createElement('button');exit.textContent='退出并重新登录';exit.onclick=()=>{session.logout();void connect();};root.append(exit);}}
}
function render(){if(!panel)return;root.innerHTML='<h1>独立验收 · 公司电脑配对</h1><p>此页使用真实配对接口和工作台组件。配对不授予账号绑定、登录或发布能力。</p>'+panel.html()+'<button data-acceptance-logout>退出验收账号</button>';}
root.addEventListener('submit',event=>panel?.submit(event));
root.addEventListener('click',event=>{if(event.target.closest('[data-acceptance-logout]')){session.logout();void connect();}else panel?.click(event);});
watch(()=>[session.token,session.user?.id,session.authRevision],()=>{panel?.invalidate();if(!applyingIdentity){revision++;void connect();}},{flush:'sync'});
window.addEventListener('pagehide',()=>{revision++;dispose();});
window.addEventListener('pageshow',event=>{if(event.persisted)void connect();});
void connect();
