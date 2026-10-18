import {advisorModuleEligible} from './advisor-client.mjs';
import {automationScope,automationUuid,automationActions,validateAutomationConfiguration,validateAutomationProject,validateAutomationProjects,validateAutomationRun,validateAutomationEvents,validateAutomationHistory,validateAutomationBasis,validateAutomationExport} from './advisor-automation-contract.mjs';
const positive=n=>Number.isSafeInteger(n)&&n>0;
const fail=(code,status)=>Object.assign(Error(code),{code,status});
const eligible=(user,module)=>advisorModuleEligible(user,module)&&(module!=='seo'||user.permissions?.['seo.content']==='edit'&&['view','edit'].includes(user.permissions?.['seo.keywords']));

export function createAdvisorAutomationClient({session,fetchImpl=fetch,subscribeSession=()=>()=>{}}){
  let generation=0,identity=null,fingerprint;
  const controllers=new Set(),listeners=new Set(),writes=new Map();
  const key=()=>JSON.stringify([session.token,session.user?.id,session.user?.tenant_id,session.authRevision,session.user?.permissions,session.modules]);
  fingerprint=key();
  function invalidate(reason='context_changed'){generation++;identity=null;for(const c of controllers)c.abort();controllers.clear();writes.clear();for(const fn of listeners)fn(reason);}
  function sync(){const next=key();if(next!==fingerprint){fingerprint=next;invalidate();}}
  function current(stamp,context){sync();if(stamp!==generation||context!==key())throw fail('CONTEXT_CHANGED');}
  async function request(path,{method='GET',body=null,preflight=false}={}){
    sync();const stamp=generation,context=key(),token=session.token;
    if(!token||typeof token!=='string'||/\s/.test(token)||!positive(session.user?.id))throw fail('NOT_AUTHENTICATED',401);
    const preflightPaths=['/api/v1/auth/me','/api/v1/auth/modules'];
    const route=/^\/api\/v1\/(seo|geo)\/workbench\/automation-projects(?:\/([1-9]\d*)\/(control|configuration-basis|events(?:\/export)?|runs(?:\/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})(?:\/events)?)?))?$/.exec(path.split('?')[0]);
    const url=new URL(path,'https://automation.invalid');
    if(url.origin!=='https://automation.invalid'||/[\\#\s]/.test(path)||(!preflightPaths.includes(path)&&!route))throw fail('ROUTE_DENIED');
    if(preflight){if(!preflightPaths.includes(path)||method!=='GET'||body!==null)throw fail('ROUTE_DENIED');}
    else{
      if(!route||!identity?.modules.includes(route[1]))throw fail('PERMISSION_DENIED',403);
      const allowed=route[3]==='control'?['tenant_id']:route[3]==='events/export'?['tenant_id','format','after_id','through_id','limit']:route[3]==='configuration-basis'?['tenant_id','operation','before_object_id','limit']:route[3]==='events'||route[3]?.endsWith('/events')?['tenant_id','after_id','limit']:route[3]==='runs'?['tenant_id','before_run_id','limit']:route[3]?['tenant_id']:['tenant_id','before_scope_id','limit'];
      for(const name of url.searchParams.keys()){
        const value=url.searchParams.get(name);
        if(!allowed.includes(name)||url.searchParams.getAll(name).length!==1)throw fail('QUERY_DENIED');
        if(name==='format'?value!=='json':name==='operation'?!/^[a-z][a-z0-9_]{0,39}$/.test(value):name==='before_run_id'?!automationUuid(value):(!/^\d+$/.test(value)||!Number.isSafeInteger(Number(value))||Number(value)<(['after_id','through_id'].includes(name)?0:1)))throw fail('QUERY_DENIED');
      }
      if(method==='GET'&&body!==null||method!=='GET'&&(!['PUT','POST'].includes(method)||route[3]!=='control'||url.search||!body))throw fail('ROUTE_DENIED');
      const tenantId=method==='GET'?Number(url.searchParams.get('tenant_id')):body.tenant_id;
      if(route[2]&&!positive(Number(route[2]))||route[3]&&!positive(tenantId)||identity.user.tenant_id!==null&&tenantId&&identity.user.tenant_id!==tenantId)throw fail('PERMISSION_DENIED',403);
    }
    const controller=new AbortController();controllers.add(controller);
    try{
      const response=await fetchImpl(path,{method,headers:{Authorization:`Bearer ${token}`,Accept:'application/json',...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{}),credentials:'omit',cache:'no-store',redirect:'error',signal:AbortSignal.any([controller.signal,AbortSignal.timeout(20000)])});
      current(stamp,context);
      if(response.status===401||response.status===403){invalidate(response.status===401?'expired':'forbidden');if(response.status===401)session.logout();throw fail(response.status===401?'AUTH_EXPIRED':'PERMISSION_DENIED',response.status);}
      if(!response.ok)throw fail(response.status===409?'AUTOMATION_CONFLICT':[404,405,501,503].includes(response.status)?'AUTOMATION_NOT_INTEGRATED':'AUTOMATION_READ_FAILED',response.status);
      const data=await response.json();current(stamp,context);return data;
    }finally{controllers.delete(controller);}
  }
  async function auth(){
    sync();const stamp=generation,context=key();
    const data=await request('/api/v1/auth/me',{preflight:true});const user=session.isAdvisorSession?{...data.user,tenant_id:session.tenantId}:data.user;
    current(stamp,context);
    if(user?.id!==session.user?.id||user.tenant_id!==(session.isAdvisorSession?session.tenantId:session.user?.tenant_id)||!positive(user.id)||!user.permissions)throw fail('IDENTITY_MISMATCH');
    const catalog=await request('/api/v1/auth/modules',{preflight:true});
    current(stamp,context);
    if(catalog?.tenant_id!==user.tenant_id||!Array.isArray(catalog.modules))throw fail('AUTOMATION_CONTRACT_MISMATCH');
    return {user,modules:['seo','geo'].filter(module=>eligible(user,module)&&catalog.modules.some(row=>row.module_code===module&&row.available===true))};
  }
  const root=scope=>{automationScope(scope);return `/api/v1/${scope.module}/workbench/automation-projects/${scope.scopeId}`;};
  const readControl=async scope=>validateAutomationProject(await request(root(scope)+'/control?'+new URLSearchParams({tenant_id:scope.tenantId})),scope);
  async function write(scope,project,payload,method){
    sync();automationScope(scope);validateAutomationProject(project,scope);
    if(!identity?.modules.includes(scope.module)||!automationUuid(payload.request_id)||payload.expected_version!==project.version||payload.tenant_id!==scope.tenantId)throw fail('AUTOMATION_INVALID_WRITE');
    const body=structuredClone(payload),writeKey=JSON.stringify([key(),scope,method,body]);
    if(writes.has(writeKey))return writes.get(writeKey);
    const promise=(async()=>{
      const stamp=generation,context=key(),freshIdentity=await auth();current(stamp,context);
      if(!freshIdentity.modules.includes(scope.module)){invalidate('forbidden');throw fail('PERMISSION_DENIED',403);}
      const fresh=await readControl(scope);current(stamp,context);
      if(fresh.version!==project.version||fresh.generation!==project.generation||fresh.current_run_id!==project.current_run_id||fresh.state!==project.state)throw fail('AUTOMATION_CONFLICT',409);
      if(method==='PUT'?(fresh.capabilities.can_configure!==true):(fresh.capabilities.can_control!==true||!fresh.allowed_actions.includes(body.action)))throw fail('AUTOMATION_CONFLICT',409);
      if(method==='PUT'&&body.configuration.operations.some(operation=>!fresh.capabilities.available_operations.includes(operation)))throw fail('AUTOMATION_INVALID_WRITE');
      let data;
      try{data=await request(root(scope)+'/control',{method,body});}
      catch(error){if(error.status&&error.status<500||['CONTEXT_CHANGED','AUTH_EXPIRED','PERMISSION_DENIED'].includes(error.code))throw error;throw fail('AUTOMATION_WRITE_UNKNOWN');}
      try{validateAutomationProject(data,scope);if(data.version<=project.version)throw fail('AUTOMATION_WRITE_UNKNOWN');}
      catch{throw fail('AUTOMATION_WRITE_UNKNOWN');}
      return data;
    })();writes.set(writeKey,promise);return promise;
  }
  const stop=subscribeSession(()=>sync());
  return {
    async initialize(){invalidate('initializing');identity=await auth();return structuredClone(identity);},
    async list(module,{beforeScopeId=null,limit=25,tenantId=null}={}){
      sync();if(!identity?.modules.includes(module))throw fail('PERMISSION_DENIED',403);
      if(!positive(limit)||limit>50||beforeScopeId!==null&&!positive(beforeScopeId)||tenantId!==null&&!positive(tenantId))throw fail('QUERY_DENIED');
      const query=new URLSearchParams({limit});if(beforeScopeId!==null)query.set('before_scope_id',beforeScopeId);if(tenantId!==null)query.set('tenant_id',tenantId);
      const data=validateAutomationProjects(await request(`/api/v1/${module}/workbench/automation-projects?${query}`),module,{beforeScopeId,limit,tenantId});
      if(identity.user.tenant_id!==null&&data.items.some(row=>row.tenant_id!==identity.user.tenant_id))throw fail('AUTOMATION_CONTRACT_MISMATCH');return data;
    },
    readControl,
    async basis(scope,{operation,beforeObjectId=null,limit=25}={}){
      if(!/^[a-z][a-z0-9_]{0,39}$/.test(operation)||!positive(limit)||limit>50||beforeObjectId!==null&&!positive(beforeObjectId))throw fail('QUERY_DENIED');
      const query=new URLSearchParams({tenant_id:scope.tenantId,operation,limit});if(beforeObjectId!==null)query.set('before_object_id',beforeObjectId);
      return validateAutomationBasis(await request(root(scope)+'/configuration-basis?'+query),scope,{operation,beforeObjectId,limit});
    },
    saveConfiguration(scope,project,configuration,requestId){const config=validateAutomationConfiguration(configuration);if(config.owner_user_id!==identity?.user.id)throw fail('AUTOMATION_INVALID_WRITE');return write(scope,project,{tenant_id:scope.tenantId,request_id:requestId,expected_version:project.version,configuration:config},'PUT');},
    act(scope,project,action,requestId){if(!automationActions.includes(action))throw fail('AUTOMATION_INVALID_WRITE');return write(scope,project,{tenant_id:scope.tenantId,request_id:requestId,expected_version:project.version,action},'POST');},
    async run(scope,runId){if(!automationUuid(runId))throw fail('QUERY_DENIED');return validateAutomationRun(await request(root(scope)+'/runs/'+runId+'?'+new URLSearchParams({tenant_id:scope.tenantId})),scope,runId);},
    async events(scope,runId,{afterId=0,limit=50}={}){if(!automationUuid(runId)||!Number.isSafeInteger(afterId)||afterId<0||!positive(limit)||limit>100)throw fail('QUERY_DENIED');return validateAutomationEvents(await request(root(scope)+'/runs/'+runId+'/events?'+new URLSearchParams({tenant_id:scope.tenantId,after_id:afterId,limit})),scope,runId,{afterId,limit});},
    async projectEvents(scope,{afterId=0,limit=50}={}){if(!Number.isSafeInteger(afterId)||afterId<0||!positive(limit)||limit>100)throw fail('QUERY_DENIED');return validateAutomationEvents(await request(root(scope)+'/events?'+new URLSearchParams({tenant_id:scope.tenantId,after_id:afterId,limit})),scope,null,{afterId,limit});},
    async exportWindow(scope,{afterId=0,throughId=null,limit=500}={}){
      if(!Number.isSafeInteger(afterId)||afterId<0||throughId!==null&&(!Number.isSafeInteger(throughId)||throughId<0)||!positive(limit)||limit>500)throw fail('QUERY_DENIED');
      const query=new URLSearchParams({tenant_id:scope.tenantId,format:'json',after_id:afterId,limit});if(throughId!==null)query.set('through_id',throughId);
      return validateAutomationExport(await request(root(scope)+'/events/export?'+query),scope,{afterId,throughId,limit});
    },
    async history(scope,{beforeRunId=null,limit=20}={}){if(beforeRunId!==null&&!automationUuid(beforeRunId)||!positive(limit)||limit>50)throw fail('QUERY_DENIED');const query=new URLSearchParams({tenant_id:scope.tenantId,limit});if(beforeRunId!==null)query.set('before_run_id',beforeRunId);return validateAutomationHistory(await request(root(scope)+'/runs?'+query),scope,{beforeRunId,limit});},
    subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn);},invalidate,
    dispose(){stop();listeners.clear();invalidate('disposed');},
  };
}
