import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSemReadonlyClient } from './readonly-client.mjs'

const dates = { start_date: '2026-09-01', end_date: '2026-09-03' }
const context = { tenantId: 1, userId: 2, authorizationRevision: 'test-1', allowedReads: ['report', 'keywords', 'keywordDetail', 'searchTerms'] }
const fixtures = JSON.parse(readFileSync(new URL('./examples.synthetic.json', import.meta.url), 'utf8'))
const examples = Object.fromEntries(fixtures.examples.map(example => [example.resource, example]))
const payload = examples.report.response
const response = (data = payload) => ({ status: 200, ok: true, json: async () => data })

test('no network until context is confirmed; only GET and whitelisted path', async () => {
  const calls = []
  const client = createSemReadonlyClient({ onClear() {}, transport: async (...args) => { calls.push(args); return response() } })
  await assert.rejects(client.read('report', dates), { code: 'NOT_AUTHORIZED' })
  assert.equal(calls.length, 0)
  client.setContext(context)
  assert.equal((await client.read('report', examples.report.consumer_params)).metrics.cost, 10)
  assert.equal(calls[0][1].method, 'GET')
  assert.equal(calls[0][1].cache, 'no-store')
  assert.match(calls[0][0], /^\/api\/v1\/dashboard\/cockpit\?tenant_id=1&/)
  await assert.rejects(client.read('writeback', {}), { code: 'UNSUPPORTED_RESOURCE' })
  await assert.rejects(client.read('searchTerms', dates), { code: 'UNSUPPORTED_FILTER' })
  await assert.rejects(client.read('report', { ...dates, tenant_id: 2 }), { code: 'UNSUPPORTED_FILTER' })
  await assert.rejects(client.read('report', { ...dates, start_date: '2026-02-30' }), { code: 'INVALID_WINDOW' })
  assert.equal(calls.length, 1)
})

test('all resources route without fabricated defaults or a sync call', async () => {
  const calls = []
  const client = createSemReadonlyClient({ onClear() {}, transport: async (url) => {
    calls.push(url)
    if (url.includes('search-terms')) return response(examples.searchTerms.response)
    if (url.includes('/100')) return response(examples.keywordDetail.response)
    return response(examples.keywords.response)
  } })
  client.setContext(context)
  await client.read('keywords', examples.keywords.consumer_params)
  await client.read('keywordDetail', examples.keywordDetail.consumer_params)
  await client.read('searchTerms', examples.searchTerms.consumer_params)
  assert.match(calls[0], /^\/api\/v1\/keywords\/cockpit\?tenant_id=1&start_date=2026-09-01&end_date=2026-09-03&baidu_account_id=11$/)
  assert.match(calls[1], /^\/api\/v1\/keywords\/cockpit\/100\?/)
  assert.match(calls[2], /^\/api\/v1\/search-terms\/cockpit\?/)
})

test('late response after customer switch cannot return even when transport ignores abort', async () => {
  let finish
  let clearCount = 0
  const client = createSemReadonlyClient({ onClear() { clearCount++ }, transport: () => new Promise(resolve => { finish = resolve }) })
  client.setContext(context)
  const old = client.read('report', dates)
  client.setContext({ ...context, tenantId: 3 })
  finish(response())
  await assert.rejects(old, { code: 'STALE_RESPONSE' })
  assert.equal(clearCount, 2)
})

test('late response after filter change cannot replace latest result', async () => {
  const finishes = []
  const client = createSemReadonlyClient({ onClear() {}, transport: () => new Promise(resolve => finishes.push(resolve)) })
  client.setContext(context)
  const first = client.read('report', dates)
  const second = client.read('report', { ...dates, baidu_account_id: 11 })
  finishes[1](response())
  await second
  finishes[0](response())
  await assert.rejects(first, { code: 'STALE_RESPONSE' })
})

for (const status of [401, 403]) test(`permission rejection ${status} invalidates all context`, async () => {
  const client = createSemReadonlyClient({ onClear() {}, transport: async () => ({ status, ok: false }) })
  client.setContext(context)
  await assert.rejects(client.read('report', dates), { code: 'ACCESS_REVOKED' })
  await assert.rejects(client.read('keywords'), { code: 'NOT_AUTHORIZED' })
})

test('foreign or simulated result is rejected', async () => {
  for (const data of [{ ...payload, tenant_id: 3 }, { ...payload, is_demo: true }]) {
    const client = createSemReadonlyClient({ onClear() {}, transport: async () => response(data) })
    client.setContext(context)
    await assert.rejects(client.read('report', dates), { code: 'CONTRACT_MISMATCH' })
  }
})

test('zero allowed reads and server failure do not fall back to demo', async () => {
  let calls = 0
  const client = createSemReadonlyClient({ onClear() {}, transport: async () => { calls++; return { status: 500, ok: false } } })
  client.setContext({ ...context, allowedReads: [] })
  await assert.rejects(client.read('report', dates), { code: 'NOT_AUTHORIZED' })
  assert.equal(calls, 0)
  client.setContext(context)
  await assert.rejects(client.read('report', dates), { code: 'READ_FAILED' })
})

test('incorrect account or date response cannot populate a filtered view', async () => {
  for (const data of [payload, { ...payload, account_scope: { mode: 'single', baidu_account_id: 12 }, window: { start: '2020-01-01', end: '2020-01-02' } }]) {
    const client = createSemReadonlyClient({ onClear() {}, transport: async () => response(data) })
    client.setContext(context)
    await assert.rejects(client.read('report', { ...dates, baidu_account_id: 12 }), { code: 'CONTRACT_MISMATCH' })
  }
})

test('all synthetic API responses are accepted by the actual consumer contract', async () => {
  assert.equal(fixtures.synthetic, true)
  for (const example of fixtures.examples) {
    const client = createSemReadonlyClient({ onClear() {}, transport: async () => response(example.response) })
    client.setContext(context)
    assert.deepEqual(await client.read(example.resource, example.consumer_params), example.response)
  }
})

test('late transport errors after invalidation are classified as stale', async () => {
  let rejectRequest
  const client = createSemReadonlyClient({ onClear() {}, transport: () => new Promise((resolve, reject) => { rejectRequest = reject }) })
  client.setContext(context)
  const pending = client.read('report', dates)
  client.invalidate()
  rejectRequest(new Error('old request failed'))
  await assert.rejects(pending, { code: 'STALE_RESPONSE' })
})

async function rejectsContract(resource, mutate, params = examples[resource].consumer_params) {
  const data = structuredClone(examples[resource].response)
  mutate(data)
  const client = createSemReadonlyClient({ onClear() {}, transport: async () => response(data) })
  client.setContext(context)
  await assert.rejects(client.read(resource, params), { code: 'CONTRACT_MISMATCH' })
  await assert.rejects(client.read(resource, params), { code: 'NOT_AUTHORIZED' })
}

test('CTR remains a ratio and missing dates cannot be fabricated as zero', async () => {
  await rejectsContract('report', data => { data.metrics.ctr = 2 })
  await rejectsContract('report', data => { data.trend[1].cost = 0 })
  await rejectsContract('report', data => { data.coverage.missing_dates = [] })
})

test('partial phone evidence cannot be presented as a complete value', async () => {
  await rejectsContract('keywords', data => { data.items[0].phone_button_clicks.value = 2 })
  await rejectsContract('keywordDetail', data => { data.phone_button_clicks.unknown_rows = 0 })
  await rejectsContract('keywords', data => {
    data.items[0].phone_button_clicks = { ...data.items[0].phone_button_clicks,
      status: 'observed', known_rows: 2, unknown_rows: 0, value: null, known_subtotal: null }
  })
})

test('dimension and search-window shapes reject incomplete or mixed summaries', async () => {
  await rejectsContract('keywordDetail', data => { data.dimensions.schedule.cells.pop() })
  await rejectsContract('keywordDetail', data => { data.dimensions.region.accounts[0].baidu_account_id = 12 })
  await rejectsContract('searchTerms', data => { data.mixed_windows = false })
  await rejectsContract('searchTerms', data => { data.items[0].window.start = '2026-01-01' })
})

test('echoed filters and JSON shape must match the active request', async () => {
  await rejectsContract('keywords', data => { data.filters.campaign_id = 999 })
  await rejectsContract('keywords', data => { data.items[0].baidu_account_id = 12 })
  await rejectsContract('report', data => { data.retrieved_at = null })
  const client = createSemReadonlyClient({ onClear() {}, transport: async () => ({ status: 200, ok: true, json: async () => undefined }) })
  client.setContext(context)
  await assert.rejects(client.read('report', examples.report.consumer_params), { code: 'CONTRACT_MISMATCH' })
})

test('late 401 from an aborted filter does not clear the current request', async () => {
  const finishes = []
  const client = createSemReadonlyClient({ onClear() {}, transport: () => new Promise(resolve => finishes.push(resolve)) })
  client.setContext(context)
  const old = client.read('report', dates)
  const current = client.read('report', examples.report.consumer_params)
  finishes[0]({ status: 401, ok: false })
  await assert.rejects(old, { code: 'STALE_RESPONSE' })
  finishes[1](response())
  assert.equal((await current).tenant_id, 1)
})

test('all-account mode preserves an explicit unassigned bucket', async () => {
  const data = structuredClone(examples.report.response)
  data.account_scope = { mode: 'all', baidu_account_id: null, includes_unassigned: true }
  data.accounts.push({
    baidu_account_id: null,
    status: 'unassigned',
    metrics: { cost: null, click: null, impression: null, ctr: null, cpc: null },
    coverage: { status: 'no_data', completeness: 'unknown', observed_days: 0,
      missing_dates: ['2026-09-01', '2026-09-02', '2026-09-03'], latest_report_date: null, updated_at: null },
  })
  const client = createSemReadonlyClient({ onClear() {}, transport: async () => response(data) })
  client.setContext(context)
  assert.equal((await client.read('report', dates)).account_scope.includes_unassigned, true)
})

test('keyword default window can truthfully return no report anchor', async () => {
  const data = structuredClone(examples.keywords.response)
  data.account_scope = { mode: 'all', baidu_account_id: null, configured_account_ids: [11, 12], observed_account_ids: [] }
  data.window = { start: null, end: null, timezone: 'Asia/Shanghai', inclusive: true, mode: 'latest_report_7d' }
  data.total = 0
  data.items = []
  const client = createSemReadonlyClient({ onClear() {}, transport: async () => response(data) })
  client.setContext(context)
  assert.equal((await client.read('keywords')).window.start, null)
  await rejectsContract('keywords', response => {
    response.window = { start: '2026-09-01', end: '2026-09-03', timezone: 'Asia/Shanghai', inclusive: true, mode: 'latest_report_7d' }
    response.account_scope = { mode: 'all', baidu_account_id: null, configured_account_ids: [11, 12], observed_account_ids: [11] }
  }, {})
})

test('all-account dimensions retain independently observed unassigned rows', async () => {
  const data = structuredClone(examples.keywordDetail.response)
  data.account_scope = { mode: 'all', baidu_account_id: null, includes_unassigned: false }
  data.dimensions.region.accounts.push({ ...structuredClone(data.dimensions.region.accounts[0]), baidu_account_id: null })
  data.dimensions.schedule.accounts.push({ ...structuredClone(data.dimensions.schedule.accounts[0]), baidu_account_id: null })
  const client = createSemReadonlyClient({ onClear() {}, transport: async () => response(data) })
  client.setContext(context)
  const result = await client.read('keywordDetail', { ...dates, keyword_id: 100 })
  assert.equal(result.dimensions.region.accounts.at(-1).baidu_account_id, null)
})
