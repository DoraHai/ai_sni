import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { legacySeoUrl, handoffLegacySeo } from '../src/router/legacySeoHandoff.js'

const pages = ['dashboard', 'alerts', 'keywords', 'keywords/27', 'rankings', 'trends', 'site',
  'content/articles', 'content/rewrites', 'content/qa', 'content/editor',
  'content/answer-editor', 'distribution', 'links', 'competitors']
const route = (path, query = {}, hash = '') => ({ path, query, hash })
function browserAt(url = '/workspace') {
  const location = new URL(url, 'https://synthetic.invalid')
  const data = new Map(); const calls = []
  return { location: { pathname: location.pathname, search: location.search, hash: location.hash,
    assign: target => calls.push(target) },
    sessionStorage: { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) },
    calls, addEventListener() {} }
}

test('all existing SEO pages hand off to the corresponding independent path with selected scope', () => {
  for (const page of pages) {
    assert.equal(legacySeoUrl(route('/seo/' + page), { tenantId: 42, siteId: 19 }), `/seo/${page}?tenant_id=42&site_id=19`)
  }
  assert.equal(legacySeoUrl(route('/seo/')), '/seo/dashboard')
  assert.equal(legacySeoUrl(route('/seo/content')), '/seo/content/articles')
})

test('explicit target scope takes precedence; site from another customer is never borrowed', () => {
  const context = { tenantId: 42, siteId: 19 }
  assert.equal(legacySeoUrl(route('/seo/distribution', { tenant_id: '43', site_id: '20' }), context), '/seo/distribution?tenant_id=43&site_id=20')
  assert.equal(legacySeoUrl(route('/seo/distribution', { tenant_id: '43' }), context), '/seo/distribution?tenant_id=43')
  assert.equal(legacySeoUrl(route('/seo/distribution', { site_id: '20' }), context), '/seo/distribution?tenant_id=42&site_id=20')
  for (const bad of ['0', '-1', '1.5', 'Infinity', ['42', '43'], {}, true, 'https://outside.invalid']) {
    const value = new URL(legacySeoUrl(route('/seo/distribution', { tenant_id: bad, site_id: '20' }), context), 'https://synthetic.invalid')
    assert.equal(value.searchParams.has('tenant_id'), false)
    assert.equal(value.searchParams.has('site_id'), false)
  }
})

test('editor filters, array queries and anchor survive without creating an external URL', () => {
  const value = legacySeoUrl(route('/seo/content/editor', { id: '7', type: 'rewrite', q: '合成 & #', tag: ['a', 'b'] }, '#preview'), { tenantId: 42, siteId: 19 })
  const url = new URL(value, 'https://synthetic.invalid')
  assert.equal(url.origin, 'https://synthetic.invalid')
  assert.equal(url.pathname, '/seo/content/editor')
  assert.equal(url.searchParams.get('q'), '合成 & #')
  assert.deepEqual(url.searchParams.getAll('tag'), ['a', 'b'])
  assert.equal(url.hash, '#preview')
})

test('SEM, workbench and SEO paths with no independent equivalent remain unchanged', () => {
  for (const path of ['/workspace', '/workspace/cockpit', '/sem/accounts', '/monitor/dashboard', '/seo/unknown', '/seo/not-a-page', '/seo/keywords/1/extra', '//outside.invalid/seo/distribution']) {
    const browser = browserAt()
    assert.equal(handoffLegacySeo(route(path), {}, browser), null)
    assert.deepEqual(browser.calls, [])
  }
})

test('full-document navigation occurs once; a misrouted SEO document cannot reload in a loop', () => {
  const browser = browserAt('/seo/distribution?tenant_id=42&site_id=19')
  const to = route('/seo/distribution', { tenant_id: '42', site_id: '19' })
  assert.equal(handoffLegacySeo(to, {}, browser), 'redirected')
  assert.equal(handoffLegacySeo(to, {}, browser), 'blocked')
  assert.deepEqual(browser.calls, ['/seo/distribution?tenant_id=42&site_id=19'])
  handoffLegacySeo(route('/workspace'), {}, browser)
  assert.equal(handoffLegacySeo(to, {}, browser), 'redirected')
})

test('disabled storage permits handoff from SEM and blocks reloading the target document', () => {
  const browser = browserAt()
  browser.sessionStorage = { getItem() { throw new Error('disabled') }, setItem() { throw new Error('disabled') } }
  assert.equal(handoffLegacySeo(route('/seo/distribution'), {}, browser), 'redirected')
  browser.location.pathname = '/seo/distribution'
  assert.equal(handoffLegacySeo(route('/seo/distribution'), {}, browser), 'blocked')
})

test('actual generic router cancels every SEO navigation before loading any old SEO component', async () => {
  // Use the real route table and Vue Router, replacing only browser/UI/session dependencies.
  const require = createRequire(import.meta.url)
  const vueRouterUrl = pathToFileURL(require.resolve('vue-router')).href
  const handoffUrl = new URL('../src/router/legacySeoHandoff.js', import.meta.url).href
  const source = await readFile(new URL('../src/router/index.js', import.meta.url), 'utf8')
  const code = source.replace(/^import .*$/gm, '').replace('createWebHistory()', 'createMemoryHistory()')
  const setup = `import { createRouter, createMemoryHistory } from ${JSON.stringify(vueRouterUrl)};
import { handoffLegacySeo } from ${JSON.stringify(handoffUrl)};
const session = { isLoggedIn: true, tenantId: 42, canView: () => true, canEdit: () => true };
const currentSeoSiteId = { value: 19 };
const ElMessage = { error() {}, warning() {} };
const SEM_PLANNED_CHANNELS = [], COCKPIT_PERMISSION_KEYS = [];
const clearChunkRecoveryMarker = () => {}, recoverFromChunkLoadError = () => false, isChunkLoadError = () => false;
const semChannelPath = () => '', loginUrl = () => '/login';
`
  await import(vueRouterUrl) // initialize Vue in Node before installing the minimal browser stub
  globalThis.window = browserAt()
  globalThis.document = { title: '' }
  const { default: router } = await import('data:text/javascript;base64,' + Buffer.from(setup + code).toString('base64'))
  const aliases = ['/deal-sniper/seo/manage', '/deal-sniper/seo/keywords', '/deal-sniper/seo/tdk',
    '/deal-sniper/seo/dashboard', '/deal-sniper/seo/trends', '/deal-sniper/seo/competitors',
    '/deal-sniper/seo/articles', '/deal-sniper/seo/rewrites', '/deal-sniper/seo/questions', '/deal-sniper/seo/channels']
  for (const path of ['/seo', '/seo/content', ...pages.map(page => '/seo/' + page), ...aliases]) {
    const before = window.calls.length
    const failure = await router.push(path + '?tenant_id=42&site_id=19')
    assert.equal(failure.type, 4, path) // navigation aborted by the global beforeEach
    assert.equal(window.calls.length, before + 1, path)
    const target = new URL(window.calls.at(-1), 'https://synthetic.invalid')
    assert(target.pathname.startsWith('/seo/'), path)
    assert.equal(target.searchParams.get('tenant_id'), '42', path)
    assert.equal(target.searchParams.get('site_id'), '19', path)
    assert.equal(router.currentRoute.value.matched.length, 0, path)
  }
})
