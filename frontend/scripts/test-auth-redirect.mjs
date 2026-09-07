import assert from 'node:assert/strict'
import test from 'node:test'

import {
  hasAvailableAcquisitionModule,
  parseSameOriginRedirect,
  resolvePostLoginPath,
} from '../src/auth/postLoginRedirect.mjs'

const ORIGIN = 'https://gsnipers.snipers.com.cn'

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
    modules: [],
  }), '/seo/dashboard?tab=sites#summary')
})

test('each purchased acquisition module defaults to the cockpit', () => {
  for (const module_code of ['sem', 'seo', 'geo']) {
    assert.equal(resolvePostLoginPath({
      redirect: '',
      currentOrigin: ORIGIN,
      modules: [{ module_code, available: true }],
    }), '/workspace/cockpit', module_code)
  }
})

test('two or three purchased acquisition modules default to the cockpit', () => {
  for (const modules of [
    [{ module_code: 'sem', available: true }, { module_code: 'seo', available: true }],
    ['sem', 'seo', 'geo'].map(module_code => ({ module_code, available: true })),
  ]) {
    assert.equal(hasAvailableAcquisitionModule(modules), true)
    assert.equal(resolvePostLoginPath({ redirect: '', currentOrigin: ORIGIN, modules }), '/workspace/cockpit')
  }
})

test('no available acquisition module or a failed module lookup falls back to workspace', () => {
  for (const modules of [
    [],
    undefined,
    [{ module_code: 'sem', available: false }],
    [{ module_code: 'diagnostic', available: true }],
  ]) {
    assert.equal(resolvePostLoginPath({ redirect: '', currentOrigin: ORIGIN, modules }), '/workspace')
  }
  assert.equal(resolvePostLoginPath({
    redirect: '/\\evil.example',
    currentOrigin: ORIGIN,
    modules: undefined,
  }), '/workspace')
})
