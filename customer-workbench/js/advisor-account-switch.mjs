const positive=id=>Number.isSafeInteger(id)&&id>0;

export function createAdvisorAccountSwitch({session,fetchImpl=fetch,navigate=path=>location.assign(path)}){
  async function request(path,method,body){
    const token=session.token,revision=session.authRevision,userId=session.user?.id;
    if(!token||!positive(userId))throw Error('NOT_AUTHENTICATED');
    const response=await fetchImpl(path,{method,headers:{Authorization:`Bearer ${token}`,Accept:'application/json',...(body?{'Content-Type':'application/json'}:{})},
      ...(body?{body:JSON.stringify(body)}:{}),credentials:'omit',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(20000)});
    if(token!==session.token||revision!==session.authRevision||userId!==session.user?.id)throw Error('STALE_SESSION');
    if(!response.ok)throw Error(response.status===429?'RATE_LIMITED':'SWITCH_DENIED');
    const data=await response.json();
    if(token!==session.token||revision!==session.authRevision||userId!==session.user?.id)throw Error('STALE_SESSION');
    return data;
  }
  return {
    async list(){
      const data=await request('/api/v1/auth/linked-accounts','GET');
      if(!Array.isArray(data.accounts)||data.accounts.some(a=>!positive(a.id)||!a.display_name||!a.customer_name))throw Error('INVALID_ACCOUNTS');
      return data.accounts;
    },
    async switchTo(targetUserId){
      if(!positive(targetUserId)||targetUserId===session.user?.id)throw Error('INVALID_TARGET');
      const data=await request('/api/v1/auth/switch-account','POST',{target_user_id:targetUserId});
      if(!data.token||data.user?.id!==targetUserId||!positive(data.user?.tenant_id)||!data.user.permissions)throw Error('INVALID_SWITCH_RESPONSE');
      session.replaceAuthForAdvisorSwitch(data.token,data.user);
      navigate('/customer-workbench/?console=advisor');
    },
  };
}
