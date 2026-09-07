import { createGeoReadonlyClient, validateGeoPeriodContext } from './readonly-client.mjs'

const GEO_READS = Object.freeze([
  'periodContext', 'metrics', 'dictionary', 'answers', 'answerDetail', 'questions',
])

function fail(code, message, status) {
  const error = new Error(message)
  error.code = code
  if (status !== undefined) error.status = status
  throw error
}

function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value) }
function positive(value) { return Number.isSafeInteger(value) && value > 0 }
function canView(permissions) { return permissions?.['geo.content'] === 'view' || permissions?.['geo.content'] === 'edit' }
function validWeekEnd(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const instant = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(instant.valueOf()) && instant.toISOString().slice(0, 10) === value && instant.getUTCDay() === 1
}

function authorizationRevision(user, tenant, weekEnd) {
  return JSON.stringify({ user_id: user.id, tenant_id: tenant.id, week_end: weekEnd,
    geo_content: user.permissions['geo.content'], tenant_name: tenant.name })
}

async function readJson(transport, path, signal, { forbiddenCode = 'NOT_AUTHORIZED', forbiddenMessage = '当前身份无权读取 GEO 资格' } = {}) {
  const response = await transport(path, { method: 'GET', cache: 'no-store', signal })
  if (response.status === 401) fail('NOT_AUTHENTICATED', '登录态已失效', 401)
  if (response.status === 403) fail(forbiddenCode, forbiddenMessage, 403)
  if (!response.ok) fail('PREFLIGHT_FAILED', `GEO 资格预检失败（${response.status}）`, response.status)
  try { return await response.json() } catch (error) {
    if (error?.code) throw error
    fail('PREFLIGHT_CONTRACT_MISMATCH', 'GEO 资格预检响应不是有效 JSON')
  }
}

function validateTenantList(data, tenantId, boundTenantId) {
  if (!object(data) || !Array.isArray(data.tenants)) fail('PREFLIGHT_CONTRACT_MISMATCH', 'GEO 客户范围响应结构无效')
  const ids = data.tenants.map(row => row?.id)
  if (new Set(ids).size !== ids.length || data.tenants.some(row => !object(row) || !positive(row.id)
      || typeof row.name !== 'string' || !row.name.trim())) {
    fail('PREFLIGHT_CONTRACT_MISMATCH', 'GEO 客户范围含无效或重复客户')
  }
  if (boundTenantId !== null && data.tenants.some(row => row.id !== boundTenantId)) {
    fail('PREFLIGHT_CONTRACT_MISMATCH', 'GEO 客户范围超出当前账号绑定客户')
  }
  const tenant = data.tenants.find(row => row.id === tenantId)
  if (!tenant) fail('TENANT_NOT_ALLOWED', '所选客户不在当前身份可用的 GEO 客户范围内')
  return tenant
}

export async function resolveGeoReadonlyContext({ transport, tenantId, weekEnd, signal, assertCurrent = () => {} }) {
  if (typeof transport !== 'function') throw new TypeError('transport must be a function')
  if (typeof assertCurrent !== 'function') throw new TypeError('assertCurrent must be a function')
  if (!positive(tenantId)) fail('INVALID_TENANT', '请选择有效客户')
  if (!validWeekEnd(weekEnd)) fail('INVALID_WEEK', '请选择有效的已结束自然周周一边界')
  const step = async (path, options) => {
    assertCurrent()
    const value = await readJson(transport, path, signal, options)
    assertCurrent()
    return value
  }

  const me = await step('/api/v1/auth/me')
  const user = me?.user
  if (!object(user) || !positive(user.id) || !object(user.permissions)
      || (user.tenant_id !== null && !positive(user.tenant_id))) {
    fail('PREFLIGHT_CONTRACT_MISMATCH', '需要已登录的普通用户及完整权限信息')
  }
  if (user.tenant_id !== null && user.tenant_id !== tenantId) fail('TENANT_NOT_ALLOWED', '当前账号未绑定所选客户')
  if (!canView(user.permissions)) fail('NO_GEO_READS', '当前账号没有 GEO 内容只读权限')

  // This GEO-owned route already limits the list to active/trial, unexpired
  // GEO entitlements and respects a user's bound tenant.
  const tenants = await step('/api/v1/geo/tenants')
  const tenant = validateTenantList(tenants, tenantId, user.tenant_id)

  // Do not replace this probe with auth/modules. The production endpoint runs
  // GEO's per-request entitlement dependency for the exact tenant and week.
  const periodPath = `/api/v1/geo/integration/read/period-context?tenant_id=${tenantId}&week_end=${weekEnd}`
  const periodContext = await step(periodPath, {
    forbiddenCode: 'GEO_SCOPE_NOT_ALLOWED',
    forbiddenMessage: '所选客户未开通 GEO、已停用、已到期或不在当前身份范围内',
  })
  try { validateGeoPeriodContext(periodContext, { tenantId, weekEnd }) } catch (error) {
    if (error?.code === 'CONTRACT_MISMATCH') fail('PREFLIGHT_CONTRACT_MISMATCH', 'GEO 周期探针响应结构或范围无效')
    throw error
  }
  const revision = authorizationRevision(user, tenant, weekEnd)
  return Object.freeze({ tenantId, weekEnd, userId: user.id, authorizationRevision: revision,
    allowedReads: GEO_READS, identity: Object.freeze({ user, tenant, periodContext }) })
}

export function createGeoAuthorizedClient({ transport, onClear }) {
  const client = createGeoReadonlyClient({ transport, onClear })
  let generation = 0
  const connecting = new Set()
  function invalidate() {
    generation++
    for (const controller of connecting) controller.abort()
    connecting.clear()
    client.invalidate()
  }
  return Object.freeze({
    async connect({ tenantId, weekEnd }) {
      invalidate()
      const started = generation
      const controller = new AbortController()
      connecting.add(controller)
      const assertCurrent = () => {
        if (controller.signal.aborted || generation !== started) fail('STALE_AUTHORIZATION', '已丢弃旧客户、旧周期或已失效的 GEO 资格预检')
      }
      try {
        const context = await resolveGeoReadonlyContext({ transport, tenantId, weekEnd,
          signal: controller.signal, assertCurrent })
        assertCurrent(); client.setContext(context); assertCurrent()
        return context
      } catch (error) {
        assertCurrent()
        throw error
      } finally { connecting.delete(controller) }
    },
    invalidate,
    read: client.read,
    officialSnapshot: client.officialSnapshot,
    answerView: client.answerView,
  })
}
