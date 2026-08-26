import client from './client'

export function fetchAlerts({ tenantId, status = 'open', priority, campaignId, alertType }) {
  return client.get('/api/v1/alerts', {
    params: {
      tenant_id: tenantId,
      status,
      priority: priority || undefined,
      campaign_id: campaignId || undefined,
      alert_type: alertType || undefined,
    },
  })
}

export function resolveAlert({ tenantId, alertId }) {
  return client.patch(`/api/v1/alerts/${alertId}/resolve`, null, { params: { tenant_id: tenantId } })
}

export function batchResolveAlerts({ tenantId, alertIds }) {
  return client.post('/api/v1/alerts/batch-resolve', {
    tenant_id: tenantId,
    alert_ids: alertIds,
  })
}
