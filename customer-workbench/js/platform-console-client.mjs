// Separate global-console transport. Customer host allowlists remain unchanged.
export const platformConsolePath='/customer-workbench/?console=platform';
export const isPlatformAdmin=user=>Number.isSafeInteger(user?.id)&&user.id>0&&user.tenant_id===null&&
  user.permissions?.['settings.accounts']==='edit'&&user.permissions?.['settings.customers']==='edit';
const fail=(code,status)=>Object.assign(Error(code),{code,status});
const routes=new Set(['/api/v1/auth/me','/api/v1/admin/console/snapshot']);
const writeRoute='/api/v1/admin/console/controls';
const operationRoute='/api/v1/admin/console/operations';
const usageRoute='/api/v1/admin/console/usage';
const queryFields=new Set(['from','to','tenant_id','user_id','module','provider','endpoint','model','state','unpriced','page_size','cursor']);
function usagePath(filters={},exporting=false){
  if(!filters||typeof filters!=='object'||Array.isArray(filters)||Object.keys(filters).some(k=>!queryFields.has(k)))throw fail('CONSOLE_INVALID_QUERY');
  const query=new URLSearchParams(Object.entries(filters).filter(([,v])=>v!==''&&v!=null).map(([k,v])=>[k,String(v)]));
  return usageRoute+(exporting?'/export':'')+(query.size?'?'+query:'');
}

export function createPlatformConsoleClient({session,fetchImpl=fetch,onExpired=()=>{},refreshUser=user=>session.refreshUser(user)}){
  let epoch=0,identity=null;
  const pending=new Set();
  const fingerprint=()=>JSON.stringify([session.token,session.user?.id,session.user?.tenant_id,session.authRevision]);
  function invalidate(){epoch++;identity=null;for(const c of pending)c.abort();pending.clear();}
  async function read(path,preflight=false,body=null,download=false){
    const url=new URL(path,'https://console.invalid');
    const permitted=url.origin==='https://console.invalid'&&(body===null?
      routes.has(path)||[usageRoute,usageRoute+'/export'].includes(url.pathname):[writeRoute,operationRoute].includes(path));
    if(!permitted||(!preflight&&!identity))throw fail('CONSOLE_NOT_AUTHORIZED',403);
    if(!session.token)throw fail('CONSOLE_LOGIN_REQUIRED',401);
    const started=epoch,key=fingerprint(),controller=new AbortController();pending.add(controller);
    const current=()=>{if(epoch!==started||fingerprint()!==key)throw fail('CONSOLE_STALE');};
    try{
      const r=await fetchImpl(path,{method:body===null?'GET':'POST',headers:{Authorization:`Bearer ${session.token}`,Accept:'application/json',...(body===null?{}:{'Content-Type':'application/json'})},
        ...(body===null?{}:{body:JSON.stringify(body)}),
        credentials:'omit',cache:'no-store',redirect:'error',signal:AbortSignal.any([controller.signal,AbortSignal.timeout(20000)])});
      current();
      if(r.status===401){invalidate();session.logout();onExpired();throw fail('CONSOLE_EXPIRED',401);}
      if(r.status===403){invalidate();throw fail('CONSOLE_FORBIDDEN',403);}
      if(!r.ok)throw fail('CONSOLE_READ_FAILED',r.status);
      if(download){
        if(!r.headers.get('content-type')?.startsWith('text/csv'))throw fail('CONSOLE_INVALID_EXPORT');
        const data=await r.blob();current();return data;
      }
      const data=await r.json();current();return data;
    }finally{pending.delete(controller);}
  }
  return {
    invalidate,
    async initialize(){
      invalidate();const {user}=await read('/api/v1/auth/me',true);
      if(user?.id!==session.user?.id||!isPlatformAdmin(user))throw fail('CONSOLE_FORBIDDEN',403);
      refreshUser(user);identity=user;
      const data=await read('/api/v1/admin/console/snapshot');
      if(data?.schema!==1||data.mode!=='read_only_inventory'||!data.sources||!data.costs)throw fail('CONSOLE_INVALID_SNAPSHOT');
      return {user,data};
    },
    async change(data){
      if(!identity)throw fail('CONSOLE_NOT_AUTHORIZED',403);
      const {user}=await read('/api/v1/auth/me',true);
      if(user?.id!==identity.id||!isPlatformAdmin(user)){invalidate();throw fail('CONSOLE_FORBIDDEN',403);}
      return read(writeRoute,false,data);
    },
    async usage(filters){return read(usagePath(filters));},
    async exportUsage(filters){
      if(!identity)throw fail('CONSOLE_NOT_AUTHORIZED',403);
      const {user}=await read('/api/v1/auth/me',true);
      if(user?.id!==identity.id||!isPlatformAdmin(user)){invalidate();throw fail('CONSOLE_FORBIDDEN',403);}
      return read(usagePath(filters,true),false,null,true);
    },
    async operation(data){
      if(!identity)throw fail('CONSOLE_NOT_AUTHORIZED',403);
      const {user}=await read('/api/v1/auth/me',true);
      if(user?.id!==identity.id||!isPlatformAdmin(user)){invalidate();throw fail('CONSOLE_FORBIDDEN',403);}
      return read(operationRoute,false,data);
    },
    getIdentity:()=>identity,
  };
}
