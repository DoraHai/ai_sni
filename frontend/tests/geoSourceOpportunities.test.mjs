import test from 'node:test'
import assert from 'node:assert/strict'
import { opportunityExportRows } from '../src/utils/geoSourceOpportunities.js'

test('opportunity export preserves evidence mapping and neutralizes spreadsheet formulas', () => {
  const rows = opportunityExportRows([{
    question: '=1+1', priority: '补充采样', reason: '观察', next_action: '核验',
    evidence: [{ snapshot_id: 7, engine: '@bad', captured_at: '2026-09-05', mentions_brand: false, urls: ['https://example.test/a'] }],
  }])
  assert.equal(rows[0][0], "'=1+1")
  assert.equal(rows[0][4], '7')
  assert.equal(rows[0][5], "'@bad")
  assert.equal(rows[0][7], '否')
  assert.equal(rows[0][8], 'https://example.test/a')
  assert.deepEqual(opportunityExportRows([]), [])
})


import { citationHeatFromItems } from '../src/utils/geoSnapshotSummary.js'

test('citation heat uses actual engine counts and per-engine denominator', () => {
  const heat = citationHeatFromItems([
    { domain: 'a', cite_count: 4, engine_counts: { x: 3, y: 1 } },
    { domain: 'b', cite_count: 4, engine_counts: { x: 1, y: 3 } },
  ])
  assert.deepEqual(heat.engines, ['x', 'y'])
  assert.deepEqual(heat.rows[0].cells, [0.75, 0.25])
  assert.deepEqual(heat.rows[1].cells, [0.25, 0.75])
})

test('citation heat does not invent distribution for old payloads', () => {
  assert.deepEqual(citationHeatFromItems([{ domain: 'old', cite_count: 10, engines: ['x', 'y'] }]).engines, [])
})

test('citation heat denominator includes channels outside the top six', () => {
  const heat = citationHeatFromItems(Array.from({ length: 7 }, (_, i) => ({ domain: String(i), cite_count: 1, engine_counts: { x: 1 } })))
  assert.equal(heat.rows.length, 6)
  assert.equal(heat.rows[0].cells[0], 1 / 7)
})
