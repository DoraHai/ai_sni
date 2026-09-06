import assert from 'node:assert/strict'
import test from 'node:test'

import { createGeoReadonlyClient } from './readonly-client.mjs'

const allReads = ['periodContext', 'metrics', 'dictionary', 'answers', 'answerDetail', 'questions']
const context = { tenantId: 16, userId: 5, weekEnd: '2026-08-31', authorizationRevision: 'role-4-v2', allowedReads: allReads }
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => data })
const period = {
  tenant_id: 16, timezone: 'Asia/Shanghai', week_end: '2026-08-31',
  current: { start: '2026-08-24T00:00:00+08:00', end: '2026-08-31T00:00:00+08:00', closed: true, status: 'ready', qualified_counts: { samples: 8, questions: 3, engines: 2 }, reasons: [] },
  previous: { start: '2026-08-17T00:00:00+08:00', end: '2026-08-24T00:00:00+08:00', closed: true, status: 'ready', qualified_counts: { samples: 8, questions: 3, engines: 2 }, reasons: [] },
  metric_status: [
    { metric_key: 'geo.visibility.ai_mention_count_7d', status: 'available', reason_codes: [] },
    { metric_key: 'geo.visibility.ai_mention_rate_7d', status: 'available', reason_codes: [] },
    { metric_key: 'geo.visibility.ai_visibility_score', status: 'available', reason_codes: [] },
  ],
  comparison: { comparable: true, reason_codes: [], checks: {} },
  metrics_url: '/api/v1/geo/integration/metrics/snapshot?tenant_id=16&week_end=2026-08-31',
  dictionary_url: '/api/v1/geo/integration/metrics/dictionary?tenant_id=16&week_end=2026-08-31',
}
const metric = { metric_key: 'geo.visibility.ai_mention_count_7d', value: 0, unit: 'count', as_of: '2026-08-31T00:00:00+08:00', trend_7d: { direction: 'flat', change_pct: null, change_abs: 0 } }
const metricSet = [
  metric,
  { ...metric, metric_key: 'geo.visibility.ai_mention_rate_7d', unit: 'percent' },
  { ...metric, metric_key: 'geo.visibility.ai_visibility_score', unit: 'score' },
]
const dictionary = Object.fromEntries(metricSet.map(row => [row.metric_key, `口径：${row.metric_key}`]))
const answer = {
  ref: { module: 'geo', type: 'answer_snapshot', id: 9010 },
  question: { id: 31, historical_text: '历史问题', current_text: '当前问题' },
  engine: { key: 'deepseek', provider: 'deepseek', model: 'deepseek-chat' },
  captured_at: '2026-08-29T02:15:00Z', captured_at_local: '2026-08-29T10:15:00+08:00', time_basis: 'stored_utc',
  source: { kind: 'real', verified_server_record: true },
  metric_adoption: [
    { metric_key: 'geo.visibility.ai_mention_count_7d', status: 'included', reasons: [] },
    { metric_key: 'geo.visibility.ai_mention_rate_7d', status: 'included', reasons: [] },
    { metric_key: 'geo.visibility.ai_visibility_score', status: 'included', reasons: [] },
  ],
  sample_eligibility: { eligible: true, reasons: [] }, week_membership: { within_window: true, included_in_cohort: true, reasons: [] },
  detail_url: '/api/v1/geo/integration/read/answers/9010?tenant_id=16&week_end=2026-08-31',
}
const answerPage = (overrides = {}) => ({
  tenant_id: 16, official_week_end: '2026-08-31', timezone: 'Asia/Shanghai',
  period_context_url: '/api/v1/geo/integration/read/period-context?tenant_id=16&week_end=2026-08-31',
  pagination: { limit: 2, has_more: true, next_cursor: 'signed.opaque', watermark_max_id: 9010 }, items: [answer], ...overrides,
})

function fixture(handler) {
  const calls = []
  const client = createGeoReadonlyClient({ transport: async (...args) => { calls.push(args); return handler(args[0], args[1]) }, onClear() {} })
  return { client, calls }
}

test('context requires a real Monday boundary for the formal complete week', () => {
  const { client } = fixture(() => assert.fail('network should not run'))
  for (const weekEnd of ['2026-02-30', '2026-08-30', '2026-8-31']) {
    assert.throws(() => client.setContext({ ...context, weekEnd }), { code: 'INVALID_CONTEXT' })
  }
})

test('reads only known GET paths from injected context and keeps metrics as the sole official source', async () => {
  const { client, calls } = fixture(path => {
    if (path.includes('period-context')) return response(period)
    if (path.includes('metrics/snapshot')) return response(metricSet)
    return response(dictionary)
  })
  client.setContext(context)
  await client.read('periodContext'); await client.read('metrics'); await client.read('dictionary')
  const official = client.officialSnapshot()
  assert.equal(official.source, 'geo_metrics_snapshot')
  assert.equal(official.metrics[0].value, 0)
  assert.equal(official.metrics[0].valueText, '0')
  assert.equal(official.metrics[0].trend.changeAbsText, '0 次')
  assert.deepEqual(calls.map(([path]) => path), [
    '/api/v1/geo/integration/read/period-context?tenant_id=16&week_end=2026-08-31',
    '/api/v1/geo/integration/metrics/snapshot?tenant_id=16&week_end=2026-08-31',
    '/api/v1/geo/integration/metrics/dictionary?tenant_id=16&week_end=2026-08-31',
  ])
  assert.ok(calls.every(([, options]) => options.method === 'GET' && options.cache === 'no-store'))
})

test('preserves null and explicitly incomparable trends instead of inventing zero or movement', async () => {
  const missing = metricSet.map(row => ({ ...row, value: null, trend_7d: { direction: null, change_pct: 20, change_abs: 2 } }))
  const incomparable = { ...period, comparison: { comparable: false, reason_codes: ['model_distribution_changed'], checks: {} } }
  const { client } = fixture(path => path.includes('period-context') ? response(incomparable)
    : path.includes('snapshot') ? response(missing) : response(dictionary))
  client.setContext(context)
  await client.read('periodContext'); await client.read('metrics'); await client.read('dictionary')
  const shown = client.officialSnapshot().metrics[0]
  assert.equal(shown.value, null); assert.equal(shown.valueText, '—')
  assert.equal(shown.trend.state, 'incomparable'); assert.equal(shown.trend.direction, null)
})

test('refuses to present an official metric without its required dictionary definition', async () => {
  const { client } = fixture(path => path.includes('period-context') ? response(period)
    : path.includes('snapshot') ? response(metricSet) : response({}))
  client.setContext(context)
  await client.read('periodContext'); await client.read('metrics'); await client.read('dictionary')
  assert.throws(() => client.officialSnapshot(), { code: 'CONTRACT_MISMATCH' })
})

test('answer cursor stays opaque and is bound to the original filter set', async () => {
  const { client, calls } = fixture(() => response(answerPage()))
  client.setContext(context)
  await client.read('answers', { sourceKind: 'real', limit: 2 })
  await client.read('answers', { sourceKind: 'real', limit: 2, cursor: 'signed.opaque' })
  assert.match(calls[1][0], /cursor=signed\.opaque/)
  await assert.rejects(client.read('answers', { sourceKind: 'manual', limit: 2, cursor: 'signed.opaque' }), { code: 'CURSOR_CONTEXT_CHANGED' })
  assert.equal(calls.length, 2)
})

test('new answer query revokes old references and cancels an in-flight detail', async () => {
  let finishDetail
  const { client } = fixture(path => {
    if (path.includes('/9010?')) return new Promise(resolve => { finishDetail = resolve })
    const items = path.includes('source_kind=manual') ? [] : [answer]
    return response(answerPage({ pagination: { limit: 2, has_more: false, next_cursor: null, watermark_max_id: 9010 }, items }))
  })
  client.setContext(context)
  await client.read('answers', { sourceKind: 'real', limit: 2 })
  const late = client.read('answerDetail', { snapshotId: 9010 })
  await client.read('answers', { sourceKind: 'manual', limit: 2 })
  finishDetail(response({ tenant_id: 16, official_week_end: '2026-08-31', period_context_url: answerPage().period_context_url, item: { ...answer, raw_text: '完整原文' } }))
  await assert.rejects(late, { code: 'STALE_RESPONSE' })
  assert.throws(() => client.answerView(9010, metric.metric_key), { code: 'UNVERIFIED_REFERENCE' })
})

test('tenant or permission revision changes reject a late response even if transport ignores abort', async () => {
  let finish
  const { client } = fixture(() => new Promise(resolve => { finish = resolve }))
  client.setContext(context)
  const late = client.read('periodContext')
  client.setContext({ ...context, tenantId: 17, authorizationRevision: 'role-4-v3' })
  finish(response(period))
  await assert.rejects(late, { code: 'STALE_RESPONSE' })
  assert.throws(() => client.officialSnapshot(), { code: 'DATA_NOT_LOADED' })
})

test('permission revision alone rejects a late response and clears verified answer references', async () => {
  let finish
  const { client } = fixture(path => path.includes('answers') ? response(answerPage()) : new Promise(resolve => { finish = resolve }))
  client.setContext(context)
  await client.read('answers', { limit: 2 })
  const late = client.read('periodContext')
  client.setContext({ ...context, authorizationRevision: 'role-4-v3' })
  finish(response(period))
  await assert.rejects(late, { code: 'STALE_RESPONSE' })
  assert.throws(() => client.answerView(9010, metric.metric_key), { code: 'UNVERIFIED_REFERENCE' })
})

test('a slower old answer query cannot refill references after a new filter completes', async () => {
  let finishOld
  const { client } = fixture(path => path.includes('source_kind=real')
    ? new Promise(resolve => { finishOld = resolve })
    : response(answerPage({ pagination: { limit: 2, has_more: false, next_cursor: null, watermark_max_id: null }, items: [] })))
  client.setContext(context)
  const old = client.read('answers', { sourceKind: 'real', limit: 2 })
  await client.read('answers', { sourceKind: 'manual', limit: 2 })
  finishOld(response(answerPage()))
  await assert.rejects(old, { code: 'STALE_RESPONSE' })
  assert.throws(() => client.answerView(9010, metric.metric_key), { code: 'UNVERIFIED_REFERENCE' })
})

test('rejects absolute, protocol-relative, escaped, duplicate and mismatched server URLs', async () => {
  for (const malicious of [
    'https://evil.invalid/api/v1/geo/integration/metrics/snapshot?tenant_id=16&week_end=2026-08-31',
    '//evil.invalid/api/v1/geo/integration/metrics/snapshot?tenant_id=16&week_end=2026-08-31',
    '/api/v1/geo/integration/metrics/%2e%2e/snapshot?tenant_id=16&week_end=2026-08-31',
    '/api/v1/geo/integration/metrics/snapshot?tenant_id=16&tenant_id=17&week_end=2026-08-31',
    '/api/v1/geo/integration/metrics/snapshot?tenant_id=17&week_end=2026-08-31',
  ]) {
    const { client } = fixture(() => response({ ...period, metrics_url: malicious }))
    client.setContext(context)
    await assert.rejects(client.read('periodContext'), { code: 'CONTRACT_MISMATCH' })
  }
})

test('answer details require a reference from the current query and validate returned URLs', async () => {
  let hostile = false
  const { client, calls } = fixture(path => {
    if (!path.includes('/9010?')) return response(answerPage())
    return response({ tenant_id: 16, official_week_end: '2026-08-31', period_context_url: answerPage().period_context_url,
      item: { ...answer, raw_text: '完整原文', detail_url: hostile ? '//evil.invalid/answers/9010' : answer.detail_url } })
  })
  client.setContext(context)
  await assert.rejects(client.read('answerDetail', { snapshotId: 9010 }), { code: 'UNVERIFIED_REFERENCE' })
  await client.read('answers', { limit: 2 })
  await client.read('answerDetail', { snapshotId: 9010 })
  assert.equal(client.answerView(9010, metric.metric_key).item.raw_text, '完整原文')
  hostile = true
  await assert.rejects(client.read('answerDetail', { snapshotId: 9010 }), { code: 'CONTRACT_MISMATCH' })
  assert.equal(calls.length, 3)
})

test('questions preserve unknown source timezone and paginate only within the same filters', async () => {
  const item = { ref: { module: 'geo', type: 'question', id: 41 }, current_text: '问题', language: 'zh-CN', status: 'active',
    timestamp_source_timezone: 'unknown', created_at: '2026-09-06T23:14:00', updated_at: '2026-09-06T23:37:00' }
  const page = before => ({ tenant_id: 16, pagination: { limit: 1, has_more: !before, next_before_id: before ? null : 41 }, items: [{ ...item, ref: { ...item.ref, id: before ? 40 : 41 } }] })
  const { client, calls } = fixture(path => response(page(path.includes('before_id=41'))))
  client.setContext(context)
  const first = await client.read('questions', { status: 'active', limit: 1 })
  assert.equal(first.items[0].created_at, '2026-09-06T23:14:00')
  assert.equal(first.items[0].timestamp_source_timezone, 'unknown')
  await client.read('questions', { status: 'active', limit: 1, beforeId: 41 })
  await assert.rejects(client.read('questions', { status: 'inactive', limit: 1, beforeId: 41 }), { code: 'CURSOR_CONTEXT_CHANGED' })
  await assert.rejects(client.read('questions', { status: 'active', limit: 1, beforeId: 39 }), { code: 'CURSOR_CONTEXT_CHANGED' })
  assert.equal(calls.length, 2)
})

test('metric arrays without tenant echo rely on the exact request context rather than invented fields', async () => {
  const { client, calls } = fixture(() => response(metricSet))
  client.setContext({ ...context, allowedReads: ['metrics'] })
  assert.deepEqual(await client.read('metrics'), metricSet)
  client.setContext({ ...context, tenantId: 17, authorizationRevision: 'new', allowedReads: ['metrics'] })
  assert.deepEqual(await client.read('metrics'), metricSet)
  assert.match(calls[1][0], /tenant_id=17/)
})

test('access revocation clears all verified references and official data', async () => {
  let forbidden = false
  const { client } = fixture(path => forbidden ? response({}, 403)
    : path.includes('answers') ? response(answerPage()) : response(period))
  client.setContext(context)
  await client.read('answers', { limit: 2 })
  forbidden = true
  await assert.rejects(client.read('periodContext'), { code: 'ACCESS_REVOKED' })
  assert.throws(() => client.answerView(9010, metric.metric_key), { code: 'UNVERIFIED_REFERENCE' })
})
