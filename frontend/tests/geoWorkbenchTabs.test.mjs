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
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(calls.at(-1).params.workbench_tab, tab || undefined)
    assert.equal(calls.at(-1).params.offset, 0)
    assert.equal(context.workbenchCounts.value.all, 9)
    assert.equal(context.workbenchCounts.value.needs_fix, 3)
    assert.equal(context.items.value[0].status, tab || 'draft')
  }
  assert.match(source, /value: 'needs_fix', label: '待修补', count: workbenchCounts.value.needs_fix/)
})
