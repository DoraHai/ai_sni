import assert from 'node:assert/strict'
import test from 'node:test'

import { geoSessionRouteDecision, installGeoAuthContextRouting } from '../src/authRouteDecision.js'

function decide({ loggedIn = true, level = 'view', route = { meta: { perm: 'geo.content' } }, devBypass = false } = {}) {
  const calls = []
  const result = geoSessionRouteDecision({
    route,
    session: {
      isLoggedIn: loggedIn,
      canView: permission => permission === 'geo.content' && ['view', 'edit'].includes(level),
    },
    devBypass,
    redirectToLogin: () => calls.push('login'),
    leaveWorkspace: () => { calls.push('portal'); return false },
  })
  return { result, calls }
}

test('public GEO route remains accessible without a session', () => {
  assert.deepEqual(decide({ loggedIn: false, level: undefined, route: { meta: { public: true } } }), {
    result: true,
    calls: [],
  })
})

test('missing session redirects to login', () => {
  assert.deepEqual(decide({ loggedIn: false }), { result: false, calls: ['login'] })
})

test('ordinary view and edit roles can open GEO routes', () => {
  assert.deepEqual(decide({ level: 'view' }), { result: true, calls: [] })
  assert.deepEqual(decide({ level: 'edit' }), { result: true, calls: [] })
})

test('a logged-in role without geo.content leaves the GEO workspace', () => {
  assert.deepEqual(decide({ level: 'none' }), { result: false, calls: ['portal'] })
})

test('development API-key bypass remains explicit policy input', () => {
  assert.deepEqual(decide({ loggedIn: false, level: undefined, devBypass: true }), {
    result: true,
    calls: [],
  })
})

function storageHarness() {
  const browser = new EventTarget()
  browser.localStorage = {}
  let reloads = 0
  let revalidations = 0
  const remove = installGeoAuthContextRouting(browser, {
    eventName: 'sem:auth-context-changed',
    revalidate: () => { revalidations += 1 },
    reload: () => { reloads += 1 },
  })
  const storageEvent = (key, storageArea = browser.localStorage) => {
    const event = new Event('storage')
    Object.defineProperties(event, { key: { value: key }, storageArea: { value: storageArea } })
    browser.dispatchEvent(event)
  }
  return { browser, remove, storageEvent, reloads: () => reloads, revalidations: () => revalidations }
}

test('current-tab auth context changes revalidate without reloading', () => {
  const { browser, revalidations, reloads } = storageHarness()
  browser.dispatchEvent(new Event('sem:auth-context-changed'))
  assert.equal(revalidations(), 1)
  assert.equal(reloads(), 0)
})

test('persistent token changes reload the standalone GEO app', () => {
  const { storageEvent, reloads } = storageHarness()
  storageEvent('sem_token')
  assert.equal(reloads(), 1)
})

test('persistent user and permission changes reload the standalone GEO app', () => {
  const { storageEvent, reloads } = storageHarness()
  storageEvent('sem_user')
  assert.equal(reloads(), 1)
})

test('tenant selection and another storage area do not reload GEO', () => {
  const { storageEvent, reloads } = storageHarness()
  storageEvent('sem_tenant_id')
  storageEvent('sem_token', {})
  assert.equal(reloads(), 0)
})

test('removing the GEO storage listener stops later reloads', () => {
  const { remove, storageEvent, reloads } = storageHarness()
  remove()
  storageEvent('sem_token')
  assert.equal(reloads(), 0)
})

test('invalid storage routing dependencies fail closed', () => {
  assert.throws(() => installGeoAuthContextRouting(null, {}), /INVALID_GEO_AUTH_ROUTE_REVALIDATION/)
  assert.throws(() => installGeoAuthContextRouting(new EventTarget(), {}), /INVALID_GEO_AUTH_ROUTE_REVALIDATION/)
})

class MemoryStorage {
  constructor() { this.values = new Map() }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null }
  setItem(key, value) { this.values.set(key, String(value)) }
  removeItem(key) { this.values.delete(key) }
}

test('real session mutations revalidate private GEO routes in the current tab', async () => {
  const browser = new EventTarget()
  browser.localStorage = new MemoryStorage()
  browser.sessionStorage = new MemoryStorage()
  globalThis.window = browser
  globalThis.localStorage = browser.localStorage
  globalThis.sessionStorage = browser.sessionStorage

  const { AUTH_CONTEXT_EVENT, session } = await import('../../src/store/session.js?geo-auth-route-test')
  let route = { meta: { perm: 'geo.content' } }
  const destinations = []
  let reloads = 0
  const revalidate = () => geoSessionRouteDecision({
    route,
    session,
    redirectToLogin: () => destinations.push('login'),
    leaveWorkspace: () => { destinations.push('portal'); return false },
  })
  const remove = installGeoAuthContextRouting(browser, {
    eventName: AUTH_CONTEXT_EVENT,
    revalidate,
    reload: () => { reloads += 1 },
  })

  session.setAuth('token', { id: 5, tenant_id: 16, permissions: { 'geo.content': 'view' } })
  assert.deepEqual(destinations, [])

  session.refreshUser({ id: 5, tenant_id: 16, permissions: { 'geo.content': 'none' } })
  assert.deepEqual(destinations, ['portal'])

  route = { meta: { public: true } }
  session.refreshUser({ id: 5, tenant_id: 16, permissions: {} })
  assert.deepEqual(destinations, ['portal'])

  route = { meta: { perm: 'geo.content' } }
  session.logout()
  assert.deepEqual(destinations, ['portal', 'login'])
  assert.equal(reloads, 0)

  remove()
  delete globalThis.window
  delete globalThis.localStorage
  delete globalThis.sessionStorage
})
