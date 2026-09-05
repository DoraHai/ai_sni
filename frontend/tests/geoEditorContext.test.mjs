import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { createEditorContext } from '../src/utils/geoEditorContext.js'
import { snapshotIds } from '../src/utils/geoTicketExecution.js'

const { parse } = createRequire(import.meta.url)('@babel/parser')
const file = readFileSync(new URL('../src/views/geo/GeoTaskEditorView.vue', import.meta.url), 'utf8')
const script = file.slice(file.indexOf('\n')+1, file.indexOf('</script>'))
const functions = parse(script, { sourceType: 'module' }).program.body.filter((n) => n.type === 'FunctionDeclaration')
const functionSource = (name) => { const n = functions.find((n) => n.id.name === name); return script.slice(n.start, n.end) }

for (const name of ['runGeoScore', 'runAiReview', 'runOptimize', 'runCheck', 'suggestBrief', 'genVariants', 'saveVariantBody', 'loadImpact', 'loadPushTargets', 'cancelActiveJob']) {
  test(`${name}: late API response cannot mutate another editor or start follow-up work`, async () => {
    let done
    const api = () => new Promise((resolve) => { done = resolve })
    const values = {
      tenantId: { value: 7 }, taskId: { value: 100 }, loadGeneration: 0,
      busy: { value: '' }, error: { value: '' }, task: { value: { id: 100 } },
      article: { title: 'A', body_markdown: 'A' }, hasMasterDraft: { value: true },
      checkResult: { value: null }, briefSuggestHint: { value: '' }, briefLocalDraft: { value: false },
      brief: {}, briefRequiredEmpty: () => false,
      channelDraftGate: { value: { allowed: true } }, channelPick: { value: ['website'] },
      jobLive: { value: false },
      variantEdit: { title: 'A', body_markdown: 'A' }, docTab: { value: 'website' },
      impact: { value: null }, impactLoading: { value: false }, impactWindowDays: { value: 14 },
      pushTargets: { value: [] }, pushSelected: { value: [] }, activeJob: { value: { id: 1 } },
      saveArticleBody: async () => true, checkGeoContentTask: api, aiReviewGeoContentTask: api,
      optimizeGeoArticle: api, suggestGeoTaskBrief: api, createGeoVariants: api, patchGeoVariant: api,
      fetchGeoContentTaskImpact: api, fetchTaskPushTargets: api, cancelGeoAsyncJob: api,
      ElMessage: new Proxy(() => { throw new Error('stale notification') }, { get: () => () => { throw new Error('stale notification') } }),
    }
    values.captureEditorContext = () => createEditorContext(() => [values.tenantId.value, values.taskId.value, 0, false])
    const c = vm.createContext(values)
    vm.runInContext(functionSource(name), c)
    const pending = c[name]('article')
    for (let i=0; i<10 && !done; i++) await Promise.resolve()
    assert.equal(typeof done, 'function', `${name} must reach API`)
    c.tenantId.value = 8; c.taskId.value = 200; c.task.value = { id: 200 }; c.busy.value = 'new operation'
    done({ id: 100, task: { id: 100 }, article: { title: 'A' } })
    assert.equal(await pending, false)
    assert.equal(c.task.value.id, 200)
    assert.equal(c.busy.value, 'new operation')
    assert.equal(c.checkResult.value, null)
    assert.equal(c.impact.value, null)
  })
}

test('leaving and returning to the same customer invalidates old work', async () => {
  let epoch = 0, disposed = false
  const request = createEditorContext(() => [7, 100, epoch, disposed])
  epoch++
  assert.equal(request.active(), false)
  await assert.rejects(request.wait(Promise.resolve('old')))
  const mounted = createEditorContext(() => [7, 100, epoch, disposed])
  disposed = true
  assert.equal(mounted.active(), false)
})

test('execution IDs preserve only valid positive snapshot identifiers', () => {
  assert.deepEqual(snapshotIds('1，2, 2、3'), [1, 2, 3])
  for (const text of ['-1', '1.5', 'abc', '1e3', '9007199254740993']) assert.throws(() => snapshotIds(text))
})

test('job polling stops without updating the UI after context changes', async () => {
  const apiSource = readFileSync(new URL('../src/api/geoContent.js', import.meta.url), 'utf8')
  const fn = apiSource.slice(apiSource.indexOf('export async function waitGeoAsyncJob('), apiSource.indexOf('export function previewGeoOnboarding(')).replace('export ', '')
  let resolve, active = true, calls = 0, ticks = 0
  const c = vm.createContext({ getGeoAsyncJob: () => { calls++; return new Promise((r) => { resolve = r }) }, setTimeout })
  vm.runInContext(fn, c)
  const pending = c.waitGeoAsyncJob(7, 1, { isCurrent: () => active, onTick: () => { ticks++ } })
  active = false
  resolve({ status: 'running' })
  assert.equal(await pending, null)
  assert.equal(calls, 1)
  assert.equal(ticks, 0)
})
