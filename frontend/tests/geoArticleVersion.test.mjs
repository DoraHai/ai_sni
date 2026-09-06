import test from 'node:test'
import assert from 'node:assert/strict'
import { articleVersionLabel } from '../src/utils/geoArticleVersion.js'

test('manual saved version is not presented as successful AI generation', () => {
  const label = articleVersionLabel({ id: 19, version_no: 2, generation_meta: { source: 'manual_edit', from_version: 1 } })
  assert.equal(label, 'V2 · 手动保存 · 文章 #19 · 基于 V1')
  assert.equal(articleVersionLabel({ id: 18, version_no: 1, generation_meta: { source: 'ai' } }), 'V1 · AI 生成 · 文章 #18')
  assert.match(articleVersionLabel({ id: 1, version_no: 1 }), /来源未记录/)
  assert.equal(articleVersionLabel(null), '尚无保存版本')
})
