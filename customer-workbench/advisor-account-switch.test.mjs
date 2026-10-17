import test from 'node:test';
import assert from 'node:assert/strict';
import {createAdvisorAccountSwitch} from './js/advisor-account-switch.mjs';

function fixture(status=200){
  const calls=[],navigation=[];
  const session={token:'old-token',user:{id:1,tenant_id:10},authRevision:1,
    replaceAuthForAdvisorSwitch(token,user){this.token=token;this.user=user;this.authRevision++;this.oldTenantCleared=true;}};
  const client=createAdvisorAccountSwitch({session,navigate:path=>navigation.push(path),
    fetchImpl:async(path,options)=>{calls.push({path,options});return {ok:status===200,status,
      json:async()=>path.endsWith('linked-accounts')?{accounts:[{id:2,display_name:'顾问 B',customer_name:'客户 B'}]}:
        {token:'new-token',user:{id:2,tenant_id:20,permissions:{'seo.site':'edit'}}}};}});
  return {client,session,calls,navigation};
}

test('lists linked accounts and replaces the complete session on switch',async()=>{
  const f=fixture();assert.equal((await f.client.list())[0].id,2);
  await f.client.switchTo(2);
  assert.equal(f.session.token,'new-token');assert.equal(f.session.user.tenant_id,20);
  assert.equal(f.session.oldTenantCleared,true);
  assert.deepEqual(f.navigation,['/customer-workbench/?console=advisor']);
  assert.equal(f.calls[1].options.method,'POST');
  assert.equal(JSON.parse(f.calls[1].options.body).target_user_id,2);
  assert.equal(f.calls[1].options.headers.Authorization,'Bearer old-token');
});

test('denied switch leaves the old session intact',async()=>{
  const f=fixture(403);await assert.rejects(()=>f.client.switchTo(2),/SWITCH_DENIED/);
  assert.equal(f.session.token,'old-token');assert.deepEqual(f.navigation,[]);
});

test('response arriving after auth changes cannot replace the new session',async()=>{
  const f=fixture();let release;
  const held=new Promise(resolve=>release=resolve);
  const client=createAdvisorAccountSwitch({session:f.session,navigate:path=>f.navigation.push(path),
    fetchImpl:async()=>{await held;return {ok:true,status:200,json:async()=>({token:'late',user:{id:2,tenant_id:20,permissions:{}}})};}});
  const pending=client.switchTo(2);f.session.authRevision++;release();
  await assert.rejects(()=>pending,/STALE_SESSION/);
  assert.equal(f.session.token,'old-token');assert.deepEqual(f.navigation,[]);
});
