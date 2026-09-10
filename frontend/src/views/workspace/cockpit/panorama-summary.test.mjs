import assert from 'node:assert/strict'
import test from 'node:test'
import { buildPanoramaSummary } from './panorama-summary.mjs'

test('builds truthful outcome and attention summaries without inventing cards', () => {
  const cards = [
    { id: 'sem-cost', moduleCode: 'sem', state: 'available', urgentCount: 0 },
    { id: 'seo-content', moduleCode: 'seo', state: 'available', urgentCount: 0 },
    { id: 'seo-review', moduleCode: 'seo', state: 'available', urgentCount: 4 },
    { id: 'geo-missing', moduleCode: 'geo', state: 'no_data', urgentCount: 0 },
    { id: 'geo-partial', moduleCode: 'geo', state: 'partial', urgentCount: 0 },
  ]
  const model = buildPanoramaSummary(cards)

  assert.deepEqual(model.outcomes.map(card => card.id), ['sem-cost', 'seo-content'])
  assert.deepEqual(model.attention.map(card => card.id), ['seo-review', 'geo-missing', 'geo-partial'])
  assert.deepEqual(model.groups.map(group => group.cards.map(card => card.id)), [
    ['sem-cost'], ['seo-content', 'geo-partial'], ['seo-review', 'geo-missing'],
  ])
})

test('keeps missing and zero distinct and returns empty summaries for empty input', () => {
  assert.deepEqual(buildPanoramaSummary([]).outcomes, [])
  assert.deepEqual(buildPanoramaSummary([]).attention, [])
  const model = buildPanoramaSummary([
    { id: 'observed-zero', moduleCode: 'sem', state: 'available', display: '0', urgentCount: 0 },
    { id: 'missing', moduleCode: 'sem', state: 'no_data', display: '—', urgentCount: 0 },
  ])
  assert.equal(model.outcomes[0].id, 'observed-zero')
  assert.equal(model.attention[0].id, 'missing')
})
