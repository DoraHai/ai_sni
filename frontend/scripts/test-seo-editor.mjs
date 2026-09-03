import assert from 'node:assert/strict'
import { test, after } from 'node:test'
import { readFile } from 'node:fs/promises'
import { JSDOM } from 'jsdom'
import { parse, compileScript, compileTemplate, compileStyle } from '@vue/compiler-sfc'
import { sanitizeSeoEditorHtml, seoPlainTextHtml, seoContentWordCount } from '../src/views/seo/seoEditorHtml.js'
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

async function mountEditor(draft, status = 'drafting', saveDraft = value => value, options = {}) {
  let row = { id: 10, title: '验收勿发布', content_type: 'guide', keyword_ids: [5], draft, status, version_count: 1, source_page_id: 234, ...options.item }
  const writes = [], errors = []
  const bindings = {
    computed: Vue.computed, nextTick: Vue.nextTick, onMounted: Vue.onMounted, reactive: Vue.reactive, ref: Vue.ref, sanitizeSeoEditorHtml, seoContentWordCount,
    useRoute: () => ({ query: { id: '10', site_id: '1', ...options.query } }), useRouter: () => ({ push() {}, replace() {} }),
    currentTenantId: Vue.ref(1), siteId: Vue.ref(1), session: { user: { name: '测试管理员' } },
    ElMessage: { warning: x => errors.push(x), error: x => errors.push(x), success() {} },
    fetchSeoSites: async () => ({ sites: [{ id: 1, status: 'active', name: '测试站' }] }),
    fetchSeoKeywords: async () => ({ items: [{ id: 5, keyword: '诺德传动' }] }),
    fetchSeoContentAssets: async () => ({ items: options.missing ? [] : [{ ...row }] }),
    fetchSeoSitePages: async () => ({ items: [{ id: 234, title: '来源', url: 'https://example.com/page' }] }),
    updateSeoContentAsset: async args => { writes.push(args); row = { ...row, ...args.payload, ...('draft' in args.payload ? { draft: saveDraft(args.payload.draft) } : {}), version_count: row.version_count + 1 }; return row },
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

// Exercise the actual list component and its Continue editing button, not a
// separately reimplemented routing function.
async function mountContentList(rows, canEdit = true) {
  const source = await readFile(new URL('../src/views/seo/SeoContentView.vue', import.meta.url), 'utf8')
  const descriptor = parse(source).descriptor
  const script = compileScript(descriptor, { id: 'seo-content-list-test', genDefaultAs: 'component' })
  const code = script.content.replace(/^import .*$/gm, '')
  let template = compileTemplate({ source: descriptor.template.content, id: 'seo-content-list-test', compilerOptions: { bindingMetadata: script.bindings } }).code
  template = template.replace(/import \{([\s\S]*?)\} from "vue"/g, (_, names) => `const {${names.replace(/ as /g, ':')}} = Vue`).replace('export function render', 'function render')
  const pushes = []
  const bindings = {
    computed: Vue.computed, onMounted: Vue.onMounted, reactive: Vue.reactive, ref: Vue.ref, watch: Vue.watch, seoContentWordCount,
    useRoute: () => ({ meta: { contentMode: 'article' }, query: {} }),
    useRouter: () => ({ push: value => pushes.push(value) }),
    currentTenantId: Vue.ref(1), siteId: Vue.ref(1),
    session: { isLoggedIn: true, canEdit: () => canEdit, user: { name: '测试管理员' } },
    ElMessage: { error: message => { throw Error(message) } }, ElMessageBox: {},
    fetchSeoSites: async () => ({ sites: [{ id: 1, status: 'active' }] }),
    fetchSeoContentAssets: async () => ({ items: rows, total: rows.length, status_counts: { drafting: rows.length } }),
    fetchSeoKeywords: async () => ({ items: [{ id: 5, keyword: '操作手册' }] }),
  }
  const Component = new Function('b', `const {${Object.keys(bindings).join(',')}}=b;${code};return component`)(bindings)
  Component.render = new Function('Vue', `${template};return render`)(Vue)
  const host = document.createElement('div'); document.body.append(host)
  const app = Vue.createApp(Component)
  app.directive('loading', {})
  for (const name of ['el-select','el-option','el-dialog','el-form','el-alert','el-form-item','el-input','el-button','el-pagination']) {
    app.component(name, { render() { return Vue.h('div', this.$slots.default?.()) } })
  }
  const instance = app.mount(host); await flush()
  return { host, pushes, state: instance.$.setupState, close() { app.unmount(); host.remove() } }
}

const acceptanceText = '【验收勿发布】仅验证编辑器保存，不调用 AI、不审核、不发布。\n第一段：NORD 操作手册测试。\n第二段：保留换行与中文尾字，正常。\n字面标签：<h1>R&D</h1>\n字面实体：&amp; 与 &lt; 保持原样。\n测试链接：https://example.com/?a=1&b=2'

test('list and editor count the same visible text, decoding HTML entities only once', async () => {
  const html = seoPlainTextHtml(acceptanceText)
  const expected = Array.from(acceptanceText.replace(/\s+/g, '')).length
  const row = { id: 11, site_id: 1, title: '验收勿发布', status: 'drafting', content_type: 'guide', draft: '旧稿', humanized_content: html }
  const list = await mountContentList([row])
  const editor = await mountEditor(html)
  try {
    assert.equal(list.state.wordCount(row), expected)
    assert.equal(editor.state.wordCount, expected)
    assert.ok(list.host.textContent.includes(`${expected} 字`))
    assert.ok(editor.host.querySelector('.document-status').textContent.includes(`${expected} 字`))
    assert.equal(editor.editor.querySelector('h1'), null)
    await editor.state.save(); await editor.state.load(); await flush()
    assert.equal(editor.state.wordCount, expected)
  } finally { list.close(); editor.close() }
})

test('word count excludes tags, attributes, comments and active content; preserves literal entities and Unicode', () => {
  for (const [html, text] of [
    ['<p>中文 &amp; 😀</p><div>尾字</div>', '中文&😀尾字'],
    ['<p>&lt;h1&gt; &amp;amp; &#x4E2D;</p>', '<h1>&amp;中'],
    ['字面 &amp;\n正常', '字面&amp;正常'],
    ['<p>正文<img src="https://example.com/x" alt="不计属性"></p><!--不计注释--><script>不计脚本</script><style>不计样式</style>', '正文'],
    ['<p><br>&nbsp; \n</p>', ''],
    [null, ''],
  ]) assert.equal(seoContentWordCount(html), Array.from(text).length, String(html))
})

test('Continue editing opens the existing site-scoped full editor, never the old dialog or a new draft', async () => {
  const row = { id: 11, site_id: 1, title: '验收勿发布', status: 'drafting', content_type: 'guide' }
  const view = await mountContentList([row])
  try {
    const button = [...view.host.querySelectorAll('button')].find(node => node.textContent === '继续编辑')
    assert.ok(button)
    button.click(); await flush()
    assert.deepEqual(view.pushes, [{ path: '/seo/content/editor', query: { id: 11, site_id: 1, type: 'original' } }])
    assert.equal(view.state.dialog, false)
    for (const [content_type, type] of [['rewrite', 'rewrite'], ['faq', 'qa'], ['qa', 'qa'], ['landing', 'original'], ['comparison', 'original']]) {
      view.state.continueEditing({ ...row, content_type })
      assert.deepEqual(view.pushes.at(-1).query, { id: 11, site_id: 1, type })
    }
    const count = view.pushes.length
    for (const status of ['review', 'ready', 'published', 'archived']) view.state.continueEditing({ ...row, status })
    view.state.continueEditing({ ...row, site_id: 2 })
    assert.equal(view.pushes.length, count)
  } finally { view.close() }
})

test('read-only content permission cannot enter editing through list action', async () => {
  const row = { id: 11, site_id: 1, status: 'drafting', content_type: 'guide' }
  const view = await mountContentList([row], false)
  try {
    assert.equal([...view.host.querySelectorAll('button')].some(node => node.textContent === '继续编辑'), false)
    view.state.continueEditing(row)
    assert.equal(view.pushes.length, 0)
  } finally { view.close() }
})

test('an unavailable existing task must not save a default template over its record', async () => {
  const view = await mountEditor('', 'drafting', value => value, { missing: true })
  try {
    view.state.form.title = '不能保存'
    view.state.form.keyword_ids = [5]
    await view.state.save()
    assert.equal(view.writes.length, 0)
    assert.ok(view.errors.includes('任务尚未成功载入，请刷新后重试'))
  } finally { view.close() }
})

for (const content_type of ['article', 'guide', 'landing', 'comparison', 'faq', 'qa', 'rewrite']) {
  test(`existing ${content_type} retains type, source, version and reviewed field when reopened without a template`, async () => {
    const view = await mountEditor('<p>原始草稿</p>', 'drafting', value => value, {
      item: { content_type, humanized_content: '<p>审核定稿</p>', outline: '', source_text: '原文事实', originality_score: 81 },
      query: { type: content_type === 'rewrite' ? 'rewrite' : ['qa','faq'].includes(content_type) ? 'qa' : 'original' },
    })
    try {
      view.editor.innerHTML = '<p>修改审核定稿，正常。</p>'
      view.editor.dispatchEvent(new Event('input', { bubbles: true })); await flush()
      await view.state.save()
      assert.equal(view.writes.length, 1)
      const payload = view.writes[0].payload
      assert.equal(payload.content_type, content_type)
      assert.equal(payload.humanized_content, '<p>修改审核定稿，正常。</p>')
      for (const key of ['draft','source_text','originality_score','rewrite_progress']) assert.equal(key in payload, false, key)
      assert.equal(payload.outline, null, 'do not insert the default guide outline into an existing record')
      assert.equal(payload.source_page_id, 234)
      assert.equal(payload.version_count, 1)
      await view.state.load(); await flush()
      assert.equal(view.editor.textContent, '修改审核定稿，正常。')
      assert.ok(view.host.textContent.includes('任务 #10'))
      assert.equal(view.host.querySelector('input[readonly]').value, view.state.contentTypeLabel)
    } finally { view.close() }
  })
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
