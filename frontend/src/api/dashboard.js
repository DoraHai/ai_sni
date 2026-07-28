import client from './client'

export function fetchDashboardToday({ tenantId, startDate, endDate }) {
  return client.get('/api/v1/dashboard/today', {
    params: {
      tenant_id: tenantId,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    },
  })
}

// AI 每日洞察（盯盘页）。未配 DeepSeek 时返回 { enabled: false }
export function fetchDashboardInsight({ tenantId, force }) {
  return client.get('/api/v1/dashboard/insight', {
    params: { tenant_id: tenantId, force: force || undefined },
  })
}
