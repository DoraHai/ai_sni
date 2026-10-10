import {createGeoHostAdapter} from './geo-host-session-adapter.mjs';
import {mountGeoWorkbench} from './geo-workbench.mjs';
// Resolved at build time to canonical SEM files, never copied into this source tree.
import {session} from '@existing-host/session';
import {watch} from 'vue';
import {existingSessionBridge,createHostSessionAdapter} from './host-session-adapter.mjs';
import {mountConnectedWorkbench} from './connected-workbench.mjs';
import {entryScope,mountWorkbenchEntry,workbenchPath,workbenchLoginPath,geoWorkbenchPath} from './workbench-entry.mjs';
import {mountPlatformConsole} from './platform-console-view.mjs';
import {mountAdvisorWorkbench} from './advisor-workbench.mjs';

const scope=entryScope(location.search),{tenantId,siteId}=scope;
let mounted;
const consoleValues=new URLSearchParams(location.search).getAll('console');
if(consoleValues.length===1&&consoleValues[0]==='advisor'){
  mounted=!session.token||scope.login?mountWorkbenchEntry({root:document.querySelector('#app'),session}):mountAdvisorWorkbench({root:document.querySelector('#app'),session,subscribeSession(listener){const stop=watch(()=>[session.token,session.user?.id,session.authRevision,JSON.stringify(session.modules)],listener,{flush:'sync'});window.addEventListener('sem:auth-context-changed',listener);return()=>{stop();window.removeEventListener('sem:auth-context-changed',listener);};}});
}else if(consoleValues.length===1&&consoleValues[0]==='platform'){
  mounted=mountPlatformConsole({root:document.querySelector('#app'),session});
}else if(scope.module==='geo'&&session.token&&!scope.invalid&&!scope.login&&tenantId&&scope.projectId){
  const projectId=scope.projectId;
  if(!session.user?.tenant_id||session.user.tenant_id===tenantId)session.setTenant(tenantId);
  const bridge=existingSessionBridge({session,watch,getSiteId:()=>session.tenantId===tenantId?projectId:null});
  const host=createGeoHostAdapter({origin:location.origin,getSession:()=>{const s=bridge.getSession();return s?{...s,projectId:s.siteId}:null;},subscribeSession:bridge.subscribeSession,
    logout:()=>session.logout(),redirectToLogin:()=>location.assign(geoWorkbenchPath(tenantId,projectId)+(scope.onsiteTaskId?'&onsite_task_id='+scope.onsiteTaskId:'')+'&login=1')});
  mounted=mountGeoWorkbench({root:document.querySelector('#app'),host,initialOnsiteTaskId:scope.onsiteTaskId,logout:()=>{session.logout();location.assign(geoWorkbenchPath()+'&login=1');}});
}else if(!session.token||scope.invalid||scope.login||!tenantId||!siteId){
  mounted=mountWorkbenchEntry({root:document.querySelector('#app'),session});
}else{
// URL values select a candidate scope only. The adapter verifies server ownership.
// Do not change a customer-bound session to a different tenant.
if(tenantId&&(!session.user?.tenant_id||session.user.tenant_id===tenantId))session.setTenant(tenantId);
const returnPath=workbenchPath(tenantId,siteId)+(scope.onsiteTaskId?'&onsite_task_id='+scope.onsiteTaskId:'');
const host=createHostSessionAdapter({
  origin:location.origin,
  ...existingSessionBridge({session,watch,getSiteId:()=>tenantId&&tenantId===session.tenantId?siteId:null}),
  returnPath,
  redirectToLogin:()=>location.assign(workbenchLoginPath(tenantId,siteId)+(scope.onsiteTaskId?'&onsite_task_id='+scope.onsiteTaskId:'')),
});
mounted=mountConnectedWorkbench({root:document.querySelector('#app'),host,environmentLabel:'客户工作台',demoHref:null,
  initialOnsiteTaskId:scope.onsiteTaskId,
  selectSpace:()=>location.assign('/customer-workbench/'),
  logout:()=>{session.logout();location.assign(workbenchLoginPath());},
});
}
window.addEventListener('pagehide',()=>mounted.dispose(),{once:true});
window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
