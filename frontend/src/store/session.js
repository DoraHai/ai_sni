import { computed, reactive } from 'vue'
import {
  AUTH_CONTEXT_EVENT,
  clearStoredAuth,
  persistentAuthForEvent,
  selectStoredAuth,
  writeAuthEnvelope,
} from './sessionStorage.js'

// Ported from the SEM advisor session: hints only; APIs authorize every request.
export function advisorClaims(token) {
  try {
    const value = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return ['advisor_identity', 'advisor_tenant'].includes(value.scope_kind) ? value : null
  } catch { return null }
}

const advisorIdentityKey = 'sem_advisor_identity_v1'
const isAdvisor = (token, user) => !!advisorClaims(token) || user?.is_advisor === true
const tenantForAuth = (token, user, fallback = null) => isAdvisor(token, user)
  ? (advisorClaims(token)?.scope_kind === 'advisor_tenant' ? advisorClaims(token).tid : null)
  : (user?.tenant_id || fallback)

function clearTenantDrafts() {
  for (let i = sessionStorage.length - 1; i >= 0; i--) {
    const key = sessionStorage.key(i)
    if (key?.startsWith('seo_pending_rewrite_') || key?.startsWith('sem_builder_handoff_') || ['seo_site_tenant_id', 'seo_site_id'].includes(key)) {
      sessionStorage.removeItem(key)
    }
  }
}

// 轻量会话 store(规模不大,不引 pinia)。token/user 持久化 localStorage,
// 当前客户(tenantId)持久化 sessionStorage(每个标签页可以看不同客户)。
// 权限：user.permissions = {菜单key: 'view'|'edit'}（自定义角色 RBAC）。
// 「记住我」：勾选=localStorage(跨重启)，不勾=sessionStorage(关页即失效)
const initialAuth = selectStoredAuth(localStorage, sessionStorage)
let authStorage = initialAuth?.storage ?? null
const _activeStore = () => (authStorage === 'local' ? localStorage : sessionStorage)
const initialTenantId = Number(sessionStorage.getItem('sem_tenant_id')) || null
const state = reactive({
  token: initialAuth?.token ?? '',
  user: initialAuth?.user ?? null,
  tenants: [],
  tenantId: initialAuth ? tenantForAuth(initialAuth.token, initialAuth.user, initialTenantId) : null,
  modules: [],
  tenantListRevision: 0,
  authRevision: 0,
})

function notifyAuthContext(kind) {
  state.authRevision += 1
  if (typeof window === 'undefined') return
  const event = new Event(AUTH_CONTEXT_EVENT)
  Object.defineProperty(event, 'detail', { value: { kind, revision: state.authRevision } })
  window.dispatchEvent(event)
}

function permissionsEqual(left = {}, right = {}) {
  const leftKeys = Object.keys(left).sort()
  const rightKeys = Object.keys(right).sort()
  return leftKeys.length === rightKeys.length
    && leftKeys.every((key, index) => key === rightKeys[index] && left[key] === right[key])
}

function authContextChangeKind(previousToken, previousUser, nextToken, nextUser) {
  if (previousToken !== nextToken
      || previousUser?.id !== nextUser?.id
      || previousUser?.tenant_id !== nextUser?.tenant_id) return 'identity'
  if (!permissionsEqual(previousUser?.permissions, nextUser?.permissions)) return 'permissions'
  return null
}

export const session = {
  get token() { return state.token },
  get user() { return state.user },
  get tenants() { return state.tenants },
  get tenantId() { return state.tenantId },
  get modules() { return state.modules },
  get tenantListRevision() { return state.tenantListRevision },
  get authRevision() { return state.authRevision },
  get inboxIdentity() {
    const claims = advisorClaims(state.token)
    if (!state.token || !state.user?.id) return null
    if (!claims || claims.scope_kind === 'advisor_identity') {
      return { token: state.token, revision: state.authRevision, scopeKind: claims?.scope_kind, userId: state.user.id }
    }
    try {
      const saved = JSON.parse(sessionStorage.getItem(advisorIdentityKey) || 'null')
      const identity = advisorClaims(saved?.token)
      if (identity?.scope_kind !== 'advisor_identity' || String(identity.sub) !== String(state.user.id)
          || !(identity.exp * 1000 > Date.now())) return null
      return { token: saved.token, revision: state.authRevision, scopeKind: 'advisor_identity', userId: state.user.id }
    } catch { return null }
  },
  get isAdvisorSession() { return isAdvisor(state.token, state.user) },
  get advisorScope() { return advisorClaims(state.token)?.scope_kind ?? null },

  get isLoggedIn() { return !!state.token },
  get permissions() { return state.user?.permissions || {} },

  // 菜单权限：返回 'view' | 'edit' | undefined
  level(key) { return state.user?.permissions?.[key] },
  canView(key) { const l = state.user?.permissions?.[key]; return l === 'view' || l === 'edit' },
  canEdit(key) { return state.user?.permissions?.[key] === 'edit' },
  // 账号与权限管理权（替代旧 isAdmin）
  get canManage() { return state.user?.permissions?.['settings.accounts'] === 'edit' },

  setAuth(token, user, remember = true) {
    const previousUserId = state.user?.id
    const store = remember ? localStorage : sessionStorage
    const other = remember ? sessionStorage : localStorage
    // Persist the pair before publishing it to reactive consumers. Storage
    // listeners always re-read both values and never combine different stores.
    writeAuthEnvelope(store, token, user)
    clearStoredAuth(other)
    authStorage = remember ? 'local' : 'session'
    state.token = token
    state.user = user
    sessionStorage.removeItem(advisorIdentityKey)
    if (advisorClaims(token)?.scope_kind === 'advisor_identity') {
      sessionStorage.setItem(advisorIdentityKey, JSON.stringify({ token, user }))
    }
    // 绑定了单客户的账号锁定该客户
    if (this.isAdvisorSession) { clearTenantDrafts(); this.setTenant(tenantForAuth(token, user)) }
    else if (user?.tenant_id) this.setTenant(user.tenant_id)
    else if (previousUserId !== user?.id) this.setTenant(null)
    notifyAuthContext('identity')
  },

  replaceAuthForAdvisorTenant(token, tenantId) {
    const claims = advisorClaims(token)
    if (this.advisorScope !== 'advisor_identity'
        || claims?.scope_kind !== 'advisor_tenant' || claims.tid !== tenantId
        || String(claims.sub) !== String(state.user?.id) || !Number.isSafeInteger(claims.gid) || claims.gid <= 0) {
      throw new TypeError('INVALID_ADVISOR_TENANT_RESPONSE')
    }
    sessionStorage.setItem(advisorIdentityKey, JSON.stringify({ token: state.token, user: state.user }))
    clearTenantDrafts()
    // Business context belongs to this tab; never publish it through localStorage.
    writeAuthEnvelope(sessionStorage, token, state.user)
    authStorage = 'session'
    state.token = token
    state.tenants = []
    state.modules = []
    state.tenantListRevision += 1
    this.setTenant(tenantId)
    notifyAuthContext('identity')
  },

  // 登录态校验后用最新 user 刷新（角色权限可能被管理员改过，即时生效）
  refreshUser(user) {
    const previous = state.user
    const changeKind = authContextChangeKind(state.token, previous, state.token, user)
    state.user = user
    writeAuthEnvelope(_activeStore(), state.token, user)
    if (this.isAdvisorSession) this.setTenant(tenantForAuth(state.token, user))
    else if (user?.tenant_id) this.setTenant(user.tenant_id)
    if (changeKind) notifyAuthContext(changeKind)
  },

  setTenants(list) {
    state.tenants = list
    if (this.isAdvisorSession) return
    if (state.tenantId && list.some((t) => t.id === state.tenantId)) return
    const stored = Number(sessionStorage.getItem('sem_tenant_id') || 0)
    if (stored && list.some((t) => t.id === stored)) {
      this.setTenant(stored)
      return
    }
    this.setTenant(list[0]?.id ?? null)
  },

  setModules(list) {
    state.modules = list || []
  },

  requestTenantReload() {
    state.tenantListRevision += 1
  },

  setTenant(id) {
    if (this.isAdvisorSession && id !== tenantForAuth(state.token, state.user)) return
    state.tenantId = id
    if (id) sessionStorage.setItem('sem_tenant_id', String(id))
    else sessionStorage.removeItem('sem_tenant_id')
  },

  logout() {
    const wasAdvisor = this.isAdvisorSession
    authStorage = null
    state.token = ''
    state.user = null
    state.tenants = []
    state.modules = []
    state.tenantId = null
    for (const s of [localStorage, sessionStorage]) clearStoredAuth(s)
    sessionStorage.removeItem('sem_tenant_id')
    sessionStorage.removeItem(advisorIdentityKey)
    if (wasAdvisor) clearTenantDrafts()
    notifyAuthContext('logout')
  },
}

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    const next = persistentAuthForEvent({
      event,
      localStore: localStorage,
      sessionStore: sessionStorage,
      currentStorage: authStorage,
    })
    if (next === undefined) return
    if (next === null) {
      if (!state.token && !state.user) return
      authStorage = null
      state.token = ''
      state.user = null
      state.tenants = []
      state.modules = []
      state.tenantId = null
      sessionStorage.removeItem('sem_tenant_id')
      notifyAuthContext('logout')
      return
    }
    const previousToken = state.token
    const previousUser = state.user
    const previousUserId = previousUser?.id
    const previousTenantId = state.tenantId
    const changeKind = authContextChangeKind(previousToken, previousUser, next.token, next.user)
    authStorage = 'local'
    state.token = next.token
    state.user = next.user
    if (!changeKind) return
    state.tenants = []
    state.modules = []
    state.tenantId = tenantForAuth(next.token, next.user,
      previousUserId === next.user.id ? previousTenantId : null)
    if (state.tenantId) sessionStorage.setItem('sem_tenant_id', String(state.tenantId))
    else sessionStorage.removeItem('sem_tenant_id')
    state.tenantListRevision += 1
    notifyAuthContext(changeKind)
  })
}

// 视图里 watch 用:当前客户变化触发重新拉数
export const currentTenantId = computed(() => state.tenantId)
