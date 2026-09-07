const SITE_STATUSES = new Set(['active', 'paused', 'archived'])

function fail(code, message, status) {
  const error = new Error(message)
  error.code = code
  if (status !== undefined) error.status = status
  throw error
}

function positive(value) {
  return Number.isSafeInteger(value) && value > 0
}

function nonempty(value) {
  return typeof value === 'string' && value.trim().length > 0
}

export async function readSeoSiteScope({ transport, tenantId, signal } = {}) {
  if (typeof transport !== 'function') throw new TypeError('transport must be a function')
  if (!positive(tenantId)) fail('INVALID_TENANT', '请选择有效客户')
  const response = await transport(
    `/api/v1/seo/workbench/sites?tenant_id=${tenantId}`,
    { method: 'GET', cache: 'no-store', signal },
  )
  if (response.status === 401) fail('NOT_AUTHENTICATED', '登录态已失效', 401)
  if (response.status === 403) fail('NOT_AUTHORIZED', '当前身份无权读取该客户的 SEO 站点范围', 403)
  if (!response.ok) fail('READ_FAILED', `SEO 站点范围读取失败（${response.status}）`, response.status)
  let data
  try {
    data = await response.json()
  } catch {
    fail('CONTRACT_MISMATCH', 'SEO 站点范围响应不是有效 JSON')
  }
  const sites = data?.sites
  const policy = data?.selection_policy
  if (data?.tenant_id !== tenantId || !Array.isArray(sites) ||
      !Array.isArray(policy?.selectable_statuses) || !Array.isArray(policy?.disabled_statuses) ||
      policy.selectable_statuses.join(',') !== 'active' || policy.disabled_statuses.join(',') !== 'paused,archived') {
    fail('CONTRACT_MISMATCH', 'SEO 站点范围或选择策略不匹配')
  }
  const ids = new Set()
  const normalized = sites.map(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item) || !positive(item.id) ||
        ids.has(item.id) || !nonempty(item.name) || !nonempty(item.domain) || !SITE_STATUSES.has(item.status)) {
      fail('CONTRACT_MISMATCH', 'SEO 站点字段无效')
    }
    ids.add(item.id)
    return Object.freeze({ id: item.id, name: item.name, domain: item.domain, status: item.status })
  })
  return Object.freeze({
    tenantId,
    selectableStatuses: Object.freeze(['active']),
    disabledStatuses: Object.freeze(['paused', 'archived']),
    sites: Object.freeze(normalized),
  })
}
