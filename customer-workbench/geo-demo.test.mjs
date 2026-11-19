import test from 'node:test';
import assert from 'node:assert/strict';
import {demoProjection, demoOverview, geoDemoArea, demoEngines, isDemoProject} from './js/geo-project-demo.mjs';
import {readFile} from 'node:fs/promises';
import {createGeoProjectPanel} from './js/geo-project-panel.mjs';
import {geoFixture} from './tests/geo-client-fixture.mjs';
import {demoFixture} from './tests/geo-demo-fixture.mjs';

test('demo has actual counts, separate probe, eight labeled engines, date and per-cell saved IDs', () => {
  const v = demoFixture(), d = demoProjection(v), html = geoDemoArea(v);
  assert.equal(d.saved_sample_count, d.ordinary.sample_count + d.brand_probe.sample_count);
  for (const text of ['GEO 演示概览', '2026-10-20 至 2026-11-18',
    '其他（演示类别）', '混元模型接口类别；不代表元宝产品端实际检测', '普通问题（排除题 85）',
    '样本依据（30 条）', '#10001', '&lt;script&gt;']) assert(html.includes(text), text);
  assert.equal((html.match(/data-demo-engine=/g) || []).length, 7 * demoEngines.length);
  assert(!html.includes('<script>') && !html.includes('真实 API 回答') && !html.includes('合格回答'));
  const filtered = geoDemoArea(v, {kind: 'ordinary', q: '83'});
  assert.equal((filtered.match(/data-demo-engine=/g) || []).length, 8);
  assert(filtered.includes(`实际保存 <strong>${d.saved_sample_count}</strong>`));
});

test('wrong scope and missing/malformed batches have no synthetic fallback', () => {
  assert(!isDemoProject({tenantId: 16, projectId: 3}));
  for (const [tid, pid] of [[16, 3], [15, 4]]) {
    const v = demoFixture(); v.tenant_id = tid; v.project_id = pid;
    assert.equal(geoDemoArea(v), '');
  }
  const mutations = [
    (v) => delete v.data.demo_batch,
    (v) => v.data.demo_batch.batch_token += '-suffix',
    (v) => v.data.demo_batch.basis.simulated = false,
    (v) => v.data.demo_batch.saved_sample_count++,
    (v) => v.data.demo_batch.ordinary.questions[0].by_engine.pop(),
    (v) => v.data.demo_batch.ordinary.questions[0].by_engine[0].samples.pop(),
    (v) => v.data.demo_batch.ordinary.questions[0].by_engine[0].samples[0].captured_at = 'broken',
    (v) => v.data.demo_batch.ordinary.questions[0].by_engine[0].mentioned_count++,
  ];
  for (const mutate of mutations) {
    const v = demoFixture(); mutate(v);
    const html = geoDemoArea(v);
    assert(html.includes('演示批次不可用') && !html.includes('data-demo-engine'));
  }
  const v = demoFixture();
  v.data.demo_batch.brand_probe = {status: 'unavailable', reason_code: 'brand_probe_conflict'};
  const html = geoDemoArea(v);
  assert(html.includes('品牌点名标记冲突') && (html.match(/data-demo-engine/g) || []).length === 48);
});

test('target full workspace reuses saved demo counts, preserves filters and clears on context loss', async () => {
  let context = {connected: true, tenantId: 15, projectId: 3, userId: 7, revision: 1};
  const host = {getContext: () => context, transport: async (url) => {
    const r = url.includes('/client/') ? url.split('/client/')[1].split('?')[0] : 'executions';
    const v = structuredClone(geoFixture(r));
    if (r === 'executions') v.project_id = 3;
    else { v.tenant_id = 15; v.project_id = 3; }
    if (r === 'overview') v.data.demo_batch = demoFixture().data.demo_batch;
    return {ok: true, json: async () => v};
  }};
  const panel = createGeoProjectPanel({host}), node = {innerHTML: ''};
  panel.renderInto(node); await panel.refresh();
  assert(node.innerHTML.includes('data-demo-engine'));
  assert(!node.innerHTML.includes('暂不可计算') && !node.innerHTML.includes('data-geo-questions'));
  const mode = {dataset: {geo: 'mode', view: 'formal'}, disabled: false};
  await node.onclick({target: {closest: () => mode}});
  assert(node.innerHTML.includes('本期要点') && node.innerHTML.includes('GEO 优化概览'));
  assert(node.innerHTML.includes('AI 提及率') && !node.innerHTML.includes('geo-demo-charts'));
  const tabs = node.innerHTML.match(/<nav class="geo-tabs"[^>]*>.*?<\/nav>/)?.[0];
  assert(tabs && !tabs.includes('data-tab="plan"') && !tabs.includes('data-all-questions'));
  assert(!node.innerHTML.includes('数据范围与依据'));
  const button = {dataset: {geo: 'read', resource: 'questions'}, disabled: false};
  await node.onclick({target: {closest: () => button}});
  assert(node.innerHTML.includes('data-geo-questions') && node.innerHTML.includes('样本依据') && node.innerHTML.includes('data-demo-engine'));
  assert(!node.innerHTML.includes('正式六引擎'));
  context = {...context, tenantId: 16}; panel.reset();
  assert(!node.innerHTML.includes('data-demo-engine') && !node.innerHTML.includes('geo-demo-t15'));
  panel.dispose();
});

test('daily/model aggregation uses saved flags once, Shanghai dates and independent probe', () => {
  const v = demoFixture({mention: ({qid, engineIndex, day}) => qid === 85 ? true :
    engineIndex === 0 && day === 0 ? true : day === 1 ? null : false});
  const d = demoOverview(v), g = d.ordinary;
  const questionCount = v.data.demo_batch.ordinary.questions.length;
  assert.equal(g.mentioned_count, questionCount);
  assert.equal(g.daily[0].date, d.period.start_date); // 16:00 UTC is next day in Beijing
  assert.equal(g.daily.at(-1).date, d.period.end_date);
  assert.equal(g.daily[0].mentioned_count, questionCount);
  assert.equal(g.daily[1].unknown_mention_count, g.daily[1].sample_count);
  assert.equal(g.daily[1].mention_rate, 0); // unknown stays in denominator
  assert.equal(g.engines[0].mentioned_count, questionCount);
  assert(g.engines.slice(1).every((e) => e.mentioned_count === 0));
  for (const rows of [g.daily, g.engines]) {
    for (const key of ['sample_count', 'mentioned_count', 'unknown_mention_count'])
      assert.equal(rows.reduce((n, r) => n + r[key], 0), g[key]);
  }
  assert.equal(g.mention_rate, 100 * g.mentioned_count / g.sample_count);
  assert.equal(d.brand_probe.mention_rate, 100);
  const changed = demoFixture({mention: ({qid, engineIndex, day}) => qid === 85 ? false :
    engineIndex === 0 && day === 0 ? true : day === 1 ? null : false});
  assert.deepEqual(demoOverview(changed).ordinary, g);
  const cells = changed.data.demo_batch.ordinary.questions[0].by_engine;
  cells.forEach((c) => c.samples.reverse());
  assert.deepEqual(demoOverview(changed).ordinary, g);
});

test('legitimate all-zero/all-unknown charts, selected date, collapsed details and missing groups', () => {
  for (const flag of [false, null]) {
    const v = demoFixture({mention: () => flag}), d = demoOverview(v);
    assert(d.ordinary.daily.every((r) => r.mention_rate === 0));
    assert(d.ordinary.engines.every((r) => r.mention_rate === 0));
    assert.equal(d.ordinary.unknown_mention_count, flag === null ? d.ordinary.sample_count : 0);
  }
  const v = demoFixture(), d = demoOverview(v);
  const html = geoDemoArea(v, {}, {selectedDay: d.ordinary.daily[0].date});
  assert.match(html, /data-geo-demo-details\s*>/);
  assert(html.includes(`value="${d.ordinary.daily[0].date}" selected`));
  assert(!html.includes('暂不可计算'));
  v.data.demo_batch.ordinary = {status: 'unavailable', reason_code: 'brand_probe_conflict'};
  const partial = geoDemoArea(v);
  assert(partial.includes('品牌点名题 85') && !partial.includes('data-demo-comparison'));
});

test('production demo code has no observed count/rate literals or fixture imports', async () => {
  const code = await readFile(new URL('./js/geo-project-demo.mjs', import.meta.url), 'utf8');
  assert(!/(^|[^\w.])(?:1680|1440|240|922|221|64\.0|92\.1|30)(?![\w.])/.test(code));
  assert(!/import .*fixture/i.test(code));
});


test('workspace model table filters on existing business and unit mapping, retains IDs and week grid', async () => {
  const {demoWorkspaceQuestions} = await import('./js/geo-project-demo-workspace.mjs');
  const {geoBasis} = await import('./js/geo-project-view.mjs');
  const v = demoFixture();
  const data = {options: {businesses: [{id: 2, name: '业务甲'}, {id: 3, name: '业务乙'}],
    units: [{id: 20, business_id: 2, display_name: '关键词甲'}, {id: 19, business_id: 3, display_name: '关键词乙'}]}};
  const all = demoWorkspaceQuestions(v, data);
  assert.equal((all.match(/data-demo-engine=/g) || []).length, 56);
  assert(all.includes('业务甲') && all.includes('关键词甲') && all.includes('#10001'));
  assert.equal((demoWorkspaceQuestions(v, data, {business_id: '2'}).match(/data-demo-engine=/g) || []).length, 16);
  assert.equal((demoWorkspaceQuestions(v, data, {business_id: '2', unit_id: '19'}).match(/data-demo-engine=/g) || []).length, 0);
  assert.equal((demoWorkspaceQuestions(v, data, {q: '83'}).match(/data-demo-engine=/g) || []).length, 8);
  assert.equal((demoWorkspaceQuestions(v, data, {}, 85).match(/data-demo-engine=/g) || []).length, 8);
  for (const g of [v.data.demo_batch.ordinary, v.data.demo_batch.brand_probe])
    for (const q of g.questions) for (const c of q.by_engine)
      assert.equal(c.samples.filter((s) => s.captured_at >= '2026-11-08T16:00:00.000Z' && s.captured_at < '2026-11-15T16:00:00.000Z').length, 7);
  const basis = geoFixture('overview');
  assert(geoBasis(basis).includes('数据范围与依据'));
  basis.tenant_id = 15; basis.project_id = 3;
  assert.equal(geoBasis(basis), '');
  basis.project_id = 4;
  assert(geoBasis(basis).includes('数据范围与依据'));
});
