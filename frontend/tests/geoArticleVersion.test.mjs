import test from 'node:test'
import assert from 'node:assert/strict'
import { articleVersionLabel, latestGenerationFailure, mergeTaskJobLists } from '../src/utils/geoArticleVersion.js'

test('manual saved version is not presented as successful AI generation', () => {
  const label = articleVersionLabel({ id: 19, version_no: 2, generation_meta: { source: 'manual_edit', from_version: 1 } })
  assert.equal(label, 'V2 · 手动保存 · 文章 #19 · 基于 V1')
  assert.equal(articleVersionLabel({ id: 18, version_no: 1, generation_meta: { source: 'ai' } }), 'V1 · AI 生成 · 文章 #18')
  assert.match(articleVersionLabel({ id: 1, version_no: 1 }), /来源未记录/)
  assert.equal(articleVersionLabel(null), '尚无保存版本')
})

test('a later failed generation is distinguished from the historical article on screen', () => {
  const article = {
    id: 19,
    version_no: 2,
    created_at: '2026-09-06T14:12:47Z',
    generation_meta: { source: 'manual_edit', from_version: 1 },
  }
  const notice = latestGenerationFailure(article, [
    { id: 6, kind: 'generate_article', status: 'failed', finished_at: '2026-09-07T00:57:21Z', error: '跨语言证据待核验' },
  ])
  assert.equal(notice.title, '最新生成任务 #6 失败，当前显示历史稿')
  assert.equal(notice.articleLabel, 'V2 · 手动保存 · 文章 #19 · 基于 V1')
  assert.match(notice.articleTime, /2026\/09\/06 22:12/)
  assert.match(notice.failedAt, /2026\/09\/07 08:57/)
  assert.equal(notice.detail, '跨语言证据待核验')
})

test('old failures do not shadow a newer saved article', () => {
  const article = { id: 20, version_no: 3, created_at: '2026-09-08T00:00:00Z' }
  assert.equal(latestGenerationFailure(article, [
    { id: 6, kind: 'generate_article', status: 'failed', finished_at: '2026-09-07T00:57:21Z' },
  ]), null)
})

test('a filtered generation result survives more than twenty newer channel jobs', () => {
  const generation = { id: 6, kind: 'generate_article', status: 'failed' }
  const channelJobs = Array.from({ length: 25 }, (_, index) => ({
    id: 7 + index,
    kind: 'create_variants',
    status: 'succeeded',
  }))
  const rows = mergeTaskJobLists([generation], channelJobs)
  assert.equal(rows.length, 26)
  assert.equal(rows.find((job) => job.kind === 'generate_article'), generation)
})
