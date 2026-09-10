import assert from 'node:assert/strict'
import test from 'node:test'
import { buildPanoramaSummary } from './panorama-summary.mjs'

test('builds truthful outcome and attention summaries without inventing cards', () => {
  const cards = [
    { id: 'sem-click', moduleCode: 'sem', state: 'available', summaryRole: 'outcome', urgentCount: 0 },
    { id: 'seo-contents', moduleCode: 'seo', state: 'available', summaryRole: 'outcome', urgentCount: 0 },
    { id: 'sem-cost', moduleCode: 'sem', state: 'available', urgentCount: 0 },
    { id: 'geo-qualified-samples', moduleCode: 'geo', state: 'available', urgentCount: 0 },
    { id: 'seo-review', moduleCode: 'seo', state: 'available', urgentCount: 4 },
    { id: 'geo-missing', moduleCode: 'geo', state: 'no_data', urgentCount: 0 },
    { id: 'geo-partial', moduleCode: 'geo', state: 'partial', urgentCount: 0 },
  ]
  const model = buildPanoramaSummary(cards)

  assert.deepEqual(model.outcomes.map(card => card.id), ['sem-click', 'seo-contents'])
  assert.deepEqual(model.attention.map(card => card.id), ['seo-review', 'geo-missing', 'geo-partial'])
  assert.deepEqual(model.groups.map(group => group.cards.map(card => card.id)), [
    ['sem-click', 'sem-cost'], ['seo-contents', 'geo-qualified-samples', 'geo-partial'], ['seo-review', 'geo-missing'],
  ])
})

test('keeps missing and zero distinct and returns empty summaries for empty input', () => {
  assert.deepEqual(buildPanoramaSummary([]).outcomes, [])
  assert.deepEqual(buildPanoramaSummary([]).attention, [])
  const model = buildPanoramaSummary([
    { id: 'observed-zero', moduleCode: 'sem', state: 'available', summaryRole: 'outcome', display: '0', urgentCount: 0 },
    { id: 'missing', moduleCode: 'sem', state: 'no_data', summaryRole: 'outcome', display: '—', urgentCount: 0 },
  ])
  assert.equal(model.outcomes[0].id, 'observed-zero')
  assert.equal(model.attention[0].id, 'missing')
})

test('does not infer outcomes from availability for scope, spend, impressions or sample counts', () => {
  const model = buildPanoramaSummary([
    { id: 'sem-account-scope', moduleCode: 'sem', state: 'available' },
    { id: 'sem-cost', moduleCode: 'sem', state: 'available' },
    { id: 'sem-impression', moduleCode: 'sem', state: 'available' },
    { id: 'geo-qualified-samples', moduleCode: 'geo', state: 'available' },
    { id: 'geo-qualified-engines', moduleCode: 'geo', state: 'available' },
  ])
  assert.deepEqual(model.outcomes, [])
})
