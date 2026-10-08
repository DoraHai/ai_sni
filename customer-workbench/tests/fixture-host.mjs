// Local contract-server fixture only. These are fake test identities, not credentials.
let session={token:'fixture-customer',userId:12,tenantId:1,siteId:9,revision:1};
const listeners=new Set();const notify=()=>{for(const fn of listeners)fn();};
window.WORKBENCH_TEST_HOST={
  lastRedirect:null,
  setIdentity(role){session={...session,token:role==='none'?'':`fixture-${role}`,userId:role==='advisor'?7:12,tenantId:1,siteId:9,revision:session.revision+1};notify();},
  selectTenant(id){session={...session,tenantId:id,siteId:id===1?9:19,revision:session.revision+1};notify();},
};
window.CUSTOMER_WORKBENCH_HOST={
  allowLocalHttp:true,environmentLabel:'本地 host stub + 契约服务器 · 非生产连接',
  getSession:()=>({...session}),subscribeSession(fn){listeners.add(fn);return()=>listeners.delete(fn);},
  logout(){session={...session,token:'',revision:session.revision+1};notify();},
  redirectToLogin(url){window.WORKBENCH_TEST_HOST.lastRedirect=url;},
};
