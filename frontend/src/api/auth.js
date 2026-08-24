import client from './client'

export function login({ username, password }) {
  return client.post('/api/v1/auth/login', { username, password })
}

export function fetchMe() {
  return client.get('/api/v1/auth/me')
}

export function fetchTenants(module = null) {
  return client.get('/api/v1/auth/tenants', {
    params: module ? { module } : undefined,
  })
}

export function fetchModules() {
  return client.get('/api/v1/auth/modules')
}

export function changePassword({ oldPassword, newPassword }) {
  return client.patch('/api/v1/auth/password', {
    old_password: oldPassword,
    new_password: newPassword,
  })
}

// ===== 账号管理(仅管理员) =====
export function fetchUsers() {
  return client.get('/api/v1/users')
}

export function createUser({ username, password, displayName, roleId, tenantId }) {
  return client.post('/api/v1/users', {
    username, password, display_name: displayName || undefined, role_id: roleId,
    tenant_id: tenantId ?? undefined,
  })
}

export function updateUser(userId, patch) {
  return client.patch(`/api/v1/users/${userId}`, patch)
}
