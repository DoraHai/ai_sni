import client from './client'

// 调价回写台账（平台主动发起的 updateWord 留痕）。返回 {status_counts, writebacks}
export function fetchWritebacks({ tenantId, status = null, limit = 200 }) {
  return client.get('/api/v1/writeback', {
    params: { tenant_id: tenantId, status, limit },
  })
}

export function fetchWritebackApprovals({ tenantId, status = null, limit = 100 }) {
  return client.get('/api/v1/writeback/approvals', {
    params: { tenant_id: tenantId, status, limit },
  })
}

export function requestWritebackApproval({ tenantId, actionType, payload, note = null, confirmation }) {
  return client.post('/api/v1/writeback/approvals', {
    tenant_id: tenantId,
    action_type: actionType,
    payload,
    note,
    confirmation,
  })
}

export function decideWritebackApproval(approvalId, decision, note = null) {
  return client.post(`/api/v1/writeback/approvals/${approvalId}/decision`, {
    decision,
    note,
  })
}
