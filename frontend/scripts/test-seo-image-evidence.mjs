import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'

const source = await readFile(new URL('../src/views/seo/SeoImageEvidenceDialog.vue', import.meta.url), 'utf8')
const code = compileScript(parse(source).descriptor, { id: 'images-test', genDefaultAs: 'component' }).content.replace(/^import .* from .*$/gm, '')
const requests = [], remediationRequests = [], historyRequests = [], copyRequests = [], previewRequests = [], reuseRequests = [], messages = []
const bindings = { computed: Vue.computed, ref: Vue.ref, watch: Vue.watch, onBeforeUnmount: Vue.onBeforeUnmount,
  fetchSeoImageEvidence: args => new Promise((resolve, reject) => requests.push({ args, resolve, reject })),
  fetchSeoImageRemediation: args => new Promise((resolve, reject) => remediationRequests.push({ args, resolve, reject })),
  fetchSeoImageRemediationHistory: args => new Promise((resolve, reject) => historyRequests.push({ args, resolve, reject })),
  fetchSeoImageRemediationReusePreview: args => new Promise((resolve, reject) => previewRequests.push({ args, resolve, reject })),
  copySeoImageRemediation: async args => { copyRequests.push(args); return { copied: 1, skipped_existing: 0, skipped_ambiguous: 0 } },
  reuseSeoImageRemediation: async args => { reuseRequests.push(args); return { copied: 1, skipped_existing: 0, skipped_ambiguous: 0 } },
  saveSeoImageRemediation: async () => ({}),
  ElMessage: { success() {}, warning(message) { messages.push(message) }, error() {} }, ElMessageBox: { confirm: async () => true },
}
const Component = new Function('b', `const {${Object.keys(bindings)}}=b;${code};return component`)(bindings)
Component.render = () => null
const renderer = Vue.createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  setText() {}, setElementText() {}, patchProp() {}, insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
const props = Vue.reactive({ visible: true, tenantId: 1, siteId: 1, page: { id: 234 } })
const child = Vue.ref()
const app = renderer.createApp({ render: () => Vue.h(Component, { ...props, ref: child }) })
app.mount({})
const state = () => child.value.$.setupState
const flush = async () => { for (let i = 0; i < 4; i++) { await Promise.resolve(); await Vue.nextTick() } }
assert.deepEqual(requests[0].args, { tenantId: 1, siteId: 1, pageId: 234, snapshotId: null })
assert.deepEqual(remediationRequests[0].args, { tenantId: 1, siteId: 1, pageId: 234, snapshotId: null })
assert.deepEqual(historyRequests[0].args, { tenantId: 1, siteId: 1, pageId: 234 })
assert.deepEqual(previewRequests[0].args, { tenantId: 1, siteId: 1, pageId: 234 })
props.tenantId = 2; props.siteId = 2
await flush()
requests.at(-1).resolve({ snapshot_id: 12, evidence: { items: [{ position: 1, alt_state: 'empty' }, { position: 2, alt_state: 'missing' }] } })
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [{ id: 7, position: 2, decision: 'informative', alt_suggestion: '产品图', review_status: 'draft' }] })
historyRequests.at(-1).resolve({ current_snapshot_id: 12, items: [{ snapshot_id: 12, approved_count: 0, candidate_count: 2 }, { snapshot_id: 11, approved_count: 1, candidate_count: 1 }] })
previewRequests.at(-1).resolve({ target_snapshot_id: 12, eligible_count: 1, source_page_count: 1 })
await flush()
requests[0].resolve({ snapshot_id: 11, evidence: { items: [{ secret: 'previous tenant' }] } })
remediationRequests[0].resolve({ snapshot_id: 11, items: [] })
historyRequests[0].resolve({ current_snapshot_id: 11, items: [] })
previewRequests[0].resolve({ target_snapshot_id: 11, eligible_count: 0, source_page_count: 0 })
await flush()
assert.equal(state().items.length, 2)
state().filter = 'missing'
assert.deepEqual(state().items, [{ position: 2, alt_state: 'missing' }])
assert.equal(state().drafts[2].id, 7)
const originalDocument = globalThis.document
const originalCreateObjectURL = URL.createObjectURL
const originalRevokeObjectURL = URL.revokeObjectURL
const originalSetTimeout = globalThis.setTimeout
const downloads = [], revoked = [], timers = []
globalThis.document = {
  body: { appendChild(anchor) { anchor.appended = true } },
  createElement(tag) {
    assert.equal(tag, 'a')
    return { style: {}, click() { downloads.push({ filename: this.download, href: this.href, appended: this.appended }) }, remove() { this.removed = true } }
  },
}
URL.createObjectURL = blob => { downloads.blob = blob; return 'blob:seo-export' }
URL.revokeObjectURL = url => revoked.push(url)
globalThis.setTimeout = callback => { timers.push(callback); return 1 }
state().data.evidence.items = [
  { position: 1, section: 'footer', source_url: 'https://example.com/decorative.png', alt_state: 'empty' },
  { position: 2, section: 'main', source_url: 'https://example.com/manual.webp', alt_state: 'missing' },
]
state().drafts[1] = { decision: 'decorative', alt_suggestion: '', review_status: 'approved', note: '已有相邻文字' }
state().drafts[2] = { decision: 'informative', alt_suggestion: 'NORDCON 软件操作手册 BU0000 封面', review_status: 'approved', note: '内容图' }
state().exportWorklist()
assert.deepEqual(downloads[0], { filename: 'SEO图片整改-234-snapshot-12.csv', href: 'blob:seo-export', appended: true })
const worklistCsv = await downloads.blob.text()
assert(worklistCsv.includes('NORDCON 软件操作手册 BU0000 封面'))
assert(!worklistCsv.includes('decorative.png'), 'remediation worklist must exclude decorative images')
assert.equal(worklistCsv.split('\n').length, 2, 'worklist contains one header and one actionable row')
state().exportAuditRecords()
assert.equal(downloads[1].filename, 'SEO图片审核记录-234-snapshot-12.csv')
const auditCsv = await downloads.blob.text()
assert(auditCsv.includes('decorative.png'))
assert(auditCsv.includes('manual.webp'))
assert.equal(auditCsv.split('\n').length, 3, 'audit export contains both reviewed candidates')
timers.forEach(callback => callback())
assert.deepEqual(revoked, ['blob:seo-export', 'blob:seo-export'])
state().drafts[2].review_status = 'draft'
state().exportWorklist()
assert.equal(downloads.length, 2)
assert.equal(messages.at(-1), '暂无已审核且需要 Alt 的内容图')
globalThis.document = originalDocument
URL.createObjectURL = originalCreateObjectURL
URL.revokeObjectURL = originalRevokeObjectURL
globalThis.setTimeout = originalSetTimeout
const reused = state().reuseAcrossPages()
await flush()
assert.deepEqual(reuseRequests[0], { tenant_id: 2, site_id: 2, page_id: 234, expected_snapshot_id: 12 })
requests.at(-1).resolve({ snapshot_id: 12, evidence: { items: [{ position: 1, alt_state: 'empty' }, { position: 2, alt_state: 'missing' }] } })
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [{ id: 7, position: 2, decision: 'informative', alt_suggestion: '产品图', review_status: 'draft' }] })
historyRequests.at(-1).resolve({ current_snapshot_id: 12, items: [{ snapshot_id: 12, approved_count: 0, candidate_count: 2 }, { snapshot_id: 11, approved_count: 1, candidate_count: 1 }] })
previewRequests.at(-1).resolve({ target_snapshot_id: 12, eligible_count: 0, source_page_count: 0 })
await reused
const copied = state().copyPrevious()
await flush()
assert.deepEqual(copyRequests[0], { tenant_id: 2, site_id: 2, page_id: 234, expected_snapshot_id: 12, source_snapshot_id: 11 })
requests.at(-1).resolve({ snapshot_id: 12, evidence: { items: [{ position: 1, alt_state: 'empty' }, { position: 2, alt_state: 'missing' }] } })
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [{ id: 8, position: 2, decision: 'informative', alt_suggestion: '产品图', review_status: 'draft' }] })
historyRequests.at(-1).resolve({ current_snapshot_id: 12, items: [{ snapshot_id: 12, approved_count: 0, candidate_count: 2 }, { snapshot_id: 11, approved_count: 1, candidate_count: 1 }] })
previewRequests.at(-1).resolve({ target_snapshot_id: 12, eligible_count: 0, source_page_count: 0 })
await copied
assert.equal(state().drafts[2].id, 8)
state().filter = 'whitespace'
assert.equal(state().items.length, 0)
const crossed = state().load()
requests.at(-1).resolve({ snapshot_id: 13, evidence: { items: [{ position: 2, alt_state: 'missing' }] } })
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [{ id: 99, position: 2, decision: 'informative' }] })
historyRequests.at(-1).resolve({ current_snapshot_id: 13, items: [{ snapshot_id: 13, approved_count: 0, candidate_count: 1 }] })
previewRequests.at(-1).resolve({ target_snapshot_id: 13, eligible_count: 0, source_page_count: 0 })
await crossed
assert.equal(state().drafts[2].id, null, 'reviews from an older snapshot cannot appear on newer evidence')
const reload = state().load()
assert.equal(state().data, null)
requests.at(-1).reject(new Error('offline'))
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [] })
historyRequests.at(-1).resolve({ current_snapshot_id: 12, items: [] })
previewRequests.at(-1).resolve({ target_snapshot_id: 12, eligible_count: 0, source_page_count: 0 })
await reload
assert.equal(state().error, 'offline')
const retry = state().load()
requests.at(-1).resolve({ snapshot_id: 12, evidence: null, legacy_candidate_count: 26 })
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [] })
historyRequests.at(-1).resolve({ current_snapshot_id: 12, items: [] })
previewRequests.at(-1).resolve({ target_snapshot_id: 12, eligible_count: 0, source_page_count: 0 })
await retry
assert.equal(state().evidence, null)
assert.equal(state().data.legacy_candidate_count, 26)
const pending = state().load()
props.visible = false
await flush()
requests.at(-1).resolve({ snapshot_id: 12, evidence: { items: [{ secret: 'closed dialog' }] } })
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [] })
historyRequests.at(-1).resolve({ current_snapshot_id: 12, items: [] })
previewRequests.at(-1).resolve({ target_snapshot_id: 12, eligible_count: 0, source_page_count: 0 })
await pending
assert.equal(state().data, null)
props.visible = true
await flush()
app.unmount()
requests.at(-1).resolve({ snapshot_id: 12, evidence: { items: [] } })
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [] })
historyRequests.at(-1).resolve({ current_snapshot_id: 12, items: [] })
previewRequests.at(-1).resolve({ target_snapshot_id: 12, eligible_count: 0, source_page_count: 0 })
await flush()
assert(!source.includes('v-html'))
assert(!/<img\b|:src=|:href=/.test(source), 'no untrusted resource loading or navigation')
for (const marker of ['旧存档未记录逐图明细', '尚无抓取存档', '最近抓取失败', '不代表图片描述质量已通过', 'evidence.truncated']) assert(source.includes(marker))
for (const marker of ['历史快照', '复制上一快照审核结论', '复制后统一为草稿', 'isHistorical']) assert(source.includes(marker))
for (const marker of ['复用同站图片结论', '地址和使用上下文完全一致', '必须逐项人工复核']) assert(source.includes(marker))
for (const marker of ['导出图片整改清单', '导出全部审核记录', '已审核且需要 Alt 的内容图']) assert(source.includes(marker))
console.log('SEO image evidence checks passed: filtering, legacy/error states, stale scope/close/unmount, no external loads')

const apiSource = await readFile(new URL('../src/api/seo.js', import.meta.url), 'utf8')
const auditCode = apiSource.match(/export function auditSeoSitePage[\s\S]*?\n}/)[0].replace('export ', '')
const sent = []
const audit = new Function('client', `${auditCode}; return auditSeoSitePage`)({ post: (...args) => sent.push(args) })
audit({ pageId: 234, tenantId: 1, siteId: 1 })
assert.deepEqual(sent[0], ['/api/v1/seo/site-pages/234/audit', null, { params: { tenant_id: 1, site_id: 1 }, timeout: 60000 }])
assert(source.includes('无需全站扫描'))
console.log('SEO single-page audit request preserves page, tenant and site scope')

const siteView = await readFile(new URL('../src/views/seo/SeoSiteOptimizationView.vue', import.meta.url), 'utf8')
const auditCalls = [...siteView.matchAll(/auditSeoSitePage\(\{([^}]+)\}\)/g)]
assert.equal(auditCalls.length, 2, 'single and batch audit calls remain covered')
for (const call of auditCalls) assert(call[1].includes('siteId: row.site_id'))
assert(siteView.includes('同一页面至少两次有效检测'))
assert(!siteView.includes('至少完成两次全站扫描后才能生成修复前后对比'))
