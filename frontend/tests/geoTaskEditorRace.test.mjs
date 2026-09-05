import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { createEditorContext } from '../src/utils/geoEditorContext.js'

function testContext(values) {
  values.captureEditorContext = () => createEditorContext(() => [values.tenantId?.value, values.taskId?.value, values.editorEpoch || 0, false])
  return vm.createContext(values)
}

const source = readFileSync(new URL('../src/views/geo/GeoTaskEditorView.vue', import.meta.url), 'utf8')
// Execute the actual component handler with controlled refs and a deferred API response.
const handler = source.slice(source.indexOf('async function saveBrief()'), source.indexOf('function briefRequiredEmpty()'))

test('switching editor context clears old title, draft and pending autosave', () => {
  const reset = source.slice(source.indexOf('function resetEditorContext()'), source.indexOf('watch([tenantId, taskId]'))
  const cleared = []
  const context = testContext({
    allFacts: { value: [] }, selectedFactIds: { value: [1] }, retrievePreview: { value: [] },
    channelAccounts: { value: [] }, publishingChannels: { value: [] }, channelBlueprint: { value: {} },
    webhookAccountId: { value: 1 }, publishUrl: { value: 'https://a.example/' }, publishNote: { value: 'A' },
    sectionHeading: { value: 'A' }, lastSavedAt: { value: new Date() }, docTab: { value: 'website' },
    variantEdit: { title: 'A', body_markdown: 'A' },
    editorEpoch: 0, activeJob: { value: {} }, generateHint: { value: '' }, impact: { value: {} }, pushTargets: { value: [] }, pushSelected: { value: [] }, pushBatchBusy: { value: true }, impactLoading: { value: true },
    autosaveTimer: 42, clearTimeout: (id) => cleared.push(id),
    busy: { value: 'save' },
    task: { value: { id: 100 } }, article: { title: 'Customer A', body_markdown: 'private draft' },
    briefLocalDraft: { value: true }, briefSuggestHint: { value: 'old hint' },
    applyBriefToForm: (brief) => cleared.push(Object.keys(brief).length),
    scoredDraftSnapshot: { value: 'old score' }, checkResult: { value: { ready: true } },
  })
  vm.runInContext(reset, context)
  context.resetEditorContext()
  assert.equal(context.task.value, null)
  assert.equal(context.publishUrl.value, '')
  assert.equal(context.webhookAccountId.value, null)
  assert.equal(context.variantEdit.body_markdown, '')
  assert.equal(context.busy.value, '')
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
  const context = testContext({
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

function articleFixture() {
  const requests = [], events = []
  const context = testContext({
    tenantId: { value: 7 }, taskId: { value: 100 }, loadGeneration: 1,
    task: { value: { id: 100, article: {} } },
    article: { title: 'A title', body_markdown: 'A private body' },
    busy: { value: '' }, checkResult: { value: 'current check' },
    scoredDraftSnapshot: { value: 'current score' }, docTab: { value: 'website' },
    lastSavedAt: { value: null }, stripCiteAppendix: (value) => value,
    saveGeoArticle: (tenant, id, body) => new Promise((resolve, reject) => {
      requests.push({ tenant, id, body, resolve, reject })
    }),
    applyArticleFromTask: (task) => Object.assign(context.article, task.article),
    ElMessage: { success: () => events.push('success'), warning: () => events.push('warning') },
    toastError: () => events.push('error'),
  })
  vm.runInContext(source.slice(source.indexOf('async function saveArticleBody('), source.indexOf('async function runGeoScore(')), context)
  return { context, requests, events }
}

for (const silent of [false, true]) {
  test(`late article save cannot copy customer A into B (silent=${silent})`, async () => {
    const { context: c, requests, events } = articleFixture()
    const pending = c.saveArticleBody({ silent })
    c.tenantId.value = 8
    c.taskId.value = 200
    c.loadGeneration++
    c.task.value = { id: 200, article: { title: 'B title', body_markdown: 'B body' } }
    Object.assign(c.article, c.task.value.article)
    c.busy.value = 'save' // A newer operation owns the current customer's busy state.
    requests[0].resolve({ id: 100, article: { title: 'A title', body_markdown: 'A private body' } })
    assert.equal(await pending, false)
    assert.equal(c.task.value.id, 200)
    assert.equal(c.article.body_markdown, 'B body')
    assert.equal(c.checkResult.value, 'current check')
    assert.equal(c.scoredDraftSnapshot.value, 'current score')
    assert.equal(c.docTab.value, 'website')
    assert.equal(c.lastSavedAt.value, null)
    assert.equal(c.busy.value, 'save')
    assert.deepEqual(events, [])
    const next = c.saveArticleBody({ silent })
    assert.equal(requests[1].tenant, 8)
    assert.equal(requests[1].id, 200)
    assert.equal(requests[1].body.body_markdown, 'B body')
    requests[1].resolve({ id: 200, article: requests[1].body })
    assert.equal(await next, true)
  })
}

for (const change of ['task', 'reload']) {
  test(`article save ignores stale response after ${change}`, async () => {
    const { context: c, requests } = articleFixture()
    const pending = c.saveArticleBody()
    if (change === 'task') c.taskId.value = 101
    else c.loadGeneration++
    requests[0].resolve({ id: 100, article: { title: 'stale', body_markdown: 'stale' } })
    assert.equal(await pending, false)
    assert.equal(c.article.title, 'A title')
    assert.equal(c.lastSavedAt.value, null)
    if (change === 'reload') assert.equal(c.busy.value, '')
  })
}

test('late article failure does not notify or clear another operation', async () => {
  const { context: c, requests, events } = articleFixture()
  const pending = c.saveArticleBody()
  c.tenantId.value = 8
  c.busy.value = 'save'
  requests[0].reject(new Error('old request failed'))
  assert.equal(await pending, false)
  assert.equal(c.busy.value, 'save')
  assert.deepEqual(events, [])
})

test('current article save applies the result and releases saving state', async () => {
  const { context: c, requests, events } = articleFixture()
  const pending = c.saveArticleBody()
  requests[0].resolve({ id: 100, article: { title: 'saved', body_markdown: 'saved body' } })
  assert.equal(await pending, true)
  assert.equal(c.article.title, 'saved')
  assert.equal(c.checkResult.value, null)
  assert.equal(c.docTab.value, 'master')
  assert.ok(c.lastSavedAt.value)
  assert.equal(c.busy.value, '')
  assert.deepEqual(events, ['success'])
})
