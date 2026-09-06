import { createSeoReadonlyClient } from './readonly-client.mjs'

const READ_PERMISSIONS = Object.freeze({
  contents: 'seo.content',
  reviewHistory: 'seo.content',
  publications: 'seo.content',
  attempts: 'seo.content',
  pages: 'seo.site',
  imageEvidence: 'seo.site',
})

function fail(code, message, status) {
  const error = new Error(message)
  error.code = code
  if (status !== undefined) error.status = status
  throw error
}

function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value) }
function positive(value) { return Number.isSafeInteger(value) && value > 0 }
function nonnegative(value) { return Number.isSafeInteger(value) && value >= 0 }
function canView(permissions, key) { return permissions?.[key] === 'view' || permissions?.[key] === 'edit' }
function countObject(value) {
  return object(value) && Object.values(value).every(nonnegative)
}

function revisionFor(user, tenantId, siteId, module, permissions) {
  const grants = Object.entries(permissions).filter(([key]) => key.startsWith('seo.'))
    .sort(([left], [right]) => left.localeCompare(right))
  return JSON.stringify({ user_id: user.id, tenant_id: tenantId, site_id: siteId,
    seo_status: module.status, seo_expires_at: module.expires_at ?? null, grants })
}

async function readJson(transport, path, signal) {
  const response = await transport(path, { method: 'GET', cache: 'no-store', signal })
  if (response.status === 401) fail('NOT_AUTHENTICATED', '登录态已失效', 401)
  if (response.status === 403) fail('NOT_AUTHORIZED', '当前身份无权读取 SEO 资格', 403)
  if (!response.ok) fail('PREFLIGHT_FAILED', `SEO 资格预检失败（${response.status}）`, response.status)
  try { return await response.json() } catch (error) {
    if (error?.code) throw error
    fail('PREFLIGHT_CONTRACT_MISMATCH', 'SEO 资格预检响应不是有效 JSON')
  }
}

async function verifySiteScope({ transport, tenantId, siteId, permissions, signal, step }) {
  const useContents = canView(permissions, 'seo.content')
  const usePages = canView(permissions, 'seo.site')
  if (!useContents && !usePages) fail('NO_SEO_READS', '当前账号没有首期 SEO 内容或页面只读权限')
  const path = useContents
    ? `/api/v1/seo/content-assets?tenant_id=${tenantId}&site_id=${siteId}&page=1&page_size=1`
    : `/api/v1/seo/site-pages?tenant_id=${tenantId}&site_id=${siteId}&page=1&page_size=1`
  let response
  try {
    response = await transport(path, { method: 'GET', cache: 'no-store', signal })
  } catch (error) {
    throw error
  }
  step()
  if (response.status === 401) fail('NOT_AUTHENTICATED', '登录态已失效', 401)
  if (response.status === 403) fail('SITE_SCOPE_NOT_ALLOWED', '所选客户、SEO 模块或读取权限已失效', 403)
  if (response.status === 404) fail('SITE_NOT_ALLOWED', '所选 SEO 站点不属于当前客户或不存在', 404)
  if (!response.ok) fail('SITE_PREFLIGHT_FAILED', `SEO 站点核验失败（${response.status}）`, response.status)
  let data
  try { data = await response.json() } catch (error) {
    if (error?.code) throw error
    fail('PREFLIGHT_CONTRACT_MISMATCH', 'SEO 站点核验响应不是有效 JSON')
  }
  step()
  if (!object(data) || !Array.isArray(data.items) || !nonnegative(data.total) ||
      data.page !== 1 || data.page_size !== 1 || data.items.length > 1 || data.items.length > data.total) {
    fail('PREFLIGHT_CONTRACT_MISMATCH', 'SEO 站点核验响应结构无效')
  }
  for (const item of data.items) {
    if (!object(item) || !positive(item.id) || item.tenant_id !== tenantId || item.site_id !== siteId) {
      fail('PREFLIGHT_CONTRACT_MISMATCH', 'SEO 站点核验返回了无效对象或其他客户/站点的数据')
    }
  }
  if (useContents && (!countObject(data.status_counts) ||
      Object.values(data.status_counts).reduce((sum, value) => sum + value, 0) !== data.total)) {
    fail('PREFLIGHT_CONTRACT_MISMATCH', 'SEO 内容核验统计缺失或与总数不符')
  }
  if (!useContents && (!object(data.stats) || !nonnegative(data.stats.total) || data.stats.total !== data.total)) {
    fail('PREFLIGHT_CONTRACT_MISMATCH', 'SEO 页面核验统计缺失或与总数不符')
  }
  return Object.freeze({ resource: useContents ? 'contents' : 'pages', empty: data.items.length === 0 })
}

export async function resolveSeoReadonlyContext({ transport, tenantId, siteId, signal, assertCurrent = () => {} }) {
  if (typeof transport !== 'function') throw new TypeError('transport must be a function')
  if (typeof assertCurrent !== 'function') throw new TypeError('assertCurrent must be a function')
  if (!positive(tenantId)) fail('INVALID_TENANT', '请选择有效客户')
  if (!positive(siteId)) fail('INVALID_SITE', '请选择有效 SEO 站点')
  const step = async path => {
    assertCurrent()
    const value = await readJson(transport, path, signal)
    assertCurrent()
    return value
  }

  const me = await step('/api/v1/auth/me')
  const user = me?.user
  if (!user || !positive(user.id) || !object(user.permissions) ||
      (user.tenant_id !== null && !positive(user.tenant_id))) {
    fail('PREFLIGHT_CONTRACT_MISMATCH', '需要已登录的普通用户及完整权限信息')
  }
  if (user.tenant_id !== null && user.tenant_id !== tenantId) fail('TENANT_NOT_ALLOWED', '当前账号未绑定所选客户')

  const modules = await step('/api/v1/auth/modules')
  if (modules?.tenant_id !== user.tenant_id) fail('PREFLIGHT_CONTRACT_MISMATCH', '模块资格与当前用户范围不一致')
  const seoModule = Array.isArray(modules?.modules) ? modules.modules.find(item => item?.module_code === 'seo') : null
  if (!seoModule || typeof seoModule.status !== 'string' || seoModule.available !== true) {
    fail('SEO_NOT_AVAILABLE', '所选身份未取得可用的 SEO 模块资格')
  }

  const tenants = await step('/api/v1/auth/tenants?module=seo')
  if (tenants?.module !== 'seo') fail('PREFLIGHT_CONTRACT_MISMATCH', '客户资格不是 SEO 范围')
  const tenant = Array.isArray(tenants?.tenants) ? tenants.tenants.find(item => item?.id === tenantId) : null
  if (!tenant) fail('TENANT_NOT_ALLOWED', '所选客户不在当前身份的 SEO 客户范围内')

  const allowedReads = Object.entries(READ_PERMISSIONS)
    .filter(([, permission]) => canView(user.permissions, permission)).map(([resource]) => resource)
  assertCurrent()
  const siteVerification = await verifySiteScope({ transport, tenantId, siteId,
    permissions: user.permissions, signal, step: assertCurrent })
  assertCurrent()
  return Object.freeze({ tenantId, siteId, userId: user.id,
    authorizationRevision: revisionFor(user, tenantId, siteId, seoModule, user.permissions),
    allowedReads: Object.freeze(allowedReads),
    identity: Object.freeze({ user, module: seoModule, tenant, siteVerification }) })
}

export function createSeoAuthorizedClient({ transport, onClear }) {
  const client = createSeoReadonlyClient({ transport, onClear })
  let generation = 0
  const connecting = new Set()
  function invalidate() {
    generation++
    for (const controller of connecting) controller.abort()
    connecting.clear()
    client.invalidate()
  }
  return Object.freeze({
    async connect({ tenantId, siteId }) {
      invalidate()
      const started = generation
      const controller = new AbortController()
      connecting.add(controller)
      const assertCurrent = () => {
        if (controller.signal.aborted || generation !== started) {
          fail('STALE_AUTHORIZATION', '已丢弃旧客户、旧站点或已失效的 SEO 资格预检')
        }
      }
      try {
        const context = await resolveSeoReadonlyContext({ transport, tenantId, siteId,
          signal: controller.signal, assertCurrent })
        assertCurrent()
        client.setContext(context)
        assertCurrent()
        return context
      } catch (error) {
        assertCurrent()
        throw error
      } finally {
        connecting.delete(controller)
      }
    },
    invalidate,
    read: client.read,
    snapshot: client.snapshot,
  })
}
