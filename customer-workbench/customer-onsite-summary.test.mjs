import test from 'node:test';
import assert from 'node:assert/strict';
import {customerOnsiteSummary as render} from './js/customer-onsite-summary.mjs';

const options = {month: '2026-10'};
function task(overrides = {}) {
  return {id: 7, module: 'seo', tenant_id: 2, scope_id: 3, title: '优化重点页面',
    workflow: {module: 'seo', month: '2026-10', work_type: 'monthly', phase: 'review', owner_name: '网站维护人',
      source: {keywords: [{keyword: '重点词'}]}}, ...overrides};
}
function list(items = [task()], overrides = {}) {
  return {module: 'seo', tenant_id: 2, scope_id: 3, items, next_before_id: null, can_create: false, ...overrides};
}
function html(data = list(), extra = {}) { return render(data, {...options, ...extra}); }
function withWorkflow(overrides) { const row = task(); Object.assign(row.workflow, overrides); return row; }

test('unread, failure, empty and malformed data remain distinct without echoing errors', () => {
  for (const value of [null, undefined]) assert.match(render(value, options), /尚未读取/);
  for (const value of [new Error('SECRET'), {error: true, message: 'SECRET', items: [task()]}]) {
    assert.match(html(value), /读取失败/); assert.doesNotMatch(html(value), /SECRET|查看任务/);
  }
  assert.match(html(list([])), /列表为空/);
  for (const value of [{}, [], false, {items: null}, list([], {can_create: null})]) {
    assert.match(html(value), /读取结果不完整/); assert.doesNotMatch(html(value), /列表为空/);
  }
});

test('mixed tenants, scopes and modules fail closed for the whole list', () => {
  for (const overrides of [{tenant_id: 99}, {scope_id: 99}, {module: 'geo'}, {workflow: {module: 'geo'}},
    {site_id: 99}, {project_id: 3}, {id: '7" onclick="alert(1)'}, {id: 0}, {workflow: null}]) {
    const result = html(list([task(), task(overrides)]));
    assert.match(result, /数据范围不匹配/); assert.doesNotMatch(result, /优化重点页面|href=/);
  }
  for (const overrides of [{module: 'geo'}, {tenant_id: '2'}, {scope_id: -1}, {site_id: 4}, {project_id: 3}, {next_before_id: 'evil'}]) {
    assert.doesNotMatch(html(list([task()], overrides)), /href=/);
  }
});

test('links carry only fixed module, matching tenant/scope and a validated task id', () => {
  for (const module of ['seo', 'geo']) {
    const row = task({module}); row.workflow.module = module;
    row.url = 'https://evil.test/?token=SECRET';
    const result = html(list([row], {module}), {module});
    const link = new URL(result.match(/href="([^"]+)"/)[1].replaceAll('&amp;', '&'), 'https://workbench.test');
    assert.equal(link.pathname, '/customer-workbench/');
    assert.deepEqual(Object.fromEntries(link.searchParams), {module, tenant_id: '2', [module === 'geo' ? 'project_id' : 'site_id']: '3', onsite_task_id: '7'});
    assert.doesNotMatch(result, /evil|SECRET|<button|data-action=/);
  }
});

test('coverage never treats a page count as a global total, including an empty page', () => {
  for (const items of [[task()], []]) {
    const result = html(list(items, {next_before_id: 6, total: 99999}));
    assert.match(result, /还有更多任务未读取/); assert.match(result, /本月计划可能不完整/);
    assert.match(result, /不是全站或项目任务总数/); assert.doesNotMatch(result, /99999/);
  }
  assert.match(html(), /不据此推断历史分页已全部读取/);
});

test('months are filtered independently of dates and startup/undated tasks are separately marked', () => {
  const rows = [task(), withWorkflow({month: '2026-09'}), withWorkflow({month: '2026-11'}),
    withWorkflow({month: null, work_type: 'startup'}), withWorkflow({month: null}), withWorkflow({month: '2026-13'})];
  rows.forEach((row, i) => { row.id = i + 1; row.title = `计划${i + 1}`; });
  const result = html(list(rows));
  assert.match(result, /已读取 6 条，其中本月 1 条/);
  assert.match(result, /启动建设（不计入本月任务）/); assert.match(result, /月份待核对（不计入本月任务）/);
  assert.match(result, /2 条其他月份任务/); assert.doesNotMatch(result, /计划2|计划3/);
  assert.match(html(list([rows[1]])), /已读取范围内暂无本月任务/);
  for (const month of ['2026-1', '2026-13', '', null, '<script>']) assert.match(html(list(), {month}), /服务月份待核对/);
});

test('true stages, owner, focus and next step appear; completion does not imply performance', () => {
  assert.match(html(), /重点词/); assert.match(html(), /待人工审核/); assert.match(html(), /网站维护人/);
  assert.match(html(), /等待顾问审核当前方案/); assert.match(html(), /月度维护/);
  const result = html(list([withWorkflow({phase: 'done'})]));
  assert.match(result, /交付已验收/); assert.match(result, /交付：已通过人工验收/);
  assert.match(result, /效果观测：收录与排名需另行查看/); assert.match(result, /未提供效果结论/);
  assert.match(html(list([withWorkflow({phase: 'acceptance', recheck: {passed: true}})])), /尚未确认交付完成/);
  assert.match(html(list([withWorkflow({phase: 'cancelled'})])), /未据此认定交付完成/);
});

test('unknown stages/types and absent owner/focus are not invented or taken from prototypes', () => {
  for (const phase of ['future_phase', 'constructor', '__proto__', null]) {
    const result = html(list([withWorkflow({phase, owner_name: '', source: {}, work_type: '__proto__'})]));
    assert.match(result, /阶段待核对/); assert.match(result, /任务类型待核对/);
    assert.match(result, /负责人：尚未提供/); assert.match(result, /重点词 \/ 任务：优化重点页面/);
    assert.doesNotMatch(result, /已通过人工验收|Object|undefined/);
  }
  assert.match(html(list(), {module: 'sem'}), /暂不支持/);
});

test('missing information uses explicit proposal lists without claiming that missing means complete', () => {
  const row = withWorkflow({ai_proposal: {missing_information: ['品牌材料', '品牌材料'],
    items: [{missing_information: '页面说明'}, {missing_information: ['补充证据', null, {}]}]}});
  assert.match(html(list([row])), /待补资料：品牌材料；页面说明；补充证据/);
  assert.match(html(), /未提供待补资料清单，请顾问核对/);
});

test('all external text is escaped, ancillary provider/governance data is never rendered', () => {
  const payload = '<img src=x onerror="alert(1)"> & \'text\'';
  const row = task({title: payload, cost: 'SECRET_COST', api_key: 'SECRET_KEY'});
  Object.assign(row.workflow, {owner_name: payload, source: {keywords: [{keyword: payload}]},
    ai_proposal: {missing_information: [payload]}, provider: 'SECRET_PROVIDER', daily_limit: 'SECRET_LIMIT'});
  const result = html(list([row]));
  assert.doesNotMatch(result, /<img|SECRET_|<button/);
  assert.equal(result.split('&lt;img').length - 1, 4);
  assert.match(result, /&quot;alert\(1\)&quot;/); assert.match(result, /&amp; &#39;text&#39;/);
});

test('GEO uses task focus and AI citation wording without consuming SEO keywords', () => {
  const row = task({module: 'geo'}); row.workflow.module = 'geo';
  const result = html(list([row], {module: 'geo'}), {module: 'geo'});
  assert.match(result, /重点问题 \/ 任务：优化重点页面/); assert.match(result, /AI 引用需另行查看/);
  assert.doesNotMatch(result, /重点词|收录与排名|site_id/);
});

test('rendering leaves the original response intact and is deterministic for an explicit month', () => {
  const data = list(); const before = structuredClone(data);
  assert.equal(html(data), html(data)); assert.deepEqual(data, before);
  assert.match(render(data), /服务月份：[1-9]\d{3}-(0[1-9]|1[0-2])/);
});
