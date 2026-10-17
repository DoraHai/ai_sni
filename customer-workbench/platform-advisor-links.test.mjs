import test from 'node:test';
import assert from 'node:assert/strict';
import {eligibleAdvisor,advisorLinkPayload,createAdvisorLinksClient} from './js/platform-advisor-links.mjs';
const admin={id:1,tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
const roles=[{id:2,name:'顾问',permissions:{'seo.site':'edit','seo.content':'edit'}},{id:3,name:'管理员',is_system:true,permissions:{'geo.assets':'edit','geo.content':'edit'}}];
const users=Array.from({length:21},(_,i)=>({id:i+10,tenant_id:i+1,is_active:true,role_id:2,username:'advisor'+i}));
const group='12345678-1234-1234-1234-123456789abc';
function fixture({status=200,mutate=()=>{}}={}){
  const calls=[],session={token:'fixture-token',user:structuredClone(admin),authRevision:0};
  const client=createAdvisorLinksClient({session,fetchImpl:async(path,options)=>{
    calls.push({path,options});
    const data=path.endsWith('/me')?{user:admin}:path.endsWith('/users')?{users}:path.endsWith('/roles')?{roles}:{group_id:group,user_ids:[10,11]};
    return {ok:!path.endsWith('account-links')||status===200,status:path.endsWith('account-links')?status:200,json:async()=>{mutate(path,session);return data;}};
  }});return {client,calls,session};
}
test('eligibility mirrors disabled, single-customer, settings and SEO/GEO boundaries',()=>{
  assert.equal(eligibleAdvisor(users[0],roles),true);
  for(const change of [{is_active:false},{tenant_id:null},{role_id:999},{role_id:3}])assert.equal(eligibleAdvisor({...users[0],...change},roles),false);
  assert.equal(eligibleAdvisor(users[0],[{id:2,permissions:{'seo.site':'edit','seo.content':'edit','settings.accounts':'edit'}}]),false);
  assert.equal(eligibleAdvisor(users[0],[{id:2,permissions:{'geo.assets':'edit','geo.content':'edit'}}]),true);
  assert.equal(eligibleAdvisor(users[0],[{id:2,permissions:{'seo.site':'edit','seo.content':'view'}}]),false);
});
test('2–20 unique eligible accounts from distinct customers and optional UUID',()=>{
  for(const ids of [[10],users.map(u=>u.id),[10,10]])assert.throws(()=>advisorLinkPayload(ids,'',users,roles));
  assert.equal(advisorLinkPayload(users.slice(0,20).map(u=>u.id),'',users,roles).user_ids.length,20);
  assert.deepEqual(advisorLinkPayload([10,11],' '+group+' ',users,roles),{user_ids:[10,11],group_id:group});
  assert.throws(()=>advisorLinkPayload([10,11],'bad',users,roles));
  assert.throws(()=>advisorLinkPayload([10,11],'',users.map(u=>({...u,tenant_id:1})),roles),/不同客户/);
});
test('catalog and creation revalidate real admin and use only existing routes',async()=>{
  const f=fixture();const data=await f.client.catalog();assert.equal(data.users.length,21);
  await f.client.create(advisorLinkPayload([10,11],'',users,roles));
  assert.deepEqual(f.calls.map(c=>[c.path,c.options.method]),[
    ['/api/v1/auth/me','GET'],['/api/v1/users','GET'],['/api/v1/roles','GET'],['/api/v1/auth/me','GET'],['/api/v1/auth/account-links','POST']]);
  assert.equal(f.calls.at(-1).options.credentials,'omit');
  assert.deepEqual(JSON.parse(f.calls.at(-1).options.body),{user_ids:[10,11]});
});
test('unprivileged sessions cannot load catalog or write',async()=>{
  const f=fixture();f.session.user.tenant_id=1;
  await assert.rejects(f.client.catalog());await assert.rejects(f.client.create({user_ids:[10,11]}));assert.equal(f.calls.length,0);
});
test('auth changes during JSON parsing reject stale data before any write',async()=>{
  const f=fixture({mutate:(path,s)=>{if(path.endsWith('/me'))s.authRevision++;}});
  await assert.rejects(f.client.create({user_ids:[10,11]}),/会话/);
  assert.equal(f.calls.some(c=>c.options.method==='POST'),false);
});
test('invalidation during catalog read rejects late results',async()=>{
  const f=fixture({mutate:path=>{if(path.endsWith('/users'))f.client.invalidate();}});
  await assert.rejects(f.client.catalog(),/会话/);
});
test('existing group and conflict responses are handled without raw server output',async()=>{
  const f=fixture({status:409});await assert.rejects(f.client.create({user_ids:[10,11],group_id:group}),/已有关联组/);
  const good=fixture();assert.equal((await good.client.create({user_ids:[10,11],group_id:group})).group_id,group);
});
