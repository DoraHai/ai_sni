const METRIC_LABELS = Object.freeze({
  'geo.visibility.ai_mention_count_7d': 'AI 回答提及',
  'geo.visibility.ai_mention_rate_7d': 'AI 回答提及率',
  'geo.visibility.ai_visibility_score': 'AI 可见度',
})

export function completedWeekEnd(value) {
  const date = new Date(`${value}T00:00:00Z`)
  if (!Number.isFinite(date.valueOf())) return null
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7))
  return date.toISOString().slice(0, 10)
}

export function completedWeekPeriodLabel(week = {}) {
  const start = week.start?.slice(0, 10) || '未知'
  const exclusiveEnd = week.end?.slice(0, 10) || week.weekEnd
  if (!exclusiveEnd) return `${start} 至 未知（完整周）`
  const date = new Date(`${exclusiveEnd}T00:00:00Z`)
  if (!Number.isFinite(date.valueOf())) return `${start} 至 未知（完整周）`
  date.setUTCDate(date.getUTCDate() - 1)
  return `${start} 至 ${date.toISOString().slice(0, 10)}（完整周）`
}

export function geoSummaryCards({ snapshot, contextRevision }) {
  const week = snapshot?.week || {}
  const periodLabel = completedWeekPeriodLabel(week)
  const metrics = (snapshot?.metrics || []).filter(metric => Object.hasOwn(METRIC_LABELS, metric.metricKey)).map(metric => {
    const reasons = metric.reasons?.map(item => item.message).filter(Boolean) || []
    const trendReasons = metric.trend?.reasons?.map(item => item.message).filter(Boolean) || []
    return {
      id: `geo-${metric.metricKey}`, moduleCode: 'geo', moduleLabel: 'GEO', label: METRIC_LABELS[metric.metricKey],
      display: metric.valueText, unit: metric.unitLabel || '', state: metric.state === 'available' ? 'available' : 'unavailable',
      reason: reasons[0] || metric.definition || '正式周指标当前没有足够依据。', contextRevision,
      periodLabel,
      sourceLabel: 'GEO 已核验完整周指标', updatedLabel: metric.asOf || '未知', series: [],
      columns: [{ key: 'value', label: '本周' }, { key: 'trend', label: '与前一周比较' }, { key: 'basis', label: '依据' }],
      rows: [{
        value: `${metric.valueText}${metric.unitLabel || ''}`,
        trend: metric.trend?.state === 'available' ? (metric.trend.changePctText || metric.trend.changeAbsText || '持平') : '暂不可比较',
        basis: reasons[0] || trendReasons[0] || metric.definition || '正式周口径',
      }],
    }
  })
  const qualifications = [
    ['samples', '本周合格回答', '条', '进入正式指标口径的回答数量'],
    ['questions', '本周有效问题', '个', '进入正式指标口径的问题数量'],
    ['engines', '本周覆盖引擎', '个', '进入正式指标口径的 AI 引擎数量'],
  ].map(([key, label, unit, definition]) => {
    const value = week.qualifiedCounts?.[key]
    const available = Number.isSafeInteger(value) && value >= 0
    const reason = week.reasons?.[0]?.message || definition
    return {
      id: `geo-qualified-${key}`, moduleCode: 'geo', moduleLabel: 'GEO', label,
      display: available ? new Intl.NumberFormat('zh-CN').format(value) : '—', unit, state: available ? 'available' : 'unavailable',
      reason, contextRevision, periodLabel,
      sourceLabel: 'GEO 正式周准入统计', updatedLabel: week.weekEnd || '未知', series: [],
      columns: [{ key: 'value', label: '本周' }, { key: 'basis', label: '说明' }],
      rows: [{ value: available ? `${value}${unit}` : '暂无可靠数字', basis: reason }],
    }
  })
  return [...metrics, ...qualifications]
}
