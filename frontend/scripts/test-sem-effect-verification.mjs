import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const view = readFileSync(new URL('../src/views/verify/PendingAdjustmentsView.vue', import.meta.url), 'utf8')
const source = view.slice(view.indexOf('async function setVerdict('), view.indexOf('\nasync function reopen('))
const calls = []
const context = {
  TENANT_ID: { value: 1 }, effectOffset: { value: 50 },
  ElMessage: { warning() {}, success() {}, error(message) { throw Error(message) } },
  ElMessageBox: { async prompt() { return { value: '报表核对消费下降' } } },
  markVerified: async (payload) => { calls.push(payload) }, load() {},
}
const setVerdict = new Function(...Object.keys(context), `${source}; return setVerdict`)(...Object.values(context))
const item = { dedup_key: 'record', effect: { sample: { state: 'collecting' } } }
await setVerdict(item, 'achieved')
assert.equal(calls.length, 0, 'insufficient evidence must not call review API')
await setVerdict(item, 'watch')
assert.equal(calls[0].verdict, 'watch')
assert.equal(context.effectOffset.value, 0)
item.effect.sample.state = 'ready'
await setVerdict(item, 'achieved')
assert.equal(calls[1].note, '报表核对消费下降')
assert.equal(calls[1].tenantId, 1)
context.ElMessageBox.prompt = async () => { context.TENANT_ID.value = 2; return { value: '切换客户后不能提交' } }
await setVerdict(item, 'missed')
assert.equal(calls.length, 2, 'tenant switch during prompt cancels submission')
context.ElMessageBox.prompt = async () => { throw Error('cancel') }
await setVerdict(item, 'missed')
assert.equal(calls.length, 2)

const loaderSource = view.slice(view.indexOf('async function load()'), view.indexOf('\nfunction delta('))
const requests = []
const loadContext = {
  TENANT_ID: { value: 1 }, data: { value: null }, error: { value: '' }, loading: { value: false },
  mode: { value: 'keyword' }, days: { value: 30 }, statusFilter: { value: 'pending' }, effectOffset: { value: 50 },
  fetchPendingAdjustments: async (params) => { requests.push(params); return { items: [] } },
  fetchBudgetAdjustments: async (params) => { requests.push(params); return { items: [] } },
}
const load = new Function(...Object.keys(loadContext), `let loadSequence = 0; ${loaderSource}; return load`)(...Object.values(loadContext))
await load()
loadContext.mode.value = 'budget'
await load()
assert.deepEqual(requests, Array(2).fill({ tenantId: 1, days: 30, status: 'pending', offset: 50, limit: 50 }))
assert.equal((view.match(/:disabled="it.effect.sample\?\.state !== 'ready'"/g) || []).length, 4)
assert.ok(view.includes('历史人工标记未留指标快照'))
assert.ok(view.includes('@current-change="changeEffectPage"'))
console.log('SEM effect review / pagination contracts passed')
