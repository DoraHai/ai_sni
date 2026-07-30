import client from './client'

export function geoContentHealth() {
  return client.get('/api/v1/geo/content-health')
}

export function fetchGeoContentStats(tenantId) {
  return client.get('/api/v1/geo/content-stats', { params: { tenant_id: tenantId } })
}

export function listGeoPrompts(tenantId, status) {
  return client.get('/api/v1/geo/prompts', { params: { tenant_id: tenantId, status } })
}

export function createGeoPrompt(body) {
  return client.post('/api/v1/geo/prompts', body)
}

export function listGeoFacts(tenantId, params = {}) {
  return client.get('/api/v1/geo/facts', { params: { tenant_id: tenantId, ...params } })
}

export function createGeoFact(body) {
  return client.post('/api/v1/geo/facts', body)
}

export function listGeoContentTasks(tenantId, status) {
  return client.get('/api/v1/geo/content-tasks', { params: { tenant_id: tenantId, status } })
}

export function getGeoContentTask(tenantId, taskId) {
  return client.get(`/api/v1/geo/content-tasks/${taskId}`, { params: { tenant_id: tenantId } })
}

export function createGeoContentTask(body) {
  return client.post('/api/v1/geo/content-tasks', body)
}

export function bindGeoTaskFacts(tenantId, taskId, factIds) {
  return client.put(`/api/v1/geo/content-tasks/${taskId}/facts`, { fact_ids: factIds }, {
    params: { tenant_id: tenantId },
  })
}

export function generateGeoContentTask(tenantId, taskId) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/generate`, null, {
    params: { tenant_id: tenantId },
    timeout: 90000,
  })
}

export function checkGeoContentTask(tenantId, taskId, requireChannels = false) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/check`, null, {
    params: { tenant_id: tenantId, require_channels: requireChannels },
  })
}

export function createGeoVariants(tenantId, taskId, channels = ['website', 'zhihu']) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/variants`, { channels }, {
    params: { tenant_id: tenantId },
  })
}

export function exportGeoVariant(tenantId, taskId, channel = 'website') {
  return client.get(`/api/v1/geo/content-tasks/${taskId}/export`, {
    params: { tenant_id: tenantId, channel },
  })
}

export function publishGeoVariant(taskId, body) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/publications`, body)
}
