import client from './client'

// oCPC 投放管理（投放管理 · oCPC 投放，只读查看层）。menu = manage.ocpc。
export function fetchOcpcPackages({ tenantId }) {
  return client.get('/api/v1/ocpc/packages', {
    params: { tenant_id: tenantId },
  })
}
