import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

test('GEO tenant picker renders the readable customer card layout', () => {
  const geoPicker = app.slice(
    app.indexOf('<div v-if="isGeoRoute" class="geo-side-foot">'),
    app.indexOf('<nav v-else class="side-shortcuts"'),
  )
  assert.match(geoPicker, /class="tenant-avatar"[\s\S]*?tenantInitials\(t\)/)
  assert.match(geoPicker, /class="tenant-copy"/)
  assert.match(geoPicker, /class="tenant-title">\{\{ t\.name \}\}<\/span>/)
  assert.match(geoPicker, /独立账户数据 · 客户 ID \{\{ t\.id \}\}/)
  assert.match(geoPicker, /class="tenant-check">✓<\/span>/)
})
