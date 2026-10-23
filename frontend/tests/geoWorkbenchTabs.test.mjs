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
        workbench_counts: { all: 9, draft: 2, polish: 1, needs_fix: 3, ready: 2, published: 1 } }
    },
  })
  vm.runInContext(load, context)
  for (const tab of ['', 'draft', 'polish', 'needs_fix', 'ready', 'published']) {
    context.setTab(tab)
    while (context.loading.value) await new Promise(resolve => setImmediate(resolve))
    assert.equal(calls.at(-1).params.workbench_tab, tab || undefined)
    assert.equal(calls.at(-1).params.offset, 0)
    assert.equal(context.workbenchCounts.value.all, 9)
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
