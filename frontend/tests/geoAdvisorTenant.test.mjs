import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import {
  bootstrapGeoSession, GEO_ADVISOR_SELECT_URL,
  GEO_ADVISOR_SELECTION_MESSAGE, GEO_ADVISOR_NO_TENANT_MESSAGE, GEO_ADVISOR_RETRY_MESSAGE,
} from '../src/utils/geoAdvisorTenant.js'
import { selectStoredAuth, writeAuthEnvelope } from '../src/store/sessionStorage.js'
import { geoSessionRouteDecision, installGeoAuthContextRouting } from '../geo-frontend/src/authRouteDecision.js'

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
  token = identity, initialUser = user, readError, profileError, listError, selectError, response, retryError,
  beforeSelectReturn, initialSuccess = false, geoRows = rows, unavailableReason } = {}) {
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
    readSession: () => Promise.all([deps.fetchMe(), deps.fetchGeoTenants()]),
    applySession: (me, tenants) => {
      if (me?.user) session.refreshUser(me.user)
      session.setTenants(tenants.tenants || [])
    },
    fetchMe: async () => {
      calls.profiles++
      if (profileError && calls.profiles > 1) throw profileError
      return { user: { ...initialUser, default_tenant_id: defaultId,
        tenant_id: session.token === token ? initialUser.tenant_id : session.tenantId } }
    },
    fetchGeoTenants: async () => {
      calls.reads++
      if (calls.reads === 1 && !initialSuccess) throw readError || selectionError()
      if (retryError) throw retryError
      return { tenants: geoRows, unavailable_reason: unavailableReason }
    },
    listAuthorizedCustomers: async () => {
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
  for (const options of [{}, { initialSuccess: true }, { readError: noTenantError() },
    { readError: new Error('fake network error') },
    { readError: Object.assign(new Error('fake unavailable service'), { status: 503 }) }]) {
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

test('second selected customer mounts only when GEO eligibility is satisfied', async () => {
  const available = await fixture({ token: business(17), initialSuccess: true, geoRows: [{ id: 17, name: '乙' }] })
  assert.equal(available.result, null)
  assert.equal(available.session.tenantId, 17)
  for (const reason of ['当前客户没有分配给你的有效 GEO 项目，请让超管核对项目顾问。',
    '当前客户的 GEO 未开通、已停用或已到期，请让超管核对有效期。']) {
    const f = await fixture({ token: business(17), initialSuccess: true, geoRows: [], unavailableReason: reason })
    assert.deepEqual(f.result, { message: reason, selectCustomer: true })
    assert.equal(f.session.tenantId, 17)
    assert.deepEqual(f.session.tenants, [])
    assert.deepEqual(f.calls.selects, [])
  }
  const fallback = await fixture({ token: business(17), initialSuccess: true, geoRows: [{ id: 15 }] })
  assert.match(fallback.result.message, /GEO 模块.*有效期.*项目管理/)
  assert.equal(fallback.session.tenantId, 17, 'an unavailable second customer cannot fall back to the first')
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
  const logout = f.session.logout
  logout()
  assert.equal(selectStoredAuth(f.local, f.tab), null)
  assert.equal(f.tab.getItem('sem_advisor_identity_v1'), null)
  assert.equal(f.session.tenantId, null)
  assert.equal(f.tab.getItem('sem_tenant_id'), null)
  f.session.setAuth('fake-ordinary-token', { id: 99, tenant_id: null, permissions: {} }, false)
  f.session.setTenants([{ id: 17 }, { id: 15 }])
  assert.equal(f.session.tenantId, 17, 'a new login must not reuse the previous customer')
})

test('legacy and envelope caches retain unknown permission levels without granting access', async () => {
  for (const level of ['none', 'future-level', '', null, false, 1, { level: 'edit' }]) {
    const cachedUser = { ...user, permissions: { 'geo.content': 'view', 'settings.accounts': level } }
    for (const storage of ['local', 'session']) {
      for (const envelope of [false, true]) {
        const local = memoryStorage(), tab = memoryStorage()
        const store = storage === 'local' ? local : tab
        if (envelope) writeAuthEnvelope(store, identity, cachedUser)
        else {
          store.setItem('sem_token', identity)
          store.setItem('sem_user', JSON.stringify(cachedUser))
        }
        assert.deepEqual(selectStoredAuth(local, tab), { token: identity, user: cachedUser, storage })
        globalThis.localStorage = local
        globalThis.sessionStorage = tab
        const { session } = await import(`../src/store/session.js?case=${++revision}`)
        assert.equal(session.isLoggedIn, true)
        assert.equal(session.canView('geo.content'), true)
        assert.equal(session.canEdit('geo.content'), false)
        assert.equal(session.canView('settings.accounts'), false)
        assert.equal(session.canEdit('settings.accounts'), false)
        assert.equal(session.canManage, false)
        const refreshed = { ...cachedUser, display_name: '刷新后的测试用户' }
        assert.doesNotThrow(() => session.refreshUser(refreshed))
        assert.deepEqual(selectStoredAuth(local, tab).user, refreshed)
        assert.equal(session.canManage, false)
      }
    }
    const f = await fixture({ initialUser: cachedUser })
    assert.equal(f.result, null)
    assert.deepEqual(f.calls.selects, [15])
    assert.deepEqual(selectStoredAuth(f.local, f.tab).user.permissions['settings.accounts'], level)
    assert.equal(f.session.canManage, false)
  }
})

test('older user shapes and nullable backend user IDs survive persistence and refresh', async () => {
  for (const cachedUser of [{ id: 42 }, { id: 42, permissions: null }, { id: null, tenant_id: null, permissions: {} }]) {
    const local = memoryStorage(), tab = memoryStorage()
    writeAuthEnvelope(local, 'fake-ordinary-token', cachedUser)
    globalThis.localStorage = local
    globalThis.sessionStorage = tab
    const { session } = await import(`../src/store/session.js?case=${++revision}`)
    assert.equal(session.isLoggedIn, true)
    assert.equal(session.canView('geo.content'), false)
    assert.doesNotThrow(() => session.refreshUser(cachedUser))
    assert.deepEqual(selectStoredAuth(local, tab).user, cachedUser)
  }
})

test('network and 5xx failures during initial read or any recovery request show retry guidance once', async () => {
  assert.equal(GEO_ADVISOR_RETRY_MESSAGE, '暂时无法核对客户授权，请刷新重试')
  for (const status of [undefined, 500, 502, 503, 504]) {
    for (const stage of ['readError', 'profileError', 'listError', 'selectError', 'retryError']) {
      const error = Object.assign(new Error('fake unavailable request'), { status })
      const f = await fixture({ [stage]: error })
      assert.deepEqual(f.result, { message: GEO_ADVISOR_RETRY_MESSAGE, selectCustomer: true })
      assert.ok(f.calls.lists <= 1)
      assert.ok(f.calls.selects.length <= 1)
      assert.ok(f.calls.reads <= 2)
    }
  }
})

test('login and advisor selection revalidate routes after publishing the complete session', async () => {
  const f = await fixture({ initialSuccess: true })
  const browser = new EventTarget()
  browser.localStorage = f.local
  globalThis.window = browser
  const { session, AUTH_CONTEXT_EVENT } = await import(`../src/store/session.js?case=${revision}`)
  const snapshots = [], destinations = [], kinds = []
  browser.addEventListener(AUTH_CONTEXT_EVENT, (event) => kinds.push(event.detail.kind))
  const remove = installGeoAuthContextRouting(browser, {
    eventName: AUTH_CONTEXT_EVENT,
    reload: () => assert.fail('current-tab login and customer selection must not reload'),
    revalidate: () => {
      snapshots.push({ token: session.token, tenantId: session.tenantId, stored: selectStoredAuth(f.local, f.tab).token })
      return geoSessionRouteDecision({
        route: { meta: { perm: 'geo.content' } }, session,
        redirectToLogin: () => destinations.push('login'),
        leaveWorkspace: () => { destinations.push('portal'); return false },
      })
    },
  })
  try {
    session.setAuth('fake-ordinary-token', { ...user, is_advisor: false, tenant_id: 15 })
    assert.deepEqual(destinations, [])
    session.setAuth('fake-other-login', { ...user, is_advisor: false, tenant_id: 17, permissions: { 'geo.content': 'none' } }, false)
    assert.deepEqual(destinations, ['portal'])
    assert.equal(session.isLoggedIn, true)
    session.setAuth(identity, user)
    assert.equal(session.tenantId, null)
    session.replaceAuthForAdvisorTenant(business(17), 17)
    assert.equal(session.tenantId, 17)
    session.setTenant(15)
    assert.equal(session.tenantId, 17)
    assert.deepEqual(kinds, ['identity', 'identity', 'identity', 'identity'])
    assert.deepEqual(snapshots.map(({ tenantId }) => tenantId), [15, 17, null, 17])
    assert.ok(snapshots.every(({ token, stored }) => token === stored))
    assert.deepEqual(destinations, ['portal'])
    assert.equal(f.local.getItem('sem_token'), identity)
    assert.equal(f.tab.getItem('sem_token'), business(17))
  } finally {
    remove()
    delete globalThis.window
  }
})

test('Vue entry gates business pages behind bootstrap and renders the customer button', () => {
  const app = readFileSync(new URL('../geo-frontend/src/App.vue', import.meta.url), 'utf8')
  assert.match(app, /await bootstrapGeoSession/)
  assert.match(app, /<template v-if="!guidance">/)
  assert.match(app, /router-view v-if="ready"/)
  assert.match(app, /:href="GEO_ADVISOR_SELECT_URL"/)
  assert.match(app, /去选择客户/)
})
