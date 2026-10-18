import {advisorDeniedCodes,advisorMessages} from '../../frontend/src/store/advisorTenant.js';
const positive=n=>Number.isSafeInteger(n)&&n>0;
const fail=code=>Object.assign(Error(advisorMessages[code]||code),{code});

export function createAdvisorTenantSwitch({session,fetchImpl=fetch}){
  let generation=0;const pending=new Set();
  const key=()=>JSON.stringify([session.token,session.authRevision,session.user?.id]);
  async function request(path,body){
    const stamp=generation,context=key(),token=session.token,controller=new AbortController();pending.add(controller);
    const current=()=>{if(stamp!==generation||context!==key())throw fail('CONTEXT_CHANGED');};
    try{
      if(!token||!positive(session.user?.id))throw fail('NOT_AUTHENTICATED');
      const response=await fetchImpl(path,{method:body?'POST':'GET',headers:{Authorization:`Bearer ${token}`,Accept:'application/json',...(body?{'Content-Type':'application/json'}:{})},
        ...(body?{body:JSON.stringify(body)}:{}),credentials:'omit',cache:'no-store',redirect:'error',signal:AbortSignal.any([controller.signal,AbortSignal.timeout(20000)])});
      current();const data=await response.json();current();
      if(!response.ok)throw fail(data?.detail?.code||'TENANT_REQUEST_FAILED');
      return data;
    }finally{pending.delete(controller);}
  }
  return {
    async list(){
      const data=await request('/api/v1/auth/tenants');
      // Existing auth clients use an envelope; also accept the agreed array form.
      const rows=Array.isArray(data)?data:data.tenants;
      if(!Array.isArray(rows)||rows.some(t=>!positive(t.id)||typeof t.name!=='string')||new Set(rows.map(t=>t.id)).size!==rows.length)throw fail('INVALID_TENANTS');
      return rows.map(({id,name})=>({id,name}));
    },
    async select(tenantId){
      if(!positive(tenantId))throw fail('INVALID_TENANT');
      const data=await request('/api/v1/auth/select-tenant',{tenant_id:tenantId});
      if(data.tenant_id!==tenantId||typeof data.tenant_name!=='string'||data.token_type!=='bearer'||typeof data.access_token!=='string'||!data.access_token||!data.expires_at)throw fail('INVALID_TENANT_RESPONSE');
      session.replaceAuthForAdvisorTenant(data.access_token,tenantId);
      return data;
    },
    invalidate(){generation++;for(const c of pending)c.abort();pending.clear();},
  };
}

// Shared by all panels, so a rejection also clears drafts, polling and downloads
// owned by panels other than the one receiving the rejected response.
export function advisorScopedFetch({session,fetchImpl,onDenied}){
  return async (...args)=>{
    const token=session.token,revision=session.authRevision,response=await fetchImpl(...args);
    if(token!==session.token||revision!==session.authRevision)throw fail('CONTEXT_CHANGED');
    if(!response.ok&&session.isAdvisorSession){
      let code;try{code=(await response.clone().json())?.detail?.code;}catch{}
      if(token!==session.token||revision!==session.authRevision)throw fail('CONTEXT_CHANGED');
      if(advisorDeniedCodes.has(code)||code==='ADVISOR_TENANT_SELECTION_REQUIRED'||code==='ADVISOR_GRANTS_UNAVAILABLE'){
        onDenied(code);throw fail(code);
      }
    }
    return response;
  };
}
