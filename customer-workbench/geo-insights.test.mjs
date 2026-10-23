import test from 'node:test';
import assert from 'node:assert/strict';
import {createGeoProjectClient} from './js/geo-project-client.mjs';
import {createGeoProjectPanel} from './js/geo-project-panel.mjs';
import {geoClientRoute, geoClientQuery} from './js/geo-client-routes.mjs';
import {geoResource, geoHome, geoBasis, geoWeekly, geoTime} from './js/geo-project-view.mjs';
import {geoMatrix, geoQuestionTable, geoQuestionFilters, geoExcludedReason} from './js/geo-project-insights.mjs';
import {geoPeriod, geoOpenWeekProgress, geoQuestionOpenWeek} from './js/geo-project-display.mjs';
import {geoFixture, question} from './tests/geo-client-fixture.mjs';

const context = {connected: true, tenantId: 1, projectId: 10, userId: 7, revision: 1};
const response = (v, status = 200) => new Response(JSON.stringify(v), {status});
const allowed = (resource, query = '') => {
  const u = new URL(`/api/v1/geo/projects/10/client/${resource}?tenant_id=1${query}`, 'https://fixture.test');
  const r = geoClientRoute(u.pathname);
  return r && geoClientQuery(u, r, context);
};
test('flat question rows preserve six canonical columns, observed zero, missing samples and escaped labels', () => {
  const q = {...question, question: '<img src=x>', business: {name: '<script>bad</script>'},
    by_engine: [
      {engine_key: 'qwen', mentioned: 1, total: 2, percentage: 50, status: 'small_sample'},
      {engine_key: 'hunyuan', mentioned: 0, total: 3, percentage: 0, status: 'observed'},
      {engine_key: 'wenxin', mentioned: 0, total: 0, percentage: 0, status: 'observed'},
    ]};
  const html = geoQuestionTable({items: [q]}, geoTime);
  assert.equal((html.match(/scope="col"/g) || []).length, 9);
  assert.equal((html.match(/scope="row"/g) || []).length, 1);
  for (const value of ['1/2 · 50%', '0/3 · 0%', '未检测', '小样本', 'data-engine="hunyuan"', 'data-resource="questions/3"'])
    assert(html.includes(value), value);
  assert(!html.includes('0/0') && !html.includes('<img') && !html.includes('<script>'));
  assert.match(html, /data-engine="wenxin"><strong>未检测<\/strong>/);
  const noSamples = geoQuestionTable({items: [{...question, by_engine: []}]}, geoTime);
  assert.equal((noSamples.match(/<strong>未检测<\/strong>/g) || []).length, 6);
  assert(!noSamples.includes('0%'));
  assert.match(geoQuestionTable({items: []}, geoTime), /colspan="9"/);
});
test('combined filter keeps all keyword choices available when changing business and caps search at backend limit', () => {
  const html = geoQuestionFilters({options: {businesses: [], units: [
    {id: 4, business_id: 2, keyword: '设备'}, {id: 5, business_id: 3, keyword: '服务'},
  ]}}, {business_id: 2, unit_id: 4, q: '<设备>'});
  assert.match(html, /value="4"  selected/);
  assert.match(html, /value="5" hidden/);
  assert.match(html, /maxlength="100"/);
  assert(!html.includes('value="<设备>"'));
});
test('period dates use Beijing dates and an inclusive last day across month/year and UTC boundaries', () => {
  for (const [start, end, expected] of [
    ['2026-10-12T00:00:00+08:00', '2026-10-19T00:00:00+08:00', '2026-10-12 至 2026-10-18'],
    ['2026-09-28T00:00:00+08:00', '2026-10-05T00:00:00+08:00', '2026-09-28 至 2026-10-04'],
    ['2025-12-29T00:00:00+08:00', '2026-01-05T00:00:00+08:00', '2025-12-29 至 2026-01-04'],
    ['2026-10-11T16:00:00Z', '2026-10-18T16:00:00Z', '2026-10-12 至 2026-10-18'],
    ['2024-02-26T00:00:00+08:00', '2024-03-04T00:00:00+08:00', '2024-02-26 至 2024-03-03'],
  ]) assert.equal(geoPeriod({start, end}), `统计周期：${expected}（北京时间）`);
  for (const p of [undefined, {}, {start: 'bad', end: '2026-10-19'}, {start: '2026-10-19', end: '2026-10-12'}])
    assert.equal(geoPeriod(p), '统计周期：暂无');
});
test('all GEO period displays use the same customer-facing inclusive dates', () => {
  const overview = geoFixture('overview'), visibility = geoFixture('visibility');
  for (const html of [geoBasis(overview), geoWeekly(overview.data.weekly), geoResource('visibility', visibility),
    geoResource('summary', geoFixture('summary')), geoHome({overview: {value: overview}, visibility: {value: visibility}})]) {
    assert.match(html, /统计周期：2026-10-12 至 2026-10-18（北京时间）/);
    assert(!html.includes('右端不含') && !html.includes('上海时区已结束完整周'));
    assert(!html.includes('2026-10-12T') && !html.includes('2026-10-19T'));
  }
});
test('open-week progress handles zero/missing/malformed counts without changing formal metrics', () => {
  assert.equal(geoOpenWeekProgress({detected_answer_count: 0}), '<p class="geo-open-week">本周（未结束）暂未检测</p>');
  for (const n of [undefined, null, -1, 0.5, '26', '<img>', NaN, Infinity]) {
    assert.equal(geoOpenWeekProgress({detected_answer_count: n}), '');
    assert.equal(geoQuestionOpenWeek(n), '');
  }
  assert.equal(geoOpenWeekProgress(), '');
  assert.equal(geoQuestionOpenWeek(0), '');
  const overview = structuredClone(geoFixture('overview'));
  const home = () => geoHome({overview: {value: overview}});
  assert.match(home(), /本周（未结束）已检测 26 条，下周一计入正式指标/);
  assert.match(home(), /检测数据还不够/);
  assert(!home().includes('0%'));
  delete overview.data.open_week_progress;
  assert(!home().includes('geo-open-week'));
  assert.match(geoHome({overview: {value: overview}, visibility: {value: geoFixture('visibility')}}), /已检测 26 条/);
  for (const resource of ['visibility', 'summary', 'questions', 'questions/3']) {
    const value = structuredClone(geoFixture(resource));
    const formalData = structuredClone(value.data);
    assert.match(geoResource(resource, value), /本周（未结束）已检测 26 条，下周一计入正式指标/);
    assert.deepEqual(value.data, formalData);
    value.data.open_week_progress.detected_answer_count = 0;
    assert.match(geoResource(resource, value), /本周（未结束）暂未检测/);
    delete value.data.open_week_progress;
    if (value.data.question) delete value.data.question.open_week_detected_count;
    for (const q of value.data.items || []) delete q.open_week_detected_count;
    assert(!geoResource(resource, value).includes('本周（未结束）'));
  }
});
test('tested_excluded renders every contracted reason, saved time and no percentage', () => {
  const cases = {
    engine_source_untrusted: '平台来源未核实', analysis_incomplete: '回答判读未完成',
    unsupported_sampling_method: '采样方式不符合正式口径', simulated_sample: '模拟样本',
    manual_sample: '人工登记样本', unknown_source: '来源未知', missing_server_evidence: '缺少巡检记录',
    snapshot_patrol_mismatch: '回答与巡检记录不一致', patrol_not_completed: '巡检未完成',
    capture_outside_patrol: '采样时间不在巡检内', brand_probe: '品牌点名题', citation_inaccurate: '引用不准确',
    unknown_capture_time: '采样时间未知', snapshot_unavailable: '回答记录不可读',
  };
  for (const [code, expected] of Object.entries(cases)) assert.equal(geoExcludedReason(code), expected);
  for (const code of ['new_backend_code', '<img src=x>', 'constructor', '__proto__'])
    assert.equal(geoExcludedReason(code), '不符合正式统计条件');
  const q = {...question, by_engine: [{engine_key: 'hunyuan', status: 'tested_excluded', mentioned: 0,
    total: 0, percentage: 0, last_sample_at: '2026-10-15T02:00:00Z',
    excluded_reason_codes: ['engine_source_untrusted', 'analysis_incomplete', '<img src=x>']}]};
  let html = geoMatrix(q, geoTime);
  assert.match(html, /已检测，未计入/);
  assert.match(html, /平台来源未核实；回答判读未完成；不符合正式统计条件/);
  assert.match(html, /样本时间：2026年10月15日 10:00/);
  assert(!html.includes('0%') && !html.includes('0/0') && !html.includes('<img'));
  assert(html.indexOf('geo-question-open-week') < html.indexOf('geo-matrix'));
  q.by_engine[0].status = 'not_tested';
  html = geoMatrix(q, geoTime);
  assert(!html.includes('平台来源未核实'));
});
test('new and legacy resource payloads pass the same tenant/project guard', async () => {
  for (const resource of ['overview', 'visibility', 'summary', 'questions', 'questions/3']) {
    for (const legacy of [false, true]) {
      const value = structuredClone(geoFixture(resource));
      const questions = resource === 'questions' ? value.data.items : value.data.question ? [value.data.question] : [];
      for (const q of questions) {
        q.by_engine = [{engine_key: 'doubao', status: 'tested_excluded', excluded_reason_codes: ['analysis_incomplete'],
          mentioned: 0, total: 0, percentage: null, last_sample_at: '2026-10-15T02:00:00Z'}];
        if (legacy) { delete q.open_week_detected_count; delete q.by_engine; }
      }
      if (legacy) delete value.data.open_week_progress;
      const client = createGeoProjectClient({getContext: () => context, transport: async () => response(value)});
      assert.deepEqual(await client.read(resource), value);
      if (resource !== 'overview') assert.doesNotThrow(() => geoResource(resource, value));
      value.tenant_id = 2;
      await assert.rejects(client.read(resource), /GEO_RESPONSE_INVALID/);
      value.tenant_id = 1; value.project_id = 11;
      await assert.rejects(client.read(resource), /GEO_RESPONSE_INVALID/);
    }
  }
});
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
test('question detail uses only the new qualified matrix and ignores the preserved legacy engine observations', () => {
  const v = structuredClone(geoFixture('questions/3'));
  v.data.question.by_engine = [{engine_key: 'doubao', mentioned: 1, total: 2, percentage: 50, status: 'small_sample'}];
  v.data.by_engine = [{engine_key: 'doubao', mentioned: 99, total: 99, percentage: 100, status: 'observed', observation: {mentioned: 99, total: 99, status: 'observed'}}];
  let html = geoResource('questions/3', v);
  assert.match(html, /1\/2 · 50%/);
  assert(!html.includes('99/99') && !html.includes('100%'));
  delete v.data.question.by_engine;
  html = geoResource('questions/3', v);
  assert(!html.includes('100%'));
  assert.match(html, /暂无/);
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
