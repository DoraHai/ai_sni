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

test('all login entry points land on the cockpit by default', () => {
  assert.equal(resolvePostLoginPath({
    redirect: '/seo/dashboard?tab=sites#summary',
    currentOrigin: ORIGIN,
    modules: [],
  }), '/workspace/cockpit')
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

test('no available acquisition module or a failed module lookup still lands on the cockpit', () => {
  for (const modules of [
    [],
    undefined,
    [{ module_code: 'sem', available: false }],
    [{ module_code: 'diagnostic', available: true }],
  ]) {
    assert.equal(resolvePostLoginPath({ redirect: '', currentOrigin: ORIGIN, modules }), '/workspace/cockpit')
  }
  assert.equal(resolvePostLoginPath({
    redirect: '/\\evil.example',
    currentOrigin: ORIGIN,
    modules: undefined,
  }), '/workspace/cockpit')
})

test('explicit customer workbench scope returns after SEO login', () => {
  for (const redirect of [
    '/customer-workbench/?tenant_id=17&site_id=3',
    `${ORIGIN}/customer-workbench?tenant_id=17&site_id=3`,
  ]) {
    assert.equal(resolvePostLoginPath({redirect, currentOrigin: ORIGIN,
      modules: [{module_code: 'seo', available: true}]}),
    '/customer-workbench/?tenant_id=17&site_id=3')
  }
})

test('workbench return requires available SEO without changing normal login defaults', () => {
  for (const modules of [undefined, [], [{module_code: 'seo', available: false}],
    [{module_code: 'seo', available: 'true'}], [{module_code: 'sem', available: true}]]) {
    assert.equal(resolvePostLoginPath({redirect: '/customer-workbench/?tenant_id=17&site_id=3',
      currentOrigin: ORIGIN, modules}), '/workspace/cockpit')
  }
})

test('workbench return rejects forged destinations and ambiguous or unsafe scope', () => {
  for (const redirect of [
    'https://evil.example/customer-workbench/?tenant_id=17&site_id=3',
    '/customer-workbench/?tenant_id=17',
    '/customer-workbench/?tenant_id=17&site_id=3&site_id=4',
    '/customer-workbench/?tenant_id=17&tenant_id=18&site_id=3',
    '/customer-workbench/?tenant_id=17&site_id=3&redirect=https://evil.example',
    '/customer-workbench/?tenant_id=0&site_id=3',
    '/customer-workbench/?tenant_id=1e2&site_id=3',
    '/customer-workbench/?tenant_id=9007199254740992&site_id=3',
    '/customer-workbench/?tenant_id=17&site_id=%255c',
    '/customer-workbench/?tenant_id=17&site_id=3#other',
    '/customer-workbench/other?tenant_id=17&site_id=3',
    '/login?tenant_id=17&site_id=3',
  ]) {
    assert.equal(resolvePostLoginPath({redirect, currentOrigin: ORIGIN,
      modules: [{module_code: 'seo', available: true}]}), '/workspace/cockpit', redirect)
  }
})
