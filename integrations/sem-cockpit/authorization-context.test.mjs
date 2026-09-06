import assert from 'node:assert/strict'
import test from 'node:test'
import { createSemAuthorizedClient, resolveSemReadonlyContext } from './authorization-context.mjs'

const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
const identity = {
  me: { user: { id: 5, tenant_id: null, permissions: {
    'monitor.dashboard': 'view', 'optimize.keywords': 'edit', 'optimize.searchterms': 'view',
  } } },
  modules: { modules: [{ module_code: 'sem', status: 'active', available: true, expires_at: null }] },
  tenants: { module: 'sem', tenants: [{ id: 16, name: '只读客户', sem_identity: { status: 'ready' } }] },
}

function preflightTransport(overrides = {}) {
  const data = { ...identity, ...overrides }
  return async path => {
    if (path === '/api/v1/auth/me') return json(data.me)
    if (path === '/api/v1/auth/modules') return json(data.modules)
    if (path === '/api/v1/auth/tenants?module=sem') return json(data.tenants)
    throw new Error(`unexpected ${path}`)
  }
}

test('preflight derives exact SEM reads from current role permissions', async () => {
  const context = await resolveSemReadonlyContext({ transport: preflightTransport(), tenantId: 16 })
  assert.equal(context.userId, 5)
  assert.equal(context.tenantId, 16)
  assert.deepEqual(context.allowedReads, ['report', 'keywords', 'keywordDetail', 'searchTerms'])
  assert.match(context.authorizationRevision, /monitor\.dashboard/)
})

test('preflight rejects unavailable module, foreign tenant, and blocked identity', async () => {
  await assert.rejects(resolveSemReadonlyContext({ transport: preflightTransport({
    modules: { modules: [{ module_code: 'sem', status: 'disabled', available: false }] },
  }), tenantId: 16 }), { code: 'SEM_NOT_AVAILABLE' })
  await assert.rejects(resolveSemReadonlyContext({ transport: preflightTransport({
    tenants: { module: 'sem', tenants: [] },
  }), tenantId: 16 }), { code: 'TENANT_NOT_ALLOWED' })
  await assert.rejects(resolveSemReadonlyContext({ transport: preflightTransport({
    tenants: { module: 'sem', tenants: [{ id: 16, sem_identity: { status: 'blocked', message: '身份冲突' } }] },
  }), tenantId: 16 }), { code: 'SEM_IDENTITY_BLOCKED' })
})

test('authorized client never probes a business route before preflight succeeds', async () => {
  const calls = []
  let clears = 0
  const client = createSemAuthorizedClient({ onClear: () => { clears++ }, transport: async path => {
    calls.push(path)
    if (path === '/api/v1/auth/me') return json(identity.me)
    if (path === '/api/v1/auth/modules') return json({ modules: [{ module_code: 'sem', available: false }] })
    throw new Error(`unexpected ${path}`)
  } })
  await assert.rejects(client.connect(16), { code: 'SEM_NOT_AVAILABLE' })
  assert.deepEqual(calls, ['/api/v1/auth/me', '/api/v1/auth/modules'])
  assert.equal(clears, 1)
  await assert.rejects(client.read('report', { start_date: '2026-09-01', end_date: '2026-09-01' }), { code: 'NOT_AUTHORIZED' })
})
