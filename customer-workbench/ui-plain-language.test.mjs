import {aiPlanView} from './js/seo-ai-plan-view.mjs';
import {onsiteView} from './js/onsite-view.mjs';
import {distributionPlanningMarkup,distributionExecutionMarkup} from './js/distribution-panel.mjs';
import {formatTime} from './js/customer-display.mjs';
import test from 'node:test';import assert from 'node:assert/strict';
import {preparationView} from './js/data-workspace-view.mjs';
import {triggerView} from './js/seo-ai-plan-view.mjs';
import {stateLabel,codeLabel,shortIdentifier} from '../integrations/workbench/ui-labels.mjs';
test('SEO business evidence explains quota failure while raw JSON stays in technical details',()=>{
 const html=preparationView({phases:{a:{state:'needs_attention',blockers:['unknown_a','unknown_b'],as_of:null,facts:{keywords_with_stale_observation:7,latest_ranking_run:{error_summary:'baidu:provider_quota_exceeded'}}}}},{});
 assert.equal((html.match(/需要顾问核对具体原因/g)||[]).length,1);assert.match(html,/服务商额度不足/);assert.match(html,/技术详情/);assert.match(html,/更新时间未提供/);
});
test('trigger denial gives a Chinese next step and an existing field link',()=>{
 const html=triggerView({content:{reason:'service_plan_content_topics_required',allowed:false}},null,false);
 assert.match(html,/请先填写至少一个内容选题/);assert.match(html,/href="#plan-topics"/);assert.doesNotMatch(html,/service_plan_content_topics_required/);
});
test('status and receipt labels are Chinese and identifiers retain an identifiable preview',()=>{
 for(const state of ['active','trial','suspended','disabled','doing'])assert.match(stateLabel(state),/[\u4e00-\u9fff]/);
 assert.equal(stateLabel('paused'),'已暂停');assert.equal(stateLabel('archived'),'已归档');assert.equal(stateLabel('new_status'),'状态待核对');assert.equal(codeLabel('PREFLIGHT_OK'),'发布预检通过');assert.equal(shortIdentifier('a'.repeat(64)),'aaaaaaaa…aaaaaa');
});

test('malformed optional provider error summary does not break business evidence rendering',()=>{
 for(const error_summary of [null,{},42])assert.doesNotThrow(()=>preparationView({phases:{a:{state:'ready',blockers:[],facts:{latest_ranking_run:{error_summary}},as_of:null}}},{}));
});

test('shared missing time stays neutral outside the SEO update label',()=>{assert.equal(formatTime(null),'时间未提供');});

test('handoff and planning summaries shorten identifiers while retaining complete technical evidence',()=>{
 const hash='a'.repeat(64),id='12345678-1234-4567-8123-123456789abc';
 const planning=distributionPlanningMarkup({requests:[],items:[{basis:'rule',state:'planned',planned_at:null,reason:'unknown',draft_version:hash,checked_at:null}]});
 const execution=distributionExecutionMarkup([],{permissions:[],waits:[],items:[{stage:'preflight',status:'succeeded',draft_version:hash,task_id:id}]},[],true);
 for(const html of [planning,execution]){assert.match(html,/aaaaaaaa…aaaaaa/);assert(html.includes(hash));assert.match(html,/<summary>技术详情/);}
 assert(execution.includes('12345678…789abc'));assert(execution.includes(id));
});

test('production-shaped editor and GEO manual workflow mark only unavailable subfeatures',()=>{
 const html=aiPlanView({enabled:false,factIds:[],keywordIds:[],policy:{can_configure:true}},null,null,false,true);
 assert.match(html,/来源维护入口[^]*pending-badge[^]*待启用/);assert.doesNotMatch(html,/pc-pending/);
 const geo=onsiteView({items:[],can_create:false},null,false,'geo');
 assert.match(geo,/官网自动修改[^]*pending-badge[^]*待启用/);assert.doesNotMatch(geo,/pc-pending/);
});
