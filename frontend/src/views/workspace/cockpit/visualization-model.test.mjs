import assert from 'node:assert/strict'
import test from 'node:test'
import { semImpressionClickFunnel, semTrendVisualization, seoContentDistribution, validVisualization, visualizationBarPercent, visualizationIndexAfterKey, visualizationIndexFromPointer } from './visualization-model.mjs'

const report = {
  metrics: { impression: 100, click: 5, ctr: 0.05 },
  coverage: { status: 'observed', missing_dates: ['2026-09-02'] },
  trend: [
    { date: '2026-09-01', status: 'observed', impression: 80 },
    { date: '2026-09-02', status: 'no_data', impression: null },
    { date: '2026-09-03', status: 'observed', impression: 20 },
  ],
}

test('SEM trend preserves missing reports as null breakpoints with coverage copy', () => {
  const view = semTrendVisualization(report, 'impression', row => String(row.impression))
  assert.equal(view.type, 'trend')
  assert.deepEqual(view.points.map(point => point.value), [80, null, 20])
  assert.equal(view.points[1].display, '缺报')
  assert.deepEqual(view.coverage, { state: 'partial', missingCount: 1, label: '缺少 1 天报告，折线在缺口处断开' })
})

test('SEM funnel has only impression and click and withholds rate for missing coverage', () => {
  const partial = semImpressionClickFunnel(report, '已观测小计 100', '已观测小计 5')
  assert.deepEqual(partial.stages, [])
  assert.equal(partial.rate, null)
  assert.match(partial.rateLabel, /缺报.*暂不展示.*不计算/)
  const covered = semImpressionClickFunnel({ ...report, coverage: { status: 'observed', missing_dates: [] } }, '100', '5')
  assert.deepEqual(covered.stages.map(stage => [stage.key, stage.metricId]), [['impression', 'sem-impression'], ['click', 'sem-click']])
  assert.equal(covered.rate, 0.05)
  assert.equal(covered.rateLabel, '曝光到点击 5%')
  const zero = semImpressionClickFunnel({ ...report, metrics: { impression: 0, click: 0, ctr: null }, coverage: { status: 'observed', missing_dates: [] } }, '0', '0')
  assert.equal(zero.rate, null)
  assert.match(zero.rateLabel, /曝光为 0.*暂不计算/)
})

test('SEM funnel fails closed when click exceeds impression or CTR disagrees', () => {
  const coverage = { status: 'observed', missing_dates: [] }
  const impossible = semImpressionClickFunnel({ ...report, metrics: { impression: 10, click: 11, ctr: 1 }, coverage }, '10', '11')
  assert.equal(impossible.state, 'unavailable')
  assert.deepEqual(impossible.stages, [])
  assert.equal(impossible.rate, null)
  assert.match(impossible.rateLabel, /数据关系无法核验/)
  const inconsistent = semImpressionClickFunnel({ ...report, metrics: { impression: 100, click: 5, ctr: 0.06 }, coverage }, '100', '5')
  assert.equal(inconsistent.state, 'unavailable')
  assert.match(inconsistent.rateLabel, /数据关系无法核验/)
})

test('SEO distribution validates totals, keeps fixed statuses first and preserves unknown statuses', () => {
  const view = seoContentDistribution({ total: 8, status_counts: { planned: 2, review: 1, published: 4, paused: 1 } })
  assert.deepEqual(view.items.map(item => item.key), ['planned', 'drafting', 'review', 'ready', 'published', 'archived', 'paused'])
  assert.equal(view.items.find(item => item.key === 'planned').value, 2)
  assert.equal(view.items.find(item => item.key === 'drafting').value, 0)
  assert.equal(view.items.find(item => item.key === 'paused').value, 1)
  assert.match(view.note, /当前内容状态分布.*库存.*不代表转化率或处理耗时/)
  const invalid = seoContentDistribution({ total: 9, status_counts: { planned: 2 } })
  assert.equal(invalid.state, 'unavailable')
  assert.deepEqual(invalid.items, [])
})

test('visualization discriminator rejects unknown and malformed payloads', () => {
  assert.equal(validVisualization({ type: 'pie', state: 'available', items: [] }), false)
  assert.equal(validVisualization({ type: 'funnel', state: 'available', stages: [{ key: 'lead', value: 1 }], rate: 1 }), false)
  assert.equal(validVisualization(semImpressionClickFunnel({ ...report, coverage: { status: 'observed', missing_dates: [] } }, '100', '5')), true)
  assert.equal(validVisualization(seoContentDistribution({ total: 1, status_counts: { review: 1 } })), true)
})

test('single-entry visualization keyboard navigation stays within its items', () => {
  assert.equal(visualizationIndexAfterKey(2, 6, 'Home'), 0)
  assert.equal(visualizationIndexAfterKey(2, 6, 'End'), 5)
  assert.equal(visualizationIndexAfterKey(0, 6, 'ArrowLeft'), 0)
  assert.equal(visualizationIndexAfterKey(5, 6, 'ArrowRight'), 5)
  assert.equal(visualizationIndexAfterKey(2, 6, 'ArrowDown'), 3)
})

test('whole-chart pointer scrub selects the nearest point without per-point targets', () => {
  assert.equal(visualizationIndexFromPointer(100, 100, 365, 366), 0)
  assert.equal(visualizationIndexFromPointer(465, 100, 365, 366), 365)
  assert.equal(visualizationIndexFromPointer(282.4, 100, 365, 366), 182)
  assert.equal(visualizationIndexFromPointer(10, 100, 365, 366), 0)
  assert.equal(visualizationIndexFromPointer(200, 100, 0, 366), -1)
})

test('bars keep verified zero at exactly zero width', () => {
  assert.equal(visualizationBarPercent(0, 10, 4), 0)
  assert.equal(visualizationBarPercent(0.1, 10, 4), 4)
  assert.equal(visualizationBarPercent(10, 10, 4), 100)
})
