// UI-05 same-origin host boundary. Reuses an injected ordinary session; never reads/stores credentials.
const positive=n=>Number.isSafeInteger(n)&&n>0;
const routes=[
  ['GET',/^\/api\/v1\/auth\/(me|modules)$/,[],'preflight'],
  ['GET',/^\/api\/v1\/auth\/tenants$/,['module'],'preflight'],
  ['GET',/^\/api\/v1\/seo\/workbench\/sites$/,['tenant_id'],'preflight'],
  ['GET',/^\/api\/v1\/seo\/content-assets$/,['tenant_id','site_id','content_id','page','page_size'],'content'],
  ['PATCH',/^\/api\/v1\/seo\/content-assets\/[1-9]\d*$/,['tenant_id'],'content',['version_count','title','outline','draft','humanized_content']],
  ['POST',/^\/api\/v1\/seo\/content-assets\/[1-9]\d*\/submit-review$/,['tenant_id'],'content',['version_count','note']],
  ['GET',/^\/api\/v1\/seo\/content-distribution\/publications$/,['tenant_id','site_id','content_id'],'content'],
  ['GET',/^\/api\/v1\/seo\/content-distribution\/publications\/[1-9]\d*\/attempts$/,['tenant_id','site_id'],'content'],
  ['POST',/^\/api\/v1\/seo\/content-distribution\/publications\/manual$/,[],'content',['tenant_id','site_id','content_id','source_version','payload_hash','platform_name','page_url','published_at']],
  ['POST',/^\/api\/v1\/seo\/content-distribution\/publications\/[1-9]\d*\/complete$/,[],'content',['tenant_id','site_id','source_version','page_url','published_at']],
  ['GET',/^\/api\/v1\/seo\/qa\/facts$/,['tenant_id','site_id'],'content'],
  ['POST',/^\/api\/v1\/seo\/qa\/facts$/,[],'content',['tenant_id','site_id','title','statement','source_name','source_url','expires_at','status']],
  ['PATCH',/^\/api\/v1\/seo\/qa\/facts\/[1-9]\d*$/,[],'content',['tenant_id','site_id','title','statement','source_name','source_url','expires_at','status','version']],
  ['PATCH',/^\/api\/v1\/seo\/keywords\/[1-9]\d*$/,['tenant_id'],'keywords',['priority','landing_page']],
  ['POST',/^\/api\/v1\/seo\/keywords$/,[],'keywords',['tenant_id','site_id','keyword','priority','landing_page']],
  ['GET',/^\/api\/v1\/seo\/keywords$/,['tenant_id','site_id','status','page','page_size','q','engine','device'],'keywords'],
  ['GET',/^\/api\/v1\/seo\/keywords\/[1-9]\d*$/,['tenant_id','engine','device','region','days'],'keywords'],
  ['GET',/^\/api\/v1\/seo\/site-pages$/,['tenant_id','site_id','q','status','page','page_size'],'site'],
  ['GET',/^\/api\/v1\/seo\/site-pages\/[1-9]\d*\/detail$/,['tenant_id'],'site'],
  ['GET',/^\/api\/v1\/seo\/workbench\/publication-page-evidence$/,['tenant_id','site_id','page','page_size'],'site'],
  ['POST',/^\/api\/v1\/seo\/workbench\/service-plan\/run$/,[],'site',['tenant_id','site_id','expected_revision','request_id']],
  ['POST',/^\/api\/v1\/seo\/workbench\/service-cycles\/run$/,[],'site',['tenant_id','site_id','kind','expected_revision','request_id']],
  ['GET',/^\/api\/v1\/seo\/workbench\/content-assets\/[1-9]\d*\/delivery$/,['tenant_id','site_id'],'content'],
  ['POST',/^\/api\/v1\/seo\/workbench\/content-assets\/[1-9]\d*\/confirmations$/,['tenant_id'],'content',['version_count','payload_hash','decision','actor_mode','note']],
  ['POST',/^\/api\/v1\/seo\/content-assets\/[1-9]\d*\/review$/,['tenant_id'],'content',['version_count','decision','note']],
  ['GET',/^\/api\/v1\/seo\/workbench\/(service-plan|service-status)$/,['tenant_id','site_id'],'site'],
  ['PUT',/^\/api\/v1\/seo\/workbench\/service-plan$/,[],'site',['tenant_id','site_id','expected_revision','optimization_directions','content_topics','service_note','status','content_cycle_enabled','content_interval_days','website_cycle_enabled','website_interval_days','website_max_pages','monitoring_cycle_enabled','monitoring_interval_days','report_cycle_enabled','content_ai_enabled','content_ai_fact_ids','content_ai_keyword_ids']],
  ['GET',/^\/api\/v1\/seo\/workbench\/executions$/,['tenant_id','site_id','page','page_size'],'site'],
  ['GET',/^\/api\/v1\/seo\/workbench\/executions\/[1-9]\d*(?:\/report)?$/,['tenant_id','site_id'],'site'],
  ['POST',/^\/api\/v1\/seo\/workbench\/executions\/[1-9]\d*\/advance$/,[],'site',['tenant_id','site_id','retry_page_id','explanation','report_sha256']],
  ['POST',/^\/api\/v1\/seo\/workbench\/content-workflows\/[1-9]\d*\/advance$/,[],'site',['tenant_id','site_id','publication_id']],
  ['DELETE',/^\/api\/v1\/seo\/workbench\/executions\/[1-9]\d*$/,['tenant_id','site_id'],'site'],
];
function error(code,status){const e=Error(code);e.code=code;e.status=status;return e;}
export function sameOriginLoginUrl(returnPath='/customer-workbench/') {
  let path='/customer-workbench/';
  try {
    const decoded=decodeURIComponent(returnPath),url=new URL(returnPath,'https://same-origin.invalid');
    if(typeof returnPath==='string'&&returnPath.startsWith('/')&&!decoded.startsWith('//')&&!/[\\\r\n]/.test(decoded)&&url.origin==='https://same-origin.invalid'&&!/^\/login(?:\/|$)/.test(url.pathname))path=returnPath;
  }catch{}
  return '/login?'+new URLSearchParams({redirect:path});
}
export function createHostSessionAdapter({origin,fetchImpl=globalThis.fetch,getSession,subscribeSession,logout,redirectToLogin,returnPath,allowLocalHttp=false}={}) {
  const base=new URL(origin);
  if(base.origin!==origin||!(base.protocol==='https:'||(allowLocalHttp&&base.protocol==='http:'&&['127.0.0.1','localhost','[::1]'].includes(base.hostname))))throw error('INVALID_ORIGIN');
  let generation=0,authorized=null,phase='disconnected',fingerprint=null,moduleCatalog=[],modulesChecked=false;
  const listeners=new Set(),pending=new Set();
  const snapshot=()=>getSession?.()??null;
  const key=s=>JSON.stringify(s?[s.token,s.userId,s.tenantId,s.siteId,s.revision]:null);
  function invalidate(reason='context_changed') {
    generation++;authorized=null;moduleCatalog=[];modulesChecked=false;phase=reason==='forbidden'?'forbidden':reason==='expired'?'unauthenticated':'disconnected';
    for(const c of pending)c.abort();pending.clear();
    for(const listener of listeners)listener({reason,phase});
  }
  function sync(){const s=snapshot(),next=key(s);if(fingerprint===null)fingerprint=next;else if(next!==fingerprint){fingerprint=next;invalidate();}return s;}
  function assertCurrent(s,started){sync();if(generation!==started||key(snapshot())!==key(s))throw error('CONTEXT_CHANGED');}
  function login(){const url=sameOriginLoginUrl(returnPath);redirectToLogin?.(url);return url;}
  async function request(path,options={},preflight=false) {
    const s=sync(),started=generation;
    if(!s?.token){throw error(typeof getSession==='function'?'NOT_AUTHENTICATED':'NOT_CONNECTED',401);}
    if(!positive(s.userId)||!positive(s.tenantId)||!positive(s.siteId)||s.revision==null||typeof s.token!=='string'||/\s/.test(s.token))throw error('INVALID_HOST_SCOPE');
    if(typeof path!=='string'||!path.startsWith('/api/v1/')||/[\\#\s]/.test(path))throw error('ROUTE_DENIED');
    const url=new URL(path,base),method=options.method??'GET';
    const route=routes.find(r=>r[0]===method&&r[1].test(url.pathname));
    if(url.origin!==origin||url.pathname!==path.split('?')[0]||!route)throw error('ROUTE_DENIED');
    if((route[3]==='preflight')!==preflight)throw error('ROUTE_DENIED');
    for(const name of url.searchParams.keys())if(!route[2].includes(name)||url.searchParams.getAll(name).length!==1)throw error('QUERY_DENIED');
    if(route[2].includes('tenant_id')&&url.searchParams.get('tenant_id')!==String(s.tenantId))throw error('SCOPE_MISMATCH');
    if(route[2].includes('site_id')&&url.searchParams.get('site_id')!==String(s.siteId))throw error('SCOPE_MISMATCH');
    if(url.pathname==='/api/v1/auth/tenants'&&url.searchParams.get('module')!=='seo')throw error('QUERY_DENIED');
    if(!preflight&&!authorized)throw error('NOT_CONNECTED');
    if(!preflight&&route[3]==='site'&&!['view','edit'].includes(authorized.user.permissions['seo.site']))throw error('PERMISSION_DENIED',403);
    if(!preflight&&route[3]==='keywords'&&!['view','edit'].includes(authorized.user.permissions['seo.keywords']))throw error('PERMISSION_DENIED',403);
    if(['GET','DELETE'].includes(method)&&options.body!==undefined)throw error('BODY_DENIED');
    if(!['GET','DELETE'].includes(method)){
      let body;try{body=JSON.parse(options.body);}catch{throw error('BODY_DENIED');}
      if(!body||Array.isArray(body)||Object.keys(body).some(k=>!route[4].includes(k)))throw error('BODY_DENIED');
      if(route[4].includes('site_id')&&(body.tenant_id!==s.tenantId||body.site_id!==s.siteId))throw error('SCOPE_MISMATCH');
    }
    const controller=new AbortController();pending.add(controller);
    try{
      const response=await fetchImpl(url.href,{method,body:options.body,headers:{Authorization:`Bearer ${s.token}`,Accept:'application/json',...(method==='GET'?{}:{'Content-Type':'application/json'})},cache:'no-store',credentials:'omit',redirect:'error',signal:controller.signal});
      assertCurrent(s,started);
      if(response.status===401){invalidate('expired');logout?.();login();throw error('AUTH_EXPIRED',401);}
      if(response.status===403){invalidate('forbidden');throw error('PERMISSION_DENIED',403);}
      return {ok:response.ok,status:response.status,headers:response.headers,
        async json(){assertCurrent(s,started);const data=await response.json();assertCurrent(s,started);return data;},
        async arrayBuffer(){assertCurrent(s,started);const data=await response.arrayBuffer();assertCurrent(s,started);return data;}};
    }catch(e){if(!['AUTH_EXPIRED','PERMISSION_DENIED'].includes(e.code))assertCurrent(s,started);throw e;}finally{pending.delete(controller);}
  }
  async function initialize() {
    const s=sync();
    if(!s?.token){phase=typeof getSession==='function'?'unauthenticated':'disconnected';return {phase};}
    if(!positive(s.tenantId)||!positive(s.siteId)){phase='scope_required';return {phase};}
    const started=generation;phase='connecting';authorized=null;
    const read=async path=>{const r=await request(path,{method:'GET'},true);if(!r.ok)throw error('PREFLIGHT_FAILED',r.status);return r.json();};
    try{
      const me=await read('/api/v1/auth/me'),user=me?.user;
      if(user?.id!==s.userId||!user.permissions||(user.tenant_id!==null&&user.tenant_id!==s.tenantId))throw error('IDENTITY_SCOPE_MISMATCH');
      const modules=await read('/api/v1/auth/modules');
      if(modules.tenant_id!==user.tenant_id||!Array.isArray(modules.modules))throw error('MODULE_UNAVAILABLE');
      moduleCatalog=modules.modules.filter(m=>['sem','seo','geo'].includes(m.module_code)).map(m=>({module_code:m.module_code,available:m.available===true}));
      modulesChecked=true;
      if(!moduleCatalog.some(m=>m.module_code==='seo'&&m.available))throw error('MODULE_UNAVAILABLE');
      if(!['view','edit'].includes(user.permissions['seo.content']))throw error('PERMISSION_DENIED',403);
      const tenants=await read('/api/v1/auth/tenants?module=seo');
      const tenant=tenants.module==='seo'&&tenants.tenants?.find(t=>t.id===s.tenantId);if(!tenant)throw error('TENANT_NOT_ALLOWED');
      const sites=await read(`/api/v1/seo/workbench/sites?tenant_id=${s.tenantId}`);
      const site=sites.sites?.find(v=>v.id===s.siteId);
      if(sites.tenant_id!==s.tenantId||!site||site.status!=='active'||!sites.selection_policy?.selectable_statuses?.includes('active'))throw error('SITE_NOT_ALLOWED');
      assertCurrent(s,started);authorized={user,tenant,site};phase='connected';return {phase,identity:structuredClone(authorized)};
    }catch(e){if(generation===started){authorized=null;phase=e.code==='MODULE_UNAVAILABLE'?'module_pending':e.status===403||['IDENTITY_SCOPE_MISMATCH','TENANT_NOT_ALLOWED','SITE_NOT_ALLOWED'].includes(e.code)?'forbidden':'connection_error';}throw e;}
  }
  const unsubscribe=subscribeSession?.(()=>{sync();});
  return {
    initialize,login,invalidate,
    transport:(path,options)=>request(path,options,false),
    getContext(){const s=sync();return authorized?{connected:true,tenantId:s.tenantId,siteId:s.siteId,userId:s.userId,revision:generation}:null;},
    getState(){sync();return {phase,identity:authorized?structuredClone(authorized):null,modules:structuredClone(moduleCatalog),modulesChecked};},
    subscribe(listener){listeners.add(listener);return()=>listeners.delete(listener);},
    dispose(){unsubscribe?.();listeners.clear();invalidate('disposed');},
  };
}

// For an existing Vue host route: pass its existing session and watch, not new storage logic.
export function existingSessionBridge({session,watch,browser=window,getSiteId}) {
  return {
    getSession:()=>({token:session.token,userId:session.user?.id,tenantId:session.tenantId,siteId:getSiteId(),revision:JSON.stringify([session.authRevision,session.modules])}),
    logout:()=>session.logout(),
    subscribeSession(listener){
      const stop=watch(()=>[session.token,session.user?.id,session.tenantId,getSiteId(),session.authRevision,JSON.stringify(session.modules)],listener,{flush:'sync'});
      browser.addEventListener('sem:auth-context-changed',listener);
      return()=>{stop();browser.removeEventListener('sem:auth-context-changed',listener);};
    },
  };
}
