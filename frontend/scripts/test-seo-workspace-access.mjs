import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test, { after } from 'node:test'
import { JSDOM } from 'jsdom'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'
import { advisorAccessGuidance, createSeoAdvisorTenantRecovery } from '../src/views/seo/seoAdvisorTenant.js'

import {
  canRenderSeoRoute,
  createSeoWorkspaceAccess,
  reconcileSeoRouteSite,
  selectOwnedSeoSite,
} from '../src/views/seo/seoWorkspaceAccess.js'

test('URL customer overrides memory only after eligibility and site ownership validation', async () => {
  const events = [], calls = []
  const access = createSeoWorkspaceAccess({
    fetchTenants: async () => ({ tenants: [{ id: 1 }, { id: 15 }] }),
    fetchSites: async id => { calls.push(id); return { sites: [{ id: 6, status: 'active' }] } },
    selectTenant: id => events.push(['select', id]), reset() {},
    ready: value => events.push(['ready', value.tenantId, value.siteId]),
    noSite() { assert.fail('unexpected no site') }, unavailable() { assert.fail('unexpected denial') },
  })
  await access.validate({ tenantId: 1, urlTenantId: '15', requestedSiteId: '6', strictSite: true })
  assert.deepEqual(events, [['select', 15]])
  assert.deepEqual(calls, [])
  await access.validate({ tenantId: 15, urlTenantId: '15', requestedSiteId: '6', strictSite: true })
  assert.deepEqual(events.at(-1), ['ready', 15, 6])
  assert.deepEqual(calls, [15])
})

test('inaccessible, malformed and bound-account URL customers never fall back', async () => {
  for (const urlTenantId of ['99', '', '0', '-1', '1.5', ['15'], ['1', '15'], '9007199254740993']) {
    const events = []
    const access = createSeoWorkspaceAccess({
      fetchTenants: async () => ({ tenants: [{ id: 1 }, { id: 15 }] }),
      fetchSites() { assert.fail('must not request sites') }, selectTenant() { assert.fail('must not switch') },
      reset() {}, ready() { assert.fail('must not mount') }, noSite() {},
      unavailable: value => events.push(value),
    })
    await access.validate({ tenantId: 1, urlTenantId, requestedSiteId: '6', strictSite: true })
    assert.match(events[0].error.message, /地址里的客户/)
  }
  let denied = false
  const bound = createSeoWorkspaceAccess({
    fetchTenants: async () => ({ tenants: [{ id: 1 }, { id: 15 }] }), boundTenantId: () => 1,
    fetchSites() { assert.fail('must not request sites') }, selectTenant() { assert.fail('must not switch') },
    reset() {}, ready() { assert.fail('must not mount') }, noSite() {}, unavailable() { denied = true },
  })
  await bound.validate({ tenantId: 1, urlTenantId: '15' })
  assert(denied)
})

test('explicit foreign, inactive and malformed sites block the page, while manual recovery retains defaults', async () => {
  for (const requestedSiteId of ['999', '7', '', '0', ['6'], ['6', '7']]) {
    const { access, events } = harness(async () => ({ sites: [{ id: 6, status: 'active' }, { id: 7, status: 'paused' }] }))
    await access.validate({ tenantId: 15, requestedSiteId, strictSite: true })
    assert.equal(events.at(-1)[0], 'unavailable')
    assert.match(events.at(-1)[1].error, /地址里的网站/)
    await access.validate({ tenantId: 15 })
    assert.equal(events.at(-1)[0], 'ready')
    assert.equal(events.at(-1)[1].siteId, 6)
  }
})

test('site management remains available before the first active site exists', () => {
  assert.equal(canRenderSeoRoute('no-active-site', '/seo/sites'), true)
  assert.equal(canRenderSeoRoute('no-active-site', '/seo/dashboard'), false)
  assert.equal(canRenderSeoRoute('unavailable', '/seo/sites'), false)
  assert.equal(canRenderSeoRoute('ready', '/seo/dashboard'), true)
})

function deferred() {
  let resolve
  let reject
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

function memoryStorage() {
  const values = new Map()
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  }
}

function harness(fetchSites) {
  const events = []
  const access = createSeoWorkspaceAccess({
    fetchSites,
    reset: (value) => events.push(['reset', value]),
    ready: (value) => events.push(['ready', value]),
    noSite: (value) => events.push(['no-site', value]),
    unavailable: (value) => events.push(['unavailable', { ...value, error: value.error?.message || null }]),
  })
  return { access, events }
}

test('A -> unavailable B -> A clears synchronously and never displays B data', async () => {
  const calls = []
  const fetchSites = async (tenantId) => {
    calls.push(tenantId)
    if (tenantId === 2) throw new Error('当前客户尚未开通 SEO 模块')
    return { sites: [{ id: 10, status: 'active' }] }
  }
  const { access, events } = harness(fetchSites)
  await access.validate({ tenantId: 1, requestedSiteId: 10 })
  await access.validate({ tenantId: 2, requestedSiteId: 10 })
  await access.validate({ tenantId: 1, requestedSiteId: 10 })
  assert.deepEqual(calls, [1, 2, 1])
  assert.deepEqual(events.map(([kind]) => kind), ['reset', 'ready', 'reset', 'unavailable', 'reset', 'ready'])
  assert.equal(events[3][1].tenantId, 2)
  assert.equal(events[5][1].siteId, 10)
})

test('site selection accepts only a site returned for the current tenant', () => {
  const sites = [{ id: 11, status: 'paused' }, { id: 12, status: 'active' }]
  assert.equal(selectOwnedSeoSite(sites, 11), 12)
  assert.equal(selectOwnedSeoSite([{ id: 11, status: 'paused' }], 11), null)
  assert.equal(selectOwnedSeoSite([{ id: 13, status: 'trial' }], 13, ['trial']), 13)
  assert.equal(selectOwnedSeoSite(sites, 99), 12)
  assert.equal(selectOwnedSeoSite([], 99), null)
})

test('late A response cannot restore data after switching to unavailable B', async () => {
  const lateA = deferred()
  const fetchSites = tenantId => tenantId === 1 ? lateA.promise : Promise.reject(new Error('SEO unavailable'))
  const { access, events } = harness(fetchSites)
  const pendingA = access.validate({ tenantId: 1, requestedSiteId: 10 })
  await access.validate({ tenantId: 2, requestedSiteId: 20 })
  lateA.resolve({ sites: [{ id: 10, status: 'active' }] })
  await pendingA
  assert.equal(events.filter(([kind]) => kind === 'ready').length, 0)
  assert.equal(events.at(-1)[0], 'unavailable')
  assert.equal(events.at(-1)[1].tenantId, 2)
})

test('unavailable customer still exposes the independently verified SEO customer list', async () => {
  const error = new Error('当前客户尚未开通 SEO 模块')
  error.seoTenants = [{ id: 1, name: 'A' }]
  const { access, events } = harness(async () => { throw error })
  await access.validate({ tenantId: 2 })
  assert.deepEqual(events.at(-1)[1].tenants, [{ id: 1, name: 'A' }])
})

test('refresh restores a stored site only after ownership validation', async () => {
  const { access, events } = harness(async () => ({ sites: [{ id: 30, status: 'active' }] }))
  await access.validate({ tenantId: 3, requestedSiteId: 999 })
  assert.equal(events[0][0], 'reset')
  assert.equal(events[1][0], 'ready')
  assert.equal(events[1][1].siteId, 30)
})

test('paused and archived-only responses enter no-active-site without mounting data', async () => {
  const { access, events } = harness(async () => ({
    selection_policy: { selectable_statuses: ['active'] },
    sites: [{ id: 40, status: 'paused' }, { id: 41, status: 'archived' }],
  }))
  await access.validate({ tenantId: 4, requestedSiteId: 40 })
  assert.equal(events.at(-1)[0], 'no-site')
  assert.equal(events.at(-1)[1].siteId, null)
  assert.deepEqual(events.at(-1)[1].selectableStatuses, ['active'])
})

test('ready route changes and browser history never select paused or archived sites', () => {
  const sites = [
    { id: 1, status: 'active' },
    { id: 2, status: 'archived' },
    { id: 3, status: 'paused' },
  ]
  const selectableStatuses = ['active']
  let currentSiteId = 1
  const replacements = []
  let noSite = false
  const changeRoute = requestedSiteId => reconcileSeoRouteSite({
    sites,
    selectableStatuses,
    requestedSiteId,
    selectSite: siteId => { currentSiteId = siteId },
    replaceSiteQuery: siteId => replacements.push(siteId),
    noSite: () => { noSite = true },
  })

  // A direct query edit and forward navigation to non-selectable sites both
  // resolve against the last authoritative policy and keep the active site.
  changeRoute(2)
  assert.equal(currentSiteId, 1)
  changeRoute(3)
  assert.equal(currentSiteId, 1)

  // Back navigation that removes site_id also resolves to the active site.
  changeRoute(null)
  assert.equal(currentSiteId, 1)
  assert.deepEqual(replacements, [1, 1, 1])
  assert.equal(noSite, false)
})

test('late mixed-status response cannot override a newer ready route selection', async () => {
  const late = deferred()
  let request = 0
  const { access, events } = harness(() => {
    request += 1
    return request === 1
      ? late.promise
      : Promise.resolve({
          selection_policy: { selectable_statuses: ['active'] },
          sites: [{ id: 10, status: 'active' }, { id: 20, status: 'archived' }],
        })
  })
  const oldValidation = access.validate({ tenantId: 1, requestedSiteId: 20 })
  await access.validate({ tenantId: 1, requestedSiteId: 10 })
  late.resolve({
    selection_policy: { selectable_statuses: ['active'] },
    sites: [{ id: 20, status: 'archived' }],
  })
  await oldValidation
  const readyEvents = events.filter(([kind]) => kind === 'ready')
  assert.equal(readyEvents.length, 1)
  assert.equal(readyEvents[0][1].siteId, 10)
})

test('separate tab controllers cannot commit each other scope responses', async () => {
  const first = deferred()
  const tabA = harness(() => first.promise)
  const tabB = harness(async () => ({ sites: [{ id: 22, status: 'active' }] }))
  const pending = tabA.access.validate({ tenantId: 1 })
  tabA.access.invalidate()
  await tabB.access.validate({ tenantId: 2, requestedSiteId: 22 })
  first.resolve({ sites: [{ id: 11, status: 'active' }] })
  await pending
  assert.equal(tabA.events.some(([kind]) => kind === 'ready'), false)
  assert.equal(tabB.events.at(-1)[1].siteId, 22)
})

test('workspace shell gates child views and uses the workbench site selector', async () => {
  const source = await readFile(new URL('../src/views/seo/SeoWorkspaceShell.vue', import.meta.url), 'utf8')
  assert.match(source, /client\.get\('\/api\/v1\/auth\/tenants', \{ params: \{ module: 'seo' \} \}\)/)
  assert.match(source, /<section v-if="!renderRoute"/)
  assert.match(source, /<router-view v-else/)
  assert.match(source, /fetchSeoWorkbenchSites\(tenantId\)/)
  assert.match(source, /urlTenantId: Object.hasOwn\(route.query, 'tenant_id'\)/)
  assert.match(source, /strictSite: Object.hasOwn\(route.query, 'site_id'\)/)
  assert.match(source, /clearSeoSiteId\(\)/)
})

test('workbench site API helper calls the scoped read URL with tenant ownership input', async () => {
  globalThis.localStorage ??= memoryStorage()
  globalThis.sessionStorage ??= memoryStorage()
  const [{ default: client }, { fetchSeoWorkbenchSites }] = await Promise.all([
    import('../src/api/client.js'),
    import('../src/api/moduleAssets.js'),
  ])
  const originalGet = client.get
  const calls = []
  client.get = async (...args) => {
    calls.push(args)
    return { sites: [] }
  }
  try {
    await fetchSeoWorkbenchSites(7)
  } finally {
    client.get = originalGet
  }
  assert.deepEqual(calls, [[
    '/api/v1/seo/workbench/sites',
    { params: { tenant_id: 7 } },
  ]])
})

test('SEO default validates eligible tenants before requesting sites', async () => {
  for (const remembered of [null, 1, 99, 18]) {
    const calls = [], events = []
    const access = createSeoWorkspaceAccess({
      fetchTenants: async () => { calls.push('tenants'); return { tenants: [{ id: 18 }, { id: 22 }] } },
      fetchSites: async id => { calls.push(id); return { sites: [{ id: 7, status: 'active' }] } },
      selectTenant: id => events.push(['select', id]),
      reset() {}, ready: result => events.push(['ready', result.tenantId]), noSite() {}, unavailable() { throw Error('unexpected unavailable') },
    })
    await access.validate({ tenantId: remembered, requestedSiteId: 999 })
    assert.deepEqual(calls, remembered === 18 ? ['tenants', 18] : ['tenants'])
    assert.deepEqual(events, remembered === 18 ? [['ready', 18]] : [['select', 18]])
  }
})

test('empty or failed eligibility and a bound account never request another tenant', async () => {
  for (const mode of ['empty', 'failed', 'bound']) {
    let siteCalls = 0, selected = 0, denied = 0
    const access = createSeoWorkspaceAccess({
      fetchTenants: async () => { if (mode === 'failed') throw Error('network'); return { tenants: mode === 'empty' ? [] : [{ id: 18 }] } },
      boundTenantId: () => mode === 'bound' ? 1 : null,
      fetchSites: async () => { siteCalls++; return {} }, selectTenant: () => selected++,
      reset() {}, ready() {}, noSite() {}, unavailable: () => denied++,
    })
    await access.validate({ tenantId: 1 })
    assert.deepEqual([siteCalls, selected, denied], [0, 0, 1])
  }
})

test('late eligibility cannot change tenant after a scope change or dispose', async () => {
  for (const action of ['invalidate', 'dispose']) {
    const pending = deferred()
    let selected = 0, sites = 0
    const access = createSeoWorkspaceAccess({
      fetchTenants: () => pending.promise, selectTenant: () => selected++,
      fetchSites: async () => { sites++; return {} }, reset() {}, ready() {}, noSite() {}, unavailable() {},
    })
    const run = access.validate({ tenantId: 1 })
    access[action]()
    pending.resolve({ tenants: [{ id: 18 }] })
    await run
    assert.deepEqual([selected, sites], [0, 0])
  }
})

// Mount the actual shell with the real session store and in-memory auth only.
// No request in these tests can reach a server.
const dom = new JSDOM('<!doctype html><body></body>', { url: 'https://seo-test.invalid/seo/dashboard' })
after(() => dom.window.close())
for (const key of ['window', 'document', 'Element', 'HTMLElement', 'SVGElement', 'Node', 'Event', 'localStorage', 'sessionStorage']) {
  globalThis[key] = dom.window[key]
}
const Vue = await import('vue')
const { session } = await import('../src/store/session.js')
const shellSource = await readFile(new URL('../src/views/seo/SeoWorkspaceShell.vue', import.meta.url), 'utf8')
const shellDescriptor = parse(shellSource).descriptor
const shellScript = compileScript(shellDescriptor, { id: 'seo-advisor-test', genDefaultAs: 'component' })
const shellCode = shellScript.content.replace(/^import .* from .*$/gm, '')
const shellTemplate = compileTemplate({
  source: shellDescriptor.template.content, id: 'seo-advisor-test',
  compilerOptions: { bindingMetadata: shellScript.bindings },
}).code.replace(/import \{([\s\S]*?)\} from "vue"/g, (_, names) => `const {${names.replace(/ as /g, ':')}} = Vue`)
  .replace('export function render', 'function render')
const flushShell = async () => { for (let i = 0; i < 40; i++) { await Promise.resolve(); await Vue.nextTick() } }
const fakeJwt = claims => `test.${Buffer.from(JSON.stringify(claims)).toString('base64url')}.test-only`
const advisorUser = { id: 101, tenant_id: 15, is_advisor: true, permissions: { 'seo.dashboard': 'view' } }
const selectionRequired = () => Object.assign(new Error('{"code":"ADVISOR_TENANT_SELECTION_REQUIRED"}'), { code: 'ADVISOR_TENANT_SELECTION_REQUIRED' })
const validSelection = tenantId => ({
  tenant_id: tenantId, tenant_name: '测试客户', token_type: 'bearer', expires_at: '2099-01-01T00:00:00Z',
  access_token: fakeJwt({ scope_kind: 'advisor_tenant', sub: 101, tid: tenantId, gid: 7 }),
})

async function mountAdvisorShell(options = {}) {
  localStorage.clear(); sessionStorage.clear()
  const user = options.normal ? { ...advisorUser, is_advisor: false } : advisorUser
  const identity = options.normal ? 'fake-normal-session' : fakeJwt({ scope_kind: 'advisor_identity', sub: user.id })
  session.setAuth(identity, user, true)
  const calls = [], sites = []
  const me = { user: { ...user, default_tenant_id: options.defaultId ?? null } }
  if (options.legacyMe) delete me.user.default_tenant_id
  const route = Vue.reactive({ path: '/seo/dashboard', query: {}, meta: { immersive: true } })
  const client = {
    async get(path, config) {
      calls.push(['GET', path, config])
      if (path === '/api/v1/auth/me') return me
      if (path === '/api/v1/auth/tenants') return options.array ? options.tenants : { tenants: options.tenants ?? [{ id: 15, name: 'A' }, { id: 17, name: 'B' }] }
      if (path === '/api/v1/seo/workbench/sites') {
        if (options.scopeError) throw options.scopeError
        if (session.advisorScope === 'advisor_identity') throw selectionRequired()
        sites.push(config.params.tenant_id)
        return { sites: [{ id: 51, status: 'active' }] }
      }
      assert.fail(`unexpected mocked GET ${path}`)
    },
    async post(path, body) {
      calls.push(['POST', path, body])
      assert.equal(path, '/api/v1/auth/select-tenant')
      if (options.selectError) throw options.selectError
      return options.selection ? options.selection(body.tenant_id) : validSelection(body.tenant_id)
    },
  }
  const siteId = Vue.ref(null)
  const bindings = {
    computed: Vue.computed, onBeforeUnmount: Vue.onBeforeUnmount, onMounted: Vue.onMounted, ref: Vue.ref, watch: Vue.watch,
    useRoute: () => route, useRouter: () => ({ push() {}, replace() {} }),
    fetchMe: () => client.get('/api/v1/auth/me'), client, session,
    fetchSeoWorkbenchSites: tenantId => client.get('/api/v1/seo/workbench/sites', { params: { tenant_id: tenantId } }),
    clearSeoSiteId: () => { siteId.value = null }, currentSeoSiteId: siteId, seoSitesRevision: Vue.ref(0),
    canRenderSeoRoute, createSeoWorkspaceAccess, advisorAccessGuidance, createSeoAdvisorTenantRecovery,
  }
  const Component = new Function('b', `const {${Object.keys(bindings).join(',')}}=b;${shellCode};return component`)(bindings)
  Component.render = new Function('Vue', `${shellTemplate};return render`)(Vue)
  const host = document.createElement('div'); document.body.append(host)
  const app = Vue.createApp(Component)
  app.component('router-view', { render: () => Vue.h('div', { class: 'test-seo-data' }, '已校验的网站数据') })
  const instance = app.mount(host)
  await flushShell()
  return {
    host, calls, sites, identity,
    async revalidate() { instance.$.setupState.validateCurrentScope(); await flushShell() },
    close() { app.unmount(); host.remove() },
  }
}

test('advisor default customer wins within grants; business auth stays in this tab and survives user refresh/reload', async () => {
  const view = await mountAdvisorShell({ defaultId: 17 })
  try {
    assert.deepEqual(view.calls.filter(c => c[0] === 'POST').map(c => c[2]), [{ tenant_id: 17 }])
    assert.deepEqual(view.sites, [17])
    assert(view.host.querySelector('.test-seo-data'))
    assert.equal(session.tenantId, 17)
    assert.equal(JSON.parse(localStorage.getItem('sem_auth_v1')).token, view.identity)
    assert.equal(JSON.parse(sessionStorage.getItem('sem_auth_v1')).token, session.token)
    assert.deepEqual(JSON.parse(sessionStorage.getItem('sem_advisor_identity_v1')), { token: view.identity, user: { ...advisorUser, default_tenant_id: 17 } })
    session.refreshUser({ ...advisorUser })
    session.setTenant(15)
    assert.equal(session.tenantId, 17)
    const reloaded = (await import(`../src/store/session.js?seo-advisor-reload=${Date.now()}`)).session
    assert.equal(reloaded.tenantId, 17)
    assert.equal(reloaded.advisorScope, 'advisor_tenant')
  } finally { view.close() }
})

test('single authorized customer auto-selects for array/envelope lists and missing/stale defaults', async () => {
  for (const array of [false, true]) {
    for (const defaultId of [null, 99]) {
      const view = await mountAdvisorShell({ array, defaultId, tenants: [{ id: 17, name: '唯一客户' }] })
      try {
        assert.equal(session.tenantId, 17)
        assert.equal(view.calls.filter(c => c[0] === 'POST').length, 1)
        assert(view.host.querySelector('.test-seo-data'))
      } finally { view.close() }
    }
  }
})

test('legacy /auth/me tenant_id is only a default preference inside the authorized list', async () => {
  const view = await mountAdvisorShell({ legacyMe: true })
  try {
    assert.equal(session.tenantId, 15)
    assert.deepEqual(view.calls.filter(c => c[0] === 'POST').map(c => c[2]), [{ tenant_id: 15 }])
    assert(view.host.querySelector('.test-seo-data'))
  } finally { view.close() }
})

test('multiple customers without an authorized default show Chinese customer-selection link without data', async () => {
  for (const defaultId of [null, 99]) {
    const view = await mountAdvisorShell({ defaultId })
    try {
      assert.match(view.host.textContent, /你有多个客户，请先选择要查看的客户/)
      const link = view.host.querySelector('.scope-gate a')
      assert.equal(link.textContent, '去选择客户')
      assert.equal(link.getAttribute('href'), '/customer-workbench/?console=advisor')
      assert.equal(view.calls.filter(c => c[0] === 'POST').length, 0)
      assert.equal(view.host.querySelector('.test-seo-data'), null)
      assert.doesNotMatch(view.host.textContent, /ADVISOR_|\{"code"/)
    } finally { view.close() }
  }
})

test('empty grants and ADVISOR_NO_TENANT show the unassigned-customer message', async () => {
  for (const scopeError of [undefined, Object.assign(new Error('ADVISOR_NO_TENANT'), { code: 'ADVISOR_NO_TENANT' })]) {
    const view = await mountAdvisorShell({ tenants: [], scopeError })
    try {
      assert.match(view.host.textContent, /你还没有被分配客户，请联系管理员/)
      assert.equal(view.host.querySelector('.scope-gate a'), null)
      assert.equal(view.calls.filter(c => c[0] === 'POST').length, 0)
      assert.doesNotMatch(view.host.textContent, /ADVISOR_/)
    } finally { view.close() }
  }
})

test('select failure is readable and never retries on scope/auth watchers', async () => {
  const view = await mountAdvisorShell({ defaultId: 15, selectError: new Error('{"detail":"RAW_ENGLISH_FAILURE"}') })
  try {
    for (let i = 0; i < 3; i++) await view.revalidate()
    assert.equal(view.calls.filter(c => c[0] === 'POST').length, 1)
    assert.match(view.host.textContent, /重新选择客户/)
    assert(view.host.querySelector('.scope-gate a'))
    assert.equal(session.advisorScope, 'advisor_identity')
    assert.equal(view.host.querySelector('.test-seo-data'), null)
    assert.doesNotMatch(view.host.textContent, /RAW_ENGLISH|ADVISOR_|\{"detail"/)
  } finally { view.close() }
})

test('a repeated selection-required response after exchange never starts a second exchange', async () => {
  const view = await mountAdvisorShell({ defaultId: 15 })
  try {
    const recovery = createSeoAdvisorTenantRecovery({ session, client: { get() { assert.fail('must not retry business auth') } } })
    assert.equal(recovery.recover(selectionRequired()), false)
    assert.equal(view.calls.filter(c => c[0] === 'POST').length, 1)
  } finally { view.close() }
})

test('malformed selection envelopes and foreign subject/tenant/grant claims never replace identity', async () => {
  const patches = [
    { tenant_id: 99 }, { token_type: 'other' }, { access_token: '' }, { expires_at: 'invalid' }, { expires_at: '2000-01-01T00:00:00Z' },
    ...[{ tid: 99 }, { sub: 999 }, { gid: 0 }, { scope_kind: 'advisor_identity' }].map(claims => ({
      access_token: fakeJwt({ scope_kind: 'advisor_tenant', sub: 101, tid: 15, gid: 7, ...claims }),
    })),
  ]
  for (const patch of patches) {
    const view = await mountAdvisorShell({ defaultId: 15, selection: id => ({ ...validSelection(id), ...patch }) })
    try {
      assert.equal(session.token, view.identity)
      assert.equal(view.host.querySelector('.test-seo-data'), null)
      assert(view.host.querySelector('.scope-gate a'))
      await view.revalidate()
      assert.equal(view.calls.filter(c => c[0] === 'POST').length, 1)
    } finally { view.close() }
  }
})

test('non-advisor scope validation and errors retain their existing behavior', async () => {
  for (const scopeError of [undefined, new Error('原有 SEO 中文提示')]) {
    const view = await mountAdvisorShell({ normal: true, scopeError })
    try {
      assert.equal(view.calls.filter(c => c[0] === 'POST').length, 0)
      assert.equal(view.calls.filter(c => c[1] === '/api/v1/auth/tenants').length, 1)
      assert.equal(view.calls.filter(c => c[1] === '/api/v1/seo/workbench/sites').length, 1)
      if (scopeError) assert.match(view.host.textContent, /原有 SEO 中文提示/)
      else assert(view.host.querySelector('.test-seo-data'))
      assert.equal(view.host.querySelector('.customer-selection'), null)
    } finally { view.close() }
  }
})

test('pending advisor recovery is shared and cannot change auth after logout or unmount', async () => {
  for (const cancel of ['logout', 'dispose']) {
    const pending = deferred()
    const identity = fakeJwt({ scope_kind: 'advisor_identity', sub: 101 })
    session.setAuth(identity, advisorUser, false)
    let posts = 0
    const recovery = createSeoAdvisorTenantRecovery({
      session,
      client: { get: () => pending.promise, post: () => { posts++; return validSelection(15) } },
    })
    const first = recovery.recover(selectionRequired())
    assert.equal(recovery.recover(selectionRequired()), first)
    const rejected = assert.rejects(first, error => error.code === 'AUTH_CONTEXT_CHANGED')
    if (cancel === 'logout') session.logout()
    else recovery.dispose()
    pending.resolve({ tenants: [{ id: 15, name: 'A' }] })
    await rejected
    assert.equal(posts, 0)
    assert.equal(session.advisorScope, cancel === 'logout' ? null : 'advisor_identity')
  }
})
