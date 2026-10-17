// GEO has an independently verified project scope; an SEO site ID conveys no authority.
import {visibilityAdvisor} from './search-visibility-client.mjs';
export function createGeoHostAdapter({origin,fetchImpl=fetch,getSession,subscribeSession,logout,redirectToLogin}){
  let revision=0,identity=null,fingerprint=null;const listeners=new Set(),pending=new Set();
  const key=s=>JSON.stringify(s?[s.token,s.userId,s.tenantId,s.projectId,s.revision]:null);
  const fail=(code,status)=>{throw Object.assign(Error(code),{code,status});};
  function invalidate(reason='context_changed'){revision++;identity=null;for(const c of pending)c.abort();pending.clear();for(const cb of listeners)cb({reason});}
  function sync(){const s=getSession();const k=key(s);if(fingerprint===null)fingerprint=k;else if(k!==fingerprint){fingerprint=k;invalidate();}return s;}
  function current(s,r){sync();if(revision!==r||key(getSession())!==key(s))fail('CONTEXT_CHANGED');}
  const readRoutes=new Set(['/api/v1/auth/me','/api/v1/auth/modules','/api/v1/geo/tenants','/api/v1/geo/projects']);
  const base=new URL(origin);if(base.origin!==origin||base.protocol!=='https:')fail('INVALID_ORIGIN');
  async function request(path,options={},preflight=false){
    const s=sync(),r=revision;const positive=n=>Number.isSafeInteger(n)&&n>0;
    if(!s?.token||/\s/.test(s.token)||![s.userId,s.tenantId,s.projectId].every(positive))fail('NOT_AUTHENTICATED');
    if(typeof path!=='string'||!path.startsWith('/api/v1/')||/[\\#\s]/.test(path))fail('ROUTE_DENIED');
    const url=new URL(path,base),method=options.method||'GET';
    if(url.origin!==origin||url.pathname!==path.split('?')[0])fail('ROUTE_DENIED');
    const list=url.pathname==='/api/v1/geo/workbench/onsite-tasks';
    const act=/^\/api\/v1\/geo\/workbench\/onsite-tasks\/[1-9]\d*\/actions$/.test(url.pathname);
    const ai=/^\/api\/v1\/geo\/workbench\/onsite-tasks\/[1-9]\d*\/ai-proposal$/.test(url.pathname);
    const aiRead=/^\/api\/v1\/geo\/workbench\/onsite-tasks\/[1-9]\d*\/ai-requests\/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(url.pathname);
    const visibility=url.pathname.match(/^\/api\/v1\/geo\/projects\/([1-9]\d*)\/search-visibility(?:\/(config|run)|\/runs\/([1-9]\d*)(\/csv)?)?$/);
    const visibilityAllowed=visibility&&Number(visibility[1])===s.projectId&&(
      method==='GET'&&visibility[2]!=='run'||method==='PUT'&&visibility[2]==='config'||method==='POST'&&visibility[2]==='run');
    const allowed=preflight?method==='GET'&&readRoutes.has(url.pathname):identity&&(visibilityAllowed||(list&&['GET','POST'].includes(method))||(aiRead&&method==='GET')||((act||ai)&&method==='POST'));
    if(!allowed)fail('ROUTE_DENIED');
    const keys=visibility?['tenant_id']:preflight?(url.pathname.endsWith('/projects')?['tenant_id']:[]):method==='GET'?['tenant_id','project_id',...(list?['before_id']:[])]:[];
    for(const name of url.searchParams.keys())if(!keys.includes(name)||url.searchParams.getAll(name).length!==1)fail('QUERY_DENIED');
    if(keys.includes('tenant_id')&&url.searchParams.get('tenant_id')!==String(s.tenantId))fail('SCOPE_MISMATCH');
    if(keys.includes('project_id')&&url.searchParams.get('project_id')!==String(s.projectId))fail('SCOPE_MISMATCH');
    if(method==='GET'&&options.body!==undefined)fail('BODY_DENIED');
    if(visibility&&(method!=='GET'||visibility[2]==='config')&&!visibilityAdvisor(identity.user))fail('PERMISSION_DENIED',403);
    if(visibility&&method!=='GET'){
      let body;try{body=options.body===undefined?{}:JSON.parse(options.body);}catch{fail('BODY_DENIED');}
      const fields=method==='PUT'?['enabled','domains','zh_url','brand_terms','core_terms','extra_article_urls','customer_visible']:[];
      if(!body||Array.isArray(body)||Object.keys(body).some(k=>!fields.includes(k)))fail('BODY_DENIED');
    }else if(method==='POST'){
      let body;try{body=JSON.parse(options.body);}catch{fail('BODY_DENIED');}
      const fields=ai?['tenant_id','project_id','expected_revision','request_id','mode']:act?['tenant_id','project_id','action','expected_revision','items','note','owner_name']:['tenant_id','project_id','request_id','work_type','month','owner_name'];
      if(!body||Array.isArray(body)||Object.keys(body).some(k=>!fields.includes(k)))fail('BODY_DENIED');
      if(body.tenant_id!==s.tenantId||body.project_id!==s.projectId)fail('SCOPE_MISMATCH');
      if(!['geo.assets','geo.content'].every(k=>identity.user.permissions[k]==='edit'))fail('PERMISSION_DENIED',403);
    }
    const c=new AbortController();pending.add(c);
    try{
      const response=await fetchImpl(url.href,{method,body:options.body,headers:{Authorization:'Bearer '+s.token,Accept:'application/json',...(['POST','PUT'].includes(method)?{'Content-Type':'application/json'}:{}),...(ai&&method==='POST'?{'X-Snipers-Onsite-Protocol':'durable-v1'}:{})},cache:'no-store',credentials:'omit',redirect:'error',signal:visibility?AbortSignal.any([c.signal,AbortSignal.timeout(20000)]):c.signal});
      current(s,r);
      if(response.status===401){invalidate('expired');logout?.();redirectToLogin?.();fail('AUTH_EXPIRED',401);}
      if(response.status===403){invalidate('forbidden');fail('PERMISSION_DENIED',403);}
      return {ok:response.ok,status:response.status,headers:response.headers,
        async json(){current(s,r);const data=await response.json();current(s,r);return data;},
        async arrayBuffer(){current(s,r);const data=await response.arrayBuffer();current(s,r);return data;}};
    }catch(e){if(!['AUTH_EXPIRED','PERMISSION_DENIED'].includes(e.code))current(s,r);throw e;}finally{pending.delete(c);}
  }
  async function initialize(){
    const s=sync(),r=revision;identity=null;
    async function read(path){const response=await request(path,{},true);if(!response.ok)fail('PREFLIGHT_FAILED',response.status);return response.json();}
    const {user}=await read('/api/v1/auth/me');
    if(user?.id!==s.userId||(user.tenant_id!=null&&user.tenant_id!==s.tenantId)||
      !['geo.assets','geo.content'].every(k=>['view','edit'].includes(user.permissions?.[k])))fail('PERMISSION_DENIED',403);
    const modules=await read('/api/v1/auth/modules');
    if(modules.tenant_id!==user.tenant_id||!modules.modules?.some(m=>m.module_code==='geo'&&m.available===true))fail('MODULE_UNAVAILABLE');
    const tenants=await read('/api/v1/geo/tenants'),tenant=tenants.tenants?.find(t=>t.id===s.tenantId);
    if(!tenant||tenant.read_only===true)fail('TENANT_NOT_ALLOWED');
    const data=await read('/api/v1/geo/projects?tenant_id='+s.tenantId);
    const project=data.projects?.find(p=>p.id===s.projectId&&p.tenant_id===s.tenantId&&p.status==='active');
    if(!project)fail('PROJECT_NOT_ALLOWED');current(s,r);identity={user,tenant,project};return {identity:structuredClone(identity)};
  }
  const unsubscribe=subscribeSession?.(()=>sync());
  return {initialize,transport:(path,options)=>request(path,options),invalidate,
    getContext:()=>{sync();return identity?{connected:true,tenantId:identity.tenant.id,projectId:identity.project.id,userId:identity.user.id,revision}: {connected:false};},
    subscribe(fn){listeners.add(fn);return ()=>listeners.delete(fn);},
    dispose(){unsubscribe?.();invalidate('disposed');listeners.clear();}};
}

