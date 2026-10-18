const positiveId = value => Number.isSafeInteger(value) && value > 0
const fail = code => Object.assign(new Error('客户选择未完成'), { code })

export function advisorAccessGuidance(error, isAdvisor) {
  if (!isAdvisor) return null
  if (error?.code === 'ADVISOR_NO_TENANT') {
    return { message: '你还没有被分配客户，请联系管理员', selectCustomer: false }
  }
  if (error?.code === 'ADVISOR_TENANT_SELECTION_REQUIRED') {
    return { message: '你有多个客户，请先选择要查看的客户', selectCustomer: true }
  }
  if (error?.code === 'SEO_ADVISOR_SELECTION_FAILED' || error?.code?.startsWith('ADVISOR_')) {
    return { message: '暂时无法进入当前客户，请前往工作台重新选择客户；如仍失败，请联系管理员', selectCustomer: true }
  }
  return null
}

// One shared attempt per mounted workspace, including failures. Route/auth
// watchers may overlap; none may start a second exchange or apply stale auth.
export function createSeoAdvisorTenantRecovery({ session, client }) {
  let attempt
  let disposed = false

  async function select() {
    const token = session.token
    const revision = session.authRevision
    const current = () => {
      if (disposed || token !== session.token || revision !== session.authRevision) {
        throw fail('AUTH_CONTEXT_CHANGED')
      }
    }
    try {
      const response = await client.get('/api/v1/auth/tenants')
      current()
      const tenants = Array.isArray(response) ? response : response?.tenants
      if (!Array.isArray(tenants) || tenants.some(t => !positiveId(t?.id) || typeof t.name !== 'string')
          || new Set(tenants.map(t => t.id)).size !== tenants.length) throw fail('INVALID_TENANTS')
      if (!tenants.length) throw fail('ADVISOR_NO_TENANT')

      const me = await client.get('/api/v1/auth/me')
      current()
      const profile = me?.user ?? me
      // Older /auth/me exposes the default as user.tenant_id. This is only a
      // preference within verified grants, never a business-scope fallback.
      // An explicit null default must remain null.
      const defaultId = Object.hasOwn(profile ?? {}, 'default_tenant_id') ? profile.default_tenant_id
        : Object.hasOwn(me ?? {}, 'default_tenant_id') ? me.default_tenant_id : profile?.tenant_id
      const selected = tenants.find(t => t.id === defaultId) || (tenants.length === 1 ? tenants[0] : null)
      if (!selected) throw fail('ADVISOR_TENANT_SELECTION_REQUIRED')

      const data = await client.post('/api/v1/auth/select-tenant', { tenant_id: selected.id })
      current()
      // Same envelope contract as customer-workbench's advisor-tenant-switch.
      if (data?.tenant_id !== selected.id || typeof data.tenant_name !== 'string'
          || data.token_type !== 'bearer' || typeof data.access_token !== 'string' || !data.access_token
          || typeof data.expires_at !== 'string' || !(Date.parse(data.expires_at) > Date.now())) {
        throw fail('INVALID_TENANT_RESPONSE')
      }
      session.replaceAuthForAdvisorTenant(data.access_token, selected.id)
      return { tenantId: selected.id }
    } catch (error) {
      if (['ADVISOR_NO_TENANT', 'ADVISOR_TENANT_SELECTION_REQUIRED', 'AUTH_CONTEXT_CHANGED'].includes(error?.code)) throw error
      throw fail('SEO_ADVISOR_SELECTION_FAILED')
    }
  }

  return {
    recover(error) {
      if (disposed || error?.code !== 'ADVISOR_TENANT_SELECTION_REQUIRED' || session.advisorScope !== 'advisor_identity') return false
      attempt ??= select()
      return attempt
    },
    dispose() { disposed = true },
  }
}
