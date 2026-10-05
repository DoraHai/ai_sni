import assert from 'node:assert/strict'
import { test } from 'node:test'
import { previousBeijingMonth, publicationListFilename } from '../src/api/seoPublicationExport.js'

test('默认上个月按北京时间计算，含跨年边界', () => {
  assert.equal(previousBeijingMonth(new Date('2026-09-30T16:30:00Z')), '2026-09')
  assert.equal(previousBeijingMonth(new Date('2026-01-01T00:00:00Z')), '2025-12')
  assert.equal(previousBeijingMonth(new Date('2025-12-31T15:59:00Z')), '2025-11')
})

test('优先解析 RFC 5987 文件名，缺失时回退', () => {
  assert.equal(publicationListFilename("attachment; filename=plain.xlsx; filename*=UTF-8''%E5%8F%91%E5%B8%83.xlsx", 'fallback.xlsx'), '发布.xlsx')
  assert.equal(publicationListFilename('attachment; filename="plain.xlsx"', 'fallback.xlsx'), 'plain.xlsx')
  assert.equal(publicationListFilename(null, 'fallback.xlsx'), 'fallback.xlsx')
})
