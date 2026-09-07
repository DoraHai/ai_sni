import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const base = '../public/deal-sniper-prototype/geo/'
const apiSource = readFileSync(new URL(base + 'assets/geo-api-v1.js', import.meta.url), 'utf8')

function storage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: (key) => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  }
}

function response(status, body) {
  return {
    status,
    ok: status >= 200 && status < 300,
    text: async () => JSON.stringify(body),
  }
}

function load({ href, local = {}, session = {}, fetch }) {
  const location = {
    href,
    origin: 'https://safe.example',
    search: new URL(href).search,
    hostname: 'safe.example',
    port: '',
  }
  const window = { location }
  const context = vm.createContext({
    window,
    localStorage: storage(local),
    sessionStorage: storage(session),
    fetch,
    URL,
    URLSearchParams,
    FormData,
    console,
  })
  vm.runInContext(apiSource, context)
  return { api: window.GeoAPI, location, ...context }
}

test('malicious origin and legacy API key cannot receive the login token', async () => {
  const calls = []
  const env = load({
    href: 'https://safe.example/deal-sniper/geo/dashboard.html?tenant_id=7&api_origin=https://evil.example&api_key=legacy',
    local: {
      sem_token: 'synthetic-current-token',
      geo_api_origin: 'https://stored-evil.example',
      geo_api_key: 'stored-legacy-key',
    },
    fetch: async (...args) => {
      calls.push(args)
      return response(200, { ok: true })
    },
  })

  await env.api.api('/content-health')
  assert.equal(calls.length, 1)
  const [url, options] = calls[0]
  assert.equal(new URL(url).origin, 'https://safe.example')
  assert.equal(options.headers.Authorization, 'Bearer synthetic-current-token')
  assert.equal(options.headers['X-API-Key'], undefined)
  assert.equal(new URL(url).searchParams.has('api_key'), false)
  assert.equal(new URL(url).searchParams.has('api_origin'), false)
})

test('missing login fails closed and strips sensitive redirect parameters', async () => {
  let fetched = false
  const env = load({
    href: 'https://safe.example/deal-sniper/geo/editor.html?tenant_id=7&api_origin=https://evil.example&api_key=legacy#task',
    fetch: async () => {
      fetched = true
      return response(200, {})
    },
  })

  await assert.rejects(env.api.api('/content-health'), /请先登录/)
  assert.equal(fetched, false)
  assert.match(env.location.href, /^\/login\?redirect=/)
  assert.equal(env.location.href.includes('api_key'), false)
  assert.equal(env.location.href.includes('api_origin'), false)
  assert.equal(decodeURIComponent(env.location.href), '/login?redirect=/deal-sniper/geo/editor.html?tenant_id=7#task')
})

test('401 clears only the token used by that request', async () => {
  let finish
  const pending = new Promise((resolve) => { finish = resolve })
  const env = load({
    href: 'https://safe.example/deal-sniper/geo/dashboard.html?tenant_id=7',
    local: { sem_token: 'old-token', sem_user: '{"id":1}' },
    fetch: () => pending,
  })

  const request = env.api.api('/content-health')
  env.localStorage.setItem('sem_token', 'new-token')
  env.localStorage.setItem('sem_user', '{"id":2}')
  finish(response(401, { detail: 'expired' }))
  await assert.rejects(request, /expired/)
  assert.equal(env.localStorage.getItem('sem_token'), 'new-token')
  assert.equal(env.localStorage.getItem('sem_user'), '{"id":2}')
  assert.equal(env.location.href, 'https://safe.example/deal-sniper/geo/dashboard.html?tenant_id=7')
})

test('401 for the current token clears its identity and returns to login', async () => {
  const env = load({
    href: 'https://safe.example/deal-sniper/geo/dashboard.html?tenant_id=7&api_key=legacy',
    local: { sem_token: 'expired-token', sem_user: '{"id":1}' },
    fetch: async () => response(401, { detail: 'expired' }),
  })

  await assert.rejects(env.api.api('/content-health'), /expired/)
  assert.equal(env.localStorage.getItem('sem_token'), null)
  assert.equal(env.localStorage.getItem('sem_user'), null)
  assert.equal(env.location.href.includes('api_key'), false)
  assert.equal(decodeURIComponent(env.location.href), '/login?redirect=/deal-sniper/geo/dashboard.html?tenant_id=7')
})

test('legacy pages no longer consume or propagate API credentials and origins', () => {
  const sidebar = readFileSync(new URL(base + 'assets/geo-sidebar-v1.js', import.meta.url), 'utf8')
  const workbench = readFileSync(new URL(base + 'assets/geo-workbench-v1.js', import.meta.url), 'utf8')
  const editor = readFileSync(new URL(base + 'editor.html', import.meta.url), 'utf8')
  const diagnosis = readFileSync(new URL('../src/views/diagnosis/DiagnosisCenterView.vue', import.meta.url), 'utf8')

  for (const source of [sidebar, workbench, editor, diagnosis]) {
    assert.equal(source.includes("get('api_key')"), false)
    assert.equal(source.includes("set('api_key'"), false)
    assert.equal(source.includes("get('api_origin')"), false)
    assert.equal(source.includes("set('api_origin'"), false)
    assert.equal(source.includes("getItem('geo_api_key')"), false)
    assert.equal(source.includes("getItem('geo_api_origin')"), false)
  }
  assert.equal(apiSource.includes('X-API-Key'), false)
})
