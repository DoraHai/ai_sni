import client from './client'

// 待验证调价（效果验证 · 待验证调价）。menu = verify.pending。
export function fetchPendingAdjustments({ tenantId, days, status }) {
  return client.get('/api/v1/adjustment-verify', {
    params: { tenant_id: tenantId, days: days || undefined, status: status || undefined },
  })
}

export function fetchBudgetAdjustments({ tenantId, days, status }) {
  return client.get('/api/v1/adjustment-verify/budget', {
    params: { tenant_id: tenantId, days: days || undefined, status: status || undefined },
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

export function fetchWritebackQueue(tenantId) {
  return client.get('/api/v1/writeback/queue', { params: { tenant_id: tenantId } })
}
