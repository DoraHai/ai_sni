import client from './client'

// 自定义角色管理（账号与权限页 · 角色 tab）。需 settings.accounts edit。
export function fetchRoles() {
  return client.get('/api/v1/roles')
}

export function createRole({ name, description, permissions }) {
  return client.post('/api/v1/roles', { name, description: description || undefined, permissions })
}

export function updateRole(roleId, patch) {
  return client.patch(`/api/v1/roles/${roleId}`, patch)
}

export function deleteRole(roleId) {
  return client.delete(`/api/v1/roles/${roleId}`)
}
