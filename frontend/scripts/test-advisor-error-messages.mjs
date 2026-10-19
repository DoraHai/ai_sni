import assert from 'node:assert/strict'
class Storage {
  values = new Map()
  get length() { return this.values.size }
  key(index) { return [...this.values.keys()][index] }
  getItem(key) { return this.values.get(key) ?? null }
  setItem(key, value) { this.values.set(key, String(value)) }
  removeItem(key) { this.values.delete(key) }
}
globalThis.window = new EventTarget()
globalThis.localStorage = new Storage()
globalThis.sessionStorage = new Storage()
const { session } = await import('../src/store/session.js')
const { default: client } = await import('../src/api/client.js')
session.setAuth('local-display-fixture', { id: 7, tenant_id: null, permissions: {} }, false)
try {
  await assert.rejects(client.get('/api/v1/users/1', {
    adapter: config => Promise.reject({ config, response: { status: 403, data: { detail: {
      code: 'ADVISOR_NAMED_ADMIN_REQUIRED', message: '需要未绑定客户的实名超级管理员',
    } } } }),
  }), { message: '需要未绑定客户的实名超级管理员', status: 403, code: 'ADVISOR_NAMED_ADMIN_REQUIRED' })
  console.log('advisor errors: Chinese server message and error code are preserved')
} finally { session.logout() }
