import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  createSeoWorkspaceAccess,
  reconcileSeoRouteSite,
  selectOwnedSeoSite,
} from '../src/views/seo/seoWorkspaceAccess.js'

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
  assert.match(source, /<section v-if="accessState !== 'ready'"/)
  assert.match(source, /<router-view v-else/)
  assert.match(source, /fetchSeoWorkbenchSites\(tenantId\)/)
  assert.match(source, /reconcileSeoRouteSite\(\{[\s\S]*selectableStatuses: selectableSiteStatuses\.value/)
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
