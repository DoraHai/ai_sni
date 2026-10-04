export const SOURCE_LABELS = Object.freeze({ real: '真实引擎采样', manual: '人工录入', simulated: '模拟/演示', unknown: '来源未知' })

export function reportParams({ from, to, businessId, projectId, granularity, provenance }) {
  return {
    from, to,
    ...(businessId ? { business_id: Number(businessId) } : {}),
    ...(projectId ? { project_id: Number(projectId) } : {}),
    ...(granularity ? { granularity } : {}),
    ...(provenance ? { provenance } : {}),
  }
}

export function rateLabel(row) {
  return row?.samples ? `${(100 * row.mentions / row.samples).toFixed(1)}%` : '无数据'
}

export function safeFilename(from, to, type) {
  return `GEO-${type}-${String(from).replaceAll(/[^0-9-]/g, '')}-${String(to).replaceAll(/[^0-9-]/g, '')}.${type === '报告' ? 'pdf' : 'xlsx'}`
}
