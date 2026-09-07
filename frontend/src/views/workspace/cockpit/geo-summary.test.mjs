import assert from 'node:assert/strict'
import test from 'node:test'
import { completedWeekEnd, geoSummaryCards } from './geo-summary.mjs'

test('uses the latest completed Monday boundary without browser timezone inference', () => {
  assert.equal(completedWeekEnd('2026-09-07'), '2026-09-07')
  assert.equal(completedWeekEnd('2026-09-13'), '2026-09-07')
  assert.equal(completedWeekEnd('invalid'), null)
})

test('keeps measured zero distinct from unavailable and excludes unlabeled competitor hashes', () => {
  const metric = (metricKey, valueText, state) => ({ metricKey, valueText, state, unitLabel: '次', asOf: '2026-09-07T00:00:00+08:00', definition: '正式定义', reasons: [], trend: { state: 'unavailable', reasons: [] } })
  const cards = geoSummaryCards({ contextRevision: 9, snapshot: {
    week: { start: '2026-08-31T00:00:00+08:00', end: '2026-09-07T00:00:00+08:00' },
    metrics: [metric('geo.visibility.ai_mention_count_7d', '0', 'available'), metric('geo.visibility.ai_visibility_score', '—', 'unavailable'), metric('geo.competitor.opaque_mention_count_7d', '3', 'available')],
  } })
  assert.equal(cards.length, 2)
  assert.deepEqual(cards.map(card => [card.label, card.display, card.state]), [['AI 回答提及', '0', 'available'], ['AI 可见度', '—', 'unavailable']])
  assert.equal(cards[0].contextRevision, 9)
})
