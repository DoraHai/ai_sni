import { createSemReadonlyClient } from './readonly-client.mjs'

const READ_PERMISSIONS = Object.freeze({
  report: 'monitor.dashboard',
  keywords: 'optimize.keywords',
  keywordDetail: 'optimize.keywords',
  searchTerms: 'optimize.searchterms',
})

function fail(code, message, status) {
  const error = new Error(message)
  error.code = code
  if (status !== undefined) error.status = status
  throw error
}

function positive(value) {
  return Number.isSafeInteger(value) && value > 0
}

function canView(permissions, key) {
  return permissions?.[key] === 'view' || permissions?.[key] === 'edit'
}

function revisionFor(user, tenantId, module, permissions) {
  const grants = Object.entries(permissions).sort(([left], [right]) => left.localeCompare(right))
  return JSON.stringify({ user_id: user.id, tenant_id: tenantId, sem_status: module.status,
    sem_expires_at: module.expires_at ?? null, grants })
}

async function readJson(transport, path) {
  const response = await transport(path, { method: 'GET', cache: 'no-store' })
  if (response.status === 401) fail('NOT_AUTHENTICATED', '登录态已失效', 401)
  if (response.status === 403) fail('NOT_AUTHORIZED', '当前身份无权读取 SEM 资格', 403)
  if (!response.ok) fail('PREFLIGHT_FAILED', `资格预检失败（${response.status}）`, response.status)
  try {
    return await response.json()
  } catch {
    fail('PREFLIGHT_CONTRACT_MISMATCH', '资格预检响应不是有效 JSON')
  }
}

export async function resolveSemReadonlyContext({ transport, tenantId }) {
  if (typeof transport !== 'function') throw new TypeError('transport must be a function')
  if (!positive(tenantId)) fail('INVALID_TENANT', '请选择有效客户')

  // Do not probe business routes until identity, module and tenant eligibility pass.
  const me = await readJson(transport, '/api/v1/auth/me')
  const user = me?.user
  if (!user || !positive(user.id) || !user.permissions || typeof user.permissions !== 'object') {
    fail('PREFLIGHT_CONTRACT_MISMATCH', '当前登录用户信息不完整')
  }
  if (user.tenant_id !== null && user.tenant_id !== tenantId) fail('TENANT_NOT_ALLOWED', '当前账号未绑定所选客户')

  const modules = await readJson(transport, '/api/v1/auth/modules')
  const semModule = Array.isArray(modules?.modules) ? modules.modules.find(item => item?.module_code === 'sem') : null
  if (!semModule?.available) fail('SEM_NOT_AVAILABLE', '所选身份未取得可用的 SEM 模块资格')

  const tenants = await readJson(transport, '/api/v1/auth/tenants?module=sem')
  const tenant = Array.isArray(tenants?.tenants) ? tenants.tenants.find(item => item?.id === tenantId) : null
  if (!tenant) fail('TENANT_NOT_ALLOWED', '所选客户不在当前身份的 SEM 客户范围内')
  if (tenant.sem_identity?.status === 'blocked') {
    fail('SEM_IDENTITY_BLOCKED', tenant.sem_identity.message || '所选客户的 SEM 身份不可用')
  }

  const allowedReads = Object.entries(READ_PERMISSIONS)
    .filter(([, permission]) => canView(user.permissions, permission)).map(([resource]) => resource)
  return Object.freeze({ tenantId, userId: user.id,
    authorizationRevision: revisionFor(user, tenantId, semModule, user.permissions),
    allowedReads: Object.freeze(allowedReads), identity: Object.freeze({ user, module: semModule, tenant }) })
}

export function createSemAuthorizedClient({ transport, onClear }) {
  const client = createSemReadonlyClient({ transport, onClear })
  return Object.freeze({
    async connect(tenantId) {
      client.invalidate()
      const context = await resolveSemReadonlyContext({ transport, tenantId })
      client.setContext(context)
      return context
    },
    invalidate: client.invalidate,
    read: client.read,
  })
}
