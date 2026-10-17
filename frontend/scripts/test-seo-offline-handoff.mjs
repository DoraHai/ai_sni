import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'
import { offlinePlatforms } from '../src/views/seo/seoOfflinePlatforms.js'

const source = await readFile(new URL('../src/views/seo/SeoOfflineHandoff.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const script = descriptor.scriptSetup.content.replace(/^import .*$/gm, '')
function fixture() {
  const writes = [], messages = [], emitted = [], downloads = [], watchers = []
  const props = { tenantId: 1, siteId: 2, identity: '7:1', contents: [
    { id: 10, title: '合成文章', status: 'ready', version_count: 3, payload_hash: 'a'.repeat(64) },
    { id: 11, title: '草稿', status: 'drafting', version_count: 1, payload_hash: 'b'.repeat(64) },
  ] }
  const state = { offlinePlatforms, defineProps: () => props, defineEmits: () => value => emitted.push(value),
    ref: value => ({ value }), reactive: value => value, computed: get => ({ get value() { return get() } }),
    watch: (_, fn) => watchers.push(fn), setTimeout: fn => fn(),
    ElMessage: Object.fromEntries(['success', 'warning', 'error'].map(k => [k, msg => messages.push([k, msg])])),
    URL: { createObjectURL: () => 'blob:synthetic', revokeObjectURL: () => {} },
    document: { createElement: () => ({ click() { downloads.push(this.download) } }) },
    exportSeoOfflineOrders: async body => { writes.push(body); return new Blob(['zip']) },
    importSeoOfflineReceipts: async args => { writes.push(args); return { rows: [{ status: 'unknown' }], committed: !args.dryRun, changed: 1 } },
  }
  vm.createContext(state)
  new vm.Script(script + ';globalThis.h={openOrders,exportOrders,previewReceipts,commitReceipts,selected,candidates,form,preview,orderDialog,receiptDialog}').runInContext(state)
  return { state, h: state.h, props, writes, messages, emitted, downloads, changeScope: () => watchers.forEach(fn => fn()) }
}
const event = () => ({ target: { files: [new File(['[]'], 'r.json')], value: 'selected' } })

test('Vue component script and template compile', () => {
  assert.equal(compileScript(descriptor, { id: 'offline-unit' }).deps?.length || 0, 0)
  assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename: 'SeoOfflineHandoff.vue', id: 'offline-unit' }).errors, [])
  assert.equal(new Set(offlinePlatforms).size, 25)
})
test('export uses frozen selected versions and excludes unreviewed articles', async () => {
  const f = fixture(); f.h.openOrders()
  assert.equal(f.h.candidates.value.length, 1)
  f.h.selected.value = ['10']; f.h.form.account = '合成账号'
  f.props.contents[0].version_count = 4
  await f.h.exportOrders()
  assert.equal(f.writes[0].articles[0].source_version, 3)
  assert.equal(f.writes[0].target_platform, offlinePlatforms[0])
  assert.equal(f.downloads[0], 'seo-offline-orders.zip')
})
test('import previews before commit and uses the same immutable file', async () => {
  const f = fixture(); await f.h.commitReceipts(); assert.equal(f.writes.length, 0)
  await f.h.previewReceipts(event()); assert.equal(f.writes[0].dryRun, true)
  await f.h.commitReceipts(); assert.equal(f.writes[1].dryRun, false)
  assert.equal(f.writes[0].file, f.writes[1].file)
  assert.deepEqual(f.emitted, ['imported'])
})
test('scope change invalidates preview, selection and account before commit', async () => {
  const f = fixture(); f.h.openOrders(); await f.h.previewReceipts(event())
  f.h.form.account = 'previous'; f.props.tenantId = 9; f.changeScope()
  await f.h.commitReceipts()
  assert.equal(f.writes.length, 1)
  assert.equal(f.h.receiptDialog.value, false)
  assert.equal(f.h.form.account, '')
  assert.equal(f.h.candidates.value.length, 0)
})
test('late preview for previous identity cannot enable import', async () => {
  const f = fixture(); let finish
  f.state.importSeoOfflineReceipts = () => new Promise(resolve => { finish = resolve })
  const pending = f.h.previewReceipts(event())
  f.props.identity = '8:2'; f.changeScope(); finish({ rows: [] }); await pending
  assert.equal(f.h.preview.value, null)
  await f.h.commitReceipts(); assert.equal(f.emitted.length, 0)
})
test('late export for previous site does not download and failure does not commit', async () => {
  const f = fixture(); f.h.openOrders(); f.h.selected.value = ['10']; f.h.form.account = '合成账号'
  f.state.exportSeoOfflineOrders = async () => { f.props.siteId = 9; return new Blob(['zip']) }
  await f.h.exportOrders(); assert.equal(f.downloads.length, 0)
  f.state.importSeoOfflineReceipts = async () => { throw Error('整批无效') }
  await f.h.previewReceipts(event()); await f.h.commitReceipts()
  assert.equal(f.emitted.length, 0)
  assert.equal(f.messages.at(-1)[1], '整批无效')
})
