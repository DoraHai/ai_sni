import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { geoLoginRedirectPath } from '../geo-frontend/src/authRedirect.js'

test('GEO login keeps the independent app route, hash and legitimate tenant', () => {
  const path = '/deal-sniper/geo/dashboard.html?tenant_id=16#/geo/tasks/14?tenant_id=16'
  assert.equal(geoLoginRedirectPath(path), path)
})

test('GEO login redirect strips credentials from shell and hash queries', () => {
  const actual = geoLoginRedirectPath(
    '/deal-sniper/geo/dashboard.html?tenant_id=16&api_origin=https://evil.example&API_KEY=x' +
    '#/geo/tasks/14?tenant_id=16&token=secret&access_token=secret2',
  )
  assert.equal(actual, '/deal-sniper/geo/dashboard.html?tenant_id=16#/geo/tasks/14?tenant_id=16')
})

test('GEO login redirect rejects absolute and protocol-relative targets', () => {
  assert.equal(geoLoginRedirectPath('https://evil.example/path'), '/')
  assert.equal(geoLoginRedirectPath('//evil.example/path'), '/')
})

test('independent GEO router uses the shared safe login URL contract', () => {
  const router = readFileSync(new URL('../geo-frontend/src/router.js', import.meta.url), 'utf8')
  assert.match(router, /loginUrl\(geoLoginRedirectPath\(\)\)/)
  assert.equal(router.includes('encodeURIComponent(window.location.href)'), false)
})
