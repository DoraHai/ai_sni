import client from './client'

// 客户画像（每日盯盘 · 客户画像）。menu = monitor.profile。
export function fetchCustomerProfile({ tenantId, refreshSummary }) {
  return client.get('/api/v1/customer-profile', {
    params: { tenant_id: tenantId, refresh_summary: refreshSummary || undefined },
    timeout: 120000, // 首次生成 AI 总结要等 DeepSeek
  })
}

export function updateCustomerProfile({ tenantId, industry, businessDesc }) {
  return client.patch('/api/v1/customer-profile', { industry, business_desc: businessDesc }, {
    params: { tenant_id: tenantId },
  })
}
