import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/views/geo/GeoTaskEditorView.vue', import.meta.url), 'utf8')
// Execute the actual component handler with controlled refs and a deferred API response.
const handler = source.slice(source.indexOf('async function saveBrief()'), source.indexOf('function briefRequiredEmpty()'))

test('switching editor context clears old title, draft and pending autosave', () => {
  const reset = source.slice(source.indexOf('function resetEditorContext()'), source.indexOf('watch([tenantId, taskId]'))
  const cleared = []
  const context = vm.createContext({
    autosaveTimer: 42, clearTimeout: (id) => cleared.push(id),
    task: { value: { id: 100 } }, article: { title: 'Customer A', body_markdown: 'private draft' },
    briefLocalDraft: { value: true }, briefSuggestHint: { value: 'old hint' },
    applyBriefToForm: (brief) => cleared.push(Object.keys(brief).length),
    scoredDraftSnapshot: { value: 'old score' }, checkResult: { value: { ready: true } },
  })
  vm.runInContext(reset, context)
  context.resetEditorContext()
  assert.equal(context.task.value, null)
  assert.equal(context.article.title, '')
  assert.equal(context.article.body_markdown, '')
  assert.equal(context.briefLocalDraft.value, false)
  assert.equal(context.briefSuggestHint.value, '')
  assert.equal(context.scoredDraftSnapshot.value, '')
  assert.equal(context.checkResult.value, null)
  assert.deepEqual(cleared, [42, 0])
})

function fixture() {
  let resolve
  const events = []
  const context = vm.createContext({
    tenantId: { value: 7 }, taskId: { value: 100 }, loadGeneration: 1,
    task: { value: { id: 100 } }, busy: { value: '' }, briefLocalDraft: { value: true },
    briefSuggestHint: { value: 'draft' }, briefPayload: () => ({ notes: 'edited' }),
    patchGeoContentTask: () => new Promise((done) => { resolve = done }),
    applyBriefToForm: (value) => events.push(value),
    ElMessage: { success: () => events.push('success') }, toastError: () => events.push('error'),
  })
  vm.runInContext(handler, context)
  return { context, events, finish: (value) => resolve(value) }
}

test('late brief save cannot overwrite another customer or task', async () => {
  const f = fixture()
  const pending = f.context.saveBrief()
  f.context.tenantId.value = 8
  f.context.taskId.value = 200
  f.context.task.value = { id: 200 }
  f.finish({ id: 100, brief: { notes: 'old' } })
  await pending
  assert.equal(f.context.task.value.id, 200)
  assert.deepEqual(f.events, [])
})

test('late brief save cannot overwrite a newer reload of the same task', async () => {
  const f = fixture()
  const pending = f.context.saveBrief()
  f.context.loadGeneration++
  f.finish({ id: 100, brief: { notes: 'old' } })
  await pending
  assert.deepEqual(f.events, [])
  assert.equal(f.context.briefLocalDraft.value, true)
})

test('current brief save applies response and clears the local draft', async () => {
  const f = fixture()
  const pending = f.context.saveBrief()
  f.finish({ id: 100, brief: { notes: 'saved' } })
  await pending
  assert.equal(f.context.task.value.brief.notes, 'saved')
  assert.equal(f.context.briefLocalDraft.value, false)
  assert.equal(f.events.at(-1), 'success')
})
