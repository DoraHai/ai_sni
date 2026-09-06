import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'

const { parse } = createRequire(import.meta.url)('@babel/parser')
const base = '../public/deal-sniper-prototype/geo/'
function find(node, predicate) {
  if (!node || typeof node !== 'object') return null
  if (predicate(node)) return node
  for (const value of Object.values(node)) {
    for (const child of Array.isArray(value) ? value : [value]) {
      const match = find(child, predicate)
      if (match) return match
    }
  }
  return null
}
function clickHandler(file, target) {
  const html = readFileSync(new URL(base + file, import.meta.url), 'utf8')
  for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) {
    const source = match[1]
    const node = find(parse(source), n => n.type === 'AssignmentExpression' && n.left?.type === 'MemberExpression'
      && n.left.property.name === 'onclick' && source.slice(n.left.start, n.left.end) === target)
    if (node) return source.slice(node.right.start, node.right.end)
  }
  throw new Error('Missing copy handler')
}
const editor = clickHandler('editor.html', "document.getElementById('btnCopyActive').onclick")
const channels = clickHandler('channels.html', "tr.querySelector('button').onclick")
const apiSource = readFileSync(new URL(base + 'assets/geo-api-v1.js', import.meta.url), 'utf8')
const preview = find(parse(apiSource), n => n.type === 'ObjectProperty' && n.key?.name === 'previewVariantExport').value
const registration = find(parse(apiSource), n => n.type === 'ObjectProperty' && n.key?.name === 'exportVariant').value

function setup(handler) {
  const requests = [], copied = [], messages = [], errors = []
  const title = { value: 'Saved title' }, body = { value: 'Saved body' }
  const v = { channel: 'website', title: title.value, body_markdown: body.value, status: 'draft' }
  const task = { id: 14, variants: [v] }
  const state = { tenant: 1 }
  const context = vm.createContext({
    task, taskId: 14, v, activeTab: 'website', err: {}, label: x => x,
    document: { getElementById: id => id === 'title' ? title : body },
    navigator: { clipboard: { writeText: async text => copied.push(text) } },
    alert: message => messages.push(message), GeoWB: { showError: (_, e) => errors.push(e.message) },
    withTenantQuery: () => ({ tenant_id: state.tenant }),
    api: async (path, options) => { requests.push(JSON.parse(JSON.stringify({ path, options }))); return { title: 'Saved title', body_markdown: 'Saved body' } },
    GeoAPI: { getTenantId: () => state.tenant },
  })
  vm.runInContext('GeoAPI.previewVariantExport = ' + apiSource.slice(preview.start, preview.end), context)
  vm.runInContext('var copyHandler = ' + handler, context)
  return { context, requests, copied, messages, errors, title, body, task, state }
}

for (const [name, handler] of [['channel list', channels], ['editor', editor]]) {
  test(`${name}: copy only performs GET and clipboard, never registration or refresh`, async () => {
    const s = setup(handler)
    const before = JSON.stringify(s.task)
    await s.context.copyHandler()
    assert.deepEqual(s.requests, [{ path: '/content-tasks/14/export', options: { method: 'GET', query: { tenant_id: 1, channel: 'website' } } }])
    assert.deepEqual(s.copied, ['# Saved title\n\nSaved body'])
    assert.equal(JSON.stringify(s.task), before)
    assert.deepEqual(s.errors, [])
    assert.match(s.messages[0], /未登记导出/)
    // Fixture deliberately exposes no exportVariant/getTask/renderAll/loadDetail.
  })
}

test('editor warns about unsaved channel edits before any request or copying', async () => {
  const s = setup(editor)
  s.body.value = 'Unsaved body'
  await s.context.copyHandler()
  assert.equal(s.requests.length, 0)
  assert.equal(s.copied.length, 0)
  assert.match(s.errors[0], /未保存修改/)
  assert.equal(s.body.value, 'Unsaved body')
})

test('master copy names the current unsaved editor content and performs no API call', async () => {
  const s = setup(editor)
  s.context.activeTab = 'master'
  s.body.value = 'Unsaved master'
  await s.context.copyHandler()
  assert.equal(s.requests.length, 0)
  assert.deepEqual(s.copied, ['# Saved title\n\nUnsaved master'])
  assert.match(s.messages[0], /未执行保存/)
})

test('editor does not copy a different server version behind the visible editor', async () => {
  const s = setup(editor)
  s.context.api = async () => ({ title: 'New title', body_markdown: 'New body' })
  await s.context.copyHandler()
  assert.equal(s.copied.length, 0)
  assert.match(s.errors[0], /服务端稿件已更新/)
})

test('editor preserves edits made while a copy read is in flight', async () => {
  const s = setup(editor)
  let resolve
  s.context.api = () => new Promise(done => { resolve = done })
  const pending = s.context.copyHandler()
  s.body.value = 'Edited while waiting'
  resolve({ title: 'Saved title', body_markdown: 'Saved body' })
  await pending
  assert.equal(s.copied.length, 0)
  assert.match(s.errors[0], /复制期间稿件发生修改/)
})

test('a late copy read cannot replace clipboard after customer switch', async () => {
  const s = setup(channels)
  let resolve
  s.context.api = () => new Promise(done => { resolve = done })
  const pending = s.context.copyHandler()
  s.state.tenant = 2
  resolve({ title: 'Saved title', body_markdown: 'Saved body' })
  await pending
  assert.equal(s.copied.length, 0)
  assert.match(s.errors[0], /页面已切换/)
})

test('legacy HTML two-argument copy call rejects before any network or clipboard work', async () => {
  const s = setup(editor)
  vm.runInContext('GeoAPI.exportVariant = ' + apiSource.slice(registration.start, registration.end), s.context)
  // Reproduce the actual a22263c08461 editor/channels call contract, verified
  // against the three deployed file hashes. Do not require old git history in CI.
  vm.runInContext(`async function legacyCopy() {
    var data = await GeoAPI.exportVariant(taskId, 'website');
    await navigator.clipboard.writeText('# ' + data.title + '\\n\\n' + data.body_markdown);
    task = await GeoAPI.getTask(taskId);
    renderAll();
  }`, s.context)
  await assert.rejects(s.context.legacyCopy(), /刷新页面/)
  assert.equal(s.requests.length, 0)
  assert.equal(s.copied.length, 0)
})

test('registration rejects malformed revisions without GET fallback or auto-fetch', async () => {
  const s = setup(editor)
  vm.runInContext('GeoAPI.exportVariant = ' + apiSource.slice(registration.start, registration.end), s.context)
  for (const revision of [undefined, null, '', {}, 42, 'a'.repeat(63), 'g'.repeat(64), 'A'.repeat(64)]) {
    await assert.rejects(s.context.GeoAPI.exportVariant(14, 'website', revision), /刷新页面/)
  }
  assert.equal(s.requests.length, 0)
})

test('valid saved revision still performs one explicit POST', async () => {
  const s = setup(editor)
  vm.runInContext('GeoAPI.exportVariant = ' + apiSource.slice(registration.start, registration.end), s.context)
  await s.context.GeoAPI.exportVariant(14, 'website', 'a'.repeat(64))
  assert.deepEqual(s.requests, [{ path: '/content-tasks/14/export', options: {
    method: 'POST', body: { expected_revision: 'a'.repeat(64) }, query: { tenant_id: 1, channel: 'website' },
  } }])
})
