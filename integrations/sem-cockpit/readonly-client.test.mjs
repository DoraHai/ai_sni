import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSemReadonlyClient } from './readonly-client.mjs'

const dates = { start_date: '2026-09-01', end_date: '2026-09-03' }
const context = { tenantId: 1, userId: 2, authorizationRevision: 'test-1', allowedReads: ['report', 'keywords', 'keywordDetail', 'searchTerms'] }
const payload = { tenant_id: 1, module: 'sem', read_only: true, is_demo: false, contract_version: 'sem-cockpit-v1',
  source: 'kw_report_snapshots', account_scope: { mode: 'all', baidu_account_id: null },
  window: { start: dates.start_date, end: dates.end_date }, metrics: { cost: null } }
const response = (data = payload) => ({ status: 200, ok: true, json: async () => data })

test('no network until context is confirmed; only GET and whitelisted path', async () => {
  const calls = []
  const client = createSemReadonlyClient({ onClear() {}, transport: async (...args) => { calls.push(args); return response() } })
  await assert.rejects(client.read('report', dates), { code: 'NOT_AUTHORIZED' })
  assert.equal(calls.length, 0)
  client.setContext(context)
  assert.equal((await client.read('report', dates)).metrics.cost, null)
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
    return response({ ...payload, keyword_id: 100,
      source: url.includes('search-terms') ? 'search_term_reports' : url.includes('/100') ? 'kw_report_snapshots' : 'keywords+kw_report_snapshots',
      account_scope: url.includes('baidu_account_id=12') ? { mode: 'single', baidu_account_id: 12 } : payload.account_scope })
  } })
  client.setContext(context)
  await client.read('keywords', { baidu_account_id: 12 })
  await client.read('keywordDetail', { ...dates, keyword_id: 100, baidu_account_id: 12 })
  await client.read('searchTerms', { q: '测试' })
  assert.match(calls[0], /^\/api\/v1\/keywords\/cockpit\?tenant_id=1&baidu_account_id=12$/)
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
  const second = client.read('report', { ...dates, baidu_account_id: 12 })
  finishes[1](response({ ...payload, account_scope: { mode: 'single', baidu_account_id: 12 } }))
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
  const fixtures = JSON.parse(readFileSync(new URL('./examples.synthetic.json', import.meta.url), 'utf8'))
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
