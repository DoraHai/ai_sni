// Resolved at build time to canonical SEM files, never copied into this source tree.
import {session} from '@existing-host/session';
import {watch} from 'vue';
import {existingSessionBridge,createHostSessionAdapter} from './host-session-adapter.mjs';
import {mountConnectedWorkbench} from './connected-workbench.mjs';
import {entryScope,mountWorkbenchEntry,workbenchPath,workbenchLoginPath} from './workbench-entry.mjs';

const scope=entryScope(location.search),{tenantId,siteId}=scope;
let mounted;
if(!session.token||scope.invalid||scope.login||!tenantId||!siteId){
  mounted=mountWorkbenchEntry({root:document.querySelector('#app'),session});
}else{
// URL values select a candidate scope only. The adapter verifies server ownership.
// Do not change a customer-bound session to a different tenant.
if(tenantId&&(!session.user?.tenant_id||session.user.tenant_id===tenantId))session.setTenant(tenantId);
const returnPath=workbenchPath(tenantId,siteId);
const host=createHostSessionAdapter({
  origin:location.origin,
  ...existingSessionBridge({session,watch,getSiteId:()=>tenantId&&tenantId===session.tenantId?siteId:null}),
  returnPath,
  redirectToLogin:()=>location.assign(workbenchLoginPath(tenantId,siteId)),
});
mounted=mountConnectedWorkbench({root:document.querySelector('#app'),host,environmentLabel:'客户工作台',demoHref:null,
  selectSpace:()=>location.assign('/customer-workbench/'),
  logout:()=>{session.logout();location.assign(workbenchLoginPath());},
});
}
window.addEventListener('pagehide',()=>mounted.dispose(),{once:true});
window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
