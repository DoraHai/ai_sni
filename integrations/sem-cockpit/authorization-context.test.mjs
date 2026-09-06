import assert from 'node:assert/strict'
import test from 'node:test'
import { createSemAuthorizedClient, resolveSemReadonlyContext } from './authorization-context.mjs'
import { createReadonlyTransport } from '../workbench/readonly-transport.mjs'

const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
const identity = {
  me: { user: { id: 5, tenant_id: null, permissions: {
    'monitor.dashboard': 'view', 'optimize.keywords': 'edit', 'optimize.searchterms': 'view',
  } } },
  modules: { tenant_id: null, modules: [{ module_code: 'sem', status: 'active', available: true, expires_at: null }] },
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
    modules: { tenant_id: null, modules: [{ module_code: 'sem', status: 'disabled', available: false }] },
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
    if (path === '/api/v1/auth/modules') return json({ tenant_id: null, modules: [{ module_code: 'sem', available: false }] })
    throw new Error(`unexpected ${path}`)
  } })
  await assert.rejects(client.connect(16), { code: 'SEM_NOT_AVAILABLE' })
  assert.deepEqual(calls, ['/api/v1/auth/me', '/api/v1/auth/modules'])
  assert.equal(clears, 1)
  await assert.rejects(client.read('report', { start_date: '2026-09-01', end_date: '2026-09-01' }), { code: 'NOT_AUTHORIZED' })
})

test('a slower old connect cannot replace a newer completed authorization', async () => {
  let releaseFirst
  let meCalls = 0
  const transport = async path => {
    if (path === '/api/v1/auth/me' && ++meCalls === 1) {
      await new Promise(resolve => { releaseFirst = resolve })
    }
    return preflightTransport()(path)
  }
  const client = createSemAuthorizedClient({ transport, onClear() {} })
  const oldConnect = client.connect(16)
  while (!releaseFirst) await Promise.resolve()
  const current = await client.connect(16)
  releaseFirst()
  await assert.rejects(oldConnect, { code: 'STALE_AUTHORIZATION' })
  assert.equal(current.tenantId, 16)
})

test('invalidate during connect prevents the pending preflight from authorizing again', async () => {
  let release
  const transport = async path => {
    if (path === '/api/v1/auth/me') await new Promise(resolve => { release = resolve })
    return preflightTransport()(path)
  }
  const client = createSemAuthorizedClient({ transport, onClear() {} })
  const pending = client.connect(16)
  while (!release) await Promise.resolve()
  client.invalidate()
  release()
  await assert.rejects(pending, { code: 'STALE_AUTHORIZATION' })
  await assert.rejects(client.read('report', { start_date: '2026-09-01', end_date: '2026-09-01' }), { code: 'NOT_AUTHORIZED' })
})

test('session change during response parsing remains STALE_SESSION', async () => {
  let session = { token: 'first-session', revision: 1 }
  let releaseBody
  const boundary = createReadonlyTransport({ origin: 'https://example.invalid', getSession: () => session,
    fetchImpl: async url => {
      assert.equal(url, 'https://example.invalid/api/v1/auth/me')
      return { ok: true, status: 200, json: () => new Promise(resolve => { releaseBody = () => resolve(identity.me) }) }
    } })
  const pending = resolveSemReadonlyContext({ transport: boundary.transport, tenantId: 16 })
  while (!releaseBody) await Promise.resolve()
  session = { token: 'second-session', revision: 2 }
  releaseBody()
  await assert.rejects(pending, { code: 'STALE_SESSION' })
})

test('preflight rejects loose module flags, mismatched scope, and array permissions', async () => {
  await assert.rejects(resolveSemReadonlyContext({ transport: preflightTransport({
    modules: { tenant_id: null, modules: [{ module_code: 'sem', available: 1 }] },
  }), tenantId: 16 }), { code: 'SEM_NOT_AVAILABLE' })
  await assert.rejects(resolveSemReadonlyContext({ transport: preflightTransport({
    modules: { tenant_id: 16, modules: [{ module_code: 'sem', available: true }] },
  }), tenantId: 16 }), { code: 'PREFLIGHT_CONTRACT_MISMATCH' })
  await assert.rejects(resolveSemReadonlyContext({ transport: preflightTransport({
    me: { user: { id: 5, tenant_id: null, permissions: [] } },
  }), tenantId: 16 }), { code: 'PREFLIGHT_CONTRACT_MISMATCH' })
})
