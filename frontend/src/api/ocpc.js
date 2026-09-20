import client from './client'

// oCPC 投放管理（投放管理 · oCPC 投放）。menu = manage.ocpc。
export function fetchOcpcPackages({ tenantId }) {
  return client.get('/api/v1/ocpc/packages', {
    params: { tenant_id: tenantId },
  })
}

export function updateOcpcBid({ tenantId, packageId, accountId, oldBid, newBid, executionMode, approvalId = null, confirmation = null, idempotencyKey = null }) {
  return client.post(`/api/v1/ocpc/packages/${packageId}/bid`, {
    tenant_id: tenantId, baidu_account_id: accountId,
    old_bid: oldBid, new_bid: newBid, execution_mode: executionMode, approval_id: approvalId,
    confirmation, idempotency_key: idempotencyKey,
  })
}
