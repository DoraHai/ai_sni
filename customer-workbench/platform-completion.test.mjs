import test from 'node:test';
import assert from 'node:assert/strict';
import {balanceNotifications,readinessRows} from './js/platform-readiness-view.mjs';
import {createPlatformConsoleClient} from './js/platform-console-client.mjs';
import {auditPath,renderAudit} from './js/platform-audit-view.mjs';
const admin={id:7,tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
const snapshot={schema:1,mode:'read_only_inventory',sources:{},costs:{}};
const reply=(data,status=200)=>({ok:status===200,status,json:async()=>data});
const sessions=()=>({user:admin,token:'fixture-token',authRevision:0,refreshUser(u){this.user=u;this.authRevision++;},logout(){this.token='';this.user=null;this.authRevision++;}});
test('low balances require actual recent successful evidence; dated package reminders remain explicit',()=>{
  const now=Date.now(),data={schema:1,state:'available',rows:[{id:'ali',name:'百炼',tenant_id:null,state:'available',warning:'low',queried_at:new Date(now).toISOString()}],observations:{schema:1,state:'available',freshness:'needs_recheck',verified_on:'2026-10-11',packages:[{name:'enabled',enabled:true,expiry_warning:'expiring'},{name:'closed',enabled:false,expiry_warning:'expired'}]}};
  assert.equal(balanceNotifications(data,s=>s,now).length,3);
  for(const change of [d=>d.rows[0].queried_at=new Date(now-400000).toISOString(),d=>d.rows[0].state='error',d=>d.rows[0].queried_at=new Date(now+1000).toISOString()]){
    const copy=structuredClone(data);change(copy);assert.equal(balanceNotifications(copy,s=>s,now).length,2);
  }
  assert.equal(balanceNotifications(null,s=>s).length,0);
});
test('readiness never converts missing configuration or service evidence to zero or completed rollout',()=>{
  const rows=readinessRows({snapshot,automation:{},balances:{rows:[{name:'Kimi',state:'not_configured'}]},balanceError:''});
  assert(rows.some(r=>r[0]==='Kimi 查询'&&r[1]==='缺查询凭据'));
  assert(rows.some(r=>r[0]==='数据库恢复演练'&&r[1]==='仍需隔离恢复演练'));
});
test('audit queries and exports verify fresh global permissions on fixed routes and discard stale downloads',async()=>{
  let user=admin,release;const s=sessions(),calls=[];
  const client=createPlatformConsoleClient({session:s,fetchImpl:async(path,o)=>{
    calls.push({path,o});if(path.endsWith('/me'))return reply({user});
    if(path.includes('/audit/export'))return {ok:true,status:200,headers:new Headers({'Content-Type':'text/csv'}),blob:()=>new Promise(r=>release=r)};
    if(path.includes('/audit'))return reply({schema:1,state:'available',rows:[],next_cursor:null});
    return reply(snapshot);
  }});
  await client.initialize();await client.audit({actor_id:7,action:'user.update'});
  assert(calls.at(-1).path.startsWith('/api/v1/admin/console/audit?'));assert.equal(calls.at(-1).o.cache,'no-store');
  const pending=client.audit({},true);while(!release)await new Promise(r=>setImmediate(r));s.logout();release(new Blob(['private']));
  await assert.rejects(pending,{code:'CONSOLE_STALE'});
  s.token='fixture-token';s.user=admin;await client.initialize();user={...admin,tenant_id:1};const n=calls.length;
  await assert.rejects(client.audit(),{code:'CONSOLE_FORBIDDEN'});assert.equal(calls.length,n+1);
  assert.throws(()=>auditPath({url:'https://other.test'}),{code:'CONSOLE_INVALID_QUERY'});
});
test('audit view escapes metadata and cannot show raw ledger values',()=>{
  const html=renderAudit({state:{filters:{},data:{state:'available',rows:[{id:'<img>',actor_id:7,action:'user.update',resource_kind:'user',recorded_fields:['secret'],after_value:'NEVER_RENDER'}]}},card:(t,b,n)=>t+b+n,table:(h,r)=>r.flat().join('|'),time:()=>'<script>'});
  assert(!html.includes('<img>')&&!html.includes('<script>')&&!html.includes('NEVER_RENDER'));
});
