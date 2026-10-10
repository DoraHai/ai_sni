const positive=n=>Number.isSafeInteger(n)&&n>0;
const modules=['seo','geo'];
const phases=['draft','review','implementation','recheck','acceptance','done','cancelled'];
const fail=(code,status)=>Object.assign(Error(code),{code,status});
export const advisorModuleEligible=(user,module)=>positive(user?.id)&&(user.tenant_id===null||positive(user.tenant_id))&&
  (module==='seo'?user.permissions?.['seo.site']==='edit':module==='geo'&&['geo.assets','geo.content'].every(k=>user.permissions?.[k]==='edit'));
export function validateAdvisorPage(data,module,{beforeId=null,limit=25}={}){
  if(data?.schema!==1||data.module!==module||!modules.includes(module)||!Array.isArray(data.items)||data.items.length>limit)throw fail('CONTRACT_MISMATCH');
  let previous=beforeId??Infinity;
  for(const row of data.items){
    if(!positive(row?.id)||row.id>=previous||row.module!==module||!positive(row.tenant_id)||!positive(row.scope_id)||
      (row.site_id!=null&&(module!=='seo'||row.site_id!==row.scope_id))||(row.project_id!=null&&(module!=='geo'||row.project_id!==row.scope_id))||
      (row.workflow?.schema!=null&&row.workflow.schema!==1)||row.workflow?.module!==module||!positive(row.workflow.revision)||!phases.includes(row.workflow.phase)||
      !Array.isArray(row.workflow.items)||!Array.isArray(row.allowed_actions))throw fail('CONTRACT_MISMATCH');
    previous=row.id;
  }
  if(data.next_before_id!==null&&(!positive(data.next_before_id)||!data.items.length||data.next_before_id!==data.items.at(-1).id))throw fail('CONTRACT_MISMATCH');
  return structuredClone(data);
}
// This boundary never permits tenant enumeration, business writes or arbitrary URLs.
export function createAdvisorClient({session,fetchImpl=fetch,subscribeSession=()=>()=>{}}){
  let generation=0,authorized=null;const controllers=new Set(),listeners=new Set();
  const key=()=>JSON.stringify([session.token,session.user?.id,session.authRevision,session.user?.permissions,session.modules]);
  let fingerprint=key();
  function invalidate(reason='context_changed'){generation++;authorized=null;for(const c of controllers)c.abort();controllers.clear();for(const fn of listeners)fn(reason);}
  function sync(){const next=key();if(next!==fingerprint){fingerprint=next;invalidate();}}
  function current(g,k){sync();if(g!==generation||key()!==k)throw fail('CONTEXT_CHANGED');}
  async function read(path){
    sync();const g=generation,k=key(),token=session.token;
    if(!token||!positive(session.user?.id)||typeof token!=='string'||/\s/.test(token))throw fail('NOT_AUTHENTICATED',401);
    const url=new URL(path,'https://same-origin.invalid');
    if(!path.startsWith('/api/v1/')||/[\\#\s]/.test(path)||url.origin!=='https://same-origin.invalid'||url.pathname!==path.split('?')[0])throw fail('ROUTE_DENIED');
    const preflight=['/api/v1/auth/me','/api/v1/auth/modules'].includes(url.pathname);
    const module=modules.find(m=>url.pathname===`/api/v1/${m}/workbench/advisor-tasks`);
    if(!preflight&&!module)throw fail('ROUTE_DENIED');
    for(const name of url.searchParams.keys())if(preflight||!['before_id','limit','tenant_id'].includes(name)||url.searchParams.getAll(name).length!==1||!/^[1-9]\d*$/.test(url.searchParams.get(name))||!positive(Number(url.searchParams.get(name))))throw fail('QUERY_DENIED');
    if(module&&(!authorized?.modules.includes(module)||Number(url.searchParams.get('limit'))>50||!url.searchParams.has('limit')))throw fail('PERMISSION_DENIED',403);
    const c=new AbortController();controllers.add(c);
    try{
      const r=await fetchImpl(path,{method:'GET',headers:{Authorization:`Bearer ${token}`,Accept:'application/json'},credentials:'omit',cache:'no-store',redirect:'error',signal:AbortSignal.any([c.signal,AbortSignal.timeout(20000)])});
      current(g,k);
      if(r.status===401||r.status===403){invalidate(r.status===401?'expired':'forbidden');if(r.status===401)session.logout();throw fail(r.status===401?'AUTH_EXPIRED':'PERMISSION_DENIED',r.status);}
      if(!r.ok)throw fail([404,405,501,503].includes(r.status)?'NOT_INTEGRATED':'READ_FAILED',r.status);
      const data=await r.json();current(g,k);return data;
    }finally{controllers.delete(c);}
  }
  const unsubscribe=subscribeSession(()=>sync());
  return {
    async initialize(){invalidate('initializing');const {user}=await read('/api/v1/auth/me');
      if(user?.id!==session.user?.id||!positive(user.id)||!user.permissions)throw fail('IDENTITY_MISMATCH');
      const catalog=await read('/api/v1/auth/modules');
      if(catalog?.tenant_id!==user.tenant_id||!Array.isArray(catalog.modules))throw fail('CONTRACT_MISMATCH');
      authorized={user,modules:modules.filter(m=>advisorModuleEligible(user,m)&&catalog.modules.some(v=>v.module_code===m&&v.available===true))};
      return structuredClone(authorized);
    },
    async list(module,{beforeId=null,limit=25,tenantId=null}={}){sync();if(!modules.includes(module)||!authorized?.modules.includes(module))throw fail('PERMISSION_DENIED',403);
      if(!positive(limit)||limit>50||(beforeId!==null&&!positive(beforeId))||(tenantId!==null&&!positive(tenantId)))throw fail('QUERY_DENIED');
      const p=new URLSearchParams({limit});if(beforeId!==null)p.set('before_id',beforeId);if(tenantId!==null)p.set('tenant_id',tenantId);
      const data=await read(`/api/v1/${module}/workbench/advisor-tasks?${p}`),page=validateAdvisorPage(data,module,{beforeId,limit});
      if((tenantId!==null&&page.items.some(v=>v.tenant_id!==tenantId))||(authorized.user.tenant_id!==null&&page.items.some(v=>v.tenant_id!==authorized.user.tenant_id)))throw fail('CONTRACT_MISMATCH');return page;
    },
    subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn);},
    invalidate,
    dispose(){unsubscribe();listeners.clear();invalidate('disposed');},
  };
}
