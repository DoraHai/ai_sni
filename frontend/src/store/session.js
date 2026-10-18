import { computed, reactive } from 'vue'
import { advisorClaims } from '../utils/geoAdvisorTenant.js'
import { selectStoredAuth, writeAuthEnvelope, clearStoredAuth } from './sessionStorage.js'

export const AUTH_CONTEXT_EVENT = 'sem:auth-context-changed'

function notifyAuthContext(kind) {
  if (typeof window === 'undefined' || typeof window.dispatchEvent !== 'function') return
  const event = new Event(AUTH_CONTEXT_EVENT)
  Object.defineProperty(event, 'detail', { value: { kind } })
  window.dispatchEvent(event)
}

// 轻量会话 store(规模不大,不引 pinia)。token/user 持久化 localStorage,
// 当前客户(tenantId)持久化 sessionStorage(每个标签页可以看不同客户)。
// 权限：user.permissions = {菜单key: 'view'|'edit'}（自定义角色 RBAC）。
// 「记住我」：勾选=localStorage(跨重启)，不勾=sessionStorage(关页即失效)
const initialAuth = selectStoredAuth(localStorage, sessionStorage)
let authStorage = initialAuth?.storage
const _activeStore = () => (authStorage === 'local' ? localStorage : sessionStorage)
const advisorTenantId = (token) => {
  const claims = advisorClaims(token)
  return claims?.scope_kind === 'advisor_tenant' ? claims.tid : null
}
const state = reactive({
  token: initialAuth?.token || '',
  user: initialAuth?.user || null,
  tenants: [],
  tenantId: advisorClaims(initialAuth?.token) ? advisorTenantId(initialAuth.token)
    : Number(sessionStorage.getItem('sem_tenant_id')) || null,
})

export const session = {
  get token() { return state.token },
  get user() { return state.user },
  get tenants() { return state.tenants },
  get tenantId() { return state.tenantId },

  get isLoggedIn() { return !!state.token },
  get permissions() { return state.user?.permissions || {} },

  // 菜单权限：返回 'view' | 'edit' | undefined
  level(key) { return state.user?.permissions?.[key] },
  canView(key) { const l = state.user?.permissions?.[key]; return l === 'view' || l === 'edit' },
  canEdit(key) { return state.user?.permissions?.[key] === 'edit' },
  // 账号与权限管理权（替代旧 isAdmin）
  get canManage() { return state.user?.permissions?.['settings.accounts'] === 'edit' },

  setAuth(token, user, remember = true) {
    state.token = token
    state.user = user
    const store = remember ? localStorage : sessionStorage
    const other = remember ? sessionStorage : localStorage
    writeAuthEnvelope(store, token, user)
    clearStoredAuth(other)
    authStorage = remember ? 'local' : 'session'
    sessionStorage.removeItem('sem_advisor_identity_v1')
    // 绑定了单客户的账号锁定该客户
    if (advisorClaims(token)) this.setTenant(advisorTenantId(token))
    else if (user?.tenant_id) this.setTenant(user.tenant_id)
    notifyAuthContext('identity')
  },

  replaceAuthForAdvisorTenant(token, tenantId) {
    const claims = advisorClaims(token)
    if (advisorClaims(state.token)?.scope_kind !== 'advisor_identity'
        || claims?.scope_kind !== 'advisor_tenant' || claims.tid !== tenantId
        || String(claims.sub) !== String(state.user?.id)
        || !Number.isSafeInteger(claims.gid) || claims.gid <= 0) {
      throw new TypeError('INVALID_ADVISOR_TENANT_RESPONSE')
    }
    sessionStorage.setItem('sem_advisor_identity_v1', JSON.stringify({ token: state.token, user: state.user }))
    writeAuthEnvelope(sessionStorage, token, state.user)
    authStorage = 'session'
    state.token = token
    this.setTenant(tenantId)
    notifyAuthContext('identity')
  },

  // 登录态校验后用最新 user 刷新（角色权限可能被管理员改过，即时生效）
  refreshUser(user) {
    state.user = user
    writeAuthEnvelope(_activeStore(), state.token, user)
    if (advisorClaims(state.token)) this.setTenant(advisorTenantId(state.token))
    else if (user?.tenant_id) this.setTenant(user.tenant_id)
    notifyAuthContext('permissions')
  },

  setTenants(list) {
    state.tenants = list
    if (advisorClaims(state.token) || state.user?.is_advisor) return
    if (state.tenantId && list.some((t) => t.id === state.tenantId)) return
    const stored = Number(sessionStorage.getItem('sem_tenant_id') || 0)
    if (stored && list.some((t) => t.id === stored)) {
      this.setTenant(stored)
      return
    }
    this.setTenant(list[0]?.id ?? null)
  },

  setTenant(id) {
    if (advisorClaims(state.token) && id !== advisorTenantId(state.token)) return
    state.tenantId = id
    if (id) sessionStorage.setItem('sem_tenant_id', String(id))
    else sessionStorage.removeItem('sem_tenant_id')
  },

  logout() {
    state.token = ''
    state.user = null
    state.tenants = []
    this.setTenant(null)
    for (const s of [localStorage, sessionStorage]) {
      clearStoredAuth(s)
    }
    sessionStorage.removeItem('sem_advisor_identity_v1')
    notifyAuthContext('logout')
  },
}

// 视图里 watch 用:当前客户变化触发重新拉数
export const currentTenantId = computed(() => state.tenantId)
