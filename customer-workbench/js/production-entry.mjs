// Resolved at build time to canonical SEM files, never copied into this source tree.
import {session} from '@existing-host/session';
import {redirectToLogin} from '@existing-host/login-redirect';
import {watch} from 'vue';
import {existingSessionBridge,createHostSessionAdapter} from './host-session-adapter.mjs';
import {mountConnectedWorkbench} from './connected-workbench.mjs';

const params=new URLSearchParams(location.search);
function scopeId(name){
  const raw=params.get(name);
  if(params.getAll(name).length!==1||!raw||!/^\d+$/.test(raw))return null;
  const value=Number(raw);return Number.isSafeInteger(value)&&value>0?value:null;
}
const tenantId=scopeId('tenant_id'),siteId=scopeId('site_id');
// URL values select a candidate scope only. The adapter verifies server ownership.
// Do not change a customer-bound session to a different tenant.
if(tenantId&&(!session.user?.tenant_id||session.user.tenant_id===tenantId))session.setTenant(tenantId);
const returnPath='/customer-workbench/'+(tenantId&&siteId?'?'+new URLSearchParams({tenant_id:String(tenantId),site_id:String(siteId)}):'');
const host=createHostSessionAdapter({
  origin:location.origin,
  ...existingSessionBridge({session,watch,getSiteId:()=>tenantId&&tenantId===session.tenantId?siteId:null}),
  returnPath,
  // Call the existing login helper with a path, never with a nested /login URL.
  redirectToLogin:()=>redirectToLogin(returnPath),
});
const mounted=mountConnectedWorkbench({root:document.querySelector('#app'),host,environmentLabel:'客户工作台',demoHref:null});
window.addEventListener('pagehide',()=>mounted.dispose(),{once:true});
window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
