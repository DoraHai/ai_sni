// Independent identity API: never imports the tenant/project-injecting client.
export const INBOX_PREFIX = '/api/v1/seo/distribution/v2/inbox'
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/
const modules = new Set(['seo', 'geo'])

function id(value) {
  if (typeof value !== 'string' || !uuid.test(value)) throw new TypeError('INVALID_RECEIPT_ID')
  return value
}

function selectors(values = {}, count = false) {
  const allowed = new Set(count ? ['state', 'q', 'ownerUserId'] : ['state', 'q', 'ownerUserId', 'limit', 'offset'])
  if (Object.keys(values).some(key => !allowed.has(key))) throw new TypeError('INBOX_SELECTOR_FORBIDDEN')
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value == null) continue
    if (key === 'state' && !['pending', 'active', 'archived'].includes(value)) throw new TypeError('INVALID_INBOX_STATE')
    if (key === 'q' && (typeof value !== 'string' || [...value].length > 100)) throw new TypeError('INVALID_INBOX_SEARCH')
    if (['ownerUserId', 'limit', 'offset'].includes(key)
        && (!Number.isSafeInteger(value) || value < (key === 'offset' ? 0 : 1)
          || (key === 'limit' && value > 100) || (key === 'offset' && value > 5000))) throw new TypeError('INVALID_INBOX_PAGE')
    query.set(key, String(value))
  }
  return query.size ? `?${query}` : ''
}

/** Inject an identity session getter and an explicitly selected business session.
 * getIdentity() => {token, revision}; getBusiness(module, tenant) => {token, revision}.
 * Shell owns session verification/selection; neither getter may mutate selection.
 */
export function createDistributionInboxApi({ getIdentity, getBusiness, fetchImpl = globalThis.fetch }) {
  async function request(path, { method = 'GET', body, business, signal } = {}) {
    const getter = business ? () => getBusiness?.(business.module, business.tenant) : getIdentity
    const context = getter?.()
    if (!context?.token) throw Object.assign(new Error('请先登录人员身份'), { code: 'INBOX_IDENTITY_REQUIRED' })
    // This is a UI boundary check, not JWT verification. Server verifies signature,
    // current role, grants and scope. Never fall back from a missing identity JWT.
    if (!business && context.scopeKind && context.scopeKind !== 'advisor_identity') {
      throw Object.assign(new Error('请使用身份会话打开收件箱'), { code: 'INBOX_IDENTITY_REQUIRED' })
    }
    const response = await fetchImpl(path, {
      method, headers: { Authorization: `Bearer ${context.token}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      credentials: 'omit', cache: 'no-store', redirect: 'error', signal,
    })
    const data = await response.json().catch(() => null)
    const current = getter?.()
    if (current?.token !== context.token || current?.revision !== context.revision) {
      throw Object.assign(new Error('登录身份或权限已变化，请刷新'), { code: 'AUTH_CONTEXT_CHANGED' })
    }
    if (!response.ok) {
      throw Object.assign(new Error(data?.detail?.message || (response.status === 503 ? '功能尚未准备好' : '操作未完成，请刷新后重试')), {
        status: response.status, code: data?.detail?.code || 'INBOX_REQUEST_FAILED',
      })
    }
    return data
  }
  const mutation = (suffix, body, signal) => request(INBOX_PREFIX + suffix, { method: 'POST', body, signal })
  function businessMutation(module, tenant, receiptId, action, body, signal) {
    if (!modules.has(module) || !Number.isSafeInteger(tenant) || tenant < 1) throw new TypeError('INVALID_BUSINESS_TARGET')
    return request(`/api/v1/${module}/distribution/v2/receipts/${id(receiptId)}/${action}?tenant_id=${tenant}`, {
      method: 'POST', body, business: { module, tenant }, signal,
    })
  }
  return {
    createPairing: (signal) => mutation('/pairings', {}, signal),
    targets: (signal) => request(INBOX_PREFIX + '/targets', { signal }),
    cancelPairing: (pairingId, expectedRevision, signal) => mutation(`/pairings/${id(pairingId)}/cancel`, { expectedRevision }, signal),
    receipts: (params, signal) => request(INBOX_PREFIX + '/receipts' + selectors(params), { signal }),
    count: (params, signal) => request(INBOX_PREFIX + '/receipts/count' + selectors(params, true), { signal }),
    receipt: (receiptId, signal) => request(INBOX_PREFIX + '/receipts/' + id(receiptId), { signal }),
    devices: (signal) => request(INBOX_PREFIX + '/devices', { signal }),
    devicesFor: (ownerUserId, signal) => {
      if (!Number.isSafeInteger(ownerUserId) || ownerUserId < 1) throw new TypeError('INVALID_INBOX_OWNER')
      return request(INBOX_PREFIX + '/devices?ownerUserId=' + ownerUserId, { signal })
    },
    revoke: (deviceId, expectedRevision, signal) => mutation(`/devices/${id(deviceId)}/revoke`, { expectedRevision }, signal),
    archive: (receiptId, expectedRevision, signal) => mutation(`/receipts/${id(receiptId)}/archive`, { expectedRevision }, signal),
    delete: (receiptId, expectedRevision, signal) => mutation(`/receipts/${id(receiptId)}/delete`, { expectedRevision }, signal),
    label: (module, tenant, receiptId, body, signal) => businessMutation(module, tenant, receiptId, 'label', body, signal),
    unlabel: (module, tenant, receiptId, body, signal) => businessMutation(module, tenant, receiptId, 'unlabel', body, signal),
    publications: (tenant, scopeId, signal) => {
      if (!Number.isSafeInteger(tenant) || tenant < 1 || (scopeId != null && (!Number.isSafeInteger(scopeId) || scopeId < 1))) throw new TypeError('INVALID_BUSINESS_TARGET')
      return request(`/api/v1/geo/distribution/v2/publications?tenant_id=${tenant}${scopeId == null ? '' : `&scope_id=${scopeId}`}`, { business: { module: 'geo', tenant }, signal })
    },
    publicationGroups: (tenant, scopeId, params = {}, signal) => {
      if (![tenant, scopeId].every(v => Number.isSafeInteger(v) && v > 0)
          || Object.keys(params).some(k => !['bucket', 'article_id', 'limit', 'cursor', 'month', 'source'].includes(k))) throw new TypeError('INVALID_GROUP_SCOPE')
      const query = new URLSearchParams({ tenant_id: tenant, scope_id: scopeId })
      for (const [key, value] of Object.entries(params)) {
        if (value == null) continue
        if (key === 'bucket' && !['linked', 'unlinked', 'invalid', 'records'].includes(value)) throw new TypeError('INVALID_GROUP_BUCKET')
        if (key === 'month' && !/^[1-9][0-9]{3}-(0[1-9]|1[0-2])$/.test(value)) throw new TypeError('INVALID_RECORD_MONTH')
        if (key === 'source' && !['all', 'native', 'external_report'].includes(value)) throw new TypeError('INVALID_RECORD_SOURCE')
        if (key === 'article_id' && (!Number.isSafeInteger(value) || value < 1)) throw new TypeError('INVALID_GROUP_ARTICLE')
        if (key === 'limit' && (!Number.isSafeInteger(value) || value < 1 || value > 100)) throw new TypeError('INVALID_GROUP_LIMIT')
        if (key === 'cursor' && (typeof value !== 'string' || !value || value.length > 4096)) throw new TypeError('INVALID_GROUP_CURSOR')
        query.set(key, value)
      }
      if (params.article_id != null && params.bucket && !['linked', 'records'].includes(params.bucket)) throw new TypeError('INVALID_GROUP_BUCKET')
      return request(`/api/v1/geo/distribution/v2/publication-groups?${query}`, { business: { module: 'geo', tenant }, signal })
    },
  }
}
