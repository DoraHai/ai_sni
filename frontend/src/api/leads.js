import client from './client'

// 线索列表（分页 + 筛选）+ 统计。返回 {total, summary, leads}
export function fetchLeads({ tenantId, status, campaignId, startDate, endDate, page, pageSize }) {
  return client.get('/api/v1/leads', {
    params: {
      tenant_id: tenantId,
      status: status || undefined,
      campaign_id: campaignId ?? undefined,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      page,
      page_size: pageSize,
    },
  })
}

// 录入单条线索
export function createLead({ tenantId, ...body }) {
  return client.post('/api/v1/leads', { tenant_id: tenantId, ...body })
}

// 从百度拉基木鱼线索落库（按 clueId 幂等去重）
export function syncLeads({ tenantId, days = 30 }) {
  return client.post('/api/v1/leads/sync', null, { params: { tenant_id: tenantId, days } })
}

// 更新线索（销售跟进：状态/金额/备注等，部分更新）
export function updateLead({ tenantId, id, ...body }) {
  return client.patch(`/api/v1/leads/${id}`, body, { params: { tenant_id: tenantId } })
}

// 删除线索
export function deleteLead({ tenantId, id }) {
  return client.delete(`/api/v1/leads/${id}`, { params: { tenant_id: tenantId } })
}
