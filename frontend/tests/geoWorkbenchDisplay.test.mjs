import assert from 'node:assert/strict'
import test from 'node:test'

import {
  answerMetricDisplay,
  answerSourceDisplay,
  officialMetricDisplay,
  officialWeekDisplay,
  progressDisplay,
} from '../src/utils/geoWorkbenchDisplay.js'

const metricKey = 'geo.visibility.ai_mention_count_7d'

test('answer sources stay distinct and unknown values fail closed', () => {
  const cases = [
    [{ source: { kind: 'real', verified_server_record: true } }, 'real', '真实回答'],
    [{ source: { kind: 'simulated', simulated: true } }, 'simulated', '模拟回答'],
    [{ source: { kind: 'manual' } }, 'manual', '人工记录'],
    [{ source: { kind: 'vendor_future_mode' } }, 'unknown', '来源未知'],
    [{}, 'unknown', '来源未知'],
  ]
  for (const [row, kind, label] of cases) {
    const result = answerSourceDisplay(row)
    assert.equal(result.kind, kind)
    assert.equal(result.label, label)
  }
  assert.equal(answerSourceDisplay(cases[0][0]).verifiedServerRecord, true)
})

test('single-sample exclusion and whole-week insufficiency remain separate', () => {
  const simulated = {
    metric_adoption: [{
      metric_key: metricKey,
      status: 'excluded',
      reasons: [{ code: 'simulated_sample', scope: 'sample', message: '模拟回答不进入正式指标' }],
    }],
  }
  const realButInsufficient = {
    metric_adoption: [{
      metric_key: metricKey,
      status: 'unavailable',
      reasons: [{ code: 'insufficient_samples', scope: 'week', message: '整周样本不足' }],
    }],
  }
  assert.deepEqual(answerMetricDisplay(simulated, metricKey), {
    status: 'excluded',
    label: '单条样本已排除',
    countsTowardOfficial: false,
    reasons: [{ code: 'simulated_sample', scope: 'sample', message: '模拟回答不进入正式指标' }],
  })
  assert.equal(answerMetricDisplay(realButInsufficient, metricKey).status, 'unavailable')
  assert.equal(answerMetricDisplay(realButInsufficient, metricKey).reasons[0].scope, 'week')
})

test('official null is unavailable while a measured zero remains zero', () => {
  const context = {
    current: {
      reasons: [{ code: 'insufficient_samples', scope: 'week', message: '本周样本不足' }],
    },
    metric_status: [{ metric_key: metricKey, status: 'unavailable', reason_codes: ['insufficient_samples'] }],
    comparison: { comparable: false, reason_codes: ['previous_week_insufficient'] },
  }
  const missing = officialMetricDisplay(
    { metric_key: metricKey, value: null, unit: 'count', as_of: '2026-08-31T00:00:00+08:00', trend_7d: null },
    context,
  )
  assert.equal(missing.valueText, '—')
  assert.equal(missing.state, 'unavailable')
  assert.equal(missing.reasons[0].code, 'insufficient_samples')
  assert.equal(missing.trend.state, 'incomparable')
  assert.equal(missing.trend.reasons[0].code, 'previous_week_insufficient')

  const zero = officialMetricDisplay(
    { metric_key: metricKey, value: 0, unit: 'count', as_of: '2026-08-31T00:00:00+08:00', trend_7d: { direction: 'flat', change_pct: null, change_abs: 0 } },
    { comparison: { comparable: true } },
  )
  assert.equal(zero.valueText, '0')
  assert.equal(zero.state, 'available')
  assert.deepEqual(zero.trend, {
    state: 'available', direction: 'flat', changePct: null, changeAbs: 0, reasons: [],
  })
})

test('explicitly incomparable context suppresses contradictory or non-finite trend values', () => {
  const contradictory = officialMetricDisplay(
    {
      metric_key: metricKey,
      value: 12,
      unit: 'count',
      as_of: '2026-08-31T00:00:00+08:00',
      trend_7d: { direction: 'up', change_pct: 20, change_abs: 2 },
    },
    { comparison: { comparable: false, reason_codes: ['model_distribution_changed'] } },
  )
  assert.deepEqual(contradictory.trend, {
    state: 'incomparable',
    direction: null,
    changePct: null,
    changeAbs: null,
    reasons: [{
      code: 'model_distribution_changed',
      scope: 'comparison',
      message: '前后周模型分布不一致',
    }],
  })

  const invalidNumbers = officialMetricDisplay(
    {
      metric_key: metricKey,
      value: 12,
      unit: 'count',
      as_of: '2026-08-31T00:00:00+08:00',
      trend_7d: { direction: 'up', change_pct: Number.NaN, change_abs: Number.POSITIVE_INFINITY },
    },
    { comparison: { comparable: true, reason_codes: [] } },
  )
  assert.equal(invalidNumbers.trend.state, 'available')
  assert.equal(invalidNumbers.trend.direction, 'up')
  assert.equal(invalidNumbers.trend.changePct, null)
  assert.equal(invalidNumbers.trend.changeAbs, null)
})

test('missing trend keeps supplied comparison reasons when comparability is unspecified', () => {
  const result = officialMetricDisplay(
    {
      metric_key: metricKey,
      value: 12,
      unit: 'count',
      as_of: '2026-08-31T00:00:00+08:00',
      trend_7d: null,
    },
    { comparison: { reason_codes: ['model_metadata_missing'] } },
  )
  assert.deepEqual(result.trend, {
    state: 'unavailable',
    direction: null,
    changePct: null,
    changeAbs: null,
    reasons: [{
      code: 'model_metadata_missing',
      scope: 'comparison',
      message: '模型或供应商历史信息不完整',
    }],
  })
})

test('official week uses server boundaries and explicit timezone unchanged', () => {
  const result = officialWeekDisplay({
    timezone: 'Asia/Shanghai',
    week_end: '2026-08-31',
    current: {
      start: '2026-08-24T00:00:00+08:00',
      end: '2026-08-31T00:00:00+08:00',
      closed: true,
      status: 'ready',
      qualified_counts: { samples: 8, questions: 3, engines: 2 },
      reasons: [],
    },
  })
  assert.equal(result.start, '2026-08-24T00:00:00+08:00')
  assert.equal(result.end, '2026-08-31T00:00:00+08:00')
  assert.equal(result.timezone, 'Asia/Shanghai')
  assert.equal(result.endExclusive, true)
  assert.equal(result.closed, true)
})

test('stale observation preserves stored status instead of inventing failure', () => {
  const result = progressDisplay({
    stored_status: 'running',
    stale: true,
    stale_reason: 'elapsed_threshold_exceeded',
    progress_pct: 45,
    progress_label: '生成中',
    error: null,
  }, '异步生成')
  assert.equal(result.storedStatus, 'running')
  assert.equal(result.label, '处理中')
  assert.equal(result.stale, true)
  assert.match(result.hint, /保留状态“处理中”/)
  assert.notEqual(result.label, '失败')
})
