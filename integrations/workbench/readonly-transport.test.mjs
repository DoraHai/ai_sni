import test from 'node:test'
import assert from 'node:assert/strict'
import { createReadonlyTransport } from './readonly-transport.mjs'

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
