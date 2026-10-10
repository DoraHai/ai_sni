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

test('configuration writes have fresh permission preflight and one fixed authenticated route',async()=>{
  const s=session(admin),calls=[];let permitted=true;
  const client=createPlatformConsoleClient({session:s,fetchImpl:async(path,o)=>{
    calls.push({path,o});return response(path.endsWith('/me')?{user:permitted?admin:{...admin,tenant_id:1}}:path.endsWith('/controls')?{revision:1}:snapshot);
  }});
  await client.initialize();
  const data={request_id:'id',kind:'provider',key:'provider:test',expected_revision:0,value:{enabled:false}};
  assert.equal((await client.change(data)).revision,1);
  assert.deepEqual(calls.slice(-2).map(c=>[c.path,c.o.method]),[['/api/v1/auth/me','GET'],['/api/v1/admin/console/controls','POST']]);
  const write=calls.at(-1).o;assert.equal(write.credentials,'omit');assert.equal(write.headers.Authorization,'Bearer test-token');
  assert.deepEqual(JSON.parse(write.body),data);
  permitted=false;const before=calls.length;
  await assert.rejects(client.change(data),{code:'CONSOLE_FORBIDDEN'});
  assert.equal(calls.length,before+1);assert.equal(client.getIdentity(),null);
});

test('identity changes during write preflight cancel the write',async()=>{
  const s=session(admin);let change=false,writes=0;
  const client=createPlatformConsoleClient({session:s,fetchImpl:async(path,o)=>{
    if(o.method==='POST')writes++;
    if(change&&path.endsWith('/me'))s.token='new-token';
    return response(path.endsWith('/me')?{user:admin}:snapshot);
  }});
  await client.initialize();change=true;
  await assert.rejects(client.change({}),{code:'CONSOLE_STALE'});assert.equal(writes,0);
});

test('history filters stay on fixed routes and CSV export checks current permission',async()=>{
  const s=session(admin),calls=[];let permitted=true;
  const client=createPlatformConsoleClient({session:s,fetchImpl:async(path,o)=>{
    calls.push({path,o});
    if(path.endsWith('/me'))return response({user:permitted?admin:{...admin,tenant_id:1}});
    if(path.includes('/usage/export'))return new Response('\ufeffid,estimated_amount\nfixture,\n',{headers:{'Content-Type':'text/csv; charset=utf-8'}});
    if(path.includes('/usage?'))return response({state:'available',rows:[],total:0});
    return response(snapshot);
  }});
  await client.initialize();
  assert.equal((await client.usage({tenant_id:1,endpoint:'provider.test/v1?name=value'})).total,0);
  const query=calls.at(-1).path;assert.equal(new URL(query,'https://test').searchParams.get('endpoint'),'provider.test/v1?name=value');
  assert.equal(new URL(query,'https://test').pathname,'/api/v1/admin/console/usage');
  await assert.rejects(client.usage({url:'https://outside.test'}),{code:'CONSOLE_INVALID_QUERY'});
  const csv=await client.exportUsage({from:'2026-10-01',to:'2026-10-10'});
  assert.match(await csv.text(),/fixture,/);
  assert.deepEqual(calls.slice(-2).map(c=>c.path.split('?')[0]),['/api/v1/auth/me','/api/v1/admin/console/usage/export']);
  permitted=false;const before=calls.length;
  await assert.rejects(client.exportUsage({}),{code:'CONSOLE_FORBIDDEN'});assert.equal(calls.length,before+1);
});

test('incident and supplier writes require fresh identity and discard stale downloads',async()=>{
  const s=session(admin);let permitted=true,hold=false,release;const writes=[];
  const client=createPlatformConsoleClient({session:s,fetchImpl:async(path,o)=>{
    if(path.endsWith('/me'))return response({user:permitted?admin:{...admin,tenant_id:1}});
    if(path.endsWith('/operations')){writes.push(JSON.parse(o.body));return response({revision:1});}
    if(path.includes('/usage/export'))return {ok:true,status:200,headers:new Headers({'Content-Type':'text/csv'}),blob:()=>new Promise(r=>release=r)};
    return response(snapshot);
  }});
  await client.initialize();await client.operation({kind:'alert',key:'fixture'});assert.equal(writes.length,1);
  const download=client.exportUsage({});while(!release)await new Promise(r=>setTimeout(r,1));
  client.invalidate();release(new Blob(['private-history']));await assert.rejects(download,{code:'CONSOLE_STALE'});
  await client.initialize();permitted=false;
  await assert.rejects(client.operation({kind:'supplier'}),{code:'CONSOLE_FORBIDDEN'});assert.equal(writes.length,1);
});
