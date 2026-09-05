import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { filterQueue, queueCounts, queueStageMeta } from '../src/utils/writebackQueue.js'

const rows = ['pending_writeback', 'executed', 'reconciliation_required', 'failed', 'new_status']
  .map((stage, id) => ({ stage, id }))
assert.deepEqual(filterQueue(rows, 'reconciliation_required'), [rows[2]])
assert.equal(filterQueue(rows, '').length, 5)
assert.equal(queueStageMeta('pending_writeback').label, '演练待回写（未真改）')
assert.equal(queueStageMeta('new_status').label, '状态未知，请核查')
assert.deepEqual(queueCounts(rows), {
  pending_writeback: 1, executed: 1, reconciliation_required: 1, failed: 1, unknown: 1,
})
assert.deepEqual(filterQueue([], 'reconciliation_required'), [])
assert.equal(queueCounts([]).reconciliation_required, 0)
assert.equal(rows.length, 5)
const view = readFileSync(new URL('../src/views/verify/PendingAdjustmentsView.vue', import.meta.url), 'utf8')
assert.ok(view.includes("const queueFilter = ref('reconciliation_required')"))
assert.ok(view.includes(':data="filteredQueue"'))
assert.ok(view.includes('mode === \'queue\' && data && !error'))
assert.ok(view.includes("session.canView('verify.adjustments')"))
assert.ok(view.includes('最多 200 条记录，不代表全部历史'))
assert.ok(view.includes("row.stage === 'reconciliation_required'"))
assert.ok(view.includes('const sequence = ++loadSequence'))
assert.ok(view.includes('if (sequence === loadSequence) data.value = result'))
assert.ok(view.indexOf('data.value = null') < view.indexOf('if (!TENANT_ID.value) return'))
// Exercise the actual view loader with deferred responses, without production APIs.
const loaderSource = view.slice(view.indexOf('async function load()'), view.indexOf('\nfunction delta('))
const pending = []
const context = {
  TENANT_ID: { value: 1 }, data: { value: { items: ['old'] } },
  error: { value: '' }, loading: { value: false }, mode: { value: 'queue' },
  days: { value: 7 }, statusFilter: { value: '' },
  fetchWritebackQueue: () => new Promise((resolve, reject) => pending.push({ resolve, reject })),
}
const load = new Function(...Object.keys(context), `let loadSequence = 0; ${loaderSource}; return load`)(...Object.values(context))
const first = load()
assert.equal(context.data.value, null)
context.TENANT_ID.value = 2
const second = load()
pending[1].resolve({ items: ['tenant-2'] })
await second
pending[0].resolve({ items: ['tenant-1'] })
await first
assert.deepEqual(context.data.value.items, ['tenant-2'])
const third = load()
assert.equal(context.data.value, null)
pending[2].reject(new Error('denied'))
await third
assert.equal(context.data.value, null)
assert.equal(context.error.value, 'denied')
assert.equal(context.loading.value, false)
const fourth = load()
context.TENANT_ID.value = null
await load()
pending[3].resolve({ items: ['stale'] })
await fourth
assert.equal(context.data.value, null)
assert.equal(context.loading.value, false)
console.log('SEM writeback queue tests passed')
