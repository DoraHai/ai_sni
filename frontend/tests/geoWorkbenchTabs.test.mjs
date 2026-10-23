import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/views/geo/GeoTasksView.vue', import.meta.url), 'utf8')
const load = source.slice(source.indexOf('async function load()'), source.indexOf('async function openCreate()'))

test('each tab requests server filtering and renders full-scope counts', async () => {
  const calls = []
  const context = vm.createContext({
    tenantId: { value: 7 }, page: { value: 3 }, pageSize: { value: 20 },
    workbenchTab: { value: '' }, q: { value: '' }, items: { value: [] },
    loading: { value: false }, error: { value: '' }, total: { value: 0 },
    workbenchCounts: { value: {} }, loadGeneration: 0,
    listGeoContentTasks: async (tenant, params) => {
      calls.push({ tenant, params })
      return { items: [{ id: 1, status: params.workbench_tab || 'draft' }], total: 1,
        workbench_counts: { all: 10, draft: 2, polish: 1, needs_fix: 3, ready: 2, published: 1, cancelled: 1 } }
    },
  })
  vm.runInContext(load, context)
  for (const tab of ['', 'draft', 'polish', 'needs_fix', 'ready', 'published', 'cancelled']) {
    context.setTab(tab)
    while (context.loading.value) await new Promise(resolve => setImmediate(resolve))
    assert.equal(calls.at(-1).params.workbench_tab, tab || undefined)
    assert.equal(calls.at(-1).params.offset, 0)
    assert.equal(context.workbenchCounts.value.all, 10)
    assert.equal(context.workbenchCounts.value.cancelled, 1)
    assert.equal(context.workbenchCounts.value.needs_fix, 3)
    assert.equal(context.items.value[0].status, tab || 'draft')
  }
  assert.match(source, /value: 'needs_fix', label: '待修补', count: workbenchCounts.value.needs_fix/)
})

test('a late previous tab response cannot overwrite the current list or counts', async () => {
  const pending = []
  const context = vm.createContext({
    tenantId: { value: 7 }, page: { value: 1 }, pageSize: { value: 20 },
    workbenchTab: { value: '' }, q: { value: '' }, items: { value: [] },
    loading: { value: false }, error: { value: '' }, total: { value: 0 },
    workbenchCounts: { value: {} }, loadGeneration: 0,
    listGeoContentTasks: () => new Promise(resolve => pending.push(resolve)),
  })
  vm.runInContext(load, context)
  const old = context.load()
  context.workbenchTab.value = 'published'
  const current = context.load()
  pending[1]({ items: [{ id: 9, status: 'published' }], total: 1, workbench_counts: { all: 5, published: 1 } })
  await current
  pending[0]({ items: [{ id: 1, status: 'draft' }], total: 9, workbench_counts: { all: 9, published: 0 } })
  await old
  assert.equal(context.items.value[0].status, 'published')
  assert.equal(context.workbenchCounts.value.all, 5)
  assert.equal(context.workbenchCounts.value.published, 1)
  assert.equal(context.total.value, 1)
  assert.equal(context.loading.value, false)
})


test('page two retains its known total while a request is pending', async () => {
  const calls = [], pending = []
  const context = vm.createContext({
    tenantId: { value: 7 }, page: { value: 1 }, pageSize: { value: 20 },
    workbenchTab: { value: '' }, q: { value: '' }, items: { value: [] },
    loading: { value: false }, error: { value: '' }, total: { value: 33 },
    workbenchCounts: { value: { all: 33 } }, loadGeneration: 0,
    listGeoContentTasks: (tenant, params) => {
      calls.push(params)
      return new Promise(resolve => pending.push(resolve))
    },
  })
  vm.runInContext(load, context)
  context.onPageChange(2)
  assert.equal(context.page.value, 2)
  assert.equal(context.total.value, 33)
  assert.equal(context.workbenchCounts.value.all, 33)
  assert.equal(calls[0].offset, 20)
  pending.shift()({ items: [{ id: 21 }], total: 33, workbench_counts: { all: 33 } })
  while (context.loading.value) await new Promise(resolve => setImmediate(resolve))
  assert.equal(context.page.value, 2)
  assert.equal(calls.length, 1)
  context.q.value = 'question'
  context.resetAndLoad()
  assert.equal(context.page.value, 1)
  assert.equal(context.total.value, 0)
  assert.equal(calls.at(-1).offset, 0)
  assert.equal(calls.at(-1).q, 'question')
  pending.shift()({ items: [], total: 0 })
  while (context.loading.value) await new Promise(resolve => setImmediate(resolve))
})

test('empty text distinguishes a filter miss from an empty workspace', () => {
  const expression = source.slice(source.indexOf('const emptyText ='), source.indexOf('const tabs ='))
  const context = vm.createContext({
    computed: fn => ({ get value() { return fn() } }),
    workbenchTab: { value: '' }, q: { value: '' },
  })
  vm.runInContext(expression + '; globalThis.empty = emptyText', context)
  assert.match(context.empty.value, /可创建/)
  context.workbenchTab.value = 'cancelled'
  assert.equal(context.empty.value, '当前筛选暂无文章')
  context.workbenchTab.value = ''
  context.q.value = 'a missing question'
  assert.equal(context.empty.value, '当前筛选暂无文章')
  context.q.value = '  '
  assert.match(context.empty.value, /可创建/)
  assert.match(source, /:empty-text="emptyText"/)
})

test('a failed page request clears both pagination and tab counts', async () => {
  const context = vm.createContext({
    tenantId: { value: 7 }, page: { value: 2 }, pageSize: { value: 20 },
    workbenchTab: { value: '' }, q: { value: '' }, items: { value: [{ id: 1 }] },
    loading: { value: false }, error: { value: '' }, total: { value: 33 },
    workbenchCounts: { value: { all: 33, cancelled: 1 } }, loadGeneration: 0,
    listGeoContentTasks: async () => { throw new Error('synthetic network failure') },
  })
  vm.runInContext(load, context)
  await context.load()
  assert.equal(context.error.value, 'synthetic network failure')
  assert.equal(context.total.value, 0)
  assert.equal(context.items.value.length, 0)
  assert(Object.values(context.workbenchCounts.value).every(value => value === 0))
  assert.equal(context.loading.value, false)
})

test('task statuses and polish summary use Chinese labels', async () => {
  const { taskStatusLabel } = await import('../src/utils/geoReportLabels.js')
  assert.equal(taskStatusLabel('adapting'), '适配中')
  assert.equal(taskStatusLabel('cancelled'), '已取消')
  assert.match(source, /label: '待润色', value: workbenchCounts.value.polish/)
  assert.match(source, /value: 'cancelled', label: '已取消'/)
  assert.match(source, /文章为全时段 · 查询期仅作用于上方建议/)
  assert.doesNotMatch(source, /近 14 天|查看 GEO 写作规范/)
})
