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

export function geoSummaryCards({ snapshot, contextRevision }) {
  const week = snapshot?.week || {}
  return (snapshot?.metrics || []).filter(metric => Object.hasOwn(METRIC_LABELS, metric.metricKey)).map(metric => {
    const reasons = metric.reasons?.map(item => item.message).filter(Boolean) || []
    const trendReasons = metric.trend?.reasons?.map(item => item.message).filter(Boolean) || []
    return {
      id: `geo-${metric.metricKey}`, moduleCode: 'geo', moduleLabel: 'GEO', label: METRIC_LABELS[metric.metricKey],
      display: metric.valueText, unit: metric.unitLabel || '', state: metric.state === 'available' ? 'available' : 'unavailable',
      reason: reasons[0] || metric.definition || '正式周指标当前没有足够依据。', contextRevision,
      periodLabel: `${week.start?.slice(0, 10) || '未知'} 至 ${week.end?.slice(0, 10) || week.weekEnd || '未知'}（完整周）`,
      sourceLabel: 'GEO 已核验完整周指标', updatedLabel: metric.asOf || '未知', series: [],
      columns: [{ key: 'value', label: '本周' }, { key: 'trend', label: '与前一周比较' }, { key: 'basis', label: '依据' }],
      rows: [{
        value: `${metric.valueText}${metric.unitLabel || ''}`,
        trend: metric.trend?.state === 'available' ? (metric.trend.changePctText || metric.trend.changeAbsText || '持平') : '暂不可比较',
        basis: reasons[0] || trendReasons[0] || metric.definition || '正式周口径',
      }],
    }
  })
}
