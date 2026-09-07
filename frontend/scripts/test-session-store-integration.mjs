import assert from 'node:assert/strict'

class MemoryStorage {
  constructor(initial = {}) { this.values = new Map(Object.entries(initial)) }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null }
  setItem(key, value) { this.values.set(key, String(value)) }
  removeItem(key) { this.values.delete(key) }
}

const user = (id, tenantId = null, level = 'view') => ({
  id, tenant_id: tenantId, permissions: { 'geo.content': level },
})
const local = new MemoryStorage({ sem_token: 'persistent-a', sem_user: JSON.stringify(user(1, 10)) })
const tab = new MemoryStorage({ sem_token: 'tab-b', sem_user: JSON.stringify(user(2, 20)), sem_tenant_id: '20' })
const browser = new EventTarget()
globalThis.window = browser
globalThis.localStorage = local
globalThis.sessionStorage = tab

function storageEvent(key) {
  const event = new Event('storage')
  Object.defineProperties(event, {
    key: { value: key },
    storageArea: { value: local },
  })
  browser.dispatchEvent(event)
}

const { session } = await import('../src/store/session.js')
assert.equal(session.token, 'tab-b')
assert.equal(session.user.id, 2)
assert.equal(session.tenantId, 20)

// A persistent login in another tab cannot replace this tab's explicit session.
local.setItem('sem_token', 'persistent-c')
local.setItem('sem_user', JSON.stringify(user(3, 30)))
storageEvent('sem_token')
assert.equal(session.token, 'tab-b')
assert.equal(session.user.id, 2)

session.logout()
assert.equal(session.isLoggedIn, false)
assert.equal(session.tenantId, null)
assert.equal(tab.getItem('sem_tenant_id'), null)

session.setTenant(99)
session.setAuth('persistent-d', user(4), true)
assert.equal(session.tenantId, null)
session.setTenant(40)
local.setItem('sem_user', JSON.stringify(user(4, null, 'edit')))
storageEvent('sem_user')
assert.equal(session.user.permissions['geo.content'], 'edit')
assert.equal(session.tenantId, 40)

// A different persistent identity clears the old selection and applies only a
// server-provided bound tenant.
local.setItem('sem_user', JSON.stringify(user(5, 50)))
local.setItem('sem_token', 'persistent-e')
storageEvent('sem_token')
assert.equal(session.user.id, 5)
assert.equal(session.tenantId, 50)

local.removeItem('sem_token')
storageEvent('sem_token')
assert.equal(session.isLoggedIn, false)
assert.equal(session.user, null)
assert.equal(session.tenantId, null)

console.log('Session store pairing and cross-tab synchronization passed')
