import test from 'node:test';
import assert from 'node:assert/strict';
import {homeView} from './js/home-view.mjs';
import {roleDescription} from '../integrations/workbench/role-description.mjs';
import {loginAccountSummary} from '../frontend/src/views/settings/login-account-summary.mjs';
const data=(total=40)=>({contents:{items:[],total},deliveries:[],failed:0,readAt:null});
test('partial homepage never presents sampled zero as no pending work',()=>{
 const html=homeView(data());assert.match(html,/已查看 0\/40 篇/);assert.match(html,/查看全部待确认稿件/);assert.doesNotMatch(html,/没有可由您确认|待确认 0|0 篇可由当前身份确认/);
 const complete=homeView(data(0));assert.match(complete,/待当前身份确认 0 篇/);
 const failed=data(0);failed.failed=1;assert.doesNotMatch(homeView(failed),/已核对全部稿件/);
});
test('missing login stats stay unknown; actual zero and never logged in remain distinct',()=>{
 for(const input of [null,{}, {account_count:1},{account_count:0,active_count:2}])assert.equal(loginAccountSummary(input).count,'统计未提供');
 assert.equal(loginAccountSummary({account_count:0,active_count:0}).login,'尚未绑定账号');
 assert.equal(loginAccountSummary({account_count:2,active_count:1}).login,'最近登录统计未提供');
 assert.equal(loginAccountSummary({account_count:2,active_count:1,last_login_at:null}).login,'已绑定账号尚无登录记录');
 assert.match(loginAccountSummary({account_count:2,active_count:1,last_login_at:'2026-10-17T08:00:00Z'}).login,/2026-10-17/);
});
test('brand role description follows actual editable keys without changing permissions',()=>{
 const role={name:'品牌方客户',description:'只读',permissions:{'sem.assets':'edit','seo.assets':'edit','geo.assets':'edit','seo.content':'view'}};
 const before=JSON.stringify(role);assert.match(roleDescription(role),/可编辑：推广账号、网站管理、项目管理/);assert.equal(JSON.stringify(role),before);
 role.permissions={'seo.content':'edit'};assert.match(roleDescription(role,[{key:'seo.content',label:'内容创作'}]),/可编辑：内容创作/);
});
