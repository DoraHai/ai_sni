import { advisorClaims } from './geoAdvisorTenant.js'

// Only application code accesses its existing session. Never invent an identity
// from a business JWT, and never persist a newly selected business session here.
export function inboxIdentity(session, storage) {
  const current = advisorClaims(session.token)
  if (!current) return session.token && !session.user?.is_advisor ? { token: session.token, scopeKind: null } : null
  if (current.scope_kind === 'advisor_identity') return { token: session.token, scopeKind: current.scope_kind }
  try {
    const saved = JSON.parse(storage.getItem('sem_advisor_identity_v1'))
    const claims = advisorClaims(saved?.token)
    if (claims?.scope_kind !== 'advisor_identity' || claims.aud !== 'advisor-session'
      || String(claims.sub) !== String(session.user?.id) || claims.exp * 1000 <= Date.now()) return null
    return { token: saved.token, scopeKind: claims.scope_kind }
  } catch { return null }
}

export function canOpenInbox(session) {
  return session.isLoggedIn && (session.user?.is_advisor === true
    || !!advisorClaims(session.token) || session.user?.role_label === '管理员')
}

export function createGeoInboxSession({ session, storage, fetchImpl = globalThis.fetch }) {
  let generation = 0
  const business = new Map()
  const identity = () => {
    const value = inboxIdentity(session, storage)
    return value && { ...value, revision: `${generation}:${session.token}:${session.tenantId}` }
  }
  async function identityRequest(path, body, signal) {
    const before = identity()
    if (!before) throw new Error('请重新登录顾问身份后打开收件箱')
    const response = await fetchImpl(path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { Authorization: `Bearer ${before.token}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      credentials: 'omit', cache: 'no-store', redirect: 'error', signal,
    })
    const data = await response.json()
    if (identity()?.revision !== before.revision || identity()?.token !== before.token) throw new Error('登录身份已变化，请刷新')
    if (!response.ok) throw new Error(data?.detail?.message || '暂时无法核对客户授权')
    return data
  }
  return {
    identity,
    clear() { generation++; business.clear() },
    business(module, tenant) {
      const value = business.get(tenant)
      if (!['seo', 'geo'].includes(module) || !value || value.identity !== identity()?.revision) return null
      return { token: value.token, revision: value.identity }
    },
    async prepare(tenant, signal) {
      const before = identity()
      if (!before) throw new Error('请重新登录人员身份')
      if (before.scopeKind == null) {
        business.set(tenant, { token: before.token, identity: before.revision }); return
      }
      const data = await identityRequest('/api/v1/auth/select-tenant', { tenant_id: tenant }, signal)
      const claims = advisorClaims(data?.access_token)
      const original = advisorClaims(before.token)
      if (data?.tenant_id !== tenant || claims?.scope_kind !== 'advisor_tenant'
        || claims.aud !== 'advisor-business' || claims.tid !== tenant || claims.sub !== original?.sub
        || !Number.isSafeInteger(claims.gid) || claims.gid < 1 || claims.exp * 1000 <= Date.now()) throw new Error('客户凭证无效，请重新核对')
      business.set(tenant, { token: data.access_token, identity: before.revision })
    },
    identityRequest,
  }
}
