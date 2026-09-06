import assert from 'node:assert/strict'
import test from 'node:test'
import { createSeoAuthorizedClient, resolveSeoReadonlyContext } from './authorization-context.mjs'
import { createReadonlyTransport } from '../workbench/readonly-transport.mjs'

const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
const identity = {
  me: { user: { id: 5, tenant_id: null, permissions: { 'seo.content': 'view', 'seo.site': 'edit' } } },
  modules: { tenant_id: null, modules: [
    { module_code: 'sem', status: 'active', available: true, expires_at: null },
    { module_code: 'seo', status: 'active', available: true, expires_at: null },
  ] },
  tenants: { module: 'seo', tenants: [{ id: 16, name: '只读客户' }] },
}
const emptyContent = { items: [], total: 0, page: 1, page_size: 1, status_counts: {} }
const emptyPages = { items: [], total: 0, page: 1, page_size: 1, stats: { total: 0 } }

function preflightTransport(overrides = {}) {
  const data = { ...identity, ...overrides }
  return async path => {
    if (path === '/api/v1/auth/me') return json(data.me)
    if (path === '/api/v1/auth/modules') return json(data.modules)
    if (path === '/api/v1/auth/tenants?module=seo') return json(data.tenants)
    if (path === '/api/v1/seo/content-assets?tenant_id=16&site_id=3&page=1&page_size=1') return json(data.site ?? emptyContent)
    if (path === '/api/v1/seo/site-pages?tenant_id=16&site_id=3&page=1&page_size=1') return json(data.site ?? emptyPages)
    throw new Error(`unexpected ${path}`)
  }
}

test('derives exact SEO reads and accepts an empty scoped content probe', async () => {
  const context = await resolveSeoReadonlyContext({ transport: preflightTransport(), tenantId: 16, siteId: 3 })
  assert.equal(context.userId, 5)
  assert.equal(context.tenantId, 16)
  assert.equal(context.siteId, 3)
  assert.deepEqual(context.allowedReads, ['contents', 'reviewHistory', 'publications', 'attempts', 'pages', 'imageEvidence'])
  assert.deepEqual(context.identity.siteVerification, { resource: 'contents', empty: true })
  assert.match(context.authorizationRevision, /"site_id":3/)
})

test('uses the page probe when the role has no content permission', async () => {
  const context = await resolveSeoReadonlyContext({ transport: preflightTransport({
    me: { user: { id: 5, tenant_id: null, permissions: { 'seo.site': 'view' } } },
  }), tenantId: 16, siteId: 3 })
  assert.deepEqual(context.allowedReads, ['pages', 'imageEvidence'])
  assert.equal(context.identity.siteVerification.resource, 'pages')
})

test('content-only permission grants no page or image read', async () => {
  const context = await resolveSeoReadonlyContext({ transport: preflightTransport({
    me: { user: { id: 5, tenant_id: null, permissions: { 'seo.content': 'view' } } },
  }), tenantId: 16, siteId: 3 })
  assert.deepEqual(context.allowedReads, ['contents', 'reviewHistory', 'publications', 'attempts'])
  assert.equal(context.identity.siteVerification.resource, 'contents')
})

test('never treats SEM availability as SEO availability', async () => {
  await assert.rejects(resolveSeoReadonlyContext({ transport: preflightTransport({
    modules: { tenant_id: null, modules: [{ module_code: 'sem', status: 'active', available: true }] },
  }), tenantId: 16, siteId: 3 }), { code: 'SEO_NOT_AVAILABLE' })
})

test('rejects loose SEO module flags and mismatched module scope', async () => {
  await assert.rejects(resolveSeoReadonlyContext({ transport: preflightTransport({
    modules: { tenant_id: null, modules: [{ module_code: 'seo', status: 'active', available: 1 }] },
  }), tenantId: 16, siteId: 3 }), { code: 'SEO_NOT_AVAILABLE' })
  await assert.rejects(resolveSeoReadonlyContext({ transport: preflightTransport({
    modules: { tenant_id: 16, modules: [{ module_code: 'seo', status: 'active', available: true }] },
  }), tenantId: 16, siteId: 3 }), { code: 'PREFLIGHT_CONTRACT_MISMATCH' })
})

test('rejects foreign tenant, missing SEO tenant and non-user identity', async () => {
  await assert.rejects(resolveSeoReadonlyContext({ transport: preflightTransport({
    me: { user: { id: 5, tenant_id: 17, permissions: { 'seo.content': 'view' } } },
  }), tenantId: 16, siteId: 3 }), { code: 'TENANT_NOT_ALLOWED' })
  await assert.rejects(resolveSeoReadonlyContext({ transport: preflightTransport({
    tenants: { module: 'seo', tenants: [] },
  }), tenantId: 16, siteId: 3 }), { code: 'TENANT_NOT_ALLOWED' })
  await assert.rejects(resolveSeoReadonlyContext({ transport: preflightTransport({
    me: { user: { id: null, tenant_id: null, permissions: { 'seo.content': 'view' } } },
  }), tenantId: 16, siteId: 3 }), { code: 'PREFLIGHT_CONTRACT_MISMATCH' })
})

test('does not probe a business route without a usable SEO read permission', async () => {
  const calls = []
  const transport = preflightTransport({ me: { user: { id: 5, tenant_id: null, permissions: { 'seo.dashboard': 'view' } } } })
  await assert.rejects(resolveSeoReadonlyContext({ transport: async (...args) => {
    calls.push(args[0]); return transport(...args)
  }, tenantId: 16, siteId: 3 }), { code: 'NO_SEO_READS' })
  assert.deepEqual(calls, ['/api/v1/auth/me', '/api/v1/auth/modules', '/api/v1/auth/tenants?module=seo'])
})

test('site probe distinguishes permission, ownership and server failures', async () => {
  for (const [status, code] of [[403, 'SITE_SCOPE_NOT_ALLOWED'], [404, 'SITE_NOT_ALLOWED'], [500, 'SITE_PREFLIGHT_FAILED']]) {
    const transport = preflightTransport({ site: {} })
    await assert.rejects(resolveSeoReadonlyContext({ transport: async path =>
      path.includes('/seo/content-assets?') ? json({}, status) : transport(path), tenantId: 16, siteId: 3 }), { code })
  }
})

test('site probe rejects a nonempty response from another scope', async () => {
  await assert.rejects(resolveSeoReadonlyContext({ transport: preflightTransport({ site: {
    items: [{ id: 1, tenant_id: 16, site_id: 4 }], total: 1, page: 1, page_size: 1, status_counts: {},
  } }), tenantId: 16, siteId: 3 }), { code: 'PREFLIGHT_CONTRACT_MISMATCH' })
})

test('site probe rejects incomplete aggregate evidence', async () => {
  await assert.rejects(resolveSeoReadonlyContext({ transport: preflightTransport({ site: {
    items: [], total: 1, page: 1, page_size: 1, status_counts: {},
  } }), tenantId: 16, siteId: 3 }), { code: 'PREFLIGHT_CONTRACT_MISMATCH' })
})

test('an empty probe is bound to the explicitly selected site request', async () => {
  const calls = []
  const base = preflightTransport()
  const context = await resolveSeoReadonlyContext({ transport: async path => {
    calls.push(path)
    if (path === '/api/v1/seo/content-assets?tenant_id=16&site_id=4&page=1&page_size=1') return json(emptyContent)
    return base(path)
  }, tenantId: 16, siteId: 4 })
  assert.equal(context.siteId, 4)
  assert.equal(context.identity.siteVerification.empty, true)
  assert.ok(calls.includes('/api/v1/seo/content-assets?tenant_id=16&site_id=4&page=1&page_size=1'))
  assert.ok(!calls.some(path => path.includes('site_id=3')))
})

test('a slower old connect cannot replace a newer site authorization', async () => {
  let releaseFirst
  let meCalls = 0
  const base = preflightTransport()
  const transport = async path => {
    if (path === '/api/v1/auth/me' && ++meCalls === 1) await new Promise(resolve => { releaseFirst = resolve })
    return base(path)
  }
  const client = createSeoAuthorizedClient({ transport, onClear() {} })
  const oldConnect = client.connect({ tenantId: 16, siteId: 3 })
  while (!releaseFirst) await Promise.resolve()
  const current = await client.connect({ tenantId: 16, siteId: 3 })
  releaseFirst()
  await assert.rejects(oldConnect, { code: 'STALE_AUTHORIZATION' })
  assert.equal(current.siteId, 3)
})

test('logout during connect prevents the pending preflight from authorizing again', async () => {
  let release
  const base = preflightTransport()
  const transport = async path => {
    if (path === '/api/v1/auth/me') await new Promise(resolve => { release = resolve })
    return base(path)
  }
  const client = createSeoAuthorizedClient({ transport, onClear() {} })
  const pending = client.connect({ tenantId: 16, siteId: 3 })
  while (!release) await Promise.resolve()
  client.invalidate(); release()
  await assert.rejects(pending, { code: 'STALE_AUTHORIZATION' })
  await assert.rejects(client.read('contents'), { code: 'NOT_AUTHORIZED' })
})

test('a late 401 from an old site connect cannot clear the newer authorization', async () => {
  let finishOld
  const base = preflightTransport()
  const transport = async path => {
    if (path === '/api/v1/seo/content-assets?tenant_id=16&site_id=3&page=1&page_size=1') {
      return new Promise(resolve => { finishOld = resolve })
    }
    if (path === '/api/v1/seo/content-assets?tenant_id=16&site_id=4&page=1&page_size=1') return json(emptyContent)
    if (path === '/api/v1/seo/content-assets?tenant_id=16&site_id=4') {
      return json({ items: [], total: 0, page: 1, page_size: 50, status_counts: {} })
    }
    return base(path)
  }
  const client = createSeoAuthorizedClient({ transport, onClear() {} })
  const oldConnect = client.connect({ tenantId: 16, siteId: 3 })
  while (!finishOld) await Promise.resolve()
  const current = await client.connect({ tenantId: 16, siteId: 4 })
  finishOld(json({}, 401))
  await assert.rejects(oldConnect, { code: 'STALE_AUTHORIZATION' })
  assert.equal(current.siteId, 4)
  assert.deepEqual((await client.read('contents')).items, [])
})

test('session revision change while parsing identity remains stale', async () => {
  let session = { token: 'first-session', revision: 1 }
  let releaseBody
  const boundary = createReadonlyTransport({ origin: 'https://example.invalid', getSession: () => session,
    fetchImpl: async url => {
      assert.equal(url, 'https://example.invalid/api/v1/auth/me')
      return { ok: true, status: 200, json: () => new Promise(resolve => { releaseBody = () => resolve(identity.me) }) }
    } })
  const pending = resolveSeoReadonlyContext({ transport: boundary.transport, tenantId: 16, siteId: 3 })
  while (!releaseBody) await Promise.resolve()
  session = { token: 'second-session', revision: 2 }; releaseBody()
  await assert.rejects(pending, { code: 'STALE_SESSION' })
})

test('invalid selected scope is rejected before any request', async () => {
  let calls = 0
  const transport = async () => { calls++; return json({}) }
  await assert.rejects(resolveSeoReadonlyContext({ transport, tenantId: 0, siteId: 3 }), { code: 'INVALID_TENANT' })
  await assert.rejects(resolveSeoReadonlyContext({ transport, tenantId: 16, siteId: 0 }), { code: 'INVALID_SITE' })
  assert.equal(calls, 0)
})
