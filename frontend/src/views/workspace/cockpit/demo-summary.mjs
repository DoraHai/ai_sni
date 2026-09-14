import { completedWeekPeriodLabel } from './geo-summary.mjs'

export function geoDemoCards({ summary, capabilities, contextRevision }) {
  if (summary?.tenant_id !== 16 || capabilities?.tenant_id !== 16
    || summary.official !== false || summary.source_kind !== 'synthetic'
    || summary.excluded_from_official_metrics !== true || summary.demo?.read_only !== true) {
    throw new Error('演示数据来源或客户范围不匹配')
  }
  const current = summary.window?.current || {}
  const keys = capabilities.historical_engine_keys
    ?? capabilities.engines?.map(item => item.engine_key)
  const engines = Array.isArray(keys) && keys.every(key => typeof key === 'string' && key)
    ? new Set(keys).size : null
  return [
    ['mention_rate', 'AI 回答提及率', current.mention_rate, '%'],
    ['mention_count', 'AI 回答提及', current.mention_count, '次'],
    ['own_domain_citation_count', '官网引用', current.own_domain_citation_count, '次'],
    ['sample_count', '演示回答样本', current.sample_count, '条'],
    ['engines', '演示覆盖引擎', engines, '个'],
  ].map(([key, label, value, unit]) => {
    const available = typeof value === 'number' && Number.isFinite(value) && value >= 0
    const previous = summary.window?.previous?.[key]
    const display = available ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(value) : '—'
    return {
      id: `geo-demo-${key}`, moduleCode: 'geo', moduleLabel: 'GEO · 演示', label,
      display, unit, state: available ? 'available' : 'unavailable', contextRevision,
      reason: '模拟数据，仅供演示；不计入正式指标，不代表实际采集或获客结果。',
      sourceLabel: 'GEO 演示数据', updatedLabel: summary.evaluated_at,
      periodLabel: completedWeekPeriodLabel(current),
      series: typeof previous === 'number' && available ? [
        { label: '前一周', value: previous, display: `${previous}${unit}` },
        { label: '本周', value, display: `${display}${unit}` },
      ] : [],
      columns: [{ key: 'value', label: '演示数值' }, { key: 'basis', label: '说明' }],
      rows: [{ value: `${display}${unit}`, basis: '固定演示数据集；不进入正式统计' }],
    }
  })
}
