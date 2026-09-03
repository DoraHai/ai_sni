import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'

const source = await readFile(new URL('../src/views/seo/SeoImageEvidenceDialog.vue', import.meta.url), 'utf8')
const code = compileScript(parse(source).descriptor, { id: 'images-test', genDefaultAs: 'component' }).content.replace(/^import .* from .*$/gm, '')
const requests = [], remediationRequests = []
const bindings = { computed: Vue.computed, ref: Vue.ref, watch: Vue.watch, onBeforeUnmount: Vue.onBeforeUnmount,
  fetchSeoImageEvidence: args => new Promise((resolve, reject) => requests.push({ args, resolve, reject })),
  fetchSeoImageRemediation: args => new Promise((resolve, reject) => remediationRequests.push({ args, resolve, reject })),
  saveSeoImageRemediation: async () => ({}),
  ElMessage: { success() {}, error() {} },
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
assert.deepEqual(requests[0].args, { tenantId: 1, siteId: 1, pageId: 234 })
assert.deepEqual(remediationRequests[0].args, { tenantId: 1, siteId: 1, pageId: 234 })
props.tenantId = 2; props.siteId = 2
await flush()
requests.at(-1).resolve({ snapshot_id: 12, evidence: { items: [{ position: 1, alt_state: 'empty' }, { position: 2, alt_state: 'missing' }] } })
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [{ id: 7, position: 2, decision: 'informative', alt_suggestion: '产品图', review_status: 'draft' }] })
await flush()
requests[0].resolve({ snapshot_id: 11, evidence: { items: [{ secret: 'previous tenant' }] } })
remediationRequests[0].resolve({ snapshot_id: 11, items: [] })
await flush()
assert.equal(state().items.length, 2)
state().filter = 'missing'
assert.deepEqual(state().items, [{ position: 2, alt_state: 'missing' }])
assert.equal(state().drafts[2].id, 7)
state().filter = 'whitespace'
assert.equal(state().items.length, 0)
const crossed = state().load()
requests.at(-1).resolve({ snapshot_id: 13, evidence: { items: [{ position: 2, alt_state: 'missing' }] } })
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [{ id: 99, position: 2, decision: 'informative' }] })
await crossed
assert.equal(state().drafts[2].id, null, 'reviews from an older snapshot cannot appear on newer evidence')
const reload = state().load()
assert.equal(state().data, null)
requests.at(-1).reject(new Error('offline'))
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [] })
await reload
assert.equal(state().error, 'offline')
const retry = state().load()
requests.at(-1).resolve({ snapshot_id: 12, evidence: null, legacy_candidate_count: 26 })
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [] })
await retry
assert.equal(state().evidence, null)
assert.equal(state().data.legacy_candidate_count, 26)
const pending = state().load()
props.visible = false
await flush()
requests.at(-1).resolve({ snapshot_id: 12, evidence: { items: [{ secret: 'closed dialog' }] } })
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [] })
await pending
assert.equal(state().data, null)
props.visible = true
await flush()
app.unmount()
requests.at(-1).resolve({ snapshot_id: 12, evidence: { items: [] } })
remediationRequests.at(-1).resolve({ snapshot_id: 12, items: [] })
await flush()
assert(!source.includes('v-html'))
assert(!/<img\b|:src=|:href=/.test(source), 'no untrusted resource loading or navigation')
for (const marker of ['旧存档未记录逐图明细', '尚无抓取存档', '最近抓取失败', '不代表图片描述质量已通过', 'evidence.truncated']) assert(source.includes(marker))
console.log('SEO image evidence checks passed: filtering, legacy/error states, stale scope/close/unmount, no external loads')

const apiSource = await readFile(new URL('../src/api/seo.js', import.meta.url), 'utf8')
const auditCode = apiSource.match(/export function auditSeoSitePage[\s\S]*?\n}/)[0].replace('export ', '')
const sent = []
const audit = new Function('client', `${auditCode}; return auditSeoSitePage`)({ post: (...args) => sent.push(args) })
audit({ pageId: 234, tenantId: 1, siteId: 1 })
assert.deepEqual(sent[0], ['/api/v1/seo/site-pages/234/audit', null, { params: { tenant_id: 1, site_id: 1 }, timeout: 60000 }])
assert(source.includes('无需全站扫描'))
console.log('SEO single-page audit request preserves page, tenant and site scope')
