import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import { ref, computed, reactive, watch, effectScope } from 'vue'
import { BACKFILL_CHANNELS, backfillChannelLabel } from '../src/utils/geoBackfillChannels.js'

const source = readFileSync(new URL('../src/components/GeoReceiptImport.vue', import.meta.url), 'utf8')
const script = source.slice(source.indexOf('const props ='), source.indexOf('</script>'))
const tick = () => new Promise(resolve => setImmediate(resolve))
const file = { name: 'receipt.json', size: 123 }
const ready = { can_confirm: true, rows: [{ status: '能导入' }] }
function fixture() {
  const props = reactive({ tenantId: 7, task: { id: 12, business_id: 20, article: { id: 16 }, variants: [{ channel: 'website' }] } })
  const notices = [], events = [], downloads = []
  let unmount
  const ctx = vm.createContext({ ref, computed, watch, BACKFILL_CHANNELS, backfillChannelLabel, defineProps: () => props,
    defineEmits: () => name => events.push(name), onBeforeUnmount: fn => { unmount = fn },
    fetchGeoProjects: async () => ({ projects: [{ id: 5, name: '合成项目', business_scope: { business_ids: [20] } }] }),
    importGeoReceipts: async () => ready, ElMessage: { success: value => notices.push(value) },
    Blob, URL: { createObjectURL: blob => { downloads.push(blob); return 'blob:test' }, revokeObjectURL: () => {} },
    document: { createElement: () => ({ click() {} }) }, setTimeout: fn => fn(),
  })
  const scope = effectScope()
  scope.run(() => vm.runInContext(script + '; state = { projects, projectId, busy, preview, error, open };', ctx))
  return { ctx, props, notices, events, downloads, state: ctx.state, stop: () => { unmount(); scope.stop() } }
}
async function upload(f, chosen = file) {
  await f.ctx.previewReceipts({ target: { files: [chosen], value: 'file' } })
}

test('upload only previews, confirmation posts same file and then refreshes parent', async () => {
  const f = fixture(); await tick(); const calls = []
  f.ctx.importGeoReceipts = async args => { calls.push(args); return args.dryRun ? ready : { committed: true, changed: 1 } }
  await upload(f)
  assert.equal(calls.length, 1); assert.equal(calls[0].dryRun, true)
  assert.equal(calls[0].projectId, 5); assert.equal(calls[0].tenantId, 7)
  assert.equal(f.events.length, 0)
  await f.ctx.confirmReceipts()
  assert.equal(calls[1].dryRun, false); assert.equal(calls[1].file, file)
  assert.deepEqual(f.events, ['imported']); assert.equal(f.state.preview.value, null); f.stop()
})

test('rejected rows prevent confirmation and invalid replacement clears prior preview', async () => {
  const f = fixture(); await tick(); let calls = 0
  f.ctx.importGeoReceipts = async () => { calls++; return { can_confirm: false, rows: [] } }
  await upload(f); await f.ctx.confirmReceipts(); assert.equal(calls, 1)
  f.ctx.importGeoReceipts = async () => ready; await upload(f)
  await upload(f, { name: 'bad.exe', size: 10 })
  assert.equal(f.state.preview.value, null); assert.match(f.state.error.value, /CSV/); f.stop()
})

test('customer switch discards delayed preview and prevents old file confirmation', async () => {
  const f = fixture(); await tick(); let done
  f.ctx.importGeoReceipts = () => new Promise(resolve => { done = resolve })
  const pending = upload(f); f.props.tenantId = 8
  done(ready); await pending; await tick()
  assert.equal(f.state.preview.value, null); assert.deepEqual(f.events, [])
  let calls = 0; f.ctx.importGeoReceipts = async () => { calls++; return ready }
  await f.ctx.confirmReceipts(); assert.equal(calls, 0); f.stop()
})

test('new article, project, or unmount invalidates preview', async () => {
  const f = fixture(); await tick(); await upload(f)
  f.state.projectId.value = 6; assert.equal(f.state.preview.value, null)
  await upload(f); f.props.task.article.id = 17; assert.equal(f.state.preview.value, null)
  await tick(); await upload(f); f.stop(); assert.equal(f.state.preview.value, null)
})

test('double confirm cannot submit twice and late success after switch stays silent', async () => {
  const f = fixture(); await tick(); await upload(f); let done, calls = 0
  f.ctx.importGeoReceipts = () => { calls++; return new Promise(resolve => { done = resolve }) }
  const pending = f.ctx.confirmReceipts(); await f.ctx.confirmReceipts(); assert.equal(calls, 1)
  f.props.tenantId = 8; done({ committed: true, changed: 1 }); await pending
  assert.deepEqual(f.events, []); assert.deepEqual(f.notices, []); f.stop()
})

test('downloaded CSV and JSON templates contain only fake example data', async () => {
  const f = fixture(); f.ctx.downloadTemplate('json'); f.ctx.downloadTemplate('csv')
  const json = await f.downloads[0].text(), csv = await f.downloads[1].text()
  assert.equal(JSON.parse(json)[0].article_id, '999999'); assert.match(json, /example.com/)
  assert.match(csv, /article_id,platform,channel_name,variant_id,public_url,published_at,note/)
  const examples = JSON.parse(json)
  assert.equal(examples[1].platform, '百度贴吧'); assert.equal(examples[1].variant_id, '888888')
  assert.equal(examples[2].platform, '其他'); assert.equal(examples[2].channel_name, '示例科技社区')
  assert.match(csv, /假数据示例/); f.stop()
})
