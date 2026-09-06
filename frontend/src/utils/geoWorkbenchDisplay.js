/**
 * Pure display adapters for the GEO cockpit/workbench read model.
 *
 * These helpers only map fields returned by /geo/integration. They never
 * derive an official metric from answer rows and never change stored state.
 */

const SOURCE_LABELS = {
  real: '真实回答',
  simulated: '模拟回答',
  manual: '人工记录',
  unknown: '来源未知',
}

const STATUS_LABELS = {
  pending: '等待处理',
  running: '处理中',
  succeeded: '已完成',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const REASON_LABELS = {
  simulated_sample: '模拟回答不进入正式指标',
  manual_sample: '人工记录不进入正式指标',
  unknown_source: '来源未知',
  unsupported_sampling_method: '不是无品牌诱导的 v2 采样',
  analysis_incomplete: '回答判读尚未完成',
  citation_inaccurate: '引用已标记不准确',
  brand_probe: '品牌点名问题不进入正式指标',
  missing_server_evidence: '缺少同租户服务端巡检证据',
  patrol_not_completed: '关联巡检尚未完成',
  capture_outside_patrol: '采样时间不在巡检起止范围内',
  snapshot_patrol_mismatch: '回答与服务端巡检原始结果不一致',
  outside_selected_week: '回答不在所选正式完整周',
  insufficient_samples: '合格回答少于正式指标门槛',
  insufficient_questions: '有效问题少于正式指标门槛',
  insufficient_engines: '有效引擎少于正式指标门槛',
  missing_own_domain: '未配置启用的官网或文档域名',
  current_week_insufficient: '本周合格样本不足',
  previous_week_insufficient: '前一周合格样本不足',
  cohort_changed: '前后周问题与引擎组合不一致',
  question_changed: '前后周历史问题文本不一致',
  model_metadata_missing: '模型或供应商历史信息不完整',
  model_distribution_changed: '前后周模型分布不一致',
  sample_distribution_changed: '前后周样本分布不一致',
}

function normalizedReasons(reasons = [], scope = null) {
  return (Array.isArray(reasons) ? reasons : []).map((item) => {
    const row = typeof item === 'string' ? { code: item } : (item || {})
    return {
      code: row.code || 'unknown',
      scope: row.scope || scope,
      message: row.message || REASON_LABELS[row.code] || row.code || '原因未知',
    }
  })
}

export function answerSourceDisplay(answer) {
  const source = answer?.source || {}
  const kind = Object.prototype.hasOwnProperty.call(SOURCE_LABELS, source.kind)
    ? source.kind
    : 'unknown'
  return {
    kind,
    label: SOURCE_LABELS[kind],
    simulated: kind === 'simulated',
    verifiedServerRecord: source.verified_server_record === true,
    storedSampleMode: source.stored_sample_mode || null,
    samplingMethod: source.sampling_method || null,
  }
}

export function answerMetricDisplay(answer, metricKey) {
  const rows = Array.isArray(answer?.metric_adoption) ? answer.metric_adoption : []
  const adoption = rows.find((row) => row?.metric_key === metricKey)
  if (!adoption) {
    return {
      status: 'unknown',
      label: '正式指标状态未知',
      countsTowardOfficial: false,
      reasons: [],
    }
  }
  const labels = {
    included: '计入正式指标',
    excluded: '单条样本已排除',
    unavailable: '单条合格，整周暂不出数',
  }
  return {
    status: adoption.status,
    label: labels[adoption.status] || '正式指标状态未知',
    countsTowardOfficial: adoption.status === 'included',
    reasons: normalizedReasons(adoption.reasons),
  }
}

function metricReasons(metric, periodContext) {
  const status = (periodContext?.metric_status || []).find(
    (row) => row?.metric_key === metric?.metric_key,
  )
  if (!status) return []
  const windowReasons = [
    ...(periodContext?.current?.reasons || []),
    ...(status.reason_codes || []),
  ]
  const unique = new Map()
  for (const reason of normalizedReasons(windowReasons, 'week')) {
    if (!unique.has(reason.code)) unique.set(reason.code, reason)
  }
  return [...unique.values()]
}

export function officialMetricDisplay(metric, periodContext = null, definition = null) {
  const hasValue = typeof metric?.value === 'number' && Number.isFinite(metric.value)
  const trend = metric?.trend_7d
  const comparable = periodContext?.comparison?.comparable
  const trendState = comparable === false
    ? 'incomparable'
    : trend == null ? 'unavailable' : 'available'
  const trendReasons = comparable === false
    ? normalizedReasons(periodContext?.comparison?.reason_codes, 'comparison')
    : []
  const showTrend = trendState === 'available'
  const direction = showTrend && ['up', 'down', 'flat'].includes(trend?.direction)
    ? trend.direction
    : null
  return {
    metricKey: metric?.metric_key || null,
    value: hasValue ? metric.value : null,
    valueText: hasValue ? String(metric.value) : '—',
    unit: metric?.unit || null,
    asOf: metric?.as_of || null,
    state: hasValue ? 'available' : 'unavailable',
    reasons: hasValue ? [] : metricReasons(metric, periodContext),
    definition: definition || null,
    trend: {
      state: trendState,
      direction,
      changePct: showTrend && Number.isFinite(trend?.change_pct) ? trend.change_pct : null,
      changeAbs: showTrend && Number.isFinite(trend?.change_abs) ? trend.change_abs : null,
      reasons: trendReasons,
    },
  }
}

export function officialWeekDisplay(periodContext) {
  const current = periodContext?.current || {}
  return {
    timezone: periodContext?.timezone || null,
    weekEnd: periodContext?.week_end || null,
    start: current.start || null,
    end: current.end || null,
    endExclusive: true,
    closed: current.closed === true,
    status: current.status || 'unknown',
    qualifiedCounts: current.qualified_counts || null,
    reasons: normalizedReasons(current.reasons, 'week'),
  }
}

export function progressDisplay(row, subject = '后台任务') {
  const storedStatus = row?.stored_status || row?.status || 'unknown'
  const stale = row?.stale === true && ['pending', 'running'].includes(storedStatus)
  return {
    storedStatus,
    label: STATUS_LABELS[storedStatus] || storedStatus,
    stale,
    staleReason: stale ? (row?.stale_reason || 'elapsed_threshold_exceeded') : null,
    hint: stale ? `${subject}疑似超时，仍保留状态“${STATUS_LABELS[storedStatus] || storedStatus}”，等待后台恢复确认` : '',
    progressPct: typeof row?.progress_pct === 'number' ? row.progress_pct : null,
    progressLabel: row?.progress_label || null,
    error: row?.error || null,
  }
}
