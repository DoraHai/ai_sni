import assert from 'node:assert/strict'
import { AUTH_ENVELOPE_KEY } from '../src/store/sessionStorage.js'
import { installAuthContextRouting } from '../src/router/authContextRouting.js'

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

const authEvents = []
browser.addEventListener('sem:auth-context-changed', event => authEvents.push(event.detail.kind))
let routeRevalidations = 0
installAuthContextRouting(browser, 'sem:auth-context-changed', () => { routeRevalidations += 1 })

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
assert.equal(session.user.permissions['geo.content'], 'view')
local.setItem(AUTH_ENVELOPE_KEY, JSON.stringify({
  version: 1, token: 'persistent-d', user: user(4, null, 'edit'),
}))
storageEvent(AUTH_ENVELOPE_KEY)
assert.equal(session.user.permissions['geo.content'], 'edit')
assert.equal(session.tenantId, 40)

// A different persistent identity clears the old selection and applies only a
// server-provided bound tenant.
local.setItem('sem_user', JSON.stringify(user(5, 50)))
local.setItem('sem_token', 'persistent-e')
storageEvent('sem_token')
assert.equal(session.user.id, 4)
local.setItem(AUTH_ENVELOPE_KEY, JSON.stringify({
  version: 1, token: 'persistent-e', user: user(5, 50),
}))
storageEvent(AUTH_ENVELOPE_KEY)
assert.equal(session.user.id, 5)
assert.equal(session.tenantId, 50)

local.removeItem(AUTH_ENVELOPE_KEY)
storageEvent(AUTH_ENVELOPE_KEY)
assert.equal(session.isLoggedIn, false)
assert.equal(session.user, null)
assert.equal(session.tenantId, null)
assert.equal(authEvents.at(-1), 'logout')
assert.ok(routeRevalidations > 0)

// A response issued under an older identity/permission revision must not reach
// a page after a cross-tab update or permission refresh.
session.setAuth('late-token', user(6, 60), false)
const { default: client } = await import('../src/api/client.js')
let finishRequest
const oldRequest = client.get('/api/v1/test-stale-auth', {
  adapter: config => new Promise(resolve => {
    finishRequest = () => resolve({ data: { secret: true }, status: 200, statusText: 'OK', headers: {}, config })
  }),
})
await new Promise(resolve => setTimeout(resolve, 0))
session.refreshUser(user(6, 60, 'edit'))
finishRequest()
await assert.rejects(oldRequest, error => error.code === 'AUTH_CONTEXT_CHANGED')

console.log('Session store pairing and cross-tab synchronization passed')
