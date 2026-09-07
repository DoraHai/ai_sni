import assert from 'node:assert/strict'
import test from 'node:test'

import {
  parseSameOriginRedirect,
  resolvePostLoginPath,
} from '../src/auth/postLoginRedirect.mjs'
import { COCKPIT_PERMISSION_KEYS } from '../src/views/workspace/cockpit/scope.mjs'

const ORIGIN = 'https://gsnipers.snipers.com.cn'

test('uses the exact shared acquisition cockpit permission scope', () => {
  assert.deepEqual(COCKPIT_PERMISSION_KEYS, [
    'monitor.dashboard',
    'optimize.keywords',
    'optimize.searchterms',
    'seo.site',
    'seo.content',
    'geo.content',
  ])
})

test('preserves valid same-origin paths, queries, hashes, and absolute URLs', () => {
  assert.equal(
    parseSameOriginRedirect('/workspace/cockpit?tenant=16#actions', ORIGIN),
    '/workspace/cockpit?tenant=16#actions',
  )
  assert.equal(
    parseSameOriginRedirect(`${ORIGIN}/seo/dashboard?tab=sites#summary`, ORIGIN),
    '/seo/dashboard?tab=sites#summary',
  )
})

test('rejects network-path, backslash, encoded-backslash, and cross-origin redirects', () => {
  for (const redirect of [
    '//evil.example/path',
    '/\\evil.example/path',
    '/%5cevil.example/path',
    '/%255cevil.example/path',
    '/%25252525255cevil.example/path',
    'https://evil.example/path',
  ]) {
    assert.equal(parseSameOriginRedirect(redirect, ORIGIN), null, redirect)
  }
})

test('rejects raw or encoded controls and malformed percent escapes', () => {
  for (const redirect of [
    '/workspace\n/cockpit',
    '/workspace%0a/cockpit',
    '/workspace%250a/cockpit',
    '/workspace/%zz',
    ' /workspace/cockpit',
  ]) {
    assert.equal(parseSameOriginRedirect(redirect, ORIGIN), null, JSON.stringify(redirect))
  }
})

test('a valid redirect has priority over the permission default', () => {
  assert.equal(resolvePostLoginPath({
    redirect: '/seo/dashboard?tab=sites#summary',
    currentOrigin: ORIGIN,
    canView: () => false,
  }), '/seo/dashboard?tab=sites#summary')
})

test('missing or rejected redirects use the shared cockpit permission scope', () => {
  for (const permission of COCKPIT_PERMISSION_KEYS) {
    assert.equal(resolvePostLoginPath({
      redirect: '',
      currentOrigin: ORIGIN,
      canView: key => key === permission,
    }), '/workspace/cockpit', permission)
  }
  assert.equal(resolvePostLoginPath({
    redirect: '/\\evil.example',
    currentOrigin: ORIGIN,
    canView: key => key === 'geo.diagnosis',
  }), '/workspace')
})
