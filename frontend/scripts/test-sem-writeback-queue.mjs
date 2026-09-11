import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  canOpenControlledActionQueue,
  coreActionFlow,
  filterQueue,
  flowAccountScopeLabel,
  flowBasisLabel,
  flowControlLabel,
  queueCounts,
  queueStageMeta,
} from '../src/utils/writebackQueue.js'

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
const flow = {
  version: 'sem-controlled-action-v1', family: 'keyword_bid',
  control: { recorded_mode: 'dry_run', account_action_scope_state: 'scope_disabled' },
  check_basis: { baidu_account_id: 17, keyword_id: 701 },
}
assert.equal(coreActionFlow({ flow }), flow)
assert.equal(coreActionFlow({ flow: { ...flow, family: 'other' } }), null)
assert.equal(flowControlLabel(flow), '演练留痕，未调用百度写接口')
assert.equal(flowAccountScopeLabel(flow), '账户有效，该动作范围未配置真写')
assert.equal(flowBasisLabel(flow), '账户 17 · 关键词 701')
assert.equal(canOpenControlledActionQueue({ 'optimize.keywords': 'edit' }), false)
assert.equal(canOpenControlledActionQueue({ 'optimize.negatives': 'edit', 'optimize.searchterms': 'edit' }), false)
assert.equal(canOpenControlledActionQueue({ 'verify.adjustments': 'view' }), true)
assert.equal(canOpenControlledActionQueue({ 'verify.adjustments': 'edit' }), true)
const view = readFileSync(new URL('../src/views/verify/PendingAdjustmentsView.vue', import.meta.url), 'utf8')
assert.ok(view.includes("? route.query.stage"))
assert.ok(view.includes(':data="filteredQueue"'))
assert.ok(view.includes('mode === \'queue\' && data && !error'))
assert.ok(view.includes('canOpenControlledActionQueue(session.permissions)'))
assert.ok(view.includes('最多 200 条记录，不代表全部历史'))
assert.ok(view.includes("row.stage === 'reconciliation_required'"))
assert.ok(view.includes('待调整'))
assert.ok(view.includes('受控执行'))
assert.ok(view.includes('结果读取'))
assert.ok(view.includes('检查依据'))
assert.ok(view.includes('行动台账'))
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
  queueFilter: { value: 'reconciliation_required' }, queueOffset: { value: 0 },
  fetchWritebackQueue: (tenantId, params) => new Promise((resolve, reject) => pending.push({ tenantId, params, resolve, reject })),
}
const load = new Function(...Object.keys(context), `let loadSequence = 0; ${loaderSource}; return load`)(...Object.values(context))
const first = load()
assert.deepEqual(pending[0].params, { stage: 'reconciliation_required', offset: 0, limit: 200 })
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
context.TENANT_ID.value = 2
context.queueFilter.value = 'executed'
context.queueOffset.value = 200
const page = load()
assert.deepEqual(pending[4].params, { stage: 'executed', offset: 200, limit: 200 })
pending[4].resolve({ counts_scope: 'tenant_history', counts: { executed: 700 }, total: 700, items: ['page-2'] })
await page
assert.equal(context.data.value.total, 700)
assert.ok(view.includes('queueOffset.value = 0'))
assert.ok(view.includes('@current-change="changeQueuePage"'))
for (const relative of [
  '../src/views/optimize/KeywordWorkbenchView.vue',
  '../src/views/optimize/NegativeWordsView.vue',
  '../src/views/optimize/SearchTermsView.vue',
]) {
  const source = readFileSync(new URL(relative, import.meta.url), 'utf8')
  assert.ok(source.includes("path: '/verify/pending'"), `${relative} must link to the controlled-action queue`)
  assert.ok(source.includes('执行与核对'))
  assert.ok(source.includes('v-if="canOpenActionQueue"'))
}
console.log('SEM writeback queue tests passed')
