import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createSeoAiRequester } from '../src/api/seoAiRequests.js'

test('uncertain transport retry retains ID; successful next action gets a new ID', async () => {
  const ids = []; let attempt = 0; let next = 0
  const request = createSeoAiRequester(async (_, payload) => {
    ids.push(payload.request_id)
    if (++attempt === 1) throw new Error('connection lost')
    return { action: 'title', title: 'draft' }
  }, () => 'user1', () => `request-${++next}`)
  await assert.rejects(request('/assist', { tenant_id: 1, action: 'title' }))
  await request('/assist', { action: 'title', tenant_id: 1 })
  await request('/assist', { tenant_id: 1, action: 'title' })
  assert.deepEqual(ids, ['request-1', 'request-1', 'request-2'])
})

test('in-progress keeps ID; refunded operation permits a fresh action', async () => {
  const ids = []; let next = 0
  const responses = [{ detail: { code: 'operation_running', message: '处理中' } },
    { detail: { code: 'operation_refunded', message: '已退还' } }, { action: 'title' }]
  const request = createSeoAiRequester(async (_, payload) => {
    ids.push(payload.request_id); return responses.shift()
  }, () => 'user1', () => `request-${++next}`)
  await assert.rejects(request('/assist', { tenant_id: 1 }))
  await assert.rejects(request('/assist', { tenant_id: 1 }))
  await request('/assist', { tenant_id: 1 })
  assert.deepEqual(ids, ['request-1', 'request-1', 'request-2'])
})

test('concurrent clicks share one transport; actor and tenant changes isolate requests', async () => {
  let release; let scope = 'actor1'; let next = 0; const ids = []
  const request = createSeoAiRequester(async (_, payload) => {
    ids.push(payload.request_id)
    if (ids.length === 1) return await new Promise(resolve => { release = resolve })
    throw new Error('unknown')
  }, () => scope, () => `request-${++next}`)
  const first = request('/assist', { tenant_id: 1 }); const duplicate = request('/assist', { tenant_id: 1 })
  assert.equal(ids.length, 1)
  scope = 'actor2'
  await assert.rejects(request('/assist', { tenant_id: 1 }))
  release({ action: 'title' }); await Promise.all([first, duplicate])
  await assert.rejects(request('/assist', { tenant_id: 1 }))
  await assert.rejects(request('/assist', { tenant_id: 2 }))
  assert.deepEqual(ids, ['request-1', 'request-2', 'request-2', 'request-3'])
})

test('refresh restores request ID without storing draft or account credentials', async () => {
  const map = new Map()
  const storage = { getItem: key => map.get(key) || null, setItem: (key, value) => map.set(key, value) }
  const ids = []; let next = 0
  const send = async (_, payload) => { ids.push(payload.request_id); throw new Error('network lost') }
  const build = () => createSeoAiRequester(send, () => 'sensitive-user-token', () => `request-00000000-${++next}`, { storage: () => storage })
  await assert.rejects(build()('/assist', { tenant_id: 1, draft: '不能落入浏览器存储的正文' }))
  await assert.rejects(build()('/assist', { tenant_id: 1, draft: '不能落入浏览器存储的正文' }))
  assert.equal(ids[0], ids[1])
  assert.doesNotMatch([...map.values()].join(''), /正文|sensitive-user-token|draft/)
  const other = createSeoAiRequester(send, () => 'other-user', () => 'request-00000000-9', { storage: () => storage })
  await assert.rejects(other('/assist', { tenant_id: 1, draft: '不能落入浏览器存储的正文' }))
  assert.notEqual(ids[1], ids[2])
})

test('unavailable or corrupt recovery storage fails before sending an AI operation', async () => {
  let calls = 0
  const request = createSeoAiRequester(async () => { calls++ }, () => 'user', () => 'request-00000000-1', {
    storage: () => ({ getItem: () => '{}', setItem: () => { throw new Error('quota') } }),
  })
  await assert.rejects(request('/assist', { tenant_id: 1 }), /保存请求标识/)
  assert.equal(calls, 0)
})
