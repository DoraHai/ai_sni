import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import vm from 'node:vm'

// Execute the actual SFC handlers with isolated state/transport, not a duplicate implementation.
const source = await readFile(new URL('../src/views/seo/SeoDistributionView.vue', import.meta.url), 'utf8')
const handlers = source.slice(source.indexOf('function openManual('), source.indexOf('function openBatch('))
function fixture() {
  const content = {id: 10, title: 'draft', version_count: 2, payload_hash: 'a'.repeat(64)}
  const writes = [], messages = []
  const state = {manualForm: {}, manualDialog: {value: false}, manualSaving: {value: false},
    contents: {value: [content]}, currentTenantId: {value: 4}, siteId: {value: 2}, scope: '4:2:7',
    load: async () => {}, createSeoManualPublication: async body => writes.push(body),
    ElMessage: {warning: msg => messages.push(msg), error: msg => messages.push(msg), success: msg => messages.push(msg)}}
  state.currentResultScope = () => state.scope
  vm.createContext(state)
  new vm.Script(handlers + ';globalThis.handlers={openManual,selectManualContent,saveManual}').runInContext(state)
  state.handlers.openManual(content)
  Object.assign(state.manualForm, {platform_name: '测试平台', page_url: 'https://example.com/article'})
  return {state, content, writes, messages}
}

test('selection freezes the version/hash that was shown, not the later background refresh', async () => {
  const {state, content, writes} = fixture()
  content.version_count = 3; content.payload_hash = 'b'.repeat(64)
  await state.handlers.saveManual()
  assert.equal(writes.length, 1)
  assert.equal(writes[0].source_version, 2)
  assert.equal(writes[0].payload_hash, 'a'.repeat(64))
  assert.equal(state.manualSaving.value, false)
})
test('explicit selection binds the selected article and its expected version', async () => {
  const {state, writes} = fixture()
  state.contents.value.push({id: 11, version_count: 4, payload_hash: 'c'.repeat(64)})
  state.manualForm.content_id = 11
  state.handlers.selectManualContent(11)
  await state.handlers.saveManual()
  assert.equal(writes[0].content_id, 11)
  assert.equal(writes[0].source_version, 4)
  assert.match(source, /v-model="manualForm.content_id"[^>]+@change="selectManualContent"/)
})
test('missing version/hash or changed identity/site prevents submission', async () => {
  for (const change of ['hash', 'version', 'scope']) {
    const {state, writes, messages} = fixture()
    if (change === 'hash') state.manualForm.payload_hash = null
    else if (change === 'version') state.manualForm.source_version = null
    else state.scope = '5:3:8'
    await state.handlers.saveManual()
    assert.equal(writes.length, 0)
    assert.equal(messages.length, 1)
  }
})
test('conflict retains the dialog and never retries with a newer version', async () => {
  const {state, writes, messages} = fixture()
  state.createSeoManualPublication = async body => {writes.push(body); throw Error('409 version conflict')}
  await state.handlers.saveManual()
  assert.equal(writes.length, 1)
  assert.equal(state.manualDialog.value, true)
  assert.match(messages[0], /409/)
  assert.equal(state.manualSaving.value, false)
})
test('late response for a previous scope does not close the current dialog or show success', async () => {
  const {state, messages} = fixture()
  state.createSeoManualPublication = async () => {state.scope = '5:3:8'}
  await state.handlers.saveManual()
  assert.equal(state.manualDialog.value, true)
  assert.equal(messages.length, 0)
})
