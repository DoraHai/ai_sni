import test from 'node:test'
import assert from 'node:assert/strict'
import { SOURCE_LABELS, rateLabel, reportParams, safeFilename } from '../src/utils/geoReport.js'

test('report params keep project and business scopes distinct', () => {
  assert.deepEqual(reportParams({ from: '2026-10-01', to: '2026-10-31', projectId: '5', businessId: '9', granularity: 'week', provenance: 'real' }),
    { from: '2026-10-01', to: '2026-10-31', project_id: 5, business_id: 9, granularity: 'week', provenance: 'real' })
})
test('rate shows missing denominator and source labels remain separate', () => {
  assert.equal(rateLabel({ mentions: 0, samples: 0 }), '无数据')
  assert.equal(rateLabel({ mentions: 1, samples: 3 }), '33.3%')
  assert.equal(SOURCE_LABELS.manual, '人工录入')
  assert.equal(SOURCE_LABELS.simulated, '模拟/演示')
  assert.equal(safeFilename('2026-10-01', '2026-10-31', '报告'), 'GEO-报告-2026-10-01-2026-10-31.pdf')
})
