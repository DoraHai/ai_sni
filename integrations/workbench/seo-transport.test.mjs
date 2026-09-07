import test from 'node:test'
import assert from 'node:assert/strict'
import { createReadonlyTransport } from './readonly-transport.mjs'
import { createSeoReadonlyClient } from '../seo-workbench/readonly-client.mjs'
import { createSeoAuthorizedClient } from '../seo-workbench/authorization-context.mjs'

test('ordinary SEO identity composes through transport and verifies an empty site', async () => {
  const paths = []
  const payloads = [
    { user: { id: 5, tenant_id: 16, permissions: { 'seo.content': 'view' } } },
    { tenant_id: 16, modules: [{ module_code: 'seo', status: 'active', available: true, expires_at: null }] },
    { module: 'seo', tenants: [{ id: 16 }] },
    { items: [], total: 0, page: 1, page_size: 1, status_counts: {} },
  ]
  const boundary = createReadonlyTransport({ origin: 'https://example.invalid',
    getSession: () => ({ token: 'synthetic', revision: 1 }), fetchImpl: async url => {
      paths.push(new URL(url).pathname + new URL(url).search)
      const data = payloads.shift()
      return { ok: true, status: 200, json: async () => data }
    } })
  const client = createSeoAuthorizedClient({ transport: boundary.transport, onClear() {} })
  const context = await client.connect({ tenantId: 16, siteId: 3 })
  assert.equal(context.identity.siteVerification.empty, true)
  assert.deepEqual(context.allowedReads, ['contents', 'reviewHistory', 'publications', 'attempts'])
  assert.deepEqual(paths, ['/api/v1/auth/me', '/api/v1/auth/modules', '/api/v1/auth/tenants?module=seo',
    '/api/v1/seo/content-assets?tenant_id=16&site_id=3&page=1&page_size=1'])
})

test('six SEO resources compose through the real readonly boundary', async () => {
  const content = { id: 1, tenant_id: 16, site_id: 3, title: 'Synthetic', status: 'ready',
    page_url: null, reviewed_at: null, updated_at: null, published_at: null, review_submitted_by: null, reviewed_by: null }
  const publication = { id: 2, tenant_id: 16, content_id: 1, status: 'published', page_url: null,
    last_error: null, published_at: null, updated_at: null }
  const page = { id: 3, tenant_id: 16, site_id: 3, url: 'https://example.invalid/page', http_status: null,
    diagnostic: { assessment_state: 'not_checked', checked_at: null, http_status: null }, last_checked_at: null, last_error: null }
  const payloads = [
    { items: [content], total: 1, page: 1, page_size: 50, status_counts: {} },
    { items: [], total: 0 },
    { items: [publication], total: 1, status_counts: {} },
    { items: [] },
    { items: [page], total: 1, page: 1, page_size: 50, stats: {} },
    { page_id: 3, url: page.url, snapshot_id: null, fetched_at: null, fetch_error: null, evidence: null },
  ]
  const calls = []
  const boundary = createReadonlyTransport({ origin: 'https://example.invalid',
    getSession: () => ({ token: 'synthetic', revision: 1 }), fetchImpl: async (url, options) => {
      calls.push({ url: new URL(url), options }); const data = payloads.shift()
      return { ok: true, status: 200, json: async () => data }
    } })
  const client = createSeoReadonlyClient({ transport: boundary.transport, onClear() {} })
  client.setContext({ tenantId: 16, siteId: 3, userId: 5, authorizationRevision: 'test',
    allowedReads: ['contents', 'reviewHistory', 'publications', 'attempts', 'pages', 'imageEvidence'] })
  await client.read('contents')
  await client.read('reviewHistory', { contentId: 1 })
  await client.read('publications', { contentId: 1 })
  await client.read('attempts', { publicationId: 2 })
  await client.read('pages')
  await client.read('imageEvidence', { pageId: 3 })
  assert.equal(calls.length, 6)
  calls.forEach(({ url, options }, index) => {
    assert.equal(url.origin, 'https://example.invalid')
    assert.equal(url.searchParams.get('tenant_id'), '16')
    assert.equal(url.searchParams.get('site_id'), index === 1 ? null : '3')
    assert.equal(options.method, 'GET')
    assert.equal(options.headers.Authorization, 'Bearer synthetic')
  })
})

test('SEO rejects unscoped, unknown and misleading filtered requests before fetch', async () => {
  const { transport } = createReadonlyTransport({ origin: 'https://example.invalid',
    getSession: () => ({ token: 'synthetic', revision: 1 }), fetchImpl: () => assert.fail('network') })
  for (const path of [
    '/api/v1/seo/content-assets?tenant_id=16',
    '/api/v1/seo/content-assets?tenant_id=16&site_id=0',
    '/api/v1/seo/content-assets/1/review-history?tenant_id=16&site_id=3',
    '/api/v1/seo/content-distribution/publications?tenant_id=16&site_id=3&content_id=1&status=failed',
    '/api/v1/seo/site-pages/image-evidence?tenant_id=16&site_id=3',
    '/api/v1/seo/site-pages/1/audit?tenant_id=16&site_id=3',
  ]) await assert.rejects(transport(path, { method: 'GET' }))
})
