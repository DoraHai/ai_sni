import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { previousBeijingMonth, monthRange, metricText, baiduAuthorizeUrl, sanitizedSecrets } from '../src/views/seo/seoSiteAnalytics.js'
test('month follows Beijing calendar', () => assert.equal(previousBeijingMonth(new Date('2026-10-01T00:30:00+08:00')), '2026-09'))
test('monthly history spans twelve months through selection', () => {
  assert.deepEqual(monthRange('2026-10'), { from_month: '2025-11', to_month: '2026-10' })
  assert.deepEqual(monthRange('2026-01'), { from_month: '2025-02', to_month: '2026-01' })
})
test('null stays no data; real zero stays zero', () => { assert.equal(metricText(null), '无数据'); assert.equal(metricText(0), '0') })
test('authorization uses documented out-of-band parameters', () => { const url = new URL(baiduAuthorizeUrl('abc')); assert.equal(url.searchParams.get('redirect_uri'), 'oob'); assert.equal(url.searchParams.get('client_id'), 'abc') })
test('empty masked secrets are not submitted', () => assert.deepEqual(sanitizedSecrets({ secret_key: '', refresh_token: 'abc' }), { refresh_token: 'abc' }))
test('optimization view defines router used by template navigation', () => {
  const source = readFileSync(new URL('../src/views/seo/SeoSiteOptimizationView.vue', import.meta.url), 'utf8')
  if (source.includes('router.push')) {
    assert.match(source, /import\s*\{[^}]*useRouter[^}]*\}\s*from\s*['"]vue-router['"]/)
    assert.match(source, /const\s+router\s*=\s*useRouter\(\)/)
  }
})
test('analytics view shows setup steps and guards unsaved authorization', () => {
  const source = readFileSync(new URL('../src/views/seo/SeoSiteAnalyticsView.vue', import.meta.url), 'utf8')
  assert.match(source, /monthRange\(month\.value\)/)
  assert.match(source, /:disabled="!canExchange"/)
  assert.match(source, /请先保存 Secret Key/)
  assert.match(source, /modeWillSwitch/)
  assert.match(source, /<ol v-if="baidu\.mode === 'account'"/)
  assert.match(source, /GA4 管理-媒体资源访问管理/)
  assert.match(source, /ElMessage\.success\(result\.last_test_message/)
})
