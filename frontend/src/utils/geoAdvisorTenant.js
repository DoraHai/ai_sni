// Claims are UI hints only; the server validates identity and customer grants.
export function advisorClaims(token) {
  try {
    const claims = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return ['advisor_identity', 'advisor_tenant'].includes(claims.scope_kind) ? claims : null
  } catch { return null }
}

const positiveId = (id) => Number.isSafeInteger(id) && id > 0
export const GEO_ADVISOR_SELECT_URL = '/customer-workbench/?console=advisor'
export const GEO_ADVISOR_SELECTION_MESSAGE = '请先选择客户，再查看 GEO 数据'
export const GEO_ADVISOR_NO_TENANT_MESSAGE = '你还没有被分配客户，请联系管理员'
const guide = (noTenant = false) => ({
  message: noTenant ? GEO_ADVISOR_NO_TENANT_MESSAGE : GEO_ADVISOR_SELECTION_MESSAGE,
  selectCustomer: !noTenant,
})

// Runs before mounting business pages: no requests carry an inferred customer id.
// One recovery attempt per bootstrap, even if the retried read returns another 409.
export async function bootstrapGeoSession({ session, readSession, applySession, fetchMe, listAuthorizedCustomers, selectTenant }) {
  const identityToken = session.token
  let expectedToken = identityToken
  const isAdvisor = !!advisorClaims(identityToken) || session.user?.is_advisor === true
  const current = () => session.token === expectedToken
  let me
  let tenants
  try {
    ;[me, tenants] = await readSession()
  } catch (error) {
    if (!current()) return isAdvisor ? guide() : null
    if (!isAdvisor) {
      session.setTenants(session.tenants || [])
      return null
    }
    if (error.code === 'ADVISOR_NO_TENANT') return guide(true)
    if (error.code !== 'ADVISOR_TENANT_SELECTION_REQUIRED') throw error
    if (error.status !== 409 || advisorClaims(identityToken)?.scope_kind !== 'advisor_identity') return guide()
    try {
      const [profile, data] = await Promise.all([fetchMe(), listAuthorizedCustomers()])
      if (!current()) return guide()
      const rows = Array.isArray(data) ? data : data?.tenants
      if (!Array.isArray(rows) || rows.some((row) => !positiveId(row?.id))
          || new Set(rows.map((row) => row.id)).size !== rows.length) return guide()
      if (!rows.length) return guide(true)
      const defaultId = profile?.user?.default_tenant_id
      const tenantId = rows.some((row) => row.id === defaultId)
        ? defaultId : rows.length === 1 ? rows[0].id : null
      if (!tenantId) return guide()
      const selected = await selectTenant(tenantId)
      if (!current()) return guide()
      const claims = advisorClaims(selected?.access_token)
      if (selected?.tenant_id !== tenantId || selected?.token_type !== 'bearer'
          || typeof selected?.tenant_name !== 'string'
          || typeof selected?.access_token !== 'string' || /\s/.test(selected.access_token)
          || typeof selected?.expires_at !== 'string' || !(Date.parse(selected.expires_at) > Date.now())
          || claims?.scope_kind !== 'advisor_tenant' || claims.tid !== tenantId
          || !positiveId(claims.gid) || String(claims.sub) !== String(session.user?.id)) return guide()
      session.replaceAuthForAdvisorTenant(selected.access_token, tenantId)
      expectedToken = selected.access_token
      ;[me, tenants] = await readSession()
    } catch (recoveryError) {
      return guide(recoveryError.code === 'ADVISOR_NO_TENANT')
    }
  }
  if (!current()) return isAdvisor ? guide() : null
  applySession(me, tenants)
  return null
}
