import { computed, reactive } from 'vue'

// 轻量会话 store(规模不大,不引 pinia)。token/user 持久化 localStorage,
// 当前客户(tenantId)持久化 sessionStorage(每个标签页可以看不同客户)。
// 权限：user.permissions = {菜单key: 'view'|'edit'}（自定义角色 RBAC）。
// 「记住我」：勾选=localStorage(跨重启)，不勾=sessionStorage(关页即失效)
const _activeStore = () => (localStorage.getItem('sem_token') ? localStorage : sessionStorage)
const state = reactive({
  token: localStorage.getItem('sem_token') || sessionStorage.getItem('sem_token') || '',
  user: JSON.parse(localStorage.getItem('sem_user') || sessionStorage.getItem('sem_user') || 'null'),
  tenants: [],
  tenantId: Number(sessionStorage.getItem('sem_tenant_id')) || null,
  modules: [],
})

export const session = {
  get token() { return state.token },
  get user() { return state.user },
  get tenants() { return state.tenants },
  get tenantId() { return state.tenantId },
  get modules() { return state.modules },

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
    store.setItem('sem_token', token)
    store.setItem('sem_user', JSON.stringify(user))
    other.removeItem('sem_token')
    other.removeItem('sem_user')
    // 绑定了单客户的账号锁定该客户
    if (user?.tenant_id) this.setTenant(user.tenant_id)
  },

  // 登录态校验后用最新 user 刷新（角色权限可能被管理员改过，即时生效）
  refreshUser(user) {
    state.user = user
    _activeStore().setItem('sem_user', JSON.stringify(user))
    if (user?.tenant_id) this.setTenant(user.tenant_id)
  },

  setTenants(list) {
    state.tenants = list
    if (!state.tenantId || !list.some((t) => t.id === state.tenantId)) {
      this.setTenant(list[0]?.id ?? null)
    }
  },

  setModules(list) {
    state.modules = list || []
  },

  setTenant(id) {
    state.tenantId = id
    if (id) sessionStorage.setItem('sem_tenant_id', String(id))
    else sessionStorage.removeItem('sem_tenant_id')
  },

  logout() {
    state.token = ''
    state.user = null
    state.tenants = []
    for (const s of [localStorage, sessionStorage]) {
      s.removeItem('sem_token')
      s.removeItem('sem_user')
    }
  },
}

// 视图里 watch 用:当前客户变化触发重新拉数
export const currentTenantId = computed(() => state.tenantId)
