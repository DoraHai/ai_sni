import test from 'node:test'
import assert from 'node:assert/strict'
import { groupKey, mergeRows, safePublicationUrl, validateGroupsPage, reportedResult } from '../src/utils/articlePublicationGroups.js'
import { createPublicationGroupsState } from '../src/views/seo/publicationGroupsState.js'
import { createDistributionInboxApi } from '../src/api/distributionInbox.js'

const identity = { module: 'seo', tenant_id: 1, scope_id: 2, task_id: null }
const group = id => ({ ...identity, group_article_id: id, content_id: id, title: '同名文章', current_version_no: 3, native_count: 2, external_count: 2 })
const external = (id, article = null) => ({ ...identity, group_article_id: article, content_id: article, source: 'external_report', key: `external:${id}`, native_publication_id: null, external_receipt_id: id })
const page = (bucket, items, changes = {}) => ({ schema: 1, read_only: true, completeness: 'complete_snapshot',
  context: { ...identity, bucket, article_id: null, revision: 'r1' }, items,
  counts: { native: 2, external: 3, articles: 2, unlinked: 1, invalid: 0, loaded: items.length },
  has_more: false, next_cursor: null, ...changes })
const rid = '00000000-0000-0000-0000-000000000001'
const target = { tenant: 1, scope: 2 }

test('only exact scoped IDs group; same title and URL retain separate identities', () => {
  const rows = [group(7), group(8)]
  assert.notEqual(groupKey(rows[0]), groupKey(rows[1]))
  assert.notEqual(groupKey(rows[0]), groupKey({ ...rows[0], scope_id: 3 }))
  assert.notEqual(groupKey(rows[0]), groupKey({ ...rows[0], tenant_id: 3 }))
  for (const id of [0, -1, '7', Number.MAX_SAFE_INTEGER + 1]) assert.throws(() => groupKey(group(id)))
  assert.throws(() => groupKey({ ...rows[0], module: 'geo' }))
  const a = external(rid, 7), b = { ...a, source: 'native', key: 'native:seo:1', native_publication_id: 1, external_receipt_id: null }
  assert.equal(mergeRows([a], [a, b], r => r.key).length, 2)
})

test('DTO rejects incomplete pages, cross scope/article/source IDs and unsafe links', () => {
  validateGroupsPage(page('linked', [group(7)]), target)
  for (const change of [{ read_only: false }, { completeness: 'partial' }, { counts: { loaded: 1 } }, { has_more: true }, { items: [group(Number.MAX_SAFE_INTEGER + 1)] }]) {
    assert.throws(() => validateGroupsPage(page('linked', [group(7)], change), target))
  }
  const detail = page('linked', [external(rid, 7)], { context: { ...identity, bucket: 'linked', article_id: 7, revision: 'r1' } })
  validateGroupsPage(detail, { ...target, article: 7 })
  assert.throws(() => validateGroupsPage(detail, { ...target, article: 8 }))
  assert.throws(() => validateGroupsPage(page('unlinked', [external(rid, 7)]), { ...target, bucket: 'unlinked' }))
  for (const url of ['javascript:alert(1)', 'data:text/html,x', 'https://name:pass@example.test', 'https://a.test/\\evil', ' https://a.test']) assert.equal(safePublicationUrl(url), null)
  assert.equal(safePublicationUrl('https://example.test/a?x=1'), 'https://example.test/a?x=1')
  for (const status of ['success', 'failed', 'pending_review', 'unknown']) assert.match(reportedResult(status), /^操作人报告/)
})

test('article, detail and unlinked cursors stay independent and deduplicate only source keys', async () => {
  const calls = []
  const model = createPublicationGroupsState({ publicationGroups: async (_m, _t, _s, q) => {
    calls.push(q)
    if (q.article_id) return page('linked', q.cursor ? [external(rid, 7)] : [{ ...external(rid, 7), source: 'native', key: 'native:seo:1', native_publication_id: 1, external_receipt_id: null }], {
      context: { ...identity, bucket: 'linked', article_id: 7, revision: 'r1' }, has_more: !q.cursor, next_cursor: q.cursor ? null : 'detail-cursor' })
    if (q.bucket === 'unlinked') return page('unlinked', [external(rid)])
    if (q.bucket === 'invalid') return page('invalid', [])
    return page('linked', q.cursor ? [group(7), group(6)] : [group(7)], { has_more: !q.cursor, next_cursor: q.cursor ? null : 'article-cursor' })
  } })
  await model.refresh(target)
  await model.details(group(7)); await model.more('linked'); await model.details(group(7), true)
  assert.deepEqual(model.state.buckets.linked.items.map(r => r.group_article_id), [7, 6])
  assert.equal(model.state.details[groupKey(group(7))].items.length, 2)
  assert.equal(model.state.buckets.unlinked.items.length, 1)
  assert.equal(model.state.counts.native, 2)
  assert(calls.some(q => q.cursor === 'article-cursor' && !q.article_id))
  assert(calls.some(q => q.cursor === 'detail-cursor' && q.article_id === 7))
})

test('failure is not zero; revoked/revised context clears cached records; late results are discarded', async () => {
  let mode = 'ok', resolveLate
  const model = createPublicationGroupsState({ publicationGroups: async (_m, _t, _s, q) => {
    if (mode === 'late') return new Promise(resolve => { if (q.bucket === 'linked') resolveLate = resolve })
    if (mode === 'error') throw Object.assign(new Error('授权已回收'), { status: 403 })
    if (mode === 'revision' && q.cursor) return page('linked', [group(6)], { context: { ...identity, bucket: 'linked', article_id: null, revision: 'r2' } })
    return page(q.bucket, q.bucket === 'linked' ? [group(7)] : [], { has_more: q.bucket === 'linked', next_cursor: q.bucket === 'linked' ? 'next' : null })
  } })
  await model.refresh(target)
  mode = 'revision'; await model.more('linked')
  assert.equal(model.state.counts, null); assert.match(model.state.error, /变化/)
  mode = 'error'; await model.refresh(target)
  assert.equal(model.state.counts, null); assert.match(model.state.error, /回收/)
  mode = 'late'; void model.refresh(target)
  model.clear(); resolveLate(page('linked', [group(7)])); await new Promise(r => setTimeout(r, 0))
  assert.equal(model.state.buckets.linked.items.length, 0)
  assert.equal(model.state.counts, null)
})

test('groups API uses an exact GET with business identity and rejects unapproved selectors', async () => {
  const calls = []
  const api = createDistributionInboxApi({ getIdentity: () => ({ token: 'identity' }), getBusiness: () => ({ token: 'business', revision: 1 }), fetchImpl: async (path, options) => {
    calls.push({ path, options }); return { ok: true, json: async () => ({}) }
  } })
  await api.publicationGroups('seo', 1, 2, { bucket: 'linked', article_id: 7, limit: 100, cursor: 'typed-cursor' })
  assert.equal(calls[0].options.method, 'GET')
  assert.equal(calls[0].options.headers.Authorization, 'Bearer business')
  assert.equal(calls[0].options.cache, 'no-store')
  assert.match(calls[0].path, /^\/api\/v1\/seo\/distribution\/v2\/publication-groups\?tenant_id=1&scope_id=2&/)
  for (const q of [{ site_id: 2 }, { ownerUserId: 1 }, { article_id: Number.MAX_SAFE_INTEGER + 1 }, { bucket: 'unlinked', article_id: 7 }, { limit: 101 }]) assert.throws(() => api.publicationGroups('seo', 1, 2, q))
})
