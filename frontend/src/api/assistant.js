import client from './client'

// 一轮对话：只传新问题，历史由后端从库读。
// 返回 {reply, suggestions:[{label,target,reason}], memories:[{type,content}]}
export function chat({ tenantId, message }) {
  return client.post('/api/v1/assistant/chat', { tenant_id: tenantId, message })
}

// 加载对话历史（保留期内，时间正序）。返回 {retain_days, messages:[{role,content,created_at}]}
export function fetchHistory({ tenantId }) {
  return client.get('/api/v1/assistant/history', { params: { tenant_id: tenantId } })
}

// 一键采纳并执行 AI 建议（暂停/调价/加否词/设日预算）。返回 {results:[{keyword,status,detail}], dry_run}
export function adoptAction({ tenantId, type, keywords = [], adjustPct, matchMode = 'exact', budget }) {
  return client.post('/api/v1/assistant/adopt', {
    tenant_id: tenantId, type, keywords, adjust_pct: adjustPct, match_mode: matchMode, budget,
  })
}

// 当前生效的客户记忆（目标/约束/偏好…）
export function fetchMemories({ tenantId }) {
  return client.get('/api/v1/assistant/memories', { params: { tenant_id: tenantId } })
}

// 确认/新增一条记忆（AI 抽取经用户确认后入库）
export function createMemory({ tenantId, memType = 'other', content, source = 'assistant' }) {
  return client.post('/api/v1/assistant/memories', {
    tenant_id: tenantId, mem_type: memType, content, source,
  })
}

// 软删除一条记忆
export function deleteMemory({ tenantId, id }) {
  return client.delete(`/api/v1/assistant/memories/${id}`, { params: { tenant_id: tenantId } })
}
