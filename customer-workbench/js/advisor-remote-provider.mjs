const base='/api/distribution/v1/remote/sessions';
const uuid=v=>typeof v==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(v);
const fail=(code,status)=>Object.assign(Error(code),{code,status});
export function createAdvisorRemoteProvider({session,fetchImpl=fetch,origin=location.origin}){
  if(new URL(origin).origin!==origin||!origin.startsWith('https://'))throw fail('INVALID_ORIGIN');
  const fingerprint=()=>JSON.stringify([session.token,session.user?.id,session.authRevision,session.tenantId,session.modules]);
  async function request(path,body,signal,binary=false){
    const stamp=fingerprint(),token=session.token;
    if(!token||typeof token!=='string'||/\s/.test(token)||!Number.isSafeInteger(session.user?.id)||session.user.id<=0)throw fail('NOT_AUTHENTICATED',401);
    const assert=()=>{if(stamp!==fingerprint())throw fail('CONTEXT_CHANGED');};
    const r=await fetchImpl(origin+path,{method:body===undefined?'GET':'POST',headers:{Authorization:`Bearer ${token}`,Accept:binary?'image/png':'application/json',...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:signal?AbortSignal.any([signal,AbortSignal.timeout(20000)]):AbortSignal.timeout(20000),credentials:'omit',redirect:'error',cache:'no-store'});assert();
    if(!r.ok){if(r.status===401)session.logout();throw fail(r.status===401?'AUTH_EXPIRED':r.status===403?'PERMISSION_DENIED':[404,503].includes(r.status)?'NOT_INTEGRATED':r.status===409?'REMOTE_CONFLICT':'REMOTE_FAILED',r.status);}
    if(binary){
      if(r.headers.get('content-type')?.split(';')[0]!=='image/png')throw fail('INVALID_IMAGE');
      const numeric=name=>{const value=r.headers.get(name);if(!/^[1-9]\d*$/.test(value||'')||!Number.isSafeInteger(Number(value)))throw fail('CONTRACT_MISMATCH');return Number(value);};
      const metadata={session_id:r.headers.get('X-Remote-Session-Id'),device_id:r.headers.get('X-Remote-Device-Id'),frame_seq:numeric('X-Frame-Seq'),control_revision:numeric('X-Control-Revision'),viewport_width:numeric('X-Viewport-Width'),viewport_height:numeric('X-Viewport-Height'),captured_at:numeric('X-Frame-Captured-At')};
      const declared=r.headers.get('content-length');if(declared&&Number(declared)>2097152)throw fail('INVALID_IMAGE');
      const blob=await r.blob();assert();if(blob.size===0||blob.size>2097152||blob.type!=='image/png')throw fail('INVALID_IMAGE');return {blob,...metadata};
    }
    const result=await r.json();assert();if(result?.schema!==1||(result.session&&result.session.controller_user_id!==session.user?.id))throw fail('CONTRACT_MISMATCH');return result;
  }
  const path=id=>{if(!uuid(id))throw fail('INVALID_SESSION');return base+'/'+id;};
  return {
    open:(body,{signal})=>request(base,body,signal),
    status:({session_id},{signal})=>request(path(session_id),undefined,signal),
    frame:({session_id},{signal})=>request(path(session_id)+'/frame',undefined,signal,true),
    input:({session_id,...body},{signal})=>request(path(session_id)+'/input',body,signal),
    close:({session_id,...body},{signal})=>request(path(session_id)+'/close',body,signal),
  };
}
