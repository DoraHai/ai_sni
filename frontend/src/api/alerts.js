import client from './client'

export function fetchAlerts({ tenantId, status = 'open', priority }) {
  return client.get('/api/v1/alerts', {
    params: {
      tenant_id: tenantId,
      status,
      priority: priority || undefined,
    },
  })
}

export function resolveAlert(alertId) {
  return client.patch(`/api/v1/alerts/${alertId}/resolve`)
}
