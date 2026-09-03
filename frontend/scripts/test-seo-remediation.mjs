import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import { remediationHandoff, validRemediationEdits, remediationDraftPatch } from '../src/views/seo/seoRemediationDraft.js'
import { seoPlainTextHtml } from '../src/views/seo/seoEditorHtml.js'

const change = () => ({ text: 'NORDAC NORDCON BU0000 操作手册正常。', reason: '保留型号，需人工核实', evidence_ids: ['title'] })
const response = () => ({ page_id: 231, tenant_id: 1, site_id: 1, proposal: { title: change(), description: change(), h1: change(), outline: [change()] },
  evidence: { current: { title: '原题' }, url: 'https://example.com/manual', fetched_at: '2026-09-03T06:00:00Z', body_sha256: 'hash', evidence: [{ id: 'title', text: 'NORDAC' }] } })
const handoff = remediationHandoff(response(), response().proposal)
assert.match(handoff, /正常。/)
assert.match(handoff, /来源页面：#231/)
assert.match(handoff, /原文：原题/)
assert.match(handoff, /未修改当前 TDK/)
assert.equal(validRemediationEdits(response().proposal), true)
const blank = response().proposal; blank.title.text = ' '
assert.equal(validRemediationEdits(blank), false)
assert.throws(() => remediationDraftPatch({ draft: '原文' }, handoff), /版本/)
const patch = remediationDraftPatch({ draft: '原文', humanized_content: '人工润色原文', version_count: 3 }, handoff)
assert.equal(patch.version_count, 3)
assert.ok(patch.draft.startsWith('<div>原文</div>') && patch.humanized_content.startsWith('<div>人工润色原文</div>'))
assert.throws(() => remediationDraftPatch({ draft: '原文', version_count: 1 }, '&'.repeat(17000)), /80000/)

const source = await readFile(new URL('../src/views/seo/SeoRemediationDialog.vue', import.meta.url), 'utf8')
const code = compileScript(parse(source).descriptor, { id: 'test', genDefaultAs: 'component' }).content.replace(/^import .* from .*$/gm, '')
const deferred = args => { let resolve, reject; const promise = new Promise((r, j) => { resolve = r; reject = j }); return { args, resolve, reject, promise } }
const reads = [], previews = [], creates = [], updates = [], messages = []
const bindings = { computed: Vue.computed, onBeforeUnmount: Vue.onBeforeUnmount, ref: Vue.ref, watch: Vue.watch,
  useRouter: () => ({ push() {} }), remediationHandoff, validRemediationEdits, remediationDraftPatch, seoPlainTextHtml,
  ElMessage: Object.fromEntries(['success','warning','error'].map(k => [k, text => messages.push([k,text])])),
  previewSeoRemediation: args => { const d = deferred(args); previews.push(d); return d.promise },
  fetchSeoContentAssets: args => { const d = deferred(args); reads.push(d); return d.promise },
  createSeoContentAsset: args => { const d = deferred(args); creates.push(d); return d.promise },
  updateSeoContentAsset: args => { const d = deferred(args); updates.push(d); return d.promise },
}
const Component = new Function('b', `const {${Object.keys(bindings).join(',')}}=b; ${code}; return component`)(bindings)
Component.render = () => null
const renderer = Vue.createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  setText() {}, setElementText() {}, patchProp() {}, insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
const tenant = Vue.ref(1), site = Vue.ref(1), visible = Vue.ref(true), child = Vue.ref(), rerender = Vue.ref(0)
const app = renderer.createApp({ render: () => { rerender.value; return Vue.h(Component, { ref: child, tenantId: tenant.value, siteId: site.value, visible: visible.value, page: { id: 231, url:'https://example.com/manual' } }) } })
app.mount({})
const state = () => child.value.$.setupState
const flush = async () => { await Promise.resolve(); await Vue.nextTick(); await Promise.resolve() }
reads.at(-1).resolve({ items: [] }); await flush()
assert.equal(previews.length, 0, 'opening never calls AI')
const generation = state().generate(); await state().generate()
assert.equal(previews.length, 1, 'double click calls provider once')
previews[0].resolve(response()); await generation
assert.equal(creates.length, 0, 'AI generation does not save')
rerender.value++; await flush()
assert.notEqual(state().proposal, null, 'same-page parent render must preserve the AI draft')
assert.equal(reads.length, 1, 'same-page parent render must not refetch repeatedly')
state().proposal.description.text = '真人中文尾字正常。'
const saving = state().save(); await state().save()
assert.equal(creates.length, 1)
assert.equal(creates[0].args.source_page_id, 231)
assert.equal(creates[0].args.status, 'drafting')
assert.match(creates[0].args.draft, /真人中文尾字正常。/)
assert.ok(creates[0].args.draft.startsWith('<div>') && creates[0].args.draft.includes('<br>'))
creates[0].resolve({ id: 77 }); await saving
await state().save(); assert.equal(creates.length, 1, 'saved draft cannot be created twice')

visible.value = false; await flush(); visible.value = true; await flush()
reads.at(-1).resolve({ items: [{ id: 77, status: 'drafting', title:'已有稿', version_count: 9, draft:'原稿' }] }); await flush()
const again = state().generate(); previews.at(-1).resolve(response()); await again
const append = state().save(); assert.equal(updates.length, 1)
assert.equal(updates[0].args.payload.version_count, 9)
assert.ok(updates[0].args.payload.draft.startsWith('<div>原稿</div>'))
updates[0].reject(new Error('内容已被其他操作更新')); await append
assert.equal(state().savedId, null, 'version conflict keeps proposal and never reports saved')

visible.value = false; await flush(); visible.value = true; await flush()
reads.at(-1).resolve({ items: [{ id:77, status:'ready' }] }); await flush()
const next = state().generate(); previews.at(-1).resolve(response()); await next
await state().save(); assert.equal(updates.length, 1, 'ready task is protected')

visible.value = false; await flush(); visible.value = true; await flush()
reads.at(-1).resolve({ items:[] }); await flush()
const stale = state().generate(); const old = previews.at(-1)
tenant.value = 2; site.value = 2; await flush()
old.resolve(response()); await stale
assert.equal(state().result, null, 'late response cannot cross customer/site')
assert.equal(state().loading, false)
app.unmount()

// Compile the real shell template, assert the actual router-view VNode key changes.
const shell = parse(await readFile(new URL('../src/views/seo/SeoWorkspaceShell.vue', import.meta.url), 'utf8')).descriptor
let rendered = compileTemplate({ source: shell.template.content, id:'shell-test' }).code
rendered = rendered.replace(/import \{([\s\S]*?)\} from "vue"/, (_, names) => `const {${names.replace(/ as /g, ':')}} = Vue`)
rendered = rendered.replace('export function render', 'function render')
const render = new Function('Vue', `${rendered}; return render`)(Vue)
const context = { session:{tenantId:1,tenants:[]}, route:{path:'/seo/site'}, currentSeoSiteId:1, visibleGroups:[],
  mobileOpen:false,immersive:false,tenantName:'test',workflow:'',title:'',navigate(){},onTenantChange(){} }
const find = node => {
  if (!node || typeof node !== 'object') return null
  if (node.type === 'router-view') return node
  if (Array.isArray(node.children)) for (const c of node.children) { const found = find(c); if (found) return found }
  return null
}
// resolveComponent outside setup returns its string name; suppress only this expected warning.
const warn = console.warn; console.warn = () => {}
try {
  assert.equal(find(render(context, [])).key, '1:1')
  context.currentSeoSiteId = 2; assert.equal(find(render(context, [])).key, '1:2')
  context.session.tenantId = 2; context.currentSeoSiteId = null
  assert.equal(find(render(context, [])).key, '2:none', 'no-site customer cannot retain previous onsite view')
} finally { console.warn = warn }
console.log('SEO remediation Vue tests passed: explicit AI, draft-only, Chinese text, append/version protection, stale scope, shell remount')

// A detached onsite view must not change the global site selector when its fetch finishes.
const onsiteSource = await readFile(new URL('../src/views/seo/SeoSiteOptimizationView.vue', import.meta.url), 'utf8')
const onsiteCode = compileScript(parse(onsiteSource).descriptor, { id:'onsite-test', genDefaultAs:'component' }).content.replace(/^import .* from .*$/gm, '')
const siteRequests = [], globalSite = Vue.ref(null), globalTenant = Vue.ref(1)
const onsiteBindings = { computed:Vue.computed, ref:Vue.ref, reactive:Vue.reactive, watch:Vue.watch, onMounted:Vue.onMounted, onBeforeUnmount:Vue.onBeforeUnmount,
  useRoute: () => Vue.reactive({ query:{} }), useRouter: () => ({ push(){} }),
  currentTenantId:globalTenant, siteId:globalSite, session:{ isLoggedIn:true, canEdit:()=>true },
  ElMessage:bindings.ElMessage, SeoSiteDiagnosticsPanel:{ render:()=>null }, formatSeoCsvTime:v=>v,
  fetchSeoSites: arg => { const d = deferred(arg); siteRequests.push(d); return d.promise } }
for (const match of onsiteSource.matchAll(/import \{ ([^}]+) \} from '\.\.\/\.\.\/api\/[^']+'/g)) {
  for (const name of match[1].split(',').map(v=>v.trim())) {
    if (!(name in onsiteBindings)) onsiteBindings[name] = async () => ({items:[],total:0,stats:{}})
  }
}
const Onsite = new Function('b', `const {${Object.keys(onsiteBindings).join(',')}}=b; ${onsiteCode}; return component`)(onsiteBindings)
Onsite.render = () => null
const detachedApp = renderer.createApp(Onsite)
detachedApp.mount({})
assert.equal(siteRequests.length, 1)
detachedApp.unmount()
siteRequests[0].resolve({sites:[{id:1,status:'active'}]}); await flush()
assert.equal(globalSite.value, null, 'unmounted page cannot resurrect a previous customer site')
const switchedApp = renderer.createApp(Onsite)
switchedApp.mount({})
globalTenant.value = 2; await flush()
assert.equal(siteRequests.length, 3)
siteRequests[1].resolve({sites:[{id:1,status:'active'}]}); await flush()
assert.equal(globalSite.value, null, 'old tenant site response ignored')
siteRequests[2].resolve({sites:[{id:2,status:'active'}]}); await flush()
assert.equal(globalSite.value, 2)
switchedApp.unmount()
console.log('SEO onsite global site selection race checks passed')
