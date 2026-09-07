import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { createGeoAuthorizedClient, resolveGeoReadonlyContext } from './authorization-context.mjs'

const contract = JSON.parse(readFileSync(new URL('./production-minimum.synthetic.json', import.meta.url), 'utf8'))
const period = contract.responses.periodContext
const contextRequest = { tenantId: 16, weekEnd: '2026-08-31' }
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
const identity = {
  me: { user: { id: 5, tenant_id: null, permissions: { 'geo.content': 'view', 'sem.assets': 'view' } } },
  tenants: { tenants: [{ id: 16, name: '只读客户' }] },
  period,
}

function preflightTransport(overrides = {}) {
  const data = { ...identity, ...overrides }
  return async path => {
    if (path === '/api/v1/auth/me') return json(data.me)
    if (path === '/api/v1/geo/tenants') return json(data.tenants)
    if (path === '/api/v1/geo/integration/read/period-context?tenant_id=16&week_end=2026-08-31') return json(data.period)
    throw new Error(`unexpected ${path}`)
  }
}

test('uses ordinary identity, geo.content, GEO tenants and the exact period probe only', async () => {
  const calls = []
  const base = preflightTransport()
  const resolved = await resolveGeoReadonlyContext({ ...contextRequest, transport: async (...args) => {
    calls.push(args[0]); return base(...args)
  } })
  assert.deepEqual(calls, [
    '/api/v1/auth/me',
    '/api/v1/geo/tenants',
    '/api/v1/geo/integration/read/period-context?tenant_id=16&week_end=2026-08-31',
  ])
  assert.ok(!calls.some(path => path.includes('/auth/modules') || path.includes('/auth/tenants')))
  assert.equal(resolved.userId, 5)
  assert.deepEqual(resolved.allowedReads, ['periodContext', 'metrics', 'dictionary', 'answers', 'answerDetail', 'questions'])
  assert.match(resolved.authorizationRevision, /"geo_content":"view"/)
  assert.ok(!resolved.authorizationRevision.includes('expires_at'))
})

test('edit permission grants reads but unrelated or loose grants stop before GEO routes', async () => {
  const edit = await resolveGeoReadonlyContext({ ...contextRequest, transport: preflightTransport({
    me: { user: { id: 5, tenant_id: null, permissions: { 'geo.content': 'edit' } } },
  }) })
  assert.equal(edit.allowedReads.length, 6)
  for (const permissions of [{ 'sem.assets': 'view' }, { 'geo.content': true }, { 'geo.content': 'read' }]) {
    const calls = []
    await assert.rejects(resolveGeoReadonlyContext({ ...contextRequest, transport: async path => {
      calls.push(path); return json({ user: { id: 5, tenant_id: null, permissions } })
    } }), { code: 'NO_GEO_READS' })
    assert.deepEqual(calls, ['/api/v1/auth/me'])
  }
})

test('bound foreign tenant and missing GEO tenant never reach the period probe', async () => {
  await assert.rejects(resolveGeoReadonlyContext({ ...contextRequest, transport: preflightTransport({
    me: { user: { id: 5, tenant_id: 17, permissions: { 'geo.content': 'view' } } },
  }) }), { code: 'TENANT_NOT_ALLOWED' })
  const calls = []
  const base = preflightTransport({ tenants: { tenants: [] } })
  await assert.rejects(resolveGeoReadonlyContext({ ...contextRequest, transport: async (...args) => {
    calls.push(args[0]); return base(...args)
  } }), { code: 'TENANT_NOT_ALLOWED' })
  assert.deepEqual(calls, ['/api/v1/auth/me', '/api/v1/geo/tenants'])
})

test('GEO tenant list rejects malformed, unsafe and duplicate identities', async () => {
  for (const tenants of [null, [{ id: 0, name: '坏客户' }], [{ id: 16, name: '' }],
    [{ id: 16, name: 'A' }, { id: 16, name: 'B' }]]) {
    await assert.rejects(resolveGeoReadonlyContext({ ...contextRequest, transport: preflightTransport({
      tenants: tenants === null ? {} : { tenants },
    }) }), { code: 'PREFLIGHT_CONTRACT_MISMATCH' })
  }
  await assert.rejects(resolveGeoReadonlyContext({ ...contextRequest, transport: preflightTransport({
    tenants: { tenants: [] },
  }) }), { code: 'TENANT_NOT_ALLOWED' })
})

test('a tenant-bound identity rejects a GEO list that leaks another tenant', async () => {
  await assert.rejects(resolveGeoReadonlyContext({ ...contextRequest, transport: preflightTransport({
    me: { user: { id: 5, tenant_id: 16, permissions: { 'geo.content': 'view' } } },
    tenants: { tenants: [{ id: 16, name: '绑定客户' }, { id: 17, name: '不应出现' }] },
  }) }), { code: 'PREFLIGHT_CONTRACT_MISMATCH' })
})

test('an insufficient or empty formal week remains authorized and does not become zero', async () => {
  const unavailable = { ...period,
    current: { ...period.current, status: 'insufficient', qualified_counts: { samples: 0, questions: 0, engines: 0 },
      reasons: [{ code: 'insufficient_samples', scope: 'week', message: '样本不足' }] },
    metric_status: period.metric_status.map(row => ({ ...row, status: 'unavailable', reason_codes: ['insufficient_samples'] })),
    comparison: { ...period.comparison, comparable: false, reason_codes: ['current_week_insufficient'] },
  }
  const resolved = await resolveGeoReadonlyContext({ ...contextRequest, transport: preflightTransport({ period: unavailable }) })
  assert.equal(resolved.identity.periodContext.current.qualified_counts.samples, 0)
  assert.equal(resolved.identity.periodContext.current.status, 'insufficient')
})

test('period probe preserves auth, scope, server and contract error meanings', async () => {
  for (const [status, code] of [[401, 'NOT_AUTHENTICATED'], [403, 'GEO_SCOPE_NOT_ALLOWED'], [500, 'PREFLIGHT_FAILED']]) {
    const base = preflightTransport()
    await assert.rejects(resolveGeoReadonlyContext({ ...contextRequest, transport: async path =>
      path.includes('/period-context?') ? json({}, status) : base(path) }), { code })
  }
  await assert.rejects(resolveGeoReadonlyContext({ ...contextRequest, transport: preflightTransport({
    period: { ...period, tenant_id: 17 },
  }) }), { code: 'PREFLIGHT_CONTRACT_MISMATCH' })
})

test('the wrapped consumer becomes readable only after every authorization step succeeds', async () => {
  const base = preflightTransport()
  const client = createGeoAuthorizedClient({ onClear() {}, transport: async path =>
    path.includes('/period-context?') ? json({}, 403) : base(path) })
  await assert.rejects(client.connect(contextRequest), { code: 'GEO_SCOPE_NOT_ALLOWED' })
  await assert.rejects(client.read('periodContext'), { code: 'NOT_AUTHORIZED' })
})

test('invalid identity, tenant or week fails closed without inventing scope', async () => {
  await assert.rejects(resolveGeoReadonlyContext({ ...contextRequest, transport: preflightTransport({
    me: { user: { id: null, tenant_id: null, permissions: { 'geo.content': 'view' } } },
  }) }), { code: 'PREFLIGHT_CONTRACT_MISMATCH' })
  let calls = 0
  const transport = async () => { calls++; return json({}) }
  await assert.rejects(resolveGeoReadonlyContext({ transport, tenantId: 0, weekEnd: contextRequest.weekEnd }), { code: 'INVALID_TENANT' })
  await assert.rejects(resolveGeoReadonlyContext({ transport, tenantId: 16, weekEnd: '2026-08-30' }), { code: 'INVALID_WEEK' })
  assert.equal(calls, 0)
})

test('a slower old connection cannot replace a newer GEO authorization', async () => {
  let releaseFirst
  let meCalls = 0
  const base = preflightTransport()
  const client = createGeoAuthorizedClient({ onClear() {}, transport: async path => {
    if (path === '/api/v1/auth/me' && ++meCalls === 1) await new Promise(resolve => { releaseFirst = resolve })
    return base(path)
  } })
  const old = client.connect(contextRequest)
  while (!releaseFirst) await Promise.resolve()
  const current = await client.connect(contextRequest)
  releaseFirst()
  await assert.rejects(old, { code: 'STALE_AUTHORIZATION' })
  assert.equal(current.tenantId, 16)
})

test('logout during GEO authorization clears the consumer and prevents later reads', async () => {
  let release
  const base = preflightTransport()
  const client = createGeoAuthorizedClient({ onClear() {}, transport: async path => {
    if (path === '/api/v1/auth/me') await new Promise(resolve => { release = resolve })
    return base(path)
  } })
  const pending = client.connect(contextRequest)
  while (!release) await Promise.resolve()
  client.invalidate(); release()
  await assert.rejects(pending, { code: 'STALE_AUTHORIZATION' })
  await assert.rejects(client.read('periodContext'), { code: 'NOT_AUTHORIZED' })
})

test('a late 401 from an old period probe cannot clear a newer authorization', async () => {
  let finishOld
  let periodCalls = 0
  const base = preflightTransport()
  const client = createGeoAuthorizedClient({ onClear() {}, transport: async path => {
    if (path.includes('/period-context?') && ++periodCalls === 1) {
      return new Promise(resolve => { finishOld = resolve })
    }
    return base(path)
  } })
  const old = client.connect(contextRequest)
  while (!finishOld) await Promise.resolve()
  const current = await client.connect(contextRequest)
  finishOld(json({}, 401))
  await assert.rejects(old, { code: 'STALE_AUTHORIZATION' })
  assert.equal(current.tenantId, 16)
  assert.equal((await client.read('periodContext')).tenant_id, 16)
})
