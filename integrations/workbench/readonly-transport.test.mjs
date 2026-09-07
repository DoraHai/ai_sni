import test from 'node:test'
import assert from 'node:assert/strict'
import { createReadonlyTransport } from './readonly-transport.mjs'
import { createSemReadonlyClient } from '../sem-cockpit/readonly-client.mjs'
import { readFileSync } from 'node:fs'

const route = '/api/v1/dashboard/cockpit?start_date=2026-09-05&end_date=2026-09-05'
function fixture(fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({ value: 0 }) })) {
  let session = { token: 'synthetic-session', revision: 1 }
  const client = createReadonlyTransport({ origin: 'https://example.invalid', fetchImpl, getSession: () => session })
  return { ...client, setSession: value => { session = value } }
}

test('GET uses explicit ordinary bearer, no cookies/cache/redirects', async () => {
  let request
  const client = fixture(async (...args) => { request = args; return { ok: true, status: 200, json: async () => ({ value: 0 }) } })
  assert.deepEqual(await (await client.transport(route, { method: 'GET' })).json(), { value: 0 })
  assert.equal(request[0], `https://example.invalid${route}`)
  assert.equal(request[1].headers.Authorization, 'Bearer synthetic-session')
  assert.equal(request[1].credentials, 'omit')
  assert.equal(request[1].redirect, 'error')
  assert.equal(request[1].cache, 'no-store')
})

test('rejects writes, unknown endpoints, off-origin and credential queries before network', async () => {
  let calls = 0
  const client = fixture(async () => { calls++; throw new Error('network should not run') })
  for (const path of ['https://evil.invalid/api/v1/dashboard/cockpit', '//evil.invalid/api/v1/dashboard/cockpit', '/api/v1/reports/analysis', '/api/v1/keywords/../dashboard/cockpit', `${route}&key=secret`, '/api/v1/dashboard/cockpit#secret']) {
    await assert.rejects(client.transport(path, { method: 'GET' }))
  }
  await assert.rejects(client.transport(route, { method: 'POST' }), { code: 'READ_ONLY' })
  await assert.rejects(client.transport(route, { method: 'GET', headers: {} }), { code: 'READ_ONLY' })
  client.setSession(null)
  await assert.rejects(client.transport(route, { method: 'GET' }), { code: 'NO_SESSION' })
  assert.equal(calls, 0)
})

test('late 401 from previous session is discarded', async () => {
  let complete
  const client = fixture(() => new Promise(resolve => { complete = resolve }))
  const pending = client.transport(route, { method: 'GET' })
  client.setSession({ token: 'next-session', revision: 2 })
  complete({ ok: false, status: 401 })
  await assert.rejects(pending, { code: 'STALE_SESSION' })
})

test('logout during body parsing prevents old response rendering', async () => {
  let complete
  const client = fixture(async () => ({ ok: true, status: 200, json: () => new Promise(resolve => { complete = resolve }) }))
  const response = await client.transport(route, { method: 'GET' })
  const body = response.json()
  client.invalidate()
  complete({ oldCustomer: true })
  await assert.rejects(body, { code: 'STALE_SESSION' })
})

test('invalidation aborts in-flight requests even if transport ignores cancellation', async () => {
  let signal, complete
  const client = fixture((url, options) => { signal = options.signal; return new Promise(resolve => { complete = resolve }) })
  const pending = client.transport(route, { method: 'GET' })
  client.invalidate()
  assert.equal(signal.aborted, true)
  complete({ ok: true, status: 200 })
  await assert.rejects(pending, { code: 'STALE_SESSION' })
})

test('real SEM consumer composes with transport for all four resources', async () => {
  const examples = JSON.parse(readFileSync(new URL('../sem-cockpit/examples.synthetic.json', import.meta.url), 'utf8')).examples
  for (const example of examples) {
    let request
    const boundary = fixture(async (...args) => { request = args; return { ok: true, status: 200, json: async () => example.response } })
    const client = createSemReadonlyClient({ transport: boundary.transport, onClear() {} })
    client.setContext({ tenantId: 1, userId: 2, authorizationRevision: 'test-1', allowedReads: ['report', 'keywords', 'keywordDetail', 'searchTerms'] })
    await client.read(example.resource, example.consumer_params)
    const url = new URL(request[0])
    assert.equal(url.origin, 'https://example.invalid')
    assert.equal(url.searchParams.get('tenant_id'), '1')
    assert.equal(request[1].headers.Authorization, 'Bearer synthetic-session')
  }
})

test('duplicate tenant or filter parameters cannot reach the network', async () => {
  const client = fixture(async () => assert.fail('network should not run'))
  await assert.rejects(client.transport(`${route}&tenant_id=1&tenant_id=2`, { method: 'GET' }), { code: 'QUERY_DENIED' })
  await assert.rejects(client.transport(`${route}&page=1&page=2`, { method: 'GET' }), { code: 'QUERY_DENIED' })
})

test('allows only the three exact SEM authorization preflight requests', async () => {
  const requests = []
  const client = fixture(async url => { requests.push(url); return { ok: true, status: 200, json: async () => ({}) } })
  for (const path of ['/api/v1/auth/me', '/api/v1/auth/modules', '/api/v1/auth/tenants?module=sem']) {
    await client.transport(path, { method: 'GET' })
  }
  assert.deepEqual(requests, [
    'https://example.invalid/api/v1/auth/me',
    'https://example.invalid/api/v1/auth/modules',
    'https://example.invalid/api/v1/auth/tenants?module=sem',
  ])
  for (const path of ['/api/v1/auth/login', '/api/v1/auth/me?tenant_id=16', '/api/v1/auth/tenants',
    '/api/v1/auth/tenants?module=geo', '/api/v1/auth/tenants?module=sem&module=sem']) {
    await assert.rejects(client.transport(path, { method: 'GET' }))
  }
})
