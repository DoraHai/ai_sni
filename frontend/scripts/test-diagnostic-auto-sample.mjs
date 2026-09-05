import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import assert from 'node:assert/strict'

const source = readFileSync(new URL('../src/views/diagnosis/DiagnosisCenterView.vue', import.meta.url), 'utf8')
const start = source.indexOf('async function createDeepSeekSample(')
const end = source.indexOf('async function copySampleResponse', start)
const watcherStart = source.indexOf('watch(\n  () => [tenantId.value, audit.value?.id')
const watcherEnd = source.indexOf('\nwatch(', watcherStart + 1)
let callback
let resolveRequest
const requests = []
const context = vm.createContext({
  tenantId: { value: 1 }, audit: { value: { id: 10, ai_enabled: true, snapshot: {} } },
  samplingLoading: { value: false }, sampleQuestions: { value: ['old question'] },
  aiSample: { value: null }, isCompetitorAudit: { value: false },
  automaticSampleAttempts: new Set(), ElMessage: { success() {}, error() {} },
  watch(_getter, handler) { callback = handler },
  runDeepSeekSample(args) { requests.push(args); return new Promise(resolve => { resolveRequest = resolve }) },
})
vm.runInContext(source.slice(start, end) + source.slice(watcherStart, watcherEnd), context)
callback()
assert.equal(requests.length, 1)
assert.equal(requests[0].questions.length, 0, 'automatic sampling uses backend defaults')
callback()
assert.equal(requests.length, 1, 'in-flight request is not duplicated')
context.tenantId.value = 2
context.audit.value = { id: 20, ai_enabled: true, snapshot: {} }
resolveRequest({ snapshot: { ai_sampling: { results: [{ question: 'old tenant' }] } } })
await new Promise(resolve => setImmediate(resolve))
assert.equal(context.audit.value.id, 20)
assert.equal(context.audit.value.snapshot.ai_sampling, undefined, 'stale result is ignored')
context.aiSample.value = { results: [] }
callback()
assert.equal(requests.length, 1, 'saved sampling is reused')
context.aiSample.value = null
context.isCompetitorAudit.value = true
callback()
assert.equal(requests.length, 1, 'competitor report is excluded')
context.isCompetitorAudit.value = false
callback()
assert.equal(requests.length, 2, 'next customer can sample after previous request settles')
resolveRequest({ snapshot: { ai_sampling: { results: [{ question: 'new default' }] } } })
await new Promise(resolve => setImmediate(resolve))
assert.equal(context.sampleQuestions.value[0], 'new default')
callback()
assert.equal(requests.length, 2, 'each report automatically runs only once')
console.log('Diagnostic automatic sampling checks passed')
