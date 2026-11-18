import test from 'node:test';
import assert from 'node:assert/strict';
import {demoProjection, geoDemoArea, demoEngines, isDemoProject} from './js/geo-project-demo.mjs';
import {createGeoProjectPanel} from './js/geo-project-panel.mjs';
import {geoFixture} from './tests/geo-client-fixture.mjs';
import {demoFixture} from './tests/geo-demo-fixture.mjs';

test('demo has actual counts, separate probe, eight labeled engines, date and per-cell saved IDs', () => {
  const v = demoFixture(), d = demoProjection(v), html = geoDemoArea(v);
  assert.equal(d.saved_sample_count, d.ordinary.sample_count + d.brand_probe.sample_count);
  for (const text of ['演示数据，不代表真实引擎检测或实际效果', '2026-10-20 至 2026-11-18',
    '其他（演示类别）', '混元模型接口类别；不代表元宝产品端实际检测', '普通问题（排除题 85）',
    '模拟样本依据（30 条）', '#10001', '&lt;script&gt;']) assert(html.includes(text), text);
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

test('panel keeps formal six-engine table, filters and evidence and clears demo on context loss', async () => {
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
  const button = {dataset: {geo: 'read', resource: 'questions'}, disabled: false};
  await node.onclick({target: {closest: () => button}});
  assert(node.innerHTML.includes('正式六引擎') && node.innerHTML.includes('data-geo-questions') &&
    node.innerHTML.includes('样本依据') && node.innerHTML.includes('data-demo-engine'));
  context = {...context, tenantId: 16}; panel.reset();
  assert(!node.innerHTML.includes('data-demo-engine') && !node.innerHTML.includes('geo-demo-t15'));
  panel.dispose();
});
