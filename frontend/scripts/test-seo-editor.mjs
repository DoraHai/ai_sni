import assert from 'node:assert/strict'
import { test, after } from 'node:test'
import { readFile } from 'node:fs/promises'
import { JSDOM } from 'jsdom'
import { parse, compileScript, compileTemplate, compileStyle } from '@vue/compiler-sfc'
import { sanitizeSeoEditorHtml, seoPlainTextHtml } from '../src/views/seo/seoEditorHtml.js'
import { remediationHandoff, remediationDraftPatch } from '../src/views/seo/seoRemediationDraft.js'

const dom = new JSDOM('<!doctype html><html><head></head><body></body></html>')
for (const key of ['window', 'document', 'Document', 'ShadowRoot', 'Element', 'HTMLElement', 'SVGElement', 'Node', 'Event']) globalThis[key] = dom.window[key]
const Vue = await import('vue')
after(() => dom.window.close())
const source = await readFile(new URL('../src/views/seo/SeoContentEditorView.vue', import.meta.url), 'utf8')
const descriptor = parse(source).descriptor
const compiled = compileScript(descriptor, { id: 'seo-editor-test', genDefaultAs: 'component' })
const code = compiled.content.replace(/^import .* from .*$/gm, '')
let templateCode = compileTemplate({ source: descriptor.template.content, id: 'seo-editor-test', compilerOptions: { bindingMetadata: compiled.bindings } }).code
templateCode = templateCode.replace(/import \{([\s\S]*?)\} from "vue"/g, (_, names) => `const {${names.replace(/ as /g, ':')}} = Vue`)
templateCode = templateCode.replace('export function render', 'function render')
const render = new Function('Vue', `${templateCode}; return render`)(Vue)
const style = document.createElement('style')
style.textContent = descriptor.styles.map(s => compileStyle({ source: s.content, id: 'seo-editor-test', scoped: false }).code).join('\n')
document.head.append(style)
const flush = async () => { for (let i = 0; i < 8; i++) { await Promise.resolve(); await Vue.nextTick() } }
const heading = '页面整改交接单（AI 辅助，人工编辑，勿直接发布）'
const handoff = `${heading}\n来源页面：#234\n\nTitle 建议：NORDBLOC.1\n理由：人工核实正常。`

async function mountEditor(draft, status = 'drafting', saveDraft = value => value) {
  let row = { id: 10, title: '验收勿发布', keyword_ids: [5], draft, status, version_count: 1, source_page_id: 234 }
  const writes = [], errors = []
  const bindings = {
    computed: Vue.computed, nextTick: Vue.nextTick, onMounted: Vue.onMounted, reactive: Vue.reactive, ref: Vue.ref, sanitizeSeoEditorHtml,
    useRoute: () => ({ query: { id: '10', site_id: '1' } }), useRouter: () => ({ push() {}, replace() {} }),
    currentTenantId: Vue.ref(1), siteId: Vue.ref(1), session: { user: { name: '测试管理员' } },
    ElMessage: Object.assign(options => {
      if (options.type === 'warning' || options.type === 'error') errors.push(options.message)
    }, { warning: x => errors.push(x), error: x => errors.push(x), success() {} }),
    fetchSeoSites: async () => ({ sites: [{ id: 1, status: 'active', name: '测试站' }] }),
    fetchSeoKeywords: async () => ({ items: [{ id: 5, keyword: '诺德传动' }] }),
    fetchSeoContentAssets: async () => ({ items: [{ ...row }] }),
    fetchSeoSitePages: async () => ({ items: [{ id: 234, title: '来源', url: 'https://example.com/page' }] }),
    updateSeoContentAsset: async args => { writes.push(args); row = { ...row, ...args.payload, draft: saveDraft(args.payload.draft), version_count: row.version_count + 1 }; return row },
    createSeoContentAsset: () => { throw Error('Must not create another task') },
    assistSeoContent: () => { throw Error('Must not call AI') },
    submitSeoContentReview: () => { throw Error('Must not submit a review') },
  }
  const Component = new Function('b', `const {${Object.keys(bindings).join(',')}}=b;${code};return component`)(bindings)
  Component.render = render
  const host = document.createElement('div'); document.body.append(host)
  const app = Vue.createApp(Component)
  for (const name of ['el-select','el-option','el-dialog','el-form','el-alert','el-form-item','el-input','el-checkbox-group','el-checkbox','el-button']) {
    app.component(name, { render() { return Vue.h('div', this.$slots.default?.()) } })
  }
  const instance = app.mount(host); await flush()
  const state = instance.$.setupState, editor = host.querySelector('.article-editor')
  return { host, editor, state, writes, errors, close() { app.unmount(); host.remove() } }
}

test('plain text and blank lines become explicit breaks; load/save/reopen is stable', async () => {
  const view = await mountEditor('第一行\r\n第二行\r\n\r\n中文尾字正常。')
  try {
    assert.equal(view.editor.innerHTML, '第一行<br>第二行<br><br>中文尾字正常。')
    assert.equal(view.writes.length, 0, 'opening never saves')
    await view.state.save(); await view.state.load(); await flush()
    assert.equal(view.writes.length, 1)
    assert.equal(view.editor.innerHTML, '第一行<br>第二行<br><br>中文尾字正常。')
    assert.equal(view.writes[0].payload.source_page_id, 234)
    assert.deepEqual(view.errors, [])
  } finally { view.close() }
})

test('existing HTML whitespace, lists and code remain HTML rather than pre-wrapped text', async () => {
  const html = '<p>原有\n  段落</p>\n<ul>\n  <li>条目</li>\n</ul>\n<pre><code>代码\n  缩进</code></pre>'
  const view = await mountEditor(html)
  try {
    assert.equal(view.editor.innerHTML, html)
    assert.equal(view.editor.querySelectorAll('br').length, 0)
    assert.ok(['', 'normal'].includes(window.getComputedStyle(view.editor).whiteSpace))
    assert.equal(view.editor.querySelector('pre').textContent, '代码\n  缩进')
    await view.state.save(); await view.state.load(); await flush()
    assert.equal(view.editor.innerHTML, html)
    const regression = document.createElement('style'); regression.textContent = '.article-editor { white-space: pre-wrap; }'
    document.head.append(regression)
    assert.equal(window.getComputedStyle(view.editor).whiteSpace, 'pre-wrap', 'CSS assertion observes the effective rule')
    regression.remove()
  } finally { view.close() }
})

test('legacy mixed handoff keeps original rich text and converts only the appended text', async () => {
  const prefix = '<p>原有\n  正文</p>'
  const view = await mountEditor(`${prefix}\n\n---\n\n${handoff}`)
  try {
    assert.equal(view.editor.querySelector('p').outerHTML, prefix)
    assert.equal(view.editor.querySelector('p br'), null)
    assert.equal(view.editor.querySelectorAll('br').length, 8)
    const loaded = view.editor.innerHTML
    await view.state.save(); await view.state.load(); await flush()
    assert.equal(view.editor.innerHTML, loaded, 'reopening does not double escape or add breaks')
  } finally { view.close() }
})

test('Enter blocks and Chinese input survive actual input/save/load; input does not rewrite DOM', async () => {
  const view = await mountEditor('原稿')
  try {
    view.editor.innerHTML = '第一行<div>快速中文输入正常。</div><div><br></div><div>末段</div>'
    const paragraph = view.editor.querySelector('div')
    view.editor.dispatchEvent(new Event('input', { bubbles: true })); await flush()
    assert.equal(view.editor.querySelector('div'), paragraph)
    await view.state.save(); await view.state.load(); await flush()
    assert.equal(view.editor.innerHTML, '第一行<div>快速中文输入正常。</div><div><br></div><div>末段</div>')
  } finally { view.close() }
})

test('ready handoff can be displayed but cannot be saved', async () => {
  const view = await mountEditor(handoff, 'ready')
  try {
    assert.equal(view.editor.getAttribute('contenteditable'), 'false')
    assert.equal(view.editor.querySelectorAll('br').length, 4)
    await view.state.save()
    assert.equal(view.writes.length, 0)
  } finally { view.close() }
})

test('production IME protection blocks premature saving and preserves the completed Chinese tail', async () => {
  const view = await mountEditor('原稿')
  try {
    view.editor.dispatchEvent(new Event('compositionstart', { bubbles: true }))
    view.editor.innerHTML = '中文尚未确认'
    view.editor.dispatchEvent(new Event('input', { bubbles: true }))
    await view.state.save()
    assert.equal(view.writes.length, 0)
    assert.ok(view.errors.some(message => message.includes('中文输入尚未完成')))
    view.errors.length = 0
    view.editor.innerHTML = '快速中文输入正常。'
    view.editor.dispatchEvent(new Event('compositionend', { bubbles: true }))
    await flush(); await view.state.save(); await view.state.load(); await flush()
    assert.equal(view.writes.length, 1)
    assert.equal(view.editor.textContent, '快速中文输入正常。')
    assert.deepEqual(view.errors, [])
  } finally { view.close() }
})

test('sanitization still strips active content and attributes on retained DIV blocks', () => {
  const html = sanitizeSeoEditorHtml('<div onclick="bad()" style="white-space:pre-wrap">正文<script>bad()</script><a href="javascript:bad()">链接</a></div>')
  assert.equal(html, '<div>正文<a>链接</a></div>')
  assert.equal(sanitizeSeoEditorHtml(html), html)
})

test('a handoff heading quoted inside existing rich blocks does not change their structure', () => {
  for (const tag of ['pre', 'p', 'blockquote']) {
    const html = `<${tag}>\n${handoff}\n</${tag}>`
    const expected = document.createElement('template'); expected.innerHTML = html
    assert.equal(sanitizeSeoEditorHtml(html), expected.innerHTML)
  }
})

test('handoff tag examples remain literal text, including after appending to rich content', () => {
  const change = { text: '<h1>产品 & 说明</h1>', reason: '需核实', evidence_ids: ['title'] }
  const generated = remediationHandoff({ page_id: 234, evidence: { url: 'https://example.com', current: {}, evidence: [] } }, { title: change, description: change, h1: change, outline: [change] })
  const patched = remediationDraftPatch({ draft: '<p>原稿</p>', version_count: 1 }, generated)
  const html = sanitizeSeoEditorHtml(patched.draft)
  const node = document.createElement('div'); node.innerHTML = html
  assert.equal(node.querySelector('h1'), null)
  assert.ok(node.textContent.includes('<h1>产品 & 说明</h1>'))
  assert.equal(sanitizeSeoEditorHtml(html), html)
})

test('a second handoff appended after an already normalized handoff preserves both', () => {
  const first = seoPlainTextHtml(handoff)
  const second = handoff.replace('NORDBLOC.1', 'NORDAC')
  const normalized = sanitizeSeoEditorHtml(remediationDraftPatch({ draft: first, version_count: 1 }, second).draft)
  const node = document.createElement('div'); node.innerHTML = normalized
  assert.equal(node.firstElementChild.outerHTML, first)
  assert.equal(node.querySelectorAll('div br').length, 8)
  assert.ok(node.lastElementChild.textContent.includes('NORDAC'))
  assert.equal(sanitizeSeoEditorHtml(normalized), normalized)
})

// The Python distribution tests validate both API fields in this same fixture
// against the real _sanitize_content_html function (not a JS approximation).
const roundtrips = JSON.parse(await readFile(new URL('../../tests/fixtures/seo_editor_html_roundtrip.json', import.meta.url), 'utf8'))
for (const fixture of roundtrips) {
  test(`backend sanitizer contract: ${fixture.name}`, async () => {
    const view = await mountEditor(fixture.api_value, 'drafting', value => {
      assert.equal(value, fixture.editor_html)
      return fixture.api_saved_again
    })
    try {
      assert.equal(view.editor.innerHTML, fixture.editor_html)
      for (const literal of fixture.text_includes) assert.ok(view.editor.textContent.includes(literal), literal)
      for (let i = 0; i < 3; i++) {
        await view.state.save(); await view.state.load(); await flush()
        assert.equal(view.editor.innerHTML, fixture.editor_html)
      }
      assert.deepEqual(view.errors, [])
    } finally { view.close() }
  })
}

test('HTML following a legacy handoff keeps its markup and rich whitespace', () => {
  const tail = '<p>人工\n  后续补充 &amp; 核实</p><ul>\n<li>保留列表</li>\n</ul>'
  const html = sanitizeSeoEditorHtml(`${handoff}\n${tail}`)
  const node = document.createElement('div'); node.innerHTML = html
  assert.equal(node.querySelector('p').outerHTML, '<p>人工\n  后续补充 &amp; 核实</p>')
  assert.equal(node.querySelector('ul').outerHTML, '<ul>\n<li>保留列表</li>\n</ul>')
  assert.equal(sanitizeSeoEditorHtml(html), html)
})

test('new handoffs escape tag examples and entities before either create or append', () => {
  const text = `${handoff}\n<h1>R&D</h1> &amp; &#65; <script>not executable</script>`
  for (const html of [seoPlainTextHtml(text), remediationDraftPatch({ draft: '原稿\nR&D &amp;', humanized_content: '润色\n原稿', version_count: 1 }, text).draft]) {
    const node = document.createElement('div'); node.innerHTML = sanitizeSeoEditorHtml(html)
    assert.ok(node.textContent.includes('<h1>R&D</h1> &amp; &#65; <script>not executable</script>'))
    assert.equal(node.querySelector('h1,script'), null)
    assert.equal(sanitizeSeoEditorHtml(node.innerHTML), node.innerHTML)
  }
})

test('converting editor HTML for AI keeps line and paragraph boundaries without calling AI', async () => {
  const view = await mountEditor('第一行\n第二行\n\n末行')
  try {
    assert.equal(view.state.draftForAi(), '第一行\n第二行\n\n末行')
    view.state.form.draft = '开头<div>段落一</div><p>段落二<br>下一行</p><img src="https://example.com/image" alt="型号图">'
    assert.equal(view.state.draftForAi(), '开头\n段落一\n段落二\n下一行\n[图片：型号图]')
    assert.equal(view.writes.length, 0)
  } finally { view.close() }
})
