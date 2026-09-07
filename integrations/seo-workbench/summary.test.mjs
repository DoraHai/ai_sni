import assert from 'node:assert/strict'
import test from 'node:test'
import { seoSummaryCards } from './summary.mjs'

test('builds separate content and page evidence without inferred clicks', () => {
  const cards = seoSummaryCards({
    contents: { total: 8, status_counts: { review: 2, ready: 1, published: 5 } },
    pages: { stats: { total: 12, healthy: 7, needs_fix: 3, unchecked: 2 } },
    contextRevision: 9,
  })
  assert.deepEqual(cards.map(item => [item.id, item.display]), [
    ['seo-contents', '8'], ['seo-review', '3'], ['seo-pages', '12'], ['seo-page-issues', '3'],
    ['seo-article-clicks', '—'],
  ])
  assert.equal(cards.at(-1).state, 'unavailable')
  assert.equal(cards.reduce((sum, item) => sum + item.urgentCount, 0), 6)
  assert.match(cards.at(-1).reason, /不能从网站总点击或关键词推算/)
  assert.ok(cards.every(item => item.moduleCode === 'seo' && item.contextRevision === 9))
})

test('keeps verified zero distinct from unavailable', () => {
  const cards = seoSummaryCards({
    contents: { total: 0, status_counts: {} },
    pages: { stats: { total: 0, healthy: 0, needs_fix: 0, unchecked: 0 } },
    contextRevision: 1,
  })
  assert.equal(cards.find(item => item.id === 'seo-contents').state, 'available')
  assert.equal(cards.find(item => item.id === 'seo-page-issues').display, '0')
  assert.equal(cards.find(item => item.id === 'seo-article-clicks').state, 'unavailable')
  assert.equal(cards.reduce((sum, item) => sum + item.urgentCount, 0), 0)
})
