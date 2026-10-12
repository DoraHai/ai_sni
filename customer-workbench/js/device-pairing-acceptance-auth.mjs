import {isPlatformAdmin} from './platform-console-client.mjs';
export async function verifyPairingAdmin({session,fetchImpl=fetch,isCurrent=()=>true}){
 const identity=()=>JSON.stringify([session.token,session.user?.id,session.authRevision]);
 const started=identity(),token=session.token,userId=session.user?.id;
 const check=()=>{if(!isCurrent()||identity()!==started)throw Error('CONTEXT_CHANGED');};
 check();
 const response=await fetchImpl('/api/v1/auth/me',{headers:{Authorization:'Bearer '+token},cache:'no-store',credentials:'omit',redirect:'error'});
 check();const value=await response.json();check();
 if(!response.ok||value.user?.id!==userId||!isPlatformAdmin(value.user))throw Error('ADMIN_REQUIRED');
 return value.user;
}
