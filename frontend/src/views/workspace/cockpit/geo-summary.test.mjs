import assert from 'node:assert/strict'
import test from 'node:test'
import { completedWeekEnd, completedWeekInclusiveEnd, completedWeekPeriodLabel, geoSummaryCards } from './geo-summary.mjs'

test('uses the latest completed Monday boundary without browser timezone inference', () => {
  assert.equal(completedWeekEnd('2026-09-07'), '2026-09-07')
  assert.equal(completedWeekEnd('2026-09-13'), '2026-09-07')
  assert.equal(completedWeekEnd('invalid'), null)
})

test('renders the inclusive dates of an exclusive complete-week boundary', () => {
  const week = { start: '2026-08-31T00:00:00+08:00', end: '2026-09-07T00:00:00+08:00', weekEnd: '2026-09-07' }
  assert.equal(completedWeekInclusiveEnd('2026-09-07'), '2026-09-06')
  assert.equal(completedWeekInclusiveEnd('invalid'), null)
  assert.equal(completedWeekPeriodLabel(week), '2026-08-31 至 2026-09-06（完整周）')
  assert.equal(completedWeekPeriodLabel({ start: week.start, weekEnd: week.weekEnd }), '2026-08-31 至 2026-09-06（完整周）')
})

test('keeps measured zero distinct from unavailable and excludes unlabeled competitor hashes', () => {
  const metric = (metricKey, valueText, state) => ({ metricKey, valueText, state, unitLabel: '次', asOf: '2026-09-07T00:00:00+08:00', definition: '正式定义', reasons: [], trend: { state: 'unavailable', reasons: [] } })
  const cards = geoSummaryCards({ contextRevision: 9, snapshot: {
    week: { start: '2026-08-31T00:00:00+08:00', end: '2026-09-07T00:00:00+08:00', weekEnd: '2026-09-07', qualifiedCounts: { samples: 8, questions: 3, engines: 2 }, reasons: [] },
    metrics: [metric('geo.visibility.ai_mention_count_7d', '0', 'available'), metric('geo.visibility.ai_visibility_score', '—', 'unavailable'), metric('geo.competitor.opaque_mention_count_7d', '3', 'available')],
  } })
  assert.equal(cards.length, 5)
  assert.deepEqual(cards.slice(0, 2).map(card => [card.label, card.display, card.state]), [['AI 回答提及', '0', 'available'], ['AI 可见度', '—', 'unavailable']])
  assert.deepEqual(cards.slice(2).map(card => [card.label, card.display]), [['本周合格回答', '8'], ['本周有效问题', '3'], ['本周覆盖引擎', '2']])
  assert.equal(cards[0].contextRevision, 9)
  assert.ok(cards.every(card => card.periodLabel === '2026-08-31 至 2026-09-06（完整周）'))
})
