import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

test('structure scan distinguishes unavailable assessment from a zero score', () => {
  const source = readFileSync(
    resolve(import.meta.dirname, '../src/views/geo/GeoStructureView.vue'),
    'utf8',
  )

  assert.match(source, /assessment_status === 'insufficient_sample'/)
  assert.match(source, /pages\.value\.every\(\(page\) => page\.status === '错误'\)/)
  assert.match(source, /无法完成结构评估/)
  assert.match(source, /成功解析/)
  assert.match(source, /抓取失败/)
  assert.doesNotMatch(source, /成功解析 0 页/)
})
