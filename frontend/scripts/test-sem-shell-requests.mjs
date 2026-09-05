import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'

const app = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
const badgeBody = app.slice(app.indexOf('async function loadBadges()'), app.indexOf('// 侧边导航结构'))
function badgeHarness({ permissions, alerts, candidates }) {
  const calls = []
  const badges = { alerts: 0, alertsToday: 0, expand: 0 }
  const context = vm.createContext({
    session: { tenantId: 3, isLoggedIn: true, tenants: [{ id: 3 }], canView: (key) => permissions.includes(key) },
    tenantModuleScope: { value: 'sem' }, badges,
    resetBadges: () => Object.assign(badges, { alerts: 0, alertsToday: 0, expand: 0 }),
    fetchAlerts: async () => { calls.push('alerts'); return alerts() },
    fetchCandidates: async () => { calls.push('candidates'); return candidates() },
  })
  vm.runInContext('let badgeLoadGeneration = 0; ' + badgeBody.replaceAll('import.meta.env.VITE_API_KEY', 'false'), context)
  return { context, calls, badges, load: () => vm.runInContext('loadBadges()', context) }
}
const successAlerts = () => ({ total_open: 9, today_new: 2 })
const successCandidates = () => ({ status_counts: { pending: 7 } })
const fail = () => { throw new Error('unavailable') }
for (const permissions of [['monitor.alerts'], ['optimize.expand'], []]) {
  const h = badgeHarness({ permissions, alerts: successAlerts, candidates: successCandidates })
  await h.load()
  assert.deepEqual(h.calls, permissions.map((p) => p === 'monitor.alerts' ? 'alerts' : 'candidates'))
}
for (const failed of ['alerts', 'candidates']) {
  const h = badgeHarness({ permissions: ['monitor.alerts', 'optimize.expand'],
    alerts: failed === 'alerts' ? fail : successAlerts,
    candidates: failed === 'candidates' ? fail : successCandidates })
  await h.load()
  assert.equal(h.badges[failed === 'alerts' ? 'expand' : 'alerts'], failed === 'alerts' ? 7 : 9)
}
let resolveOld
const h = badgeHarness({ permissions: ['monitor.alerts'], alerts: () => new Promise((resolve) => { resolveOld = resolve }), candidates: successCandidates })
const oldRequest = h.load()
h.context.session.tenantId = 4
resolveOld(successAlerts())
await oldRequest
assert.equal(h.badges.alerts, 0, 'ignore results for a previous tenant')

const tenantBody = app.slice(app.indexOf('async function loadTenants()'), app.indexOf('// 刷新当前用户'))
let rejectOld
let calls = 0
const tenantContext = vm.createContext({
  session: { isLoggedIn: true, setTenants: () => {} },
  tenantModuleScope: { value: 'sem' }, bootstrapError: { value: '' },
  loadBadges: () => {}, loadWritebackMode: () => {},
  fetchTenants: () => ++calls === 1 ? new Promise((_, reject) => { rejectOld = reject }) : Promise.resolve({ tenants: [] }),
})
vm.runInContext('let tenantLoadGeneration = 0; ' + tenantBody, tenantContext)
const oldTenantRequest = vm.runInContext('loadTenants()', tenantContext)
await vm.runInContext('loadTenants()', tenantContext)
rejectOld(new Error('stale failed request'))
await oldTenantRequest
assert.equal(tenantContext.bootstrapError.value, '', 'old failure cannot overwrite a newer successful load')
console.log('SEM shell request permission, partial failure and stale tenant checks passed')
