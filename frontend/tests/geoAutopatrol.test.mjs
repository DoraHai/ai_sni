import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { beijingTime, createSelfServiceController, toggleAllowed, patrolError, patrolStatus } from '../src/utils/geoAutopatrol.js'

const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
const status = (patch = {}) => ({ tenant_id: 7, revision: 4, enabled: false, admin_locked: false, can_toggle: true, can_enable: true, ...patch })
function fixture(read = async () => status(), write = async body => status({ enabled: body.enabled, revision: 5 })) {
  const state = {}, calls = []
  const controller = createSelfServiceController({ state, read, write: body => { calls.push(body); return write(body) } })
  return { state, calls, controller }
}
test('toggle permissions obey server capabilities, allow closing when enable is blocked', () => {
  assert.equal(toggleAllowed(status({ can_toggle: false })), false)
  assert.equal(toggleAllowed(status({ can_enable: false })), false)
  assert.equal(toggleAllowed(status({ enabled: true, can_enable: false })), true)
  assert.equal(toggleAllowed(status({ admin_locked: true })), false)
  assert.equal(toggleAllowed(null), false)
})
test('tenant change aborts reads, clears old state and rejects late responses', async () => {
  const waits = [], signals = []
  const f = fixture((id, signal) => { signals.push(signal); const d = deferred(); waits.push(d); return d.promise })
  const first = f.controller.setTenant(7)
  const second = f.controller.setTenant(8)
  assert.equal(signals[0].aborted, true)
  assert.equal(f.state.data, null)
  waits[1].resolve(status({ tenant_id: 8 })); await second
  waits[0].resolve(status()); await first
  assert.equal(f.state.data.tenant_id, 8)
})
test('double toggle sends one restricted request and waits for server-confirmed state', async () => {
  const d = deferred(), f = fixture(undefined, () => d.promise)
  await f.controller.setTenant(7)
  const pending = f.controller.toggle(); await f.controller.toggle()
  assert.deepEqual(f.calls, [{ tenant_id: 7, enabled: true, expected_revision: 4 }])
  assert.equal(f.state.data.enabled, false)
  d.resolve(status({ enabled: true, revision: 5 })); await pending
  assert.equal(f.state.data.enabled, true)
  assert.equal(f.state.busy, false)
})
test('late mutation cannot affect another customer or unlock its busy state', async () => {
  const d = deferred(), f = fixture(async id => status({ tenant_id: id }), () => d.promise)
  await f.controller.setTenant(7)
  const pending = f.controller.toggle()
  await f.controller.setTenant(8)
  d.resolve(status({ enabled: true })); await pending
  assert.equal(f.state.data.tenant_id, 8)
  assert.equal(f.state.data.enabled, false)
})
test('404 remains unavailable and makes no write/fallback request', async () => {
  const f = fixture(async () => { throw { status: 404 } })
  await f.controller.setTenant(7); await f.controller.toggle()
  assert.equal(f.state.error, '功能未就绪')
  assert.equal(f.state.data, null)
  assert.equal(f.calls.length, 0)
})
for (const code of [409, 423]) test(`${code} refreshes revision and never retries a write`, async () => {
  let reads = 0
  const f = fixture(async () => status({ revision: ++reads }), async () => { throw { status: code } })
  await f.controller.setTenant(7); await f.controller.toggle()
  assert.equal(f.calls.length, 1); assert.equal(reads, 2)
  assert.equal(f.state.data.revision, 2); assert.equal(f.state.busy, false)
  assert.equal(f.state.error, patrolError({ status: code }))
})
test('Beijing time does not depend on browser timezone and missing results stay unknown', () => {
  assert.equal(beijingTime('2026-10-22T23:05:00Z'), '2026-10-23 07:05')
  assert.equal(beijingTime(null), '—'); assert.equal(beijingTime('invalid'), '—')
  assert.equal(patrolStatus(status()), '已关闭')
  assert.equal(patrolStatus(status({ blocked_reason: 'future_reason' })), '受阻：检测暂时受阻，请刷新状态')
})

test('API wrappers enforce contract bodies and keep switch/manual revisions separate', async () => {
  const source = readFileSync(new URL('../src/api/geoContent.js', import.meta.url), 'utf8')
  const wrappers = source.slice(source.indexOf('export function fetchPatrolSelfService'), source.indexOf('export function listVisibilityPatrolRuns')).replaceAll('export function', 'function')
  const calls = []
  const client = Object.fromEntries(['get', 'put', 'post'].map(method => [method, (...args) => { calls.push([method, ...args]); return Promise.resolve({}) }]))
  const ctx = vm.createContext({ client })
  vm.runInContext(wrappers, ctx)
  await ctx.putPatrolSelfService({ tenant_id: 7, enabled: true, expected_revision: 4, engine_keys: ['other'], owner_user_id: 99 })
  await ctx.putPatrolManualLimit({ tenant_id: 7, manual_daily_limit: 12, expected_revision: 2, reason: '合成调整', enabled: true })
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    ['put', '/api/v1/geo/visibility-patrol/self-service', { tenant_id: 7, enabled: true, expected_revision: 4 }],
    ['put', '/api/v1/geo/visibility-patrol/manual-limit', { tenant_id: 7, manual_daily_limit: 12, expected_revision: 2, reason: '合成调整' }],
  ])
})

const adminSource = readFileSync(new URL('../src/components/GeoPatrolAdmin.vue', import.meta.url), 'utf8')
const adminScript = adminSource.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
function adminFixture(list = async () => ({ items: [], total: 0 })) {
  const writes = [], events = [], hooks = []
  const ctx = vm.createContext({
    ref: value => ({ value }), reactive: value => value, defineEmits: () => event => events.push(event), onBeforeUnmount: fn => hooks.push(fn),
    AbortController, listPatrolAdminSettings: list, patrolError,
    patrolAdminAction: async body => writes.push(JSON.parse(JSON.stringify(body))),
    putPatrolManualLimit: async body => writes.push(JSON.parse(JSON.stringify(body))),
  })
  vm.runInContext(adminScript, ctx)
  return { ctx, writes, events, hooks, eval: code => vm.runInContext(code, ctx) }
}
test('admin filters and pagination go to one batch endpoint, late lists are discarded', async () => {
  const waits = [], params = []
  const f = adminFixture(p => { params.push(JSON.parse(JSON.stringify(p))); const d = deferred(); waits.push(d); return d.promise })
  f.eval("filters.enabled = 'false'; filters.admin_locked = 'true'; filters.blocked = 'true'; filters.search = ' 合成 '; page.value = 3")
  const next = f.ctx.load()
  assert.deepEqual(params[1], { page: 3, page_size: 20, search: '合成', enabled: false, admin_locked: true, blocked: true })
  waits[1].resolve({ items: [{ tenant_id: 8 }], total: 41 }); await next
  waits[0].resolve({ items: [{ tenant_id: 7 }], total: 1 }); await Promise.resolve()
  assert.equal(f.eval('rows.value[0].tenant_id'), 8)
})
test('manual limit uses its independent revision, retains reason and includes zero', async () => {
  const f = adminFixture(); await f.ctx.load()
  f.eval("open({tenant_id:7,tenant_name:'合成客户',revision:99,manual_limit_revision:3,manual_quota:{limit:10}}, 'manual_limit'); limit.value=0; reason.value=' 暂停手动 '; ")
  await f.ctx.submit()
  assert.deepEqual(f.writes, [{ tenant_id: 7, manual_daily_limit: 0, expected_revision: 3, reason: '暂停手动' }])
})
test('admin refuses empty reason and out-of-range limit; only explicit force/unlock operations exist', async () => {
  const f = adminFixture(); await f.ctx.load()
  f.eval("open({tenant_id:7,revision:4,manual_quota:{limit:10}}, 'force_disable')")
  await f.ctx.submit(); assert.equal(f.writes.length, 0)
  f.eval("reason.value='安全停用'"); await f.ctx.submit()
  assert.deepEqual(f.writes[0], { tenant_id: 7, action: 'force_disable', expected_revision: 4, reason: '安全停用' })
  assert.doesNotMatch(adminSource, /open\(row,\s*['"]enable['"]\)/)
  f.eval("open({tenant_id:7,manual_quota:{limit:10}}, 'manual_limit'); reason.value='调整'; limit.value=101")
  await f.ctx.submit(); assert.equal(f.writes.length, 1)
})
test('history clears customer data and aborts pending requests on close/change', async () => {
  const source = readFileSync(new URL('../src/components/GeoPatrolHistory.vue', import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  const props = { open: true, tenantId: 7, manual: false }, waits = [], signals = []
  const ctx = vm.createContext({ defineProps: () => props, defineEmits: () => () => {},
    ref: value => ({ value }), watch() {}, onBeforeUnmount() {}, AbortController, patrolError,
    listPatrolSettingHistory: (id, page, signal) => { const d = deferred(); waits.push(d); signals.push(signal); return d.promise },
  })
  vm.runInContext(script, ctx)
  const first = ctx.load(); props.tenantId = 8; const next = ctx.load()
  waits[1].resolve({ items: [{ tenant_id: 8 }], total: 1 }); await next
  waits[0].resolve({ items: [{ tenant_id: 7 }], total: 1 }); await first
  assert.equal(vm.runInContext('items.value[0].tenant_id', ctx), 8)
  props.open = false; await ctx.load()
  assert.equal(vm.runInContext('items.value.length', ctx), 0)
  assert.equal(signals[0].aborted, true)
})
