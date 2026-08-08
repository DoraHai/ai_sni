import client from './client'

export function fetchBaiduOAuthStatus(tenantId) {
  return client.get('/api/v1/oauth/baidu/status', {
    params: { tenant_id: tenantId },
  })
}

export function startBaiduOAuth({ tenantId, returnPath = '/onboarding' }) {
  return client.post('/api/v1/oauth/baidu/authorize', {
    tenant_id: tenantId,
    return_path: returnPath,
  })
}
