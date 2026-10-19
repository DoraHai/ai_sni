import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { createDistributionInboxApi, INBOX_PREFIX } from '../src/api/distributionInbox.js'
import { createInboxState } from '../src/views/seo/distributionInboxState.js'

const id = '11111111-1111-4111-8111-111111111111'
const pending = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data })
const fixture = () => {
  const calls = []
  let identity = { token: 'synthetic-identity', revision: 1, scopeKind: 'advisor_identity' }
  let business = { token: 'synthetic-business', revision: 1 }
  const api = createDistributionInboxApi({ getIdentity: () => identity, getBusiness: () => business,
    fetchImpl: async (path, config) => { calls.push({ path, config }); return response({ schema: 2, items: [], count: 0 }) } })
  return { api, calls, identity: value => { identity = value }, business: value => { business = value } }
}

test('vectors use Node JSON.stringify + SHA256 exactly', async () => {
  const vectors = JSON.parse(await readFile(new URL('../../tests/fixtures/inbox_vectors_v2.json', import.meta.url), 'utf8'))
  assert.equal(vectors.events[0].event.platform, '新平台')
  assert.equal(vectors.events[0].event.title, '合成标题 😀')
  const keys = ['schema','eventId','attemptId','occurredAt','platform','title','reportedAccount','result','reasonCode','publicUrl','reviewed']
  for (const vector of vectors.events) {
    const encoded = JSON.stringify(keys.map(key => vector.event[key]))
    assert.equal(encoded, vector.canonicalJson)
    assert.equal(createHash('sha256').update(encoded).digest('hex'), vector.event.payloadDigest)
  }
})

test('pairing is one click with no tenant/module/platform and no cookies', async () => {
  const { api, calls } = fixture()
  await api.createPairing()
  assert.equal(calls[0].path, INBOX_PREFIX + '/pairings')
  assert.deepEqual(JSON.parse(calls[0].config.body), {})
  assert.deepEqual(calls[0].config.headers, { Authorization: 'Bearer synthetic-identity', 'Content-Type': 'application/json' })
  assert.equal(calls[0].config.credentials, 'omit')
  assert.equal(calls[0].config.redirect, 'error')
  assert.equal(calls[0].config.cache, 'no-store')
})

test('all identity endpoints use only fixed SEO paths and explicit selectors', async () => {
  const { api, calls } = fixture()
  await api.cancelPairing(id, 0); await api.receipts({ state: 'pending', q: '合成 & 公开' }); await api.count({ state: 'pending' })
  await api.receipt(id); await api.devices(); await api.revoke(id, 1); await api.archive(id, 1); await api.delete(id, 1)
  assert.equal(calls.length, 8)
  assert(calls.every(c => c.path.startsWith(INBOX_PREFIX+'/')))
  assert(calls.every(c => !c.path.includes('tenant_id') && !c.path.includes('project_id')))
  assert(calls.every(c => c.config.headers.Authorization === 'Bearer synthetic-identity'))
  assert.equal(new URL(calls[1].path, 'https://synthetic.invalid').searchParams.get('q'), '合成 & 公开')
})

test('unexpected selectors and malformed IDs cannot become routes', async () => {
  const { api, calls } = fixture()
  for (const query of [{ tenant_id: 1 }, { project_id: 1 }, { state: 'all' }, { q: 'x'.repeat(101) }, { limit: true }, { offset: -1 }]) {
    assert.throws(() => api.receipts(query), TypeError)
  }
  assert.throws(() => api.count({ limit: 50 }), TypeError)
  for (const bad of ['../devices', id+'/label', 'not-uuid', { toString: () => id }]) assert.throws(() => api.receipt(bad), TypeError)
  assert.equal(calls.length, 0)
})

test('label/unlabel use selected module business JWT and tenant, never identity', async () => {
  const { api, calls } = fixture()
  await api.label('geo', 42, id, { expectedRevision: 1, targetTenant: 42 })
  await api.unlabel('seo', 43, id, { expectedRevision: 2, reason: '合成' })
  assert.equal(calls[0].path, `/api/v1/geo/distribution/v2/receipts/${id}/label?tenant_id=42`)
  assert.equal(calls[1].path, `/api/v1/seo/distribution/v2/receipts/${id}/unlabel?tenant_id=43`)
  assert(calls.every(c => c.config.headers.Authorization === 'Bearer synthetic-business'))
  assert.throws(() => api.label('anything', 42, id, {}), TypeError)
  assert.throws(() => api.label('seo', true, id, {}), TypeError)
})

test('missing identity never falls back to a business JWT or API key', async () => {
  const { api, calls, identity } = fixture()
  identity(null)
  await assert.rejects(api.devices(), { code: 'INBOX_IDENTITY_REQUIRED' })
  identity({ token: 'synthetic-business', revision: 2, scopeKind: 'advisor_tenant' })
  await assert.rejects(api.devices(), { code: 'INBOX_IDENTITY_REQUIRED' })
  assert.equal(calls.length, 0)
})

test('identity/permission changes discard late API successes and errors', async () => {
  for (const status of [200, 403]) {
    const delayed = pending()
    let context = { token: 'synthetic-identity', revision: 1 }
    const api = createDistributionInboxApi({ getIdentity: () => context, fetchImpl: () => delayed.promise })
    const result = api.devices()
    context = { ...context, revision: 2 }
    delayed.resolve(response({ items: [{ label: 'old private record' }] }, status))
    await assert.rejects(result, { code: 'AUTH_CONTEXT_CHANGED' })
  }
})

test('503 and capacity refusal preserve fixed Chinese errors', async () => {
  for (const [status, code, message] of [[503, 'INBOX_SCHEMA_NOT_READY', '功能尚未准备好'], [429, 'INBOX_CAPACITY_EXCEEDED', '待标记录已满']]) {
    const api = createDistributionInboxApi({ getIdentity: () => ({ token: 'synthetic', revision: 1 }),
      fetchImpl: async () => response({ detail: { code, message } }, status) })
    await assert.rejects(api.devices(), { status, code, message })
  }
})

function modelFixture() {
  const calls = []
  const api = {
    receipts: async () => ({ items: [{ id, revision: 1, assignment: null }] }), devices: async () => ({ items: [] }), count: async () => ({ count: 1 }),
    createPairing: async () => ({ pairingCode: 'synthetic-once' }), revoke: async (...args) => calls.push(['revoke', ...args]),
    label: async (...args) => calls.push(['label', ...args]), unlabel: async (...args) => calls.push(['unlabel', ...args]),
  }
  const model = createInboxState(api)
  return { api, model, calls }
}

test('identity reset clears visible records/code immediately and ignores late pairing/list responses', async () => {
  for (const operation of ['pair', 'refresh']) {
    const { api, model } = modelFixture()
    const delayed = pending()
    if (operation === 'pair') api.createPairing = () => delayed.promise
    else api.receipts = () => delayed.promise
    const result = model[operation]()
    model.clear()
    delayed.resolve(operation === 'pair' ? { pairingCode: 'old-private-code' } : { items: [{ id: 'old-private-record' }] })
    await result
    assert.deepEqual(model.state, { items: [], devices: [], count: 0, pairing: null, busy: false, error: '' })
  }
})

test('clear during mutation never starts a list request in the new identity', async () => {
  const { api, model } = modelFixture()
  const delayed = pending(); let reads = 0
  api.revoke = () => delayed.promise
  api.receipts = async () => { reads += 1; return { items: [] } }
  const result = model.revoke({ id, revision: 1 }); model.clear(); delayed.resolve({})
  await result
  assert.equal(reads, 0)
})

test('failed unlabel never writes a new target and preserves the existing record', async () => {
  const { api, model, calls } = modelFixture()
  await model.refresh()
  const receipt = { id, revision: 3, assignment: { tenantId: 42, module: 'geo' } }
  api.unlabel = async () => { throw new Error('无权在原客户撤销') }
  await model.unlabel(receipt)
  assert.equal(model.state.items.length, 1)
  assert.equal(model.state.error, '无权在原客户撤销')
  assert.equal(calls.length, 0)
})

test('successful unlabel and later failed label leave event pending; no atomic cross-target claim', async () => {
  const { api, model, calls } = modelFixture()
  const receipt = { id, revision: 3, assignment: { tenantId: 42, module: 'geo' } }
  await model.unlabel(receipt)
  assert.equal(calls[0][0], 'unlabel')
  assert.deepEqual(calls[0].slice(1, 5), ['geo', 42, id, { expectedRevision: 3, reason: '人工撤销归属' }])
  assert.equal(model.state.items[0].assignment, null)
  api.label = async () => { throw new Error('目标客户授权已撤回') }
  await model.label(model.state.items[0], { module: 'seo', tenantId: 43 })
  assert.equal(model.state.items[0].assignment, null)
  assert.equal(model.state.error, '目标客户授权已撤回')
})

test('repeated clicks do not create multiple pairing requests', async () => {
  const { api, model } = modelFixture()
  const delayed = pending(); let calls = 0
  api.createPairing = () => { calls += 1; return delayed.promise }
  const result = model.pair(); await model.pair(); assert.equal(calls, 1)
  delayed.resolve({ pairingCode: 'synthetic' }); await result
  assert.equal(model.state.busy, false)
})
