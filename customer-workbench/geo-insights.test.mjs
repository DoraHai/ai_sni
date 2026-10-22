import test from 'node:test';
import assert from 'node:assert/strict';
import {createGeoProjectClient} from './js/geo-project-client.mjs';
import {createGeoProjectPanel} from './js/geo-project-panel.mjs';
import {geoClientRoute, geoClientQuery} from './js/geo-client-routes.mjs';
import {geoResource} from './js/geo-project-view.mjs';
import {geoMatrix} from './js/geo-project-insights.mjs';
import {geoFixture, question} from './tests/geo-client-fixture.mjs';

const context = {connected: true, tenantId: 1, projectId: 10, userId: 7, revision: 1};
const response = (v, status = 200) => new Response(JSON.stringify(v), {status});
const allowed = (resource, query = '') => {
  const u = new URL(`/api/v1/geo/projects/10/client/${resource}?tenant_id=1${query}`, 'https://fixture.test');
  const r = geoClientRoute(u.pathname);
  return r && geoClientQuery(u, r, context);
};
test('new exact read routes accept contracted filters and deny arbitrary export/scope parameters', () => {
  for (const r of ['summary', 'article-citations', 'recommendations', 'reports/export.pdf', 'reports/export.xlsx']) assert(allowed(r));
  assert(allowed('questions', '&business_id=2&unit_id=4&q=选择&status=all&limit=100'));
  for (const q of ['&project_id=11', '&date_start=2026-01-01', '&engine_key=hunyuan', '&cursor=old', '&week_end=2026-10-19&week_end=2026-10-12'])
    assert.equal(allowed('reports/export.pdf', q), false);
  for (const q of ['&business_id=0', '&unit_id=-1', '&unit_id=2&unit_id=3']) assert.equal(allowed('questions', q), false);
  assert.equal(allowed('recommendations', '&week_end=2026-10-19'), false);
  for (const r of ['reports/export.csv', 'reports/export.pdf/retry', 'summary/rebuild']) assert(!allowed(r));
});
test('four summary values respect qualification, actual zeros, position and annotation sample counts', () => {
  const v = structuredClone(geoFixture('summary', {ready: true}));
  let html = geoResource('summary', v);
  for (const text of ['品牌提及率', '品牌提及回答数', '平均推荐位置', '品牌正向评价率', '1.5', '有效位置 2', '已标注 2 / 提及 4', '元宝数据取自腾讯混元模型接口']) assert(html.includes(text));
  v.data.metrics.brand_mention_rate = 0;
  assert.match(geoResource('summary', v), />0%/);
  v.data.sample_status = 'insufficient';
  html = geoResource('summary', v);
  assert(!html.includes('0%'));
  v.data.sample_status = 'ready';
  v.data.metrics.sample_count = 0;
  v.data.metrics.valid_position_count = 0;
  v.data.metrics.annotated_mention_count = 0;
  assert(!geoResource('summary', v).includes('0%'));
});
test('matrix keeps fixed domestic order, distinct missing states, X/Y, percentage, time and small samples', () => {
  const html = geoMatrix({...question, by_engine: [
    {engine_key: 'doubao', mentioned: 1, total: 2, percentage: 50, last_sample_at: 'saved-time', status: 'small_sample'},
    {engine_key: 'qwen', mentioned: 0, total: 3, percentage: 0, status: 'observed'},
    {engine_key: 'hunyuan', mentioned: 0, total: 0, percentage: 0, status: 'not_tested'},
    {engine_key: 'wenxin', status: 'not_configured'}, {engine_key: 'kimi', status: 'failed'},
  ]}, (t) => t);
  let index = -1;
  for (const name of ['豆包', 'DeepSeek', '千问', '元宝', '文心', 'Kimi']) {
    assert(html.indexOf(`<b>${name}</b>`) > index); index = html.indexOf(`<b>${name}</b>`);
  }
  for (const text of ['1/2 · 50%', '0/3 · 0%', '小样本', 'saved-time', '未检测', '未配置', '检测失败']) assert(html.includes(text));
  assert(!html.includes('0/0'));
});
test('article evidence is generated from authorized answer ID; links and suggestions are escaped', () => {
  const v = structuredClone(geoFixture('article-citations'));
  v.data.items[0].title = '<img src=x onerror=bad>';
  const html = geoResource('article-citations', v);
  assert.match(html, /1\/2 · 50%/);
  assert.match(html, /data-resource="answers\/5"/);
  assert(!html.includes('must-not-follow'));
  assert(!html.includes('<img'));
  v.data.coverage.status = 'insufficient_evidence';
  v.data.items[0].status = 'not_tested';
  v.data.items[0].percentage = 0;
  assert(!geoResource('article-citations', v).includes('0%'));
  assert.match(geoResource('recommendations', geoFixture('recommendations')), /建议与依据：已有检查记录缺少 FAQ 结构/);
});
test('binary reports validate type and recheck context after bytes finish, without trusting filenames', async () => {
  let ctx = {...context}, release;
  const c = createGeoProjectClient({getContext: () => ctx, transport: async () => ({ok: true,
    headers: new Headers({'content-type': 'application/pdf', 'content-disposition': 'attachment; filename="unsafe.html"'}),
    arrayBuffer: () => new Promise((r) => { release = r; }),
  })});
  const pending = c.read('reports/export.pdf', {week_end: '2026-10-19'});
  await Promise.resolve();
  ctx = {...ctx, projectId: 11};
  release(new ArrayBuffer(10));
  await assert.rejects(pending, /CONTEXT_CHANGED/);
  const invalid = createGeoProjectClient({getContext: () => context,
    transport: async () => new Response('<html>error</html>', {headers: {'content-type': 'text/html'}})});
  await assert.rejects(invalid.read('reports/export.pdf'), /RESPONSE_INVALID/);
  const valid = createGeoProjectClient({getContext: () => context,
    transport: async () => new Response('%PDF-synthetic', {headers: {'content-type': 'application/pdf'}})});
  assert.equal((await valid.read('reports/export.pdf')).filename, 'GEO-10-closed-week.pdf');
});
test('filtered pagination preserves server filters to the last page, then permission failure clears all cached data', async () => {
  const node = {innerHTML: ''}, calls = [];
  let deny = false;
  const panel = createGeoProjectPanel({host: {getContext: () => context, transport: async (path) => {
    const u = new URL(path, 'https://fixture.test');
    const r = u.pathname.endsWith('executions') ? 'executions' : u.pathname.split('/client/')[1];
    calls.push(u);
    if (deny) return response({}, 403);
    const v = structuredClone(geoFixture(r, {more: r === 'questions' && !u.searchParams.has('cursor')}));
    if (r === 'questions') v.data.items[0].question = u.searchParams.has('cursor') ? '最后一页' : '第一条合成问题';
    return response(v);
  }}});
  const click = (dataset) => node.onclick({target: {closest: () => ({dataset})}});
  panel.renderInto(node);
  await panel.refresh();
  await click({geo: 'tab', tab: 'data'});
  await node.onsubmit({preventDefault() {}, target: {matches: (selector) => selector === '[data-geo-questions]', elements: {
    business_id: {value: '2'}, unit_id: {value: '4'}, q: {value: '  设备  '},
  }}});
  await click({geo: 'more'});
  const last = calls.at(-1);
  for (const [k, v] of Object.entries({business_id: '2', unit_id: '4', q: '设备', week_end: '2026-10-19', cursor: 'opaque-fixture-cursor'}))
    assert.equal(last.searchParams.get(k), v);
  assert.match(node.innerHTML, /最后一页/);
  assert(!node.innerHTML.includes('data-geo="more"'));
  deny = true;
  await click({geo: 'read', resource: 'answers/5'});
  await click({geo: 'tab', tab: 'data'});
  assert(!node.innerHTML.includes('第一条合成问题'));
  assert(!node.innerHTML.includes('最后一页'));
  assert(!node.innerHTML.includes('有效位置 2'));
  panel.dispose();
});
