import client from './client'

// 月度分析报告（客户交付）。数据模块实时聚合，AI 叙述按月缓存。
export function fetchMonthlyReport({ tenantId, year, month, force }) {
  return client.get('/api/v1/reports/monthly', {
    params: { tenant_id: tenantId, year, month, force: force || undefined },
    timeout: 120000, // 首次生成要等 DeepSeek
  })
}

export function fetchAvailableMonths({ tenantId }) {
  return client.get('/api/v1/reports/monthly/available-months', {
    params: { tenant_id: tenantId },
  })
}

export function monthlyReportExportUrl({ tenantId, year, month, format = 'csv' }) {
  const params = new URLSearchParams({
    tenant_id: tenantId,
    year,
    month,
    format,
  })
  return `/api/v1/reports/monthly/export?${params.toString()}`
}
