import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const source = await readFile(new URL('../src/views/optimize/KeywordExpandView.vue', import.meta.url), 'utf8')
assert.match(source, /ai_freshness_counts\?\.stale/)
assert.match(source, /ai_freshness_counts\?\.unverified/)
assert.match(source, /row.ai_freshness !== 'current'/)
assert.match(source, /历史结果未核验/)
assert.match(source, /普通评估会跳过旧结果/)
assert.match(source, /不作为默认 AI 出价依据/)
// Check each visible explanation, not just one matching occurrence in the file.
const footer = source.match(/<div class="note">([\s\S]*?)<\/div>/)[1]
assert.match(footer, /系统配置的模型/)
assert.match(footer, /AI 评估每次最多 5 个去重词/)
assert.match(footer, /实际数量见评估按钮/)
assert.match(footer, /超时不自动重试/)
assert.match(footer, /不自动继续或采纳/)
assert.match(footer, /需人工确认，不等于已判定为无关词/)
assert.match(footer, /「仅看业务相关」会隐藏其他分类/)
assert.match(source, /候选拉取上限/)
assert.doesNotMatch(source, /DeepSeek|隐藏通用噪音|每次最多 20/)
const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
  .replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*$/gm, '')
  .replace(/import\.meta\.env/g, '({})')
const makeView = new Function('deps', `
  const {computed,ref,reactive,watch,onMounted,session,ElMessage,ElMessageBox,
    sampleCandidates,syncExpansion,evaluateCandidates,fetchCandidates} = deps;
  ${script}
  return {syncForm,runSync,runEvaluate,evaluationResult,evaluationRound,load,data};
`)

function fixture(overrides = {}) {
  const calls = []
  const messages = []
  const deps = {
    ref: value => ({value}), reactive: value => value,
    computed: fn => ({get value() { return fn() }}), watch() {}, onMounted() {},
    session: {tenantId: 3},
    ElMessage: Object.fromEntries(['success', 'warning', 'error', 'info'].map(k => [k, msg => messages.push([k,msg])])),
    ElMessageBox: {confirm: async () => {}},
    sampleCandidates: async args => {calls.push(['sample',args]); return {candidates_written: 5}},
    syncExpansion: async args => {calls.push(['bulk',args]); return {seeds: [],planner_candidates: 1,query_candidates: 0}},
    evaluateCandidates: async args => {calls.push(['eval',args]); return {enabled:true,evaluated:2,successful_words:2,remaining:7,failed_words:1}},
    fetchCandidates: async () => ({}), ...overrides,
  }
  return {view: makeView(deps), deps, calls, messages}
}

const f = fixture()
assert.equal(f.view.syncForm.smallBatch, true)
assert.equal(f.view.syncForm.limit, 20)
await f.view.runSync()
assert.equal(f.calls.length, 0, 'empty seed must not call a service')
f.view.syncForm.seeds = '粉末涂料'
await f.view.runSync()
assert.deepEqual(f.calls, [['sample',{tenantId:3,seed:'粉末涂料',limit:20}]])
await f.view.runEvaluate()
assert.deepEqual(f.calls[1], ['eval',{tenantId:3,force:false,limit:5,afterId:0,retryIds:undefined}])
assert.match(f.view.evaluationResult.value, /剩余 0 词/)
assert.match(f.view.evaluationResult.value, /失败或缺失 1 词/)
assert.equal(f.calls.length, 2, 'no automatic AI after sample or continuation after evaluation')

for (const limit of [null, 0, 21, 1.5]) {
  const g = fixture()
  Object.assign(g.view.syncForm, {seeds:'粉末',limit})
  await g.view.runSync()
  await g.view.runEvaluate()
  assert.equal(g.calls.length, 0)
}
const cancel = fixture({ElMessageBox:{confirm:async () => {throw new Error('cancel')}}})
cancel.view.syncForm.smallBatch = false
await cancel.view.runSync()
await cancel.view.runEvaluate(true)
assert.equal(cancel.calls.length, 0, 'bulk and force actions require confirmation')

let confirmationText = ''
const confirmed = fixture({ElMessageBox:{confirm:async message => {confirmationText = message}}})
await confirmed.view.runEvaluate(true)
assert.match(confirmationText, /每批最多 5 词/)
assert.equal(confirmed.calls[0][1].limit, 5, 'confirmation and transmitted limit agree')

for (const limit of [1, 3, 5, 6, 20]) {
  let prompt = ''
  const bounded = fixture({ElMessageBox:{confirm:async message => {prompt = message}}})
  bounded.view.syncForm.limit = limit
  await bounded.view.runEvaluate(true)
  const actual = Math.min(limit, 5)
  assert.match(prompt, new RegExp(`每批最多 ${actual} 词`))
  assert.equal(bounded.calls[0][1].limit, actual)
  assert.equal(bounded.calls.length, 1, 'one explicit evaluation, no hidden continuation')
}

const disabled = fixture({evaluateCandidates:async () => ({enabled:false})})
await disabled.view.runEvaluate()
assert.deepEqual(disabled.messages, [['warning', '未启用 AI 评估，请联系管理员检查模型配置']])
assert.equal(disabled.view.evaluationRound.value, null)

const rejected = fixture({evaluateCandidates: async () => {throw new Error('HTTP 422')}})
rejected.view.evaluationRound.value = {force:true,failedIds:[1,2,3,4,5,6],nextAfterId:20,deferred:5}
await rejected.view.runEvaluate(false, 'retry')
assert.deepEqual(rejected.view.evaluationRound.value.failedIds, [1,2,3,4,5,6], 'rejected retry must retain every queued ID')

let finish
let evaluationCalls = 0
const pending = fixture({evaluateCandidates: () => {evaluationCalls++; return new Promise(resolve => {finish=resolve})}})
const inFlight = pending.view.runEvaluate()
await pending.view.runEvaluate()
assert.equal(evaluationCalls, 1, 'double click cannot dispatch another evaluation')
pending.deps.session.tenantId = 4
finish({enabled:true,evaluated:20,successful_words:20,remaining:4})
await inFlight
assert.equal(pending.view.evaluationResult.value, '', 'old customer results must not appear under a new customer')
assert.equal(pending.messages.length, 0)

const loaders = []
const switching = fixture({fetchCandidates: () => new Promise(resolve => loaders.push(resolve))})
const oldLoad = switching.view.load()
switching.deps.session.tenantId = 4
const newLoad = switching.view.load()
loaders[1]({total:4})
await newLoad
loaders[0]({total:3})
await oldLoad
assert.equal(switching.view.data.value.total, 4, 'stale candidate lists cannot overwrite the current customer')

const batchCalls = []
const batches = fixture({evaluateCandidates: async args => {
  batchCalls.push(args)
  if (args.retryIds) return {enabled:true,evaluated:args.retryIds.length,successful_words:args.retryIds.length,failed_candidate_ids:[],next_after_id:null,deferred:0}
  if (args.afterId) return {enabled:true,evaluated:5,successful_words:5,failed_candidate_ids:[],next_after_id:null,deferred:0}
  return {enabled:true,evaluated:0,failed_words:20,failed_candidate_ids:Array.from({length:20}, (_,i)=>i+1),next_after_id:20,deferred:5}
}})
await batches.view.runEvaluate(true)
assert.equal(batchCalls.length, 1)
assert.equal(batches.view.evaluationRound.value.failedIds.length, 20)
await batches.view.runEvaluate(false, 'next')
assert.equal(batchCalls[1].afterId, 20)
assert.equal(batchCalls[1].force, true, 'continuation preserves the round mode')
assert.equal(batches.view.evaluationRound.value.nextAfterId, null)
await batches.view.runEvaluate(false, 'next')
assert.equal(batchCalls.length, 2, 'end-of-round does not restart automatically')
// Even an old 20-word failure queue retries only five IDs; retain the rest.
assert.equal(batches.view.syncForm.limit, 20)
await batches.view.runEvaluate(false, 'retry')
assert.deepEqual(batchCalls[2].retryIds, [1,2,3,4,5])
assert.equal(batchCalls[2].afterId, 0)
assert.equal(batches.view.evaluationRound.value.failedIds.length, 15)
assert.equal(batches.view.evaluationRound.value.nextAfterId, null)
assert.match(batches.view.evaluationResult.value, /待重试 15 词/)

const failedRetry = fixture({evaluateCandidates: async args => ({enabled:true,evaluated:0,failed_words:args.retryIds.length,failed_candidate_ids:args.retryIds})})
failedRetry.view.evaluationRound.value = {force:true,failedIds:[1,2,3],nextAfterId:20,deferred:5}
failedRetry.view.syncForm.limit = 1
await failedRetry.view.runEvaluate(false, 'retry')
assert.deepEqual(failedRetry.view.evaluationRound.value.failedIds, [2,3,1], 'persistent failures rotate behind untried retries')
assert.equal(failedRetry.view.evaluationRound.value.nextAfterId, 20, 'retry never advances the main cursor')

const api = await readFile(new URL('../src/api/expansion.js', import.meta.url), 'utf8')
const requestModule = await import(`data:text/javascript,${encodeURIComponent(api.replace("import client from './client'", 'const client = { post: (...args) => args }'))}`)
assert.equal(requestModule.sampleCandidates({tenantId:3,seed:'粉末'})[2].params.limit, 20)
assert.equal(requestModule.evaluateCandidates({tenantId:3,force:true,limit:5})[2].params.limit, 5)
assert.equal(requestModule.evaluateCandidates({tenantId:3,afterId:20})[2].params.after_id, 20)
assert.equal(requestModule.evaluateCandidates({tenantId:3})[2].params.limit, 5)
assert.equal(requestModule.evaluateCandidates({tenantId:3})[2].timeout, 60000)
assert.match(source, /Math.min\(syncForm.limit, 5\)/)
assert.match(source, /每次最多 5 词/)
assert.deepEqual(requestModule.evaluateCandidates({tenantId:3,retryIds:[1,2]})[1], {retry_ids:[1,2]})
assert.match(source, /:max="20"/)
assert.doesNotMatch(source, /全部重评/)
console.log('SEM expansion small-batch request and UI behavior tests passed')
