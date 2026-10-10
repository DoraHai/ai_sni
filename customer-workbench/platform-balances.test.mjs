import test from 'node:test';
import assert from 'node:assert/strict';
import {createPlatformConsoleClient} from './js/platform-console-client.mjs';
import {renderBalances,balanceRoute} from './js/platform-balances-view.mjs';
const admin={id:7,tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
const response=(data,status=200)=>({ok:status===200,status,json:async()=>data});
const fixture=(handler)=>{const session={user:admin,token:'fixture',authRevision:0,refreshUser(u){this.user=u;},logout(){this.token='';}};return {session,client:createPlatformConsoleClient({session,fetchImpl:(p,o)=>p.endsWith('/me')?response({user:admin}):p.endsWith('/snapshot')?response({schema:1,mode:'read_only_inventory',sources:{},costs:{}}):handler(p,o)})};};
test('balance reads use fixed authorized GET with validated pagination and real refresh flag',async()=>{
 const calls=[];const {client}=fixture((p,o)=>{calls.push([p,o]);return response({schema:1,state:'available',rows:[]});});
 await assert.rejects(client.balances(),{status:403});assert.equal(calls.length,0);await client.initialize();
 await client.balances({refresh:true,after_id:10});assert.equal(calls[0][0],balanceRoute+'?refresh=true&after_id=10');assert.equal(calls[0][1].method,'GET');assert.equal(calls[0][1].credentials,'omit');
 for(const options of [{refresh:'true'},{after_id:-1},{after_id:1.1}])await assert.rejects(client.balances(options),{code:'CONSOLE_INVALID_QUERY'});
});
test('403 clears authorization, 404 is unavailable and late balance bodies cannot cross identities',async()=>{
 for(const status of [403,404]){const {client}=fixture(()=>response({},status));await client.initialize();await assert.rejects(client.balances(),{status});if(status===403)assert.equal(client.getIdentity(),null);}
 let release;const {client,session}=fixture(()=>({ok:true,status:200,json:()=>new Promise(r=>release=r)}));await client.initialize();const promise=client.balances();while(!release)await new Promise(r=>setTimeout(r,1));session.token='new';release({schema:1,state:'available',rows:[]});await assert.rejects(promise,{code:'CONSOLE_STALE'});
});
test('balance panel renders real zero, unknown errors and warnings without raw secrets or HTML',()=>{
 const render=state=>renderBalances({state,card:(t,b,n)=>t+b+n,table:(h,r)=>h.join('|')+r.flat().join('|'),time:s=>s||'暂无记录'});
 const html=render({busy:false,cursors:[],data:{rows:[{id:'deepseek',name:'<img src=x>',state:'available',warning:'low',queried_at:'2026-10-10T12:00:00Z',api_key:'private',balances:[{currency:'CNY',available:'0',cash:'0',warning_threshold:'100'}]},{id:'aliyun',name:'阿里云',state:'not_configured',warning:'unknown',balances:[]}]}});
 assert.match(html,/CNY 0/);assert.match(html,/余额不足预警/);assert.match(html,/未配置余额查询凭据/);assert.match(html,/未知/);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img|private/);
 assert.match(render({busy:true,cursors:[],data:null,error:'查询失败'}),/disabled/);
});
