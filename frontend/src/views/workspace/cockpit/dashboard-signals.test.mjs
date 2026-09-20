import test from 'node:test'
import assert from 'node:assert/strict'
import { dashboardChannels, dashboardHighlights } from './dashboard-signals.mjs'
const modules = [{ module_code: 'sem' }, { module_code: 'geo' }]
const trend = { type: 'trend', state: 'available', points: [{ key: '2026-09-01', label: '09-01', value: null, display: '缺报' }], coverage: { label: '缺报' } }
const card = { id: 'cost', moduleCode: 'sem', label: '推广花费', display: '12', state: 'partial', contextRevision: 3, visualization: trend }
test('only current authorized channel and revision enter dashboard', () => {
 const channels = dashboardChannels([card, { ...card, id: 'stale', contextRevision: 2 }, { ...card, id: 'seo', moduleCode: 'seo' }], modules, 3)
 assert.deepEqual(channels[0].metrics.map(c => c.id), ['cost'])
 assert.equal(channels[1].metrics.length, 0)
})
test('preserve missing samples and never invent historical points from snapshots', () => {
 const channels = dashboardChannels([card, { ...card, id: 'geo', moduleCode: 'geo', visualization: undefined }], modules, 3)
 assert.equal(channels[0].charts[0].visualization.points[0].value, null)
 assert.equal(channels[1].charts.length, 0)
})
test('denied and invalid visuals are not rendered', () => {
 for (const change of [{ state: 'denied' }, { visualization: { ...trend, points: [{ key: 'bad', value: '42' }] } }]) {
  assert.equal(dashboardChannels([{ ...card, ...change }], modules, 3)[0].charts.length, 0)
 }
})
test('headline metrics retain original labels and do not duplicate data', () => {
 const channels = dashboardChannels([card], modules, 3)
 assert.deepEqual(dashboardHighlights(channels).map(c => [c.id, c.label]), [['cost', '推广花费']])
})
