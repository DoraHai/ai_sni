import test from 'node:test';
import assert from 'node:assert/strict';
import {createPlatformConsoleClient,isPlatformAdmin} from './js/platform-console-client.mjs';
const admin={id:7,tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
const snapshot={schema:1,mode:'read_only_inventory',sources:{},costs:{actual_amount:null}};
const response=(body,status=200)=>({ok:status===200,status,json:async()=>body});
const session=user=>({user,token:'test-token',authRevision:0,refreshUser(u){this.user=u;this.authRevision++;},logout(){this.token='';this.user=null;this.authRevision++;}});

test('console requires an unbound named identity with both management permissions',()=>{
  assert(isPlatformAdmin(admin));
  for(const u of [null,{...admin,id:null},{...admin,tenant_id:1},{...admin,tenant_id:undefined},
    {...admin,permissions:{'settings.accounts':'edit'}},{...admin,permissions:{'settings.accounts':'view','settings.customers':'edit'}}])assert(!isPlatformAdmin(u));
});
test('server identity is checked before fetching the global snapshot',async()=>{
  const paths=[],s=session(admin);
  const client=createPlatformConsoleClient({session:s,fetchImpl:async path=>{paths.push(path);return response({user:{...admin,tenant_id:1}});}});
  await assert.rejects(client.initialize(),{code:'CONSOLE_FORBIDDEN'});
  assert.deepEqual(paths,['/api/v1/auth/me']);
});
test('reads only the two global preflight routes and authenticates without keys',async()=>{
  const calls=[],s=session(admin);
  const client=createPlatformConsoleClient({session:s,fetchImpl:async(path,o)=>{calls.push({path,o});return response(path.endsWith('/me')?{user:admin}:snapshot);}});
  assert.equal((await client.initialize()).data,snapshot);
  assert.deepEqual(calls.map(c=>c.path),['/api/v1/auth/me','/api/v1/admin/console/snapshot']);
  for(const {o} of calls){assert.equal(o.method,'GET');assert.equal(o.cache,'no-store');assert.equal(o.credentials,'omit');assert.equal(o.redirect,'error');assert.equal(o.headers.Authorization,'Bearer test-token');assert(!('X-API-Key' in o.headers));}
});
test('late global data is rejected after session changes, including body parsing',async()=>{
  const s=session(admin);let release;
  const client=createPlatformConsoleClient({session:s,fetchImpl:async path=>path.endsWith('/me')?response({user:admin}):
    {ok:true,status:200,json:()=>new Promise(r=>release=r)}});
  const pending=client.initialize();while(!release)await new Promise(r=>setTimeout(r,1));
  s.token='different-token';release(snapshot);
  await assert.rejects(pending,{code:'CONSOLE_STALE'});
});
test('expiry clears the canonical session and permission denial invalidates authorization',async()=>{
  for(const status of [401,403]){
    const s=session(admin);let expired=0;
    const client=createPlatformConsoleClient({session:s,onExpired:()=>expired++,fetchImpl:async path=>path.endsWith('/me')?response({user:admin}):response({},status)});
    await assert.rejects(client.initialize(),{code:status===401?'CONSOLE_EXPIRED':'CONSOLE_FORBIDDEN'});
    assert.equal(client.getIdentity(),null);assert.equal(expired,status===401?1:0);
    if(status===401)assert.equal(s.token,'');
  }
});
