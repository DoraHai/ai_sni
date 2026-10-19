import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash, webcrypto } from 'node:crypto'
import { reportContext, reportDigest, reportToggle } from '../src/utils/geoDistributionReport.js'

test('tenant/project/identity epochs discard delayed results after reset', () => {
  const scope = reportContext(), pending = scope.capture()
  assert.equal(scope.current(pending), true)
  scope.reset()
  assert.equal(scope.current(pending), false)
  const second = scope.capture()
  scope.reset()
  assert.equal(scope.current(second), false)
})
test('Chinese, newline, escaping and emoji digest agrees with JSON.stringify UTF-8', async () => {
  const variant = { title: '中文😀', body_markdown: '第一行\n"第二行\\' }
  const expected = createHash('sha256').update(JSON.stringify(['geo-article-100', variant.title, variant.body_markdown, []])).digest('hex')
  assert.equal(await reportDigest(100, variant, webcrypto.subtle), expected)
})
test('closing a scope preserves a disabled tenant switch', () => {
  assert.deepEqual(reportToggle({ enabled: false, scope_enabled: true, revision: 2, scope_revision: 1 }),
    { enabled: false, scope_enabled: false, expected_revision: 2, expected_scope_revision: 1 })
})
