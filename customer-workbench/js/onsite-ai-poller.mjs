// Polling reads a durable request; it never resubmits an AI operation.
export const onsiteAiPending=task=>['queued','running'].includes(task?.workflow?.ai_run?.state);

export function createOnsiteAiPoller({getTask,getContext,read,apply,canRead=()=>true,onError=()=>{},
  schedule=globalThis.setTimeout,cancel=globalThis.clearTimeout,now=Date.now,
  interval=3000,maxDuration=12*60*1000,maxFailures=3}){
  let active=null,timer=null,generation=0,disposed=false,blocked=null;
  const identity=()=>{
    const task=getTask(),context=getContext();
    if(!onsiteAiPending(task)||!context?.connected||!task.workflow.ai_run.request_id)return null;
    return {key:JSON.stringify([context.tenantId,context.siteId,context.projectId,context.userId,
      context.revision,task.id,task.workflow.ai_run.request_id]),taskId:task.id,requestId:task.workflow.ai_run.request_id};
  };
  function stop(){generation++;if(timer!==null)cancel(timer);timer=null;active=null;}
  function later(token){timer=schedule(()=>{timer=null;void tick(token);},interval);}
  function fail(error){blocked=active?.key;stop();onError(error);}
  async function tick(token){
    if(disposed||token!==generation||!active)return;
    if(identity()?.key!==active.key){sync();return;}
    if(now()-active.startedAt>=maxDuration){fail(Object.assign(Error('AI_POLL_LIMIT'),{code:'AI_POLL_LIMIT'}));return;}
    if(!canRead()){later(token);return;}
    const key=active.key;
    try{
      const data=await read(active.taskId,active.requestId);
      if(disposed||token!==generation)return;
      if(identity()?.key!==key){sync();return;}
      active.failures=0;
      // An edit or another operation may begin while the GET is in flight.
      if(canRead())apply(data);
    }catch(error){
      if(disposed||token!==generation)return;
      if(identity()?.key!==key){sync();return;}
      if(['AUTH_EXPIRED','PERMISSION_DENIED','CONTEXT_CHANGED','AI_REQUEST_SUPERSEDED','CONTRACT_MISMATCH'].includes(error.code)
        ||[401,403,404].includes(error.status)||++active.failures>=maxFailures){fail(error);return;}
    }
    if(disposed||token!==generation)return;
    if(identity()?.key!==key){sync();return;}
    later(token);
  }
  function sync(){
    if(disposed)return;
    const current=identity();
    if(!current){stop();blocked=null;return;}
    if(current.key===active?.key||current.key===blocked)return;
    stop();blocked=null;active={...current,startedAt:now(),failures:0};later(generation);
  }
  return {sync,dispose(){disposed=true;stop();blocked=null;}};
}
