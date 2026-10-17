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
 assert.equal(stateLabel('new_status'),'状态待核对');assert.equal(codeLabel('PREFLIGHT_OK'),'发布预检通过');assert.equal(shortIdentifier('a'.repeat(64)),'aaaaaaaa…aaaaaa');
});
