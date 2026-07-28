import client from './client'

// AI 调价建议列表（默认待处理）。返回 {total_pending, type_counts, suggestions}
export function fetchSuggestions({ tenantId, status = 'pending', limit = 200 }) {
  return client.get('/api/v1/suggestions', {
    params: { tenant_id: tenantId, status, limit },
  })
}

// 更新建议状态：adopted（已采纳）/ ignored（已忽略）/ pending（恢复）
export function updateSuggestionStatus(id, status) {
  return client.patch(`/api/v1/suggestions/${id}/status`, null, {
    params: { status },
  })
}
