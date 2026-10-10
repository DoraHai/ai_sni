// Versioned onsite writes only follow freshly read, server-granted actions.
export function onsiteTaskId(search=''){
  const p=new URLSearchParams(search),values=p.getAll('onsite_task_id');
  if(!values.length)return null;
  if(values.length!==1||! /^[1-9]\d*$/.test(values[0]))throw Error('INVALID_ONSITE_TASK');
  const id=Number(values[0]);if(!Number.isSafeInteger(id)||id>=Number.MAX_SAFE_INTEGER)throw Error('INVALID_ONSITE_TASK');
  return id;
}
export function createOnsiteClient({transport,getContext,module='seo'}) {
  let rows=new Map(),latest=null;const aiRequests=new Map();
  const fail=(code,status)=>{rows.clear();latest=null;throw Object.assign(Error(code),{code,status});};
  function ctx(){const c=getContext();if(!c?.connected)fail('NOT_CONNECTED');return {...c};}
  const stamp=c=>JSON.stringify([c.tenantId,c.siteId,c.projectId,c.userId,c.revision]);
  function same(c){if(stamp(ctx())!==stamp(c))fail('CONTEXT_CHANGED');}
  const field=module==='geo'?'project_id':'site_id',id=c=>module==='geo'?c.projectId:c.siteId;
  const scope=c=>({tenant_id:c.tenantId,[field]:id(c)});
  const base=`/api/v1/${module}/workbench/onsite-tasks`;
  async function request(path,method,c,body){
    let response;try{response=await transport(path,{method,...(body?{body:JSON.stringify(body)}:{})});}
    catch(e){if(['AUTH_EXPIRED','PERMISSION_DENIED','CONTEXT_CHANGED'].includes(e.code))throw e;fail(method==='GET'?'READ_FAILED':'WRITE_OUTCOME_UNKNOWN');}
    same(c);let data;try{data=await response.json();}catch{fail(method==='GET'?'CONTRACT_MISMATCH':'WRITE_OUTCOME_UNKNOWN');}
    same(c);if(!response.ok)fail(typeof data.detail==='string'?data.detail:data.detail?.code||'REQUEST_FAILED',response.status);return data;
  }
  function validate(row,c){
    if(!Number.isSafeInteger(row?.id)||row.id<=0||row.module!==module||row.tenant_id!==c.tenantId||row.scope_id!==id(c)||
      row.workflow?.module!==module||!Number.isInteger(row.workflow.revision)||row.workflow.revision<1||
      !Array.isArray(row.workflow.items)||!Array.isArray(row.allowed_actions))fail('CONTRACT_MISMATCH');
    rows.set(row.id,{context:stamp(c),row:structuredClone(row)});return row;
  }
  return {
    invalidate(){rows.clear();latest=null;aiRequests.clear();},
    async list(beforeId=null){const c=ctx(),p=new URLSearchParams(scope(c));if(beforeId)p.set('before_id',beforeId);
      const data=await request(base+'?'+p,'GET',c);
      if(data.module!==module||data.tenant_id!==c.tenantId||data.scope_id!==id(c)||!Array.isArray(data.items)||typeof data.can_create!=='boolean')fail('CONTRACT_MISMATCH');
      rows.clear();data.items.forEach(row=>validate(row,c));latest={context:stamp(c),canCreate:data.can_create};return data;},
    async create(input){const c=ctx();if(latest?.context!==stamp(c)||latest.canCreate!==true)fail('ADVISOR_REQUIRED');
      const data=await request(base,'POST',c,{...input,...scope(c),request_id:crypto.randomUUID()});return validate(data,c);},
    async act(taskId,action,input={}){const c=ctx(),stored=rows.get(taskId);
      if(!stored||stored.context!==stamp(c)||!stored.row.allowed_actions.includes(action))fail('ACTION_EXPIRED');
      const data=await request(base+'/'+taskId+'/actions','POST',c,{...input,...scope(c),action,expected_revision:stored.row.workflow.revision});
      return validate(data,c);},
    async propose(taskId,mode='initial'){
      const c=ctx(),stored=rows.get(taskId);
      if(!['initial','revise'].includes(mode))fail('AI_MODE_DENIED');
      if(!stored||stored.context!==stamp(c)||!stored.row.allowed_actions.includes('save_proposal')||
        stored.row.capabilities?.ai_planning?.enabled!==true||stored.row.capabilities.ai_planning.can_generate!==true||
        ['running','unknown'].includes(stored.row.workflow.ai_run?.state))
        fail('AI_PLANNING_UNAVAILABLE');
      const key=JSON.stringify([stamp(c),taskId,stored.row.workflow.revision,mode]);
      if(aiRequests.has(key))return aiRequests.get(key);
      const requestId=crypto.randomUUID();
      const pending=(async()=>{
        const data=await request(base+'/'+taskId+'/ai-proposal','POST',c,
          {...scope(c),expected_revision:stored.row.workflow.revision,request_id:requestId,mode});
        if(data?.id!==taskId||data.workflow?.ai_run?.request_id!==requestId||
          !['running','ready','failed','unknown','stale'].includes(data.workflow.ai_run.state))fail('WRITE_OUTCOME_UNKNOWN');
        return validate(data,c);
      })();
      aiRequests.set(key,pending);
      // Keep the promise for this read version: a duplicate click never pays twice.
      return pending;
    },
  };
}

