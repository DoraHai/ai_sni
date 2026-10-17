import test from 'node:test';
import assert from 'node:assert/strict';
import {groupLoginAccounts,loginAccountSummary,formatLoginTime} from '../../frontend/src/views/settings/login-account-summary.mjs';
const user=(id,tenant_id,is_active=true,last_login_at=null)=>({id,tenant_id,is_active,last_login_at});
const response={users:[user(1,null),user(2,1,true,'2026-10-17T08:00:00Z'),user(3,1,false,'2026-10-17T10:00:00+02:00'),user(4,1,true,'2026-10-17T11:00:00Z'),user(5,2,true,'2026-10-17T12:00:00Z')]};
test('missing statistics use complete list, strict tenant groups and latest instant; global/other accounts excluded',()=>{
 const groups=groupLoginAccounts(response),summary=loginAccountSummary(undefined,groups,1);
 assert.equal(summary.count,'3 个 · 启用 2');assert.equal(summary.login,'最近登录 2026-10-17 19:00');assert.equal(summary.source,'按账号清单统计');
 assert.equal(loginAccountSummary(null,groups,2).count,'1 个 · 启用 1');assert.equal(loginAccountSummary(null,groups,3).count,'0 个 · 启用 0');
 assert.equal(loginAccountSummary(null,groups,'1').count,'统计未提供');assert.equal(groups.has(null),false);
});
test('server fields win independently, including actual zero and null login; partial missing fields alone use the list',()=>{
 const groups=groupLoginAccounts(response);
 assert.deepEqual(loginAccountSummary({account_count:0,active_count:0,last_login_at:null},groups,1),{count:'0 个 · 启用 0',login:'尚未绑定账号',source:''});
 assert.deepEqual(loginAccountSummary({account_count:0},groups,1),{count:'0 个 · 启用 0',login:'尚未绑定账号',source:''});
 const mixed=loginAccountSummary({account_count:8},groups,1);assert.equal(mixed.count,'8 个 · 启用 2');assert.equal(mixed.source,'部分字段按账号清单统计（其余采用服务端统计）');
 assert.equal(loginAccountSummary({account_count:3,active_count:2,last_login_at:null},groups,1).login,'已绑定账号尚无登录记录');
 assert.equal(loginAccountSummary({account_count:-1},groups,1).count,'统计未提供');
});
test('failed/forbidden, partial, paginated, malformed and duplicate lists cannot manufacture counts',()=>{
 for(const input of [null,{}, {users:null}, {...response,truncated:true},{...response,partial:true},{...response,has_more:true},{...response,next_cursor:'next'},{...response,pagination:{total:10}},{...response,total:99},{...response,state:'forbidden'},
  {users:[user(1,'1')]},{users:[user(1,1),user(1,1)]},{users:[user(1,1,'true')]},{users:[user(1,1,true,'invalid')]},{users:[{id:1,tenant_id:1,is_active:true}]},{users:[user(1,0)]}]) {
  assert.equal(groupLoginAccounts(input),null);assert.equal(loginAccountSummary(null,groupLoginAccounts(input),1).count,'统计未提供');
 }
 assert.equal(loginAccountSummary({account_count:0,active_count:0,last_login_at:null},null,1).count,'0 个 · 启用 0');
});
test('valid complete empty list means actual zero; missing login evidence stays unknown without a complete list',()=>{
 assert.equal(loginAccountSummary(null,groupLoginAccounts({users:[]}),1).login,'尚未绑定账号');
 assert.equal(loginAccountSummary({account_count:2,active_count:1}).login,'最近登录统计未提供');
});

test('login time is fixed Beijing time for UTC naive, Z, offset, microseconds and day/year boundaries',()=>{
 for (const [raw,expected] of [
  ['2026-10-15T17:54:44.858794','2026-10-16 01:54'],
  ['2026-10-15T17:54:44.858794Z','2026-10-16 01:54'],
  ['2026-10-16T01:54:44.858794+08:00','2026-10-16 01:54'],
  ['2026-10-15T12:54:44-0500','2026-10-16 01:54'],
  ['2026-12-31T16:00:00','2027-01-01 00:00'],
  ['2026-10-15T00:00:00Z','2026-10-15 08:00'],
 ]) assert.equal(formatLoginTime(raw),expected);
 for (const raw of [null,undefined,'','  ']) assert.equal(formatLoginTime(raw),'从未登录');
 for (const raw of ['invalid','2026-02-30T12:00:00','2026-13-01T12:00:00','2026-01-01T25:00:00','2026-01-01T12:00:00+99:00',{},123]) assert.equal(formatLoginTime(raw),'未知');
 assert.equal(loginAccountSummary({account_count:1,active_count:1,last_login_at:'bad'}).login,'最近登录统计未提供');
 assert.equal(loginAccountSummary({account_count:1,active_count:1,last_login_at:null}).login,'已绑定账号尚无登录记录');
});
test('latest mixed naive UTC and offset times are compared as instants independently of host timezone',()=>{
 const groups=groupLoginAccounts({users:[user(1,1,true,'2026-10-15T17:00:00'),user(2,1,true,'2026-10-16T00:30:00+08:00')]});
 assert.equal(groups.get(1).last_login_at,'2026-10-15T17:00:00');
 assert.equal(loginAccountSummary(null,groups,1).login,'最近登录 2026-10-16 01:00');
});
