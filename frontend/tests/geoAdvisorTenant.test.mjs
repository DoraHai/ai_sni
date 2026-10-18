import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import {
  bootstrapGeoSession, GEO_ADVISOR_SELECT_URL,
  GEO_ADVISOR_SELECTION_MESSAGE, GEO_ADVISOR_NO_TENANT_MESSAGE,
} from '../src/utils/geoAdvisorTenant.js'
import { selectStoredAuth, writeAuthEnvelope } from '../src/store/sessionStorage.js'

// All credentials in these tests are invented, unsigned test strings.
const jwt = (claims) => `fake.${Buffer.from(JSON.stringify(claims)).toString('base64url')}.fake`
const identity = jwt({ sub: '42', scope_kind: 'advisor_identity' })
const business = (id, extra = {}) => jwt({ sub: '42', scope_kind: 'advisor_tenant', tid: id, gid: 8, ...extra })
const user = { id: 42, tenant_id: null, is_advisor: true, permissions: { 'geo.content': 'view' } }
const selectionError = () => Object.assign(new Error('fake selection error'), {
  code: 'ADVISOR_TENANT_SELECTION_REQUIRED', status: 409,
})
const noTenantError = () => Object.assign(new Error('fake no tenant error'), {
  code: 'ADVISOR_NO_TENANT', status: 403,
})
const memoryStorage = () => {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  }
}
let revision = 0
async function fixture({ rows = [{ id: 15, name: '甲' }, { id: 17, name: '乙' }], defaultId = 15,
  token = identity, initialUser = user, readError, listError, selectError, response, retryError,
  beforeSelectReturn, initialSuccess = false } = {}) {
  const local = memoryStorage()
  const tab = memoryStorage()
  writeAuthEnvelope(local, token, initialUser)
  tab.setItem('sem_tenant_id', '999') // A stale URL/tab customer must never choose a grant.
  globalThis.localStorage = local
  globalThis.sessionStorage = tab
  const { session } = await import(`../src/store/session.js?case=${++revision}`)
  const originalLocal = local.getItem('sem_auth_v1')
  const calls = { reads: 0, profiles: 0, lists: 0, selects: [] }
  const deps = {
    session,
    fetchMe: async () => {
      calls.profiles++
      return { user: { ...initialUser, default_tenant_id: defaultId,
        tenant_id: session.token === token ? initialUser.tenant_id : session.tenantId } }
    },
    fetchGeoTenants: async () => {
      calls.reads++
      if (calls.reads === 1 && !initialSuccess) throw readError || selectionError()
      if (retryError) throw retryError
      return { tenants: rows }
    },
    fetchTenants: async () => {
      calls.lists++
      assert.equal(session.token, identity)
      if (listError) throw listError
      return { tenants: rows }
    },
    selectTenant: async (id) => {
      calls.selects.push(id)
      assert.equal(session.token, identity)
      if (selectError) throw selectError
      beforeSelectReturn?.(session)
      return response || { access_token: business(id), tenant_id: id, tenant_name: '甲',
        token_type: 'bearer', expires_at: '2099-01-01T00:00:00Z' }
    },
  }
  const result = await bootstrapGeoSession(deps)
  return { session, result, calls, local, tab, originalLocal }
}

test('authorized default customer wins; scoped token stays in this tab and survives refresh', async () => {
  const f = await fixture({ defaultId: 17 })
  assert.equal(f.result, null)
  assert.deepEqual(f.calls.selects, [17])
  assert.equal(f.calls.reads, 2)
  assert.equal(f.session.tenantId, 17)
  assert.equal(f.local.getItem('sem_auth_v1'), f.originalLocal)
  assert.equal(f.local.getItem('sem_token'), identity)
  assert.deepEqual(JSON.parse(f.tab.getItem('sem_advisor_identity_v1')), { token: identity, user })
  const envelope = JSON.parse(f.tab.getItem('sem_auth_v1'))
  assert.equal(envelope.version, 1)
  assert.equal(envelope.token, business(17))
  assert.equal(f.tab.getItem('sem_tenant_id'), '17')
  assert.equal(selectStoredAuth(f.local, f.tab).token, business(17))
  const { session: reloaded } = await import(`../src/store/session.js?case=${++revision}`)
  assert.equal(reloaded.token, business(17))
  assert.equal(reloaded.tenantId, 17)
})

test('single authorized customer is selected when default is absent or unauthorized', async () => {
  for (const defaultId of [null, 999]) {
    const f = await fixture({ rows: [{ id: 17, name: '唯一' }], defaultId })
    assert.equal(f.result, null)
    assert.deepEqual(f.calls.selects, [17])
  }
})

test('multiple customers without an authorized default show Chinese guidance', async () => {
  for (const defaultId of [null, 999]) {
    const f = await fixture({ defaultId })
    assert.deepEqual(f.result, { message: GEO_ADVISOR_SELECTION_MESSAGE, selectCustomer: true })
    assert.deepEqual(f.calls.selects, [])
    assert.equal(f.tab.getItem('sem_auth_v1'), null)
    assert.equal(f.session.tenantId, null)
  }
  assert.equal(GEO_ADVISOR_SELECT_URL, '/customer-workbench/?console=advisor')
})

test('empty grants and NO_TENANT from initial read, list, select or retry show exact Chinese text', async () => {
  for (const options of [
    { rows: [] }, { readError: noTenantError() }, { listError: noTenantError() },
    { selectError: noTenantError() }, { retryError: noTenantError() },
  ]) {
    const f = await fixture(options)
    assert.deepEqual(f.result, { message: GEO_ADVISOR_NO_TENANT_MESSAGE, selectCustomer: false })
  }
})

test('non-advisor success and errors preserve existing behavior without auth calls', async () => {
  for (const options of [{}, { initialSuccess: true }, { readError: noTenantError() }]) {
    const f = await fixture({ ...options, token: 'fake-ordinary-token',
      initialUser: { ...user, is_advisor: false, tenant_id: 15 } })
    assert.equal(f.result, null)
    assert.equal(f.calls.lists, 0)
    assert.deepEqual(f.calls.selects, [])
    assert.equal(f.session.token, 'fake-ordinary-token')
    assert.equal(f.tab.getItem('sem_advisor_identity_v1'), null)
  }
})

test('a second selection-required response stops after one selection and one reload', async () => {
  const f = await fixture({ retryError: selectionError() })
  assert.equal(f.result.message, GEO_ADVISOR_SELECTION_MESSAGE)
  assert.deepEqual(f.calls.selects, [15])
  assert.equal(f.calls.lists, 1)
  assert.equal(f.calls.reads, 2)
})

test('business scoped tokens and advisor user hints cannot initiate auto-selection', async () => {
  for (const token of [business(15), 'fake-unscoped-token']) {
    const f = await fixture({ token })
    assert.equal(f.result.message, GEO_ADVISOR_SELECTION_MESSAGE)
    assert.equal(f.calls.lists, 0)
    assert.deepEqual(f.calls.selects, [])
  }
})

test('successful advisor reads and non-409 errors never auto-select a customer', async () => {
  const existing = await fixture({ token: business(17), initialSuccess: true })
  assert.equal(existing.result, null)
  assert.equal(existing.session.tenantId, 17)
  assert.deepEqual(existing.calls.selects, [])
  const wrongStatus = await fixture({ readError: Object.assign(selectionError(), { status: 403 }) })
  assert.equal(wrongStatus.result.message, GEO_ADVISOR_SELECTION_MESSAGE)
  assert.equal(wrongStatus.calls.lists, 0)
  assert.deepEqual(wrongStatus.calls.selects, [])
})

test('malformed grant lists and selection responses never persist business auth', async () => {
  for (const rows of [null, [{ id: -1 }], [{ id: 15 }, { id: 15 }]]) {
    const f = await fixture({ rows })
    assert.equal(f.result.message, GEO_ADVISOR_SELECTION_MESSAGE)
    assert.deepEqual(f.calls.selects, [])
  }
  const good = { access_token: business(15), tenant_id: 15, tenant_name: '甲',
    token_type: 'bearer', expires_at: '2099-01-01T00:00:00Z' }
  for (const patch of [
    { tenant_id: 17 }, { token_type: 'Basic' }, { access_token: '' },
    { expires_at: '' }, { expires_at: '2000-01-01T00:00:00Z' },
    { access_token: business(17) }, { access_token: business(15, { sub: '43' }) },
    { access_token: business(15, { gid: null }) }, { access_token: identity },
  ]) {
    const f = await fixture({ response: { ...good, ...patch } })
    assert.equal(f.result.message, GEO_ADVISOR_SELECTION_MESSAGE)
    assert.equal(f.session.token, identity)
    assert.equal(f.tab.getItem('sem_auth_v1'), null)
  }
})

test('a late selection cannot overwrite a changed login context', async () => {
  const f = await fixture({ beforeSelectReturn: (session) => session.logout() })
  assert.equal(f.result.message, GEO_ADVISOR_SELECTION_MESSAGE)
  assert.equal(f.session.token, '')
  assert.equal(f.tab.getItem('sem_auth_v1'), null)
})

test('legacy pairs work, malformed envelopes fail closed, and logout clears all auth', async () => {
  const local = memoryStorage(), tab = memoryStorage()
  local.setItem('sem_token', identity)
  local.setItem('sem_user', JSON.stringify(user))
  assert.equal(selectStoredAuth(local, tab).token, identity)
  tab.setItem('sem_auth_v1', '{bad-json')
  tab.setItem('sem_token', business(17))
  tab.setItem('sem_user', JSON.stringify(user))
  assert.equal(selectStoredAuth(local, tab).token, identity)
  const f = await fixture()
  f.session.logout()
  assert.equal(selectStoredAuth(f.local, f.tab), null)
  assert.equal(f.tab.getItem('sem_advisor_identity_v1'), null)
})

test('Vue entry gates business pages behind bootstrap and renders the customer button', () => {
  const app = readFileSync(new URL('../geo-frontend/src/App.vue', import.meta.url), 'utf8')
  assert.match(app, /await bootstrapGeoSession/)
  assert.match(app, /ready && guidance/)
  assert.match(app, /router-view v-else-if="ready"/)
  assert.match(app, /:href="GEO_ADVISOR_SELECT_URL"/)
  assert.match(app, /去选择客户/)
})
