import client from './client'

// 投放分析报告（客户交付）。数据模块实时聚合，AI 叙述按日期区间缓存。
export function fetchAnalysisReport({ tenantId, startDate, endDate, force }) {
  return client.get('/api/v1/reports/analysis', {
    params: {
      tenant_id: tenantId,
      start_date: startDate,
      end_date: endDate,
      force: force || undefined,
    },
    timeout: 120000, // 首次生成要等 DeepSeek
  })
}

export function analysisReportExportUrl({
  tenantId,
  startDate,
  endDate,
  format = 'csv',
}) {
  const params = new URLSearchParams({
    tenant_id: tenantId,
    start_date: startDate,
    end_date: endDate,
    format,
  })
  return `/api/v1/reports/analysis/export?${params.toString()}`
}
