import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createMemoryHistory, createRouter } from 'vue-router'
import { installGeoChunkReload } from '../geo-frontend/src/chunkReload.js'

const KEY = 'geo:chunk-reload-at'
const MESSAGE = '页面资源加载失败，请按 Ctrl+F5 刷新；仍失败请检查网络'
const chunkError = () => new TypeError('Failed to fetch dynamically imported module: /assets/GeoFactsView-old.js')

function harness(storage = new Map(), currentPath = '') {
  const win = new EventTarget()
  const calls = { reloads: 0, messages: [], routes: [], order: [] }
  const guards = []
  const after = []
  const errors = []
  win.sessionStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => { storage.set(key, value); calls.order.push('mark') },
  }
  win.history = {
    state: { back: null },
    replaceState(state, title, href) {
      calls.routes.push(href)
      calls.order.push('route')
      assert.equal(state, win.history.state)
    },
  }
  win.location = { reload: () => { calls.reloads++; calls.order.push('reload') } }
  const router = {
    currentRoute: { value: { path: currentPath } },
    beforeEach: (fn) => guards.push(fn),
    afterEach: (fn) => after.push(fn),
    onError: (fn) => errors.push(fn),
    resolve: (route) => ({ href: `#${route}` }),
  }
  installGeoChunkReload(win, router, (message) => calls.messages.push(message))
  return {
    win, calls, storage,
    navigate: (route) => guards.forEach((fn) => fn({ fullPath: route })),
    showPage: (path) => { router.currentRoute.value.path = path },
    finish: () => after.forEach((fn) => fn()),
    fail: (error, route) => errors.forEach((fn) => fn(error, route && { fullPath: route })),
    emit(type, error) {
      const event = new Event(type, { cancelable: true })
      event.payload = error
      event.reason = error
      win.dispatchEvent(event)
      return event
    },
  }
}

test('first Vite failure marks storage before reloading once at the intended route', () => {
  const h = harness()
  h.navigate('/geo/knowledge?tenant_id=16#facts')
  const event = h.emit('vite:preloadError', chunkError())
  h.fail(chunkError(), '/geo/knowledge?tenant_id=16#facts')
  h.emit('unhandledrejection', chunkError())
  assert.equal(h.calls.reloads, 1)
  assert.deepEqual(h.calls.routes, ['#/geo/knowledge?tenant_id=16#facts'])
  assert.deepEqual(h.calls.order, ['mark', 'route', 'reload'])
  assert.deepEqual(h.calls.messages, [])
  assert.ok(Number(h.storage.get(KEY)) > 0)
  assert.equal(event.defaultPrevented, false, 'Vite must still reject to the router')
})

test('a second page failure within 30 seconds shows one persistent prompt without reload', () => {
  const firstPage = harness()
  firstPage.fail(chunkError(), '/geo/knowledge')
  const secondPage = harness(firstPage.storage)
  secondPage.emit('vite:preloadError', chunkError())
  secondPage.fail(chunkError(), '/geo/knowledge')
  secondPage.emit('unhandledrejection', chunkError())
  assert.equal(secondPage.calls.reloads, 0)
  assert.deepEqual(secondPage.calls.routes, [])
  assert.deepEqual(secondPage.calls.messages, [MESSAGE])
  assert.equal(secondPage.storage.get(KEY), firstPage.storage.get(KEY))
})

test('the time window survives successful navigation, and expires after 30 seconds', () => {
  const recent = harness(new Map([[KEY, String(Date.now())]]))
  recent.navigate('/geo/overview')
  recent.finish()
  recent.fail(chunkError(), '/geo/knowledge')
  assert.equal(recent.calls.reloads, 0)
  const expired = harness(new Map([[KEY, String(Date.now() - 30_001)]]))
  expired.fail(chunkError(), '/geo/knowledge')
  assert.equal(expired.calls.reloads, 1)
})

test('ordinary errors do not reload, notify, mark storage or suppress normal reporting', (t) => {
  const logged = []
  t.mock.method(console, 'error', (error) => logged.push(error))
  for (const error of [new Error('API 404'), new TypeError('Failed to fetch'), new Error('render failed')]) {
    const h = harness()
    assert.equal(h.emit('vite:preloadError', error).defaultPrevented, false)
    assert.equal(h.emit('unhandledrejection', error).defaultPrevented, false)
    h.fail(error, '/geo/overview')
    assert.equal(h.calls.reloads, 0)
    assert.equal(h.storage.size, 0)
    assert.deepEqual(h.calls.messages, [])
  }
  assert.equal(logged.length, 3)
})

test('dynamic import and CSS failures from different browsers use the same recovery', () => {
  for (const message of [
    'error loading dynamically imported module: /assets/old.js',
    'Importing a module script failed.',
    'Loading chunk 42 failed.',
    'Loading CSS chunk view-old failed.',
    'Unable to preload CSS for /assets/old.css',
  ]) {
    const h = harness()
    h.emit('unhandledrejection', new Error(message))
    assert.equal(h.calls.reloads, 1, message)
  }
  const h = harness()
  h.fail(Object.assign(new Error('old chunk'), { name: 'ChunkLoadError' }))
  assert.equal(h.calls.reloads, 1)
})

test('unavailable sessionStorage shows the prompt instead of risking a refresh loop', () => {
  for (const method of ['getItem', 'setItem']) {
    const h = harness()
    h.win.sessionStorage[method] = () => { throw new Error('storage blocked') }
    h.fail(chunkError(), '/geo/knowledge')
    assert.equal(h.calls.reloads, 0)
    assert.deepEqual(h.calls.messages, [MESSAGE])
  }
})

test('failed lazy navigation preserves form and article pages without changing their URL', () => {
  for (const path of ['/geo/tasks/12', '/geo/tasks/12/distribution', '/geo/brand',
    '/geo/knowledge', '/geo/questions', '/geo/projects', '/geo/import', '/geo/publishing',
    '/geo/placements', '/geo/report', '/geo/models', '/geo/channel-polish-prompts', '/geo/visibility/snapshots',
    '/geo/competitors', '/geo/visibility', '/geo/citations', '/geo/tickets', '/geo/evaluation', '/geo/future-editing-page']) {
    const h = harness(new Map(), path)
    h.navigate('/geo/overview')
    h.fail(chunkError(), '/geo/overview')
    h.emit('unhandledrejection', chunkError())
    assert.equal(h.calls.reloads, 0, path)
    assert.deepEqual(h.calls.routes, [], path)
    assert.equal(h.storage.size, 0, path)
    assert.equal(h.calls.messages.length, 1, path)
    assert.match(h.calls.messages[0], /先保存或复制未保存内容/)
  }
  const readonly = harness(new Map(), '/geo/overview')
  readonly.fail(chunkError(), '/geo/structure')
  assert.equal(readonly.calls.reloads, 1)
})

test('an earlier read-only warning never suppresses the later save-before-refresh warning', () => {
  const h = harness(new Map([[KEY, String(Date.now())]]), '/geo/overview')
  h.fail(chunkError(), '/geo/structure')
  assert.deepEqual(h.calls.messages, [MESSAGE])
  h.showPage('/geo/competitors')
  h.fail(chunkError(), '/geo/structure')
  h.emit('unhandledrejection', chunkError())
  assert.equal(h.calls.reloads, 0)
  assert.equal(h.calls.messages.length, 2)
  assert.match(h.calls.messages[1], /先保存或复制未保存内容/)
})

test('a history write failure still reloads the current page once', () => {
  const h = harness()
  h.win.history.replaceState = () => { throw new Error('history unavailable') }
  h.fail(chunkError(), '/geo/knowledge')
  assert.equal(h.calls.reloads, 1)
})

test('real Vue Router lazy import failure preserves other onError handlers and target', async () => {
  const h = harness()
  const error = chunkError()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/geo/overview', component: {} },
      { path: '/geo/knowledge', component: () => Promise.reject(error) },
    ],
  })
  const originalErrors = []
  router.onError((caught) => originalErrors.push(caught))
  installGeoChunkReload(h.win, router, (message) => h.calls.messages.push(message))
  await router.push('/geo/overview')
  await assert.rejects(router.push('/geo/knowledge?tenant_id=16'), (caught) => caught === error)
  assert.equal(h.calls.reloads, 1)
  assert.deepEqual(h.calls.routes, ['/geo/knowledge?tenant_id=16'])
  assert.deepEqual(originalErrors, [error])
})

test('the published GEO entry installs recovery before initial router navigation', () => {
  const main = readFileSync(new URL('../geo-frontend/src/main.js', import.meta.url), 'utf8')
  assert.ok(main.indexOf('installGeoChunkReload(window') < main.indexOf('.use(router)'))
  assert.match(main, /ElMessage\(\{ message, type: 'warning', duration: 0, showClose: true \}\)/)
})
