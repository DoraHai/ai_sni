import test from 'node:test'
import assert from 'node:assert/strict'
import { createSeoReadonlyClient } from './readonly-client.mjs'

const context = { tenantId: 16, siteId: 3, userId: 9, authorizationRevision: 'auth-1',
  allowedReads: ['contents', 'reviewHistory', 'publications', 'attempts', 'pages', 'imageEvidence'] }
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => data })
const content = { id: 101, tenant_id: 16, site_id: 3, status: 'ready', title: '合成文章', page_url: null,
  source_page_id: null, version_count: 2, review_submitted_by: 7, reviewed_by: 8,
  reviewed_at: '2026-09-07T01:00:00Z', published_at: null, updated_at: '2026-09-07T01:00:00Z' }
const publication = { id: 201, tenant_id: 16, content_id: 101, platform_code: 'zhihu', platform_name: '知乎',
  publish_mode: 'assisted', status: 'published', page_url: 'https://example.invalid/article', last_error: null,
  published_at: '2026-09-07T02:00:00Z', updated_at: '2026-09-07T02:00:00Z' }
const page = { id: 301, tenant_id: 16, site_id: 3, url: publication.page_url, http_status: 200, last_error: null,
  last_checked_at: '2026-09-07T03:00:00Z', diagnostic: { assessment_state: 'assessed', checked_at: '2026-09-07T03:00:00Z', http_status: 200 } }

function fixture(handler) {
  const calls = []
  const client = createSeoReadonlyClient({ onClear() {}, transport: async (...args) => {
    calls.push(args)
    return handler ? handler(...args) : response({ items: [], total: 0, page: 1, page_size: 50, status_counts: {} })
  } })
  return { client, calls }
}

test('requires verified context and uses only reviewed GET routes', async () => {
  const { client, calls } = fixture()
  await assert.rejects(client.read('contents'), { code: 'NOT_AUTHORIZED' })
  client.setContext(context)
  await client.read('contents')
  assert.match(calls[0][0], /^\/api\/v1\/seo\/content-assets\?tenant_id=16&site_id=3$/)
  assert.deepEqual(calls[0][1].method, 'GET')
  await assert.rejects(client.read('publish'), { code: 'UNSUPPORTED_RESOURCE' })
})

test('empty 200 is preserved as empty and never fabricated as a zero performance result', async () => {
  const { client } = fixture()
  client.setContext(context)
  const result = await client.read('contents')
  assert.deepEqual(result.items, [])
  assert.equal(result.total, 0)
  assert.throws(() => client.snapshot(101), { code: 'UNVERIFIED_REFERENCE' })
})

test('review history is bound to a content already verified in the current site', async () => {
  const { client, calls } = fixture(path => path.includes('review-history')
    ? response({ items: [{ id: 1, action: 'approve', actor_id: 8, created_at: '2026-09-07T01:00:00Z' }], total: 1 })
    : response({ items: [content], total: 1, page: 1, page_size: 50, status_counts: { ready: 1 } }))
  client.setContext(context)
  await assert.rejects(client.read('reviewHistory', { contentId: 101 }), { code: 'UNVERIFIED_REFERENCE' })
  assert.equal(calls.length, 0)
  await client.read('contents')
  await client.read('reviewHistory', { contentId: 101 })
  const url = new URL(calls[1][0], 'https://example.invalid')
  assert.equal(url.searchParams.get('tenant_id'), '16')
  assert.equal(url.searchParams.has('site_id'), false)
})

test('publication and attempt reads require the verified parent chain', async () => {
  const { client, calls } = fixture(path => {
    if (path.includes('/201/attempts')) return response({ items: [{ id: 401, action: 'publish', status: 'succeeded', error: null,
      started_at: '2026-09-07T02:00:00Z', completed_at: '2026-09-07T02:01:00Z' }] })
    if (path.includes('publications?')) return response({ items: [publication], total: 1, status_counts: { published: 1 } })
    return response({ items: [content], total: 1, page: 1, page_size: 50, status_counts: { ready: 1 } })
  })
  client.setContext(context)
  await assert.rejects(client.read('publications', { contentId: 101 }), { code: 'UNVERIFIED_REFERENCE' })
  await client.read('contents')
  await assert.rejects(client.read('attempts', { publicationId: 201 }), { code: 'UNVERIFIED_REFERENCE' })
  await client.read('publications', { contentId: 101 })
  assert.equal(new URL(calls.at(-1)[0], 'https://example.invalid').searchParams.get('content_id'), '101')
  await client.read('attempts', { publicationId: 201 })
  assert.match(calls.at(-1)[0], /\/publications\/201\/attempts\?tenant_id=16&site_id=3$/)
})

test('page and image evidence require an exact verified page identity', async () => {
  const { client } = fixture(path => path.includes('image-evidence')
    ? response({ page_id: 301, url: page.url, snapshot_id: 501, fetched_at: '2026-09-07T03:00:00+08:00', fetch_error: null, evidence: { items: [] } })
    : response({ items: [page], total: 1, page: 1, page_size: 50, stats: {} }))
  client.setContext(context)
  await assert.rejects(client.read('imageEvidence', { pageId: 301 }), { code: 'UNVERIFIED_REFERENCE' })
  await client.read('pages')
  assert.equal((await client.read('imageEvidence', { pageId: 301 })).snapshot_id, 501)
})

test('snapshot keeps review, publication, page check and search performance separate', async () => {
  const { client } = fixture(path => {
    if (path.includes('image-evidence')) return response({ page_id: 301, url: page.url, snapshot_id: 501,
      fetched_at: '2026-09-07T03:00:00+08:00', fetch_error: null, evidence: { items: [] } })
    if (path.includes('site-pages?')) return response({ items: [page], total: 1, page: 1, page_size: 50, stats: {} })
    if (path.includes('publications?')) return response({ items: [publication], total: 1, status_counts: { published: 1 } })
    return response({ items: [content], total: 1, page: 1, page_size: 50, status_counts: { ready: 1 } })
  })
  client.setContext(context)
  await client.read('contents'); await client.read('publications', { contentId: 101 })
  await client.read('pages'); await client.read('imageEvidence', { pageId: 301 })
  const view = client.snapshot(101, { pageBinding: { pageId: 301, pageUrl: page.url,
    targetKind: 'publication_page_url', publicationId: 201 } })
  assert.equal(view.review.label, '审核通过')
  assert.equal(view.publication_summary.successful_count, 1)
  assert.equal(view.page_evidence.mapping_state, 'matched')
  assert.equal(view.page_evidence.latest_snapshot_id, 501)
  assert.equal(view.page_evidence.passed, null)
  assert.equal(view.search_performance.article_clicks, null)
})

test('approved content without publications is explicitly pending publication', async () => {
  const { client } = fixture(path => path.includes('publications?')
    ? response({ items: [], total: 0, status_counts: {} })
    : response({ items: [content], total: 1, page: 1, page_size: 50, status_counts: { ready: 1 } }))
  client.setContext(context)
  await client.read('contents'); await client.read('publications', { contentId: 101 })
  const view = client.snapshot(101)
  assert.equal(view.content.label, '已审核待发布')
  assert.equal(view.page_evidence.mapping_state, 'not_linked')
})

test('cross-tenant or cross-site rows fail closed and clear context', async () => {
  const foreign = { ...content, site_id: 4 }
  const { client } = fixture(() => response({ items: [foreign], total: 1, page: 1, page_size: 50, status_counts: { ready: 1 } }))
  client.setContext(context)
  await assert.rejects(client.read('contents'), { code: 'CONTRACT_MISMATCH' })
  await assert.rejects(client.read('contents'), { code: 'NOT_AUTHORIZED' })
})

test('HTTP failures remain unavailable and never become empty data', async () => {
  for (const status of [404, 500]) {
    const { client } = fixture(() => response({}, status))
    client.setContext(context)
    await assert.rejects(client.read('contents'), { code: status === 404 ? 'NOT_FOUND' : 'READ_FAILED' })
  }
  for (const status of [401, 403]) {
    const { client } = fixture(() => response({}, status))
    client.setContext(context)
    await assert.rejects(client.read('contents'), { code: 'ACCESS_REVOKED' })
    await assert.rejects(client.read('contents'), { code: 'NOT_AUTHORIZED' })
  }
})

test('network failures remain unavailable and are not converted to empty data', async () => {
  const { client } = fixture(() => { throw new Error('synthetic offline') })
  client.setContext(context)
  await assert.rejects(client.read('contents'), { code: 'READ_FAILED' })
})

test('late response after tenant or site change is discarded', async () => {
  let finish
  const { client } = fixture(() => new Promise(resolve => { finish = resolve }))
  client.setContext(context)
  const old = client.read('contents')
  client.setContext({ ...context, tenantId: 17, siteId: 4, authorizationRevision: 'auth-2' })
  finish(response({ items: [], total: 0, page: 1, page_size: 50, status_counts: {} }))
  await assert.rejects(old, { code: 'STALE_RESPONSE' })
})

test('unsupported filters and malformed pagination are rejected', async () => {
  const { client, calls } = fixture()
  client.setContext(context)
  await assert.rejects(client.read('contents', { tenantId: 99 }), { code: 'UNSUPPORTED_FILTER' })
  await assert.rejects(client.read('contents', { page: 0 }), { code: 'INVALID_FILTER' })
  await assert.rejects(client.read('contents', { pageSize: 201 }), { code: 'INVALID_FILTER' })
  assert.equal(calls.length, 0)
})

test('publication endpoint keeps its real unpaginated total semantics', async () => {
  const { client } = fixture(path => {
    if (path.includes('publications?')) return response({ items: [publication], total: 2, status_counts: { published: 2 } })
    return response({ items: [content], total: 1, page: 1, page_size: 50, status_counts: { ready: 1 } })
  })
  client.setContext(context); await client.read('contents')
  await assert.rejects(client.read('publications', { contentId: 101 }), { code: 'CONTRACT_MISMATCH' })
})

test('filtered object and snapshot identities must match the request', async () => {
  const { client } = fixture(path => {
    if (path.includes('image-evidence')) return response({ page_id: 301, url: page.url, snapshot_id: 999,
      fetched_at: '2026-09-07T03:00:00+08:00', fetch_error: null, evidence: {} })
    if (path.includes('site-pages?')) return response({ items: [page], total: 1, page: 1, page_size: 50, stats: {} })
    return response({ items: [content], total: 1, page: 1, page_size: 50, status_counts: { ready: 1 } })
  })
  client.setContext(context)
  await assert.rejects(client.read('contents', { contentId: 999 }), { code: 'CONTRACT_MISMATCH' })

  client.setContext(context)
  await client.read('pages', { pageId: 301 })
  await assert.rejects(client.read('imageEvidence', { pageId: 301, snapshotId: 501 }), { code: 'CONTRACT_MISMATCH' })
})

test('refreshing publications revokes removed publication references', async () => {
  let publicationReads = 0
  const { client } = fixture(path => {
    if (path.includes('/201/attempts')) return response({ items: [] })
    if (path.includes('publications?')) {
      publicationReads++
      return publicationReads === 1
        ? response({ items: [publication], total: 1, status_counts: { published: 1 } })
        : response({ items: [], total: 0, status_counts: {} })
    }
    return response({ items: [content], total: 1, page: 1, page_size: 50, status_counts: { ready: 1 } })
  })
  client.setContext(context); await client.read('contents')
  await client.read('publications', { contentId: 101 })
  await client.read('attempts', { publicationId: 201 })
  await client.read('publications', { contentId: 101 })
  await assert.rejects(client.read('attempts', { publicationId: 201 }), { code: 'UNVERIFIED_REFERENCE' })
})

test('an empty content refresh revokes prior content and every dependent reference', async () => {
  let contentReads = 0
  const { client } = fixture(path => {
    if (path.includes('publications?')) return response({ items: [publication], total: 1, status_counts: { published: 1 } })
    contentReads++
    return contentReads === 1
      ? response({ items: [content], total: 1, page: 1, page_size: 50, status_counts: { ready: 1 } })
      : response({ items: [], total: 0, page: 1, page_size: 50, status_counts: {} })
  })
  client.setContext(context)
  await client.read('contents'); await client.read('publications', { contentId: 101 })
  await client.read('contents')
  assert.throws(() => client.snapshot(101), { code: 'UNVERIFIED_REFERENCE' })
  await assert.rejects(client.read('reviewHistory', { contentId: 101 }), { code: 'UNVERIFIED_REFERENCE' })
  await assert.rejects(client.read('attempts', { publicationId: 201 }), { code: 'UNVERIFIED_REFERENCE' })
})

test('an empty page refresh revokes prior page and image-evidence access', async () => {
  let pageReads = 0
  const { client } = fixture(() => {
    pageReads++
    return pageReads === 1
      ? response({ items: [page], total: 1, page: 1, page_size: 50, stats: {} })
      : response({ items: [], total: 0, page: 1, page_size: 50, stats: {} })
  })
  client.setContext(context)
  await client.read('pages'); await client.read('pages')
  await assert.rejects(client.read('imageEvidence', { pageId: 301 }), { code: 'UNVERIFIED_REFERENCE' })
})

test('a late attempt cannot refill cache after its publication set is refreshed away', async () => {
  let finishAttempt
  let publicationReads = 0
  const { client } = fixture(path => {
    if (path.includes('/201/attempts')) return new Promise(resolve => { finishAttempt = resolve })
    if (path.includes('publications?')) {
      publicationReads++
      return publicationReads === 1
        ? response({ items: [publication], total: 1, status_counts: { published: 1 } })
        : response({ items: [], total: 0, status_counts: {} })
    }
    return response({ items: [content], total: 1, page: 1, page_size: 50, status_counts: { ready: 1 } })
  })
  client.setContext(context)
  await client.read('contents'); await client.read('publications', { contentId: 101 })
  const late = client.read('attempts', { publicationId: 201 })
  await client.read('publications', { contentId: 101 })
  finishAttempt(response({ items: [{ id: 401, action: 'publish', status: 'succeeded', error: null,
    started_at: '2026-09-07T02:00:00Z', completed_at: '2026-09-07T02:01:00Z' }] }))
  await assert.rejects(late, { code: 'STALE_RESPONSE' })
  await assert.rejects(client.read('attempts', { publicationId: 201 }), { code: 'UNVERIFIED_REFERENCE' })
})

test('filtered publication subsets cannot drive an all-publication snapshot', async () => {
  const { client, calls } = fixture()
  client.setContext(context)
  await assert.rejects(client.read('publications', { contentId: 101, status: 'failed' }), { code: 'UNSUPPORTED_FILTER' })
  assert.equal(calls.length, 0)
})
