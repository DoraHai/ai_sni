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
const Component = (await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))).default
const id = '11111111-1111-4111-8111-111111111111'
const flush = async () => { await new Promise(r => setTimeout(r, 0)); await nextTick() }

function mount(targets = []) {
  const calls = []
  const api = {
    receipts: async () => ({ items: [{ id, revision: 0, platform: '新平台', title: '<img src=x onerror=alert(1)>',
      reportedAccount: '<script>unsafe</script>', result: 'success', publicUrl: 'https://example.invalid/article',
      occurredAt: '2026-10-19T11:00:00.000Z', receivedAt: '2026-10-19T11:01:00.000Z' }] }),
    devices: async () => ({ items: [{ id, revision: 0, label: '合成电脑', state: 'active' }] }), count: async () => ({ count: 1 }),
    createPairing: async () => { calls.push('pair'); return { pairingCode: 'DHT2-'+'a'.repeat(32) } },
    revoke: async () => calls.push('revoke'), label: async (...args) => calls.push(['label',...args]),
    unlabel: async (...args) => calls.push(['unlabel',...args]),
  }
  const element = document.createElement('div'); document.body.append(element)
  const app = createApp(Component, { api, identity: 'synthetic-1', targets }); app.mount(element)
  return { element, calls, close: () => { app.unmount(); element.remove() } }
}
const click = async (element, label) => { [...element.querySelectorAll('button')].find(b => b.textContent === label).click(); await flush() }

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
    assert(!button.disabled)
    button.click(); await flush()
    assert.deepEqual(view.calls[0].slice(0,5), ['label','geo',42,id,{ expectedRevision: 0, targetTenant: 42, scopeId: null }])
  } finally { view.close() }
})
