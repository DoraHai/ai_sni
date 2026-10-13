import test from 'node:test';
import assert from 'node:assert/strict';
import {createPlatformConsoleClient} from './js/platform-console-client.mjs';
import {renderBalances,renderCoverage,renderObservations,balanceRoute} from './js/platform-balances-view.mjs';
import {billingObservations} from './tests/platform-billing-fixture.mjs';
const admin={id:7,tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
const response=(data,status=200)=>({ok:status===200,status,json:async()=>data});
const fixture=(handler)=>{const session={user:admin,token:'fixture',authRevision:0,refreshUser(u){this.user=u;},logout(){this.token='';}};return {session,client:createPlatformConsoleClient({session,fetchImpl:(p,o)=>p.endsWith('/me')?response({user:admin}):p.endsWith('/snapshot')?response({schema:1,mode:'read_only_inventory',sources:{},costs:{}}):handler(p,o)})};};
test('balance reads use fixed authorized GET with validated pagination and real refresh flag',async()=>{
 const calls=[];const {client}=fixture((p,o)=>{calls.push([p,o]);return response({schema:1,state:'available',rows:[]});});
 await assert.rejects(client.balances(),{status:403});assert.equal(calls.length,0);await client.initialize();
 await client.balances({refresh:true,after_id:10});assert.equal(calls[0][0],balanceRoute+'?refresh=true&after_id=10');assert.equal(calls[0][1].method,'GET');assert.equal(calls[0][1].credentials,'omit');
 for(const options of [{refresh:'true'},{after_id:-1},{after_id:1.1}])await assert.rejects(client.balances(options),{code:'CONSOLE_INVALID_QUERY'});
});

test('coverage separates supported services, observed configuration and live supplier results',()=>{
 const card=(t,b,n)=>t+b+n,table=(h,r)=>h.join('|')+r.flat().join('|'),time=s=>s||'暂无记录';
 const coverage={state:'schema_pending',rows:[
  {id:'sem.deepseek',connection_id:'sem.deepseek',module:'sem',name:'DeepSeek',configured:true,configuration_source:'sem_runtime',capability:'direct',balance_row_id:'deepseek'},
  {id:'seo.chinaz.sogou_pc_keywords_api_key',module:'seo',name:'站长 / 搜狗 PC',configured:null,capability:'package',note:'套餐查询接口待确认',secrets:{api_key:'PRIVATE'}},
  {id:'geo.geo_kimi',module:'geo',name:'Kimi <img src=x>',configured:true,enabled:false,configuration_source:'service_registry',capability:'direct'},
  {id:'geo.geo_qwen',module:'geo',name:'通义千问',configured:null,capability:'billing_authorization'}]};
 const html=renderCoverage({coverage,rows:[{id:'deepseek',state:'available',balances:[{currency:'CNY',available:'0'}]}],card,table,time});
 for(const term of ['SEM','SEO','GEO','站长 / 搜狗 PC','配置待核对','剩余次数 / 到期日','CNY 0','账务授权待接入','已停用，未查询','金额不汇总相加'])assert(html.includes(term),term);
 assert.match(html,/&lt;img/);assert.doesNotMatch(html,/PRIVATE|<img/);
 const absent=renderCoverage({coverage:null,rows:[],card,table,time});assert.match(absent,/尚未提供全部服务覆盖清单/);
 const failed=renderBalances({state:{error:'查询失败',data:{coverage,rows:[]},cursors:[]},card,table,time});assert.doesNotMatch(failed,/站长 \/ 搜狗/);
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
test('historical amounts and manual quotas never masquerade as live query success',()=>{
 const card=(t,b,n)=>t+b+n,table=(h,r)=>h.join('|')+r.flat().join('|'),time=s=>s||'暂无记录';
 const o=structuredClone(billingObservations);o.freshness='needs_recheck';o.api_key='PRIVATE';o.packages[0].name='<img src=x>';
 const html=renderObservations({observations:o,card,table});
 for(const term of ['2026-10-11','需重新核对','2027-09-01','247','250','核验时余量正常','核验时已耗尽','已关闭','核验账号未开通','不代表当前接口已配置','不会更新这些余量'])assert(html.includes(term),term);
 assert.doesNotMatch(html,/余量低|PRIVATE|<img/);assert.match(html,/&lt;img/);
 const unavailable=renderBalances({state:{cursors:[],data:{rows:[{id:'tencent',name:'腾讯云',state:'permission_denied',warning:'unknown',balances:[]}],observations:o}},card,table,time});
 assert.match(unavailable,/查询授权不足/);assert.match(unavailable,/未取得余额/);assert.match(unavailable,/CNY 20.00/);
 assert.doesNotMatch(unavailable,/余额不足预警/);
});
test('returned cash, grants, credits and frozen amounts remain distinct',()=>{
 const html=renderBalances({state:{cursors:[],data:{rows:[{id:'tencent',name:'腾讯云',billing_account_id:'fixture-account',state:'available',warning:'normal',balances:[{currency:'CNY',available:'20',cash:'10',grant:'10',credit:'100',frozen:'2',arrears:'0'}]},
 {id:'qianfan',name:'千帆',state:'available',balances:[{currency:'CNY',available:'25',cash:'25',balance_kind:'cash'}]}]}},card:(t,b,n)=>t+b+n,table:(h,r)=>h.join('|')+r.flat().join('|'),time:s=>s||'暂无记录'});
 for(const term of ['账务账号 fixture-account','赠额 / 代金券 CNY 10','信用额度 CNY 100','冻结 CNY 2','现金账户余额'])assert(html.includes(term),term);
});
