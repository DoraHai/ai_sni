import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const router = readFileSync(new URL('../src/router/index.js', import.meta.url), 'utf8')

test('new GEO prototype routes are canonical', () => {
  assert.match(router, /path: '\/geo\/import'/)
  assert.match(router, /GeoArticleImportView\.vue/)
  assert.match(router, /path: '\/geo\/articles\/:taskId\/distribution'/)
  assert.match(router, /GeoDistributionView\.vue/)
  assert.match(router, /path: '\/geo\/publishing-channels'/)
  assert.match(router, /path: '\/geo\/channels'/)
  assert.match(
    router,
    /path: '\/geo\/publishing-channels',[\s\S]*?redirect: \(to\) => \(\{ path: '\/geo\/channels', query: to\.query \}\)/,
  )
})
