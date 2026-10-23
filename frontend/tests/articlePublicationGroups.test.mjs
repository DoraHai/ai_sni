import test from 'node:test'
import assert from 'node:assert/strict'
import { createPublicationGroupsState, groupKey, mergeRows, publicationTime, reportedResult,
  safePublicationLink, scopeId, validateGroupPage } from '../src/utils/articlePublicationGroups.js'
import { createDistributionInboxApi } from '../src/api/distributionInbox.js'
import { createInboxState } from '../src/components/geoDistributionInboxState.js'

const ctx = { module: 'geo', tenantId: 101, projectId: 1 }
const rid = '00000000-0000-4000-8000-000000000001'
const counts = { native_records: 2, external_records: 2, article_groups: 1, unlinked_records: 0, invalid_records: 0, loaded_items: 1 }
const group = { group_article_id: 1, task_id: 1, content_id: null, title: '<img onerror=alert(1)>', native_count: 2, external_count: 2 }
const external = { source: 'external_report', source_key: `external:${rid}`, group_article_id: 1, task_id: 1,
  article_version_id: null, article_version_no: 1, native_publication_id: null, external_receipt_id: rid }
const native = { source: 'native', source_key: 'native:geo:5', group_article_id: 1, task_id: 1,
  article_version_id: 888, article_version_no: 2, native_publication_id: 5, external_receipt_id: null }
function page(params = {}, items = null, more = false, revision = 'revision-1') {
  return { schema: 1, read_only: true,
    context: { module: 'geo', tenant_id: 101, scope_id: 1, bucket: params.bucket || 'linked', article_id: params.article_id || null, audience: 'internal' },
    items: items || (params.article_id ? [native, external] : params.bucket && params.bucket !== 'linked' ? [] : [group]),
    counts, next_cursor: more ? 'cursor-signed' : null, has_more: more, completeness: { complete: true, revision } }
}
const api = (fn = () => {}) => ({ publicationGroups: async (tid, pid, params) => { fn(tid, pid, params); return page(params) } })

test('identity is module+tenant+project+task, not title/URL/version row ID', () => {
  assert.notEqual(groupKey(ctx, 1), groupKey({ ...ctx, projectId: 2 }, 1))
  assert.notEqual(groupKey(ctx, 1), groupKey({ ...ctx, tenantId: 202 }, 1))
  assert.notEqual(groupKey(ctx, 1), groupKey(ctx, 888))
  assert.throws(() => groupKey({ ...ctx, module: 'seo' }, 1))
  const sameUrl = [{ id: 'native:geo:5', url: 'https://example.com/a' }, { id: `external:${rid}`, url: 'https://example.com/a' }]
  assert.equal(mergeRows([], sameUrl, r => r.id).length, 2)
  assert.equal(mergeRows(sameUrl, sameUrl, r => r.id).length, 2)
})

test('unsafe IDs, schemes, userinfo and missing times never become identities or links', () => {
  for (const value of ['9007199254740992', Number.MAX_SAFE_INTEGER + 1, '0', '-1', '01', {}, null]) assert.equal(scopeId(value), null)
  assert.equal(scopeId('101'), 101)
  for (const url of ['javascript:alert(1)', 'https://user:pass@example.com', 'data:text/html,foo', '//example.com', 'https://a.com/\\b']) assert.equal(safePublicationLink(url), null)
  assert.equal(safePublicationLink('https://example.com/a?x=1'), 'https://example.com/a?x=1')
  assert.equal(publicationTime(null), '未提供')
  assert.equal(publicationTime('2026-10-23T00:00:00'), '未提供')
  assert.match(publicationTime('2026-10-23T00:00:00Z'), /08:00/)
  for (const result of ['success', 'failed', 'pending_review', 'unknown']) assert.match(reportedResult(result), /^操作人报告/)
})

test('DTO distinguishes task and version; rejects cross-context and malformed sources', () => {
  const p = { article_id: 1 }
  assert.equal(validateGroupPage(page(p), ctx, p).items[0].article_version_id, 888)
  for (const change of [d => d.context.scope_id = 2, d => d.context.tenant_id = 202, d => d.items[0].task_id = 888,
    d => d.items[1].article_version_id = 1, d => d.counts = {}, d => d.completeness.complete = false]) {
    const data = structuredClone(page(p)); change(data)
    assert.throws(() => validateGroupPage(data, ctx, p))
  }
})

test('API only calls new exact GET with explicit scope and strict query whitelist', async () => {
  const calls = []
  const client = createDistributionInboxApi({ getBusiness: () => ({ token: 'synthetic', revision: 1 }),
    fetchImpl: async (url, options) => { calls.push([url, options]); return { ok: true, json: async () => page() } } })
  await client.publicationGroups(101, 1, { article_id: 1, limit: 100 })
  const [url, options] = calls[0]
  assert.match(url, /^\/api\/v1\/geo\/distribution\/v2\/publication-groups\?tenant_id=101&scope_id=1&article_id=1&limit=100$/)
  assert.equal(options.method, 'GET'); assert.equal(options.cache, 'no-store'); assert.equal(options.body, undefined)
  for (const params of [{ site_id: 1 }, { article_id: Number.MAX_SAFE_INTEGER + 1 }, { bucket: 'unlinked', article_id: 1 }, { limit: 101 }]) assert.throws(() => client.publicationGroups(101, 1, params))
  assert.throws(() => client.publicationGroups(101, null))
})

test('list and article details paginate independently while keeping global counts', async () => {
  const calls = []
  const state = createPublicationGroupsState({ publicationGroups: async (tid, pid, params) => {
    calls.push(params)
    return page(params, null, !params.cursor)
  } })
  await state.refresh(ctx)
  await state.detail(1)
  await state.detail(1, true)
  await state.list('linked', true)
  assert.equal(state.state.groups.length, 1)
  assert.equal(state.state.details[1].length, 2)
  assert.equal(state.state.counts.native_records, 2)
  assert.equal(state.state.counts.article_groups, 1)
  assert.deepEqual(calls.at(-2), { bucket: 'linked', article_id: 1, limit: 20, cursor: 'cursor-signed' })
  assert.deepEqual(calls.at(-1), { bucket: 'linked', limit: 20, cursor: 'cursor-signed' })
})

test('Shanghai times have exact date format including midnight', () => {
  assert.equal(publicationTime('2026-10-23T02:45:00Z'), '2026-10-23 10:45')
  assert.equal(publicationTime('2026-10-22T16:00:00Z'), '2026-10-23 00:00')
})

test('twenty per page replaces rows and previous rereads its original cursor', async () => {
  const calls = []
  const model = createPublicationGroupsState({ publicationGroups: async (tid, pid, params) => {
    calls.push(params)
    return page(params, params.bucket === 'linked' ? [{ ...group, group_article_id: params.cursor ? 2 : 1, task_id: params.cursor ? 2 : 1 }] : [], !params.cursor)
  } })
  await model.refresh(ctx)
  assert.equal(calls[0].limit, 20)
  await model.list('linked', true)
  assert.equal(model.state.pages.linked, 2)
  assert.deepEqual(model.state.groups.map(g => g.task_id), [2])
  await model.list('linked', 'previous')
  assert.deepEqual(calls.at(-1), { bucket: 'linked', limit: 20 })
  assert.equal(model.state.pages.linked, 1)
  assert.deepEqual(model.state.groups.map(g => g.task_id), [1])
})

test('late response after scope/identity clear cannot restore records', async () => {
  let resolve
  const pending = new Promise(r => { resolve = r })
  const model = createPublicationGroupsState({ publicationGroups: () => pending })
  const reading = model.refresh(ctx)
  model.clear(); resolve(page())
  await reading
  assert.equal(model.state.groups.length, 0); assert.equal(model.state.counts, null)
})

test('task-only reads always include article and project, with no tenant-wide fetch', async () => {
  const calls = []
  const model = createPublicationGroupsState(api((...args) => calls.push(args)))
  await model.refresh({ ...ctx, taskId: 1 })
  assert.deepEqual(calls, [[101, 1, { bucket: 'linked', article_id: 1, limit: 20 }]])
  await model.refresh({ ...ctx, projectId: null, taskId: 1 })
  assert.equal(calls.length, 1); assert.deepEqual(model.state.groups, [])
})

test('403/409/cursor errors invalidate cached records; 503 preserves records with visible error', async () => {
  for (const status of [400, 403, 409, 503]) {
    let fail = false
    const model = createPublicationGroupsState({ publicationGroups: async (tid, pid, params) => {
      if (fail) throw Object.assign(new Error('测试读取失败'), { status })
      return page(params)
    } })
    await model.refresh(ctx); fail = true
    await model.detail(1)
    assert.match(model.state.error, /测试读取失败/)
    assert.equal(model.state.groups.length, status === 503 ? 1 : 0)
    if (status !== 503) assert.equal(model.state.counts, null)
  }
})

test('revision mismatch never combines independent requests into an apparently complete list', async () => {
  let n = 0
  const model = createPublicationGroupsState({ publicationGroups: async (tid, pid, params) => page(params, null, false, `r${n++}`) })
  await model.refresh(ctx)
  assert.match(model.state.error, /已变化/)
  assert.deepEqual(model.state.groups, []); assert.equal(model.state.counts, null)
})

test('inbox focus rereads exact receipt beyond paged list and clear invalidates it', async () => {
  const calls = []
  const model = createInboxState({ receipt: async id => { calls.push(id); return { id, revision: 3 } } })
  await model.focus(rid)
  assert.equal(model.state.focused.id, rid); assert.deepEqual(calls, [rid])
  model.clear(); assert.equal(model.state.focused, null)
})

test('409 keeps inbox row and requires manual candidate reread; no automatic new label', async () => {
  let calls = 0
  const model = createInboxState({ receipt: async id => ({ id }), label: async () => {
    calls++; throw Object.assign(new Error('版本冲突'), { status: 409 })
  } })
  await model.focus(rid)
  await model.label({ id: rid, revision: 1 }, { module: 'geo', tenantId: 101, scopeId: 1, article: { id: 1, version: 2, digest: 'fixed' } })
  assert.equal(calls, 1); assert.equal(model.state.conflict, true); assert.equal(model.state.focused.id, rid)
})

test('successful unlabel/archive/delete remove the focused card even if list reload fails', async () => {
  const beforeConfirm = globalThis.confirm
  globalThis.confirm = () => true
  try {
    for (const action of ['unlabel', 'archive', 'remove']) {
      let failMutation = true
      const row = { id: rid, revision: 1, assignment: { module: 'geo', tenantId: 101 } }
      const mutate = async () => { if (failMutation) throw Object.assign(new Error('conflict'), { status: 409 }) }
      const model = createInboxState({ receipt: async () => row, unlabel: mutate, archive: mutate, delete: mutate,
        receipts: async () => { throw new Error('list unavailable') }, devices: async () => ({ items: [] }), count: async () => ({ count: 0 }) })
      await model.focus(rid)
      await model[action](row)
      assert.equal(model.state.focused.id, rid, `${action} failure must preserve the row`)
      failMutation = false
      await model[action](row)
      assert.equal(model.state.focused, null, `${action} success must not retain old content/assignment`)
      assert.equal(model.state.error, 'list unavailable')
    }
  } finally { globalThis.confirm = beforeConfirm }
})
