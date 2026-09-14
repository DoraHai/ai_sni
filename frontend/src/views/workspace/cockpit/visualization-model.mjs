const finite = value => typeof value === 'number' && Number.isFinite(value) && value >= 0
const integer = value => Number.isSafeInteger(value) && value >= 0
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)

export function semTrendVisualization(report, key, formatValue) {
  if (!record(report) || !Array.isArray(report.trend) || !record(report.coverage) || !Array.isArray(report.coverage.missing_dates)) {
    return { type: 'trend', state: 'unavailable', points: [], coverage: { state: 'unavailable', missingCount: null, label: '趋势覆盖信息无效，暂不展示' } }
  }
  const missing = new Set(report.coverage.missing_dates)
  const points = report.trend.map(row => {
    const missingReport = row?.status === 'no_data' || missing.has(row?.date)
    const observed = !missingReport && row?.status === 'observed' && finite(row[key])
    return { key: String(row?.date || ''), label: row?.date?.slice(5) || '未知日期', value: observed ? row[key] : null, display: observed ? String(formatValue(row)) : (missingReport ? '缺报' : '当日不可计算') }
  })
  const missingCount = missing.size
  return {
    type: 'trend', state: 'available', points,
    coverage: {
      state: missingCount ? 'partial' : 'covered', missingCount,
      label: missingCount ? `缺少 ${missingCount} 天报告，折线在缺口处断开` : '所选日期未发现缺报；上游完整性仍未知',
    },
  }
}

export function semImpressionClickFunnel(report, formatImpression, formatClick) {
  const coverage = report?.coverage
  const impression = report?.metrics?.impression
  const click = report?.metrics?.click
  const ctr = report?.metrics?.ctr
  const covered = coverage?.status === 'observed' && Array.isArray(coverage.missing_dates) && coverage.missing_dates.length === 0
  const metricsValid = integer(impression) && integer(click)
  const relationshipValid = metricsValid && click <= impression
  const expectedRate = relationshipValid && impression > 0 ? click / impression : null
  const ctrValid = relationshipValid && (impression === 0
    ? ctr === null
    : finite(ctr) && ctr <= 1 && Math.abs(ctr - expectedRate) <= 0.000001)
  if (!covered || !metricsValid || !relationshipValid || !ctrValid) {
    const rateLabel = !covered ? '存在缺报，漏斗暂不展示且不计算点击率'
      : !metricsValid ? '曝光或点击数据无效，漏斗暂不展示且不计算点击率'
        : '曝光、点击与点击率的数据关系无法核验，漏斗暂不展示且不计算点击率'
    return {
      type: 'funnel', state: 'unavailable', stages: [], rate: null,
      rateLabel,
      coverage: { state: 'partial', missingCount: Array.isArray(coverage?.missing_dates) ? coverage.missing_dates.length : null, label: '仅在所选日期无缺报时展示曝光到点击' },
    }
  }
  const rate = impression > 0 ? ctr : null
  return {
    type: 'funnel', state: 'available', stages: [
      { key: 'impression', metricId: 'sem-impression', label: '曝光', value: impression, display: String(formatImpression) },
      { key: 'click', metricId: 'sem-click', label: '点击', value: click, display: String(formatClick) },
    ],
    rate,
    rateLabel: rate === null ? '曝光为 0，暂不计算点击率' : `曝光到点击 ${new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 2 }).format(rate)}`,
    coverage: { state: 'covered', missingCount: 0, label: '所选日期未发现缺报；上游完整性仍未知' },
  }
}

const seoStatuses = [
  ['planned', '待开始'], ['drafting', '撰写中'], ['review', '审核中'],
  ['ready', '已审核待发布'], ['published', '已发布'], ['archived', '已归档'],
]

export function seoContentDistribution(contents) {
  const total = contents?.total
  const counts = contents?.status_counts
  const entries = record(counts) ? Object.entries(counts) : []
  const valid = integer(total) && entries.every(([key, value]) => key.length > 0 && integer(value))
    && entries.reduce((sum, [, value]) => sum + value, 0) === total
  if (!valid) return { type: 'distribution', state: 'unavailable', items: [], note: '内容状态计数与总数无法对账，当前内容状态分布暂不展示。' }
  const known = new Set(seoStatuses.map(([key]) => key))
  const ordered = [...seoStatuses, ...entries.filter(([key]) => !known.has(key)).sort(([a], [b]) => a.localeCompare(b, 'zh-CN')).map(([key]) => [key, key])]
  return {
    type: 'distribution', state: 'available',
    items: ordered.map(([key, label]) => ({ key, metricId: 'seo-contents', label, value: counts[key] ?? 0, display: new Intl.NumberFormat('zh-CN').format(counts[key] ?? 0) })),
    note: '当前内容状态分布直接来自状态库存，不代表转化率或处理耗时。',
  }
}

export function validVisualization(value) {
  if (!record(value) || !['trend', 'funnel', 'distribution'].includes(value.type) || !['available', 'unavailable'].includes(value.state)) return false
  if (value.type === 'trend') return Array.isArray(value.points) && value.points.length <= 366 && record(value.coverage) && typeof value.coverage.label === 'string'
    && new Set(value.points.map(item => item.key)).size === value.points.length
    && value.points.every(item => record(item) && typeof item.key === 'string' && item.key.length > 0 && typeof item.label === 'string' && typeof item.display === 'string' && (item.value === null || finite(item.value)))
  if (value.type === 'funnel') return Array.isArray(value.stages) && (value.state === 'unavailable' ? value.stages.length === 0 : value.stages.length === 2)
    && (value.state === 'unavailable' || value.stages.map(item => item.key).join(',') === 'impression,click')
    && value.stages.every(item => record(item) && finite(item.value) && typeof item.metricId === 'string' && typeof item.display === 'string')
    && (value.rate === null || (finite(value.rate) && value.rate <= 1)) && typeof value.rateLabel === 'string' && record(value.coverage) && typeof value.coverage.label === 'string'
  return Array.isArray(value.items) && typeof value.note === 'string' && new Set(value.items.map(item => item.key)).size === value.items.length
    && value.items.every(item => record(item) && typeof item.key === 'string' && item.key.length > 0 && typeof item.label === 'string' && integer(item.value) && typeof item.display === 'string')
}

export function visualizationIndexAfterKey(index, length, key) {
  if (!Number.isSafeInteger(length) || length <= 0) return -1
  if (key === 'Home') return 0
  if (key === 'End') return length - 1
  if (key === 'ArrowLeft' || key === 'ArrowUp') return Math.max(0, index - 1)
  if (key === 'ArrowRight' || key === 'ArrowDown') return Math.min(length - 1, index + 1)
  return Math.max(0, Math.min(length - 1, index))
}

export function visualizationIndexFromPointer(clientX, left, width, length) {
  if (![clientX, left, width].every(value => typeof value === 'number' && Number.isFinite(value)) || width <= 0 || !Number.isSafeInteger(length) || length <= 0) return -1
  const ratio = Math.max(0, Math.min(1, (clientX - left) / width))
  return Math.round(ratio * (length - 1))
}

export function visualizationBarPercent(value, maxValue, minimumVisible = 3) {
  if (!finite(value) || !finite(maxValue) || maxValue <= 0 || value === 0) return 0
  return Math.min(100, Math.max(minimumVisible, value / maxValue * 100))
}
