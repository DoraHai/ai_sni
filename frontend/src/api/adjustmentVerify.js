import client from './client'

// 待验证调价（效果验证 · 待验证调价）。menu = verify.pending。
export function fetchPendingAdjustments({ tenantId, days, status, offset = 0, limit = 50 }) {
  return client.get('/api/v1/adjustment-verify', {
    params: { tenant_id: tenantId, days: days || undefined, status: status || undefined, offset, limit },
  })
}

export function fetchBudgetAdjustments({ tenantId, days, status, offset = 0, limit = 50 }) {
  return client.get('/api/v1/adjustment-verify/budget', {
    params: { tenant_id: tenantId, days: days || undefined, status: status || undefined, offset, limit },
  })
}

export function markVerified({ tenantId, dedupKey, verdict, note, reopen }) {
  return client.patch(`/api/v1/adjustment-verify/${encodeURIComponent(dedupKey)}`,
    { verdict, note, reopen: reopen || undefined },
    { params: { tenant_id: tenantId } })
}

export function genAiVerdict({ tenantId, dedupKey, force }) {
  return client.post(`/api/v1/adjustment-verify/${encodeURIComponent(dedupKey)}/ai`, null, {
    params: { tenant_id: tenantId, force: force || undefined },
    timeout: 60000,
  })
}

export function fetchWritebackQueue(tenantId, { stage, offset = 0, limit = 200 } = {}) {
  return client.get('/api/v1/writeback/queue', {
    params: { tenant_id: tenantId, stage: stage || undefined, offset, limit },
  })
}

export function reconcileWriteback({ tenantId, recordType, recordId, decision, note }) {
  return client.post(`/api/v1/writeback/queue/${recordType}/${recordId}/reconcile`, {
    tenant_id: tenantId,
    decision,
    note,
  })
}
