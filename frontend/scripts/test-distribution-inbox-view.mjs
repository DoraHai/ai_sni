import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { JSDOM } from 'jsdom'
import { parse, compileScript } from '@vue/compiler-sfc'

const dom = new JSDOM('<!doctype html><body></body>', { url: 'https://synthetic.invalid/' })
for (const name of ['window', 'document', 'Node', 'Element', 'HTMLElement', 'SVGElement']) globalThis[name] = dom.window[name]
const { createApp, nextTick } = await import('vue')
const require = createRequire(import.meta.url)
const source = await readFile(new URL('../src/views/seo/DistributionInbox.vue', import.meta.url), 'utf8')
const parsed = parse(source)
assert.deepEqual(parsed.errors, [])
const compiled = compileScript(parsed.descriptor, { id: 'synthetic-inbox', inlineTemplate: true })
const code = compiled.content
  .replace(/from (['"])vue\1/g, 'from '+JSON.stringify(pathToFileURL(require.resolve('vue')).href))
  .replace("from './distributionInboxState.js'", 'from '+JSON.stringify(new URL('../src/views/seo/distributionInboxState.js', import.meta.url).href))
  .replace("from '../../utils/articlePublicationGroups.js'", 'from '+JSON.stringify(new URL('../src/utils/articlePublicationGroups.js', import.meta.url).href))
const Component = (await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))).default
const id = '11111111-1111-4111-8111-111111111111'
const flush = async () => { await new Promise(r => setTimeout(r, 0)); await nextTick() }

function mount(targets = [], assignment = null, empty = false) {
  const calls = []
  const api = {
    receipts: async () => ({ items: empty ? [] : [{ id, revision: 0, platform: '新平台', title: '<img src=x onerror=alert(1)>',
      reportedAccount: '<script>unsafe</script>', result: 'success', publicUrl: 'https://example.invalid/article',
      occurredAt: '2026-10-23T16:30:00Z', receivedAt: '2026-10-23T16:31:00Z', assignment }] }),
    devices: async () => ({ items: ['active','revoked','expired','future'].map(state => ({ id: state, revision: 0, label: '合成电脑', state })) }), count: async () => ({ count: empty ? 0 : 1 }),
    createPairing: async () => { calls.push('pair'); return { pairingCode: 'DHT2-'+'a'.repeat(32) } },
    revoke: async () => calls.push('revoke'), label: async (...args) => calls.push(['label',...args]),
    unlabel: async (...args) => calls.push(['unlabel',...args]),
  }
  const element = document.createElement('div'); document.body.append(element)
  const app = createApp(Component, { api, identity: 'synthetic-1', targets }); app.mount(element)
  return { element, calls, api, close: () => { app.unmount(); element.remove() } }
}
const click = async (element, label) => { [...element.querySelectorAll('button')].find(b => b.textContent === label).click(); await flush() }

for (const [status, code, message] of [
  [409, 'DUPLICATE_LINK', '已有相同链接，请核对'],
  [409, 'REVISION_CONFLICT', '记录已被改过，请重新读取后再试'],
  [409, 'CROSS_TARGET_REQUIRES_UNLABEL', '请先在原客户撤销标注，再选择新客户或模块'],
  [409, 'URL_HASH_COLLISION', '链接标识冲突，请联系超管核对'],
  [409, 'CONTENT_CONFIRMATION_REQUIRED', '当前稿件版本尚未获得客户确认或顾问代确认，请确认后再标注'],
  [403, 'INBOX_FORBIDDEN', '当前身份无权操作此记录'],
  [404, 'RECEIPT_NOT_FOUND', '记录不存在或无权查看'],
  [422, 'INVALID_SHAPE', '回传格式不正确，请核对后重试'],
]) {
  test(`label ${code} stays next to the clicked button and only revision asks for reread`, async () => {
    const view = mount([{ tenantId: 42, name: '示例客户甲', modules: ['seo'] }]); await flush()
    try {
      let writes = 0
      view.api.label = async () => { writes += 1; throw Object.assign(new Error(message), { status, code }) }
      const tenant = view.element.querySelector('article select')
      tenant.value = '42'; tenant.dispatchEvent(new dom.window.Event('change', { bubbles: true })); await flush()
      await click(view.element, '标注客户')
      const button = [...view.element.querySelectorAll('button')].find(b => b.textContent === '标注客户')
      assert.equal(button.nextElementSibling.getAttribute('role'), 'alert')
      assert.equal(button.nextElementSibling.textContent, message)
      assert.equal(view.element.querySelectorAll('article [role=alert]').length, 1)
      assert.equal(view.element.textContent.includes('重新读取候选和回执'), code === 'REVISION_CONFLICT')
      assert.equal(writes, 1)
    } finally { view.close() }
  })
}
const select = async (element, value) => {
  element.value = String(value)
  element.dispatchEvent(new dom.window.Event('change', { bubbles: true }))
  await flush()
}

test('receipt times cross midnight in Beijing and device states use Chinese labels', async () => {
  const view = mount(); await flush()
  try {
    assert(view.element.textContent.includes('操作人报告时间（北京时间）：2026-10-24 00:30'))
    assert(view.element.textContent.includes('收到时间（北京时间）：2026-10-24 00:31'))
    const devices = view.element.querySelector('section:last-child')
    for (const text of ['使用中','已停用','已过期','未知状态']) assert(devices.textContent.includes(text))
    assert.deepEqual([...devices.querySelectorAll('button')].map(b => b.disabled), [false,true,true,false])
  } finally { view.close() }
})

test('filter switches update the section title and empty message', async () => {
  const view = mount([], null, true); await flush()
  try {
    for (const [filter, label] of [['pending','待标客户'],['active','已标客户'],['archived','已归档']]) {
      await select(view.element.querySelector('section:nth-of-type(2) select'), filter)
      assert.equal(view.element.querySelector('#receipts-title').textContent, `${label}（0）`)
      assert(view.element.textContent.includes(`暂无${label}记录`))
    }
  } finally { view.close() }
})

test('rendered inbox has only three sections, zero-grant guidance and safe plain text links', async () => {
  const view = mount(); await flush()
  try {
    assert.equal(view.element.querySelectorAll('section').length, 3)
    assert(view.element.textContent.includes('暂无可标注的客户，请联系超管授权'))
    assert(view.element.textContent.includes('新平台'))
    assert(view.element.textContent.includes('<img src=x onerror=alert(1)>'))
    assert.equal(view.element.querySelectorAll('img,script').length, 0)
    const link = view.element.querySelector('a')
    assert.equal(link.rel, 'noopener noreferrer'); assert.equal(link.getAttribute('referrerpolicy'), 'no-referrer')
    assert(view.element.textContent.includes('页面尚未核验'))
    assert(view.element.querySelector('details').textContent.includes('不选网站的话，这条回传不会出现在网站的发布记录里。'))
    assert(view.element.querySelector('details') && !view.element.querySelector('details').open)
    await click(view.element, '生成配对码')
    assert.equal(view.calls[0], 'pair')
    assert.equal(view.element.querySelector('code').textContent, 'DHT2-'+'a'.repeat(32))
    await click(view.element, '停用')
    assert.equal(view.calls[1], 'revoke')
  } finally { view.close() }
})

test('dual module customers require an explicit module and label uses the chosen tenant', async () => {
  const view = mount([{ tenantId: 42, name: '合成客户', modules: ['seo','geo'] }]); await flush()
  try {
    const tenant = view.element.querySelector('article select')
    tenant.value = '42'; tenant.dispatchEvent(new dom.window.Event('change', { bubbles: true })); await flush()
    const button = [...view.element.querySelectorAll('button')].find(b => b.textContent === '标注客户')
    assert(button.disabled)
    const module = view.element.querySelectorAll('article select')[1]
    module.value = 'geo'; module.dispatchEvent(new dom.window.Event('change', { bubbles: true })); await flush()
    assert(view.element.querySelector('details').textContent.includes('不选项目的话，这条回传不会出现在项目的发布记录里。'))
    assert(!view.element.querySelector('details').textContent.includes('不选网站的话'))
    assert(!button.disabled)
    button.click(); await flush()
    assert.deepEqual(view.calls[0].slice(0,5), ['label','geo',42,id,{ expectedRevision: 0, targetTenant: 42, scopeId: null }])
  } finally { view.close() }
})

const targets = [{ tenantId: 42, name: '合成客户', modules: ['seo', 'geo'], scopes: [
  { id: 7, module: 'seo', name: '合成网站' }, { id: 7, module: 'geo', name: '合成项目' },
] }]
for (const { module, scopeId, expected, missing } of [
  { module: 'seo', scopeId: 7, expected: '合成客户 · SEO · 合成网站', missing: false },
  { module: 'geo', scopeId: 7, expected: '合成客户 · GEO · 合成项目', missing: false },
  { module: 'seo', scopeId: null, expected: '合成客户 · SEO · 网站待补', missing: true },
  { module: 'geo', scopeId: null, expected: '合成客户 · GEO · 项目待补', missing: true },
  { module: 'seo', scopeId: 99, expected: '合成客户 · SEO · 网站 #99', missing: false },
  { module: 'geo', scopeId: 99, expected: '合成客户 · GEO · 项目 #99', missing: false },
]) {
  test(`assigned card shows ${expected} outside collapsed details`, async () => {
    const view = mount(targets, { tenantId: 42, module, scopeId }); await flush()
    try {
      const summary = view.element.querySelector('.assignment-target')
      assert.equal(summary.textContent, expected)
      assert.equal(summary.querySelectorAll('.assignment-scope-missing').length, Number(missing))
      assert.equal(summary.closest('details'), null)
      assert.equal(view.element.querySelector('details').open, false)
      assert.equal(view.calls.length, 0)
    } finally { view.close() }
  })
}

test('assigned card falls back for missing customer and scope names and hides inaccessible assignments', async () => {
  for (const [available, assignment, expected] of [
    [[], { tenantId: 88, module: 'seo', scopeId: 9 }, '客户 #88 · SEO · 网站 #9'],
    [[], { tenantId: 88, module: 'geo', scopeId: 9 }, '客户 #88 · GEO · 项目 #9'],
    [[{ tenantId: 88, modules: ['seo'], scopes: [{ id: 9, module: 'seo' }] }], { tenantId: 88, module: 'seo', scopeId: 9 }, '客户 #88 · SEO · 网站 #9'],
    [targets, { hidden: true }, null],
  ]) {
    const view = mount(available, assignment); await flush()
    try {
      assert.equal(view.element.querySelector('.assignment-target')?.textContent ?? null, expected)
      if (!expected) assert(view.element.textContent.includes('客户归属不可查看'))
    } finally { view.close() }
  }
})

for (const module of ['seo', 'geo']) {
  test(`only ${module} scope is selected with the single module and sent on label`, async () => {
    const view = mount([{ tenantId: 42, name: '合成客户', modules: [module], scopes: [
      { id: 7, module, name: '唯一范围' }, { id: 8, module: module === 'seo' ? 'geo' : 'seo', name: '其他模块范围' },
    ] }]); await flush()
    try {
      await select(view.element.querySelector('article select'), 42)
      assert.equal(view.element.querySelector('details select').value, '7')
      await click(view.element, '标注客户')
      assert.deepEqual(view.calls[0].slice(0, 5), ['label', module, 42, id, { expectedRevision: 0, targetTenant: 42, scopeId: 7 }])
    } finally { view.close() }
  })
}

test('multiple scopes keep the empty default and label sends no scope', async () => {
  const view = mount([{ tenantId: 42, name: '合成客户', modules: ['seo'], scopes: [
    { id: 7, module: 'seo', name: '网站一' }, { id: 8, module: 'seo', name: '网站二' },
  ] }]); await flush()
  try {
    await select(view.element.querySelector('article select'), 42)
    const scope = view.element.querySelector('details select')
    assert.equal(scope.value, '')
    assert.equal(scope.selectedOptions[0].textContent, '范围待补')
    await click(view.element, '标注客户')
    assert.equal(view.calls[0][4].scopeId, null)
  } finally { view.close() }
})

test('customer and module switches recompute the scope and clear stale article choices', async () => {
  const view = mount([
    { tenantId: 42, name: '客户一', modules: ['seo', 'geo'], scopes: [
      { id: 7, module: 'seo', name: '网站一', articles: [{ id: 3, title: '合成稿件', version: 1, digest: 'synthetic' }] },
      { id: 8, module: 'geo', name: '项目一' },
    ] },
    { tenantId: 43, name: '客户二', modules: ['seo'], scopes: [{ id: 9, module: 'seo', name: '网站二' }] },
    { tenantId: 44, name: '客户三', modules: ['seo'], scopes: [] },
    { tenantId: 45, name: '客户四', modules: ['seo'], scopes: [
      { id: 10, module: 'seo', name: '网站三' }, { id: 11, module: 'seo', name: '网站四' },
    ] },
  ]); await flush()
  const tenant = () => view.element.querySelector('article select')
  const scope = () => view.element.querySelector('details select')
  const article = () => view.element.querySelectorAll('details select')[1]
  const module = () => view.element.querySelectorAll('article select')[1]
  try {
    await select(tenant(), 42)
    assert.equal(scope().value, '')
    await select(module(), 'seo'); assert.equal(scope().value, '7')
    await select(article(), 3)
    await select(module(), 'geo')
    assert.equal(scope().value, '8'); assert.equal(article().value, '')
    await click(view.element, '标注客户')
    assert.equal(view.calls[0][4].scopeId, 8); assert(!Object.hasOwn(view.calls[0][4], 'articleId'))
    await select(module(), ''); assert.equal(scope().value, '')
    await select(module(), 'seo'); await select(article(), 3)
    await select(tenant(), 43)
    assert.equal(scope().value, '9'); assert.equal(article().value, '')
    await click(view.element, '标注客户')
    assert.equal(view.calls[1][2], 43); assert.equal(view.calls[1][4].scopeId, 9)
    assert(!Object.hasOwn(view.calls[1][4], 'articleId'))
    await select(tenant(), 45); assert.equal(scope().value, '')
    await select(tenant(), 43); assert.equal(scope().value, '9')
    await select(tenant(), 44); assert.equal(scope().value, '')
    await select(tenant(), ''); assert.equal(scope().value, '')
  } finally { view.close() }
})


test('rendered revision hint survives unrelated success and failure and only clears after successful reread', async () => {
  const view = mount([{ tenantId: 42, name: '示例客户甲', modules: ['seo'] }]); await flush()
  try {
    view.api.label = async () => { throw Object.assign(new Error('记录已被改过，请重新读取后再试'), { code: 'REVISION_CONFLICT' }) }
    await select(view.element.querySelector('article select'), 42)
    await click(view.element, '标注客户')
    await click(view.element, '生成配对码')
    assert.equal(view.element.querySelector('article [role=alert]').textContent, '记录已被改过，请重新读取后再试')
    assert.equal(view.element.textContent.split('记录已被改过，请重新读取后再试').length - 1, 1)
    view.api.createPairing = async () => { throw new Error('配对失败') }
    await click(view.element, '生成配对码')
    assert(view.element.textContent.includes('重新读取候选和回执'))
    view.api.receipt = async () => { throw new Error('读取失败') }
    await click(view.element, '重新读取候选和回执')
    assert(view.element.textContent.includes('重新读取候选和回执'))
    view.api.receipt = async () => ({ id, revision: 2, assignment: null })
    await click(view.element, '重新读取候选和回执')
    assert(!view.element.textContent.includes('重新读取候选和回执'))
    assert.equal(view.element.querySelector('article [role=alert]'), null)
  } finally { view.close() }
})


test('hidden assignment retains a readable conflict explanation after an unrelated list refresh', async () => {
  const view = mount([{ tenantId: 42, name: '示例客户甲', modules: ['seo'] }]); await flush()
  try {
    view.api.label = async () => { throw Object.assign(new Error('记录已被改过，请重新读取后再试'), { code: 'REVISION_CONFLICT' }) }
    await select(view.element.querySelector('article select'), 42)
    await click(view.element, '标注客户')
    view.api.receipts = async () => ({ items: [{ id, revision: 2, assignment: { hidden: true } }] })
    await click(view.element, '搜索')
    assert(view.element.textContent.includes('客户归属不可查看'))
    assert.equal(view.element.querySelector('article [role=alert]').textContent, '记录已被改过，请重新读取后再试')
    assert(view.element.textContent.includes('重新读取候选和回执'))
    assert(!view.element.textContent.includes('保存标注修改'))
  } finally { view.close() }
})
