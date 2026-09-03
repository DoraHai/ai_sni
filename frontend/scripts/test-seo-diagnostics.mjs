// Real Vue reactive setup with an in-memory renderer and stubbed APIs. No network.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'

const source = await readFile(new URL('../src/views/seo/SeoSiteDiagnosticsPanel.vue', import.meta.url), 'utf8')
const code = compileScript(parse(source).descriptor, { id: 'test', genDefaultAs: 'component' }).content.replace(/^import .* from .*$/gm, '')
const requests = [], writes = [], messages = []
const deferred = args => { let resolve; const promise = new Promise(r => { resolve = r }); return { args, resolve, promise } }
const bindings = { computed: Vue.computed, onBeforeUnmount: Vue.onBeforeUnmount, ref: Vue.ref, watch: Vue.watch,
  SeoRemediationDialog: { render: () => null }, SeoImageEvidenceDialog: { render: () => null }, session: { canEdit: () => true },
  ElMessage: Object.fromEntries(['success', 'warning', 'error'].map(k => [k, text => messages.push([k, text])])),
  fetchSeoSiteDiagnostics: args => { const d = deferred(args); requests.push(d); return d.promise },
  saveSeoIndexReview: args => { const d = deferred(args); writes.push(d); return d.promise },
  fetchSeoIndexReviews: async () => ({ items: [], next_before_id: null }),
}
const Component = new Function('b', `const {${Object.keys(bindings).join(',')}} = b; ${code}; return component`)(bindings)
Component.render = () => null
const renderer = Vue.createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  setText() {}, setElementText() {}, patchProp() {}, insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
const site = Vue.ref(1), tenant = Vue.ref(1), child = Vue.ref()
const app = renderer.createApp({ render: () => Vue.h(Component, { ref: child, tenantId: tenant.value, siteId: site.value, canEdit: true }) })
app.mount({})
const state = () => child.value.$.setupState
const flush = async () => { await Promise.resolve(); await Vue.nextTick(); await Promise.resolve() }
const payload = (items = []) => ({ items, total: items.length, coverage: { inventory: items.length } })
assert.equal(requests.length, 1)
site.value = 2
await flush()
assert.equal(requests.length, 2)
requests[1].resolve(payload())
await flush()
requests[0].resolve(payload([{ id: 231, title: 'OLD SITE' }]))
await flush()
assert.deepEqual(state().result.items, [], 'ignore stale site response')
state().open({ id: 231, url: 'https://example.com/', review: { id: 8, intent: 'index' } })
await flush()
await state().save()
assert.equal(writes.length, 0, 'blank note rejected')
state().reason = '确认用途，快速中文输入正常。'
const firstSave = state().save()
await state().save()
assert.equal(writes.length, 1, 'duplicate click suppressed')
assert.equal(writes[0].args.expected_review_id, 8)
assert.equal(writes[0].args.reason, '确认用途，快速中文输入正常。')
assert.equal(writes[0].args.site_id, 2)
tenant.value = 3; site.value = 4
await flush()
assert.equal(state().dialog, false)
assert.equal(state().selected, null)
writes[0].resolve({ review: { id: 9 } })
await firstSave
await flush()
assert.equal(messages.filter(([type]) => type === 'success').length, 0, 'no stale tenant success')
assert.deepEqual(state().result.items, [])
assert.equal(state().saving, false)
app.unmount()
console.log('SEO diagnostics Vue checks passed: stale response, blank note, duplicate save, Chinese payload, tenant switch')
await import('./test-seo-image-evidence.mjs')
