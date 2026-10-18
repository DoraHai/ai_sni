// Display/session hints only. Every API request is authorized by the server.
export function advisorClaims(token) {
  try {
    const value = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return ['advisor_identity', 'advisor_tenant'].includes(value.scope_kind) ? value : null
  } catch { return null }
}

export const advisorDeniedCodes = new Set(['ADVISOR_TENANT_NOT_GRANTED', 'ADVISOR_GRANT_REVOKED', 'ADVISOR_NO_TENANT'])
export const advisorDeniedMessage = '你没有这个客户的访问权限（可能已被收回），请切换到其他客户'
export const advisorMessages = {
  ADVISOR_MULTI_TENANT_DISABLED: '顾问多客户功能尚未开放',
  ADVISOR_NO_TENANT: '你还没有被分配客户，请联系管理员',
  ADVISOR_TENANT_NOT_GRANTED: advisorDeniedMessage,
  ADVISOR_GRANT_REVOKED: advisorDeniedMessage,
  ADVISOR_TENANT_SELECTION_REQUIRED: '请先选择客户',
  ADVISOR_GRANTS_UNAVAILABLE: '客户授权暂时无法核验，请稍后重试或联系管理员',
  ADVISOR_GRANTS_CONFLICT: '该账号的客户已被别人修改，请刷新后再改',
  ADVISOR_GRANTS_VERSION_REQUIRED: '客户授权版本缺失，请刷新后再改',
  ADVISOR_TENANT_SESSION_EXPIRED: '当前客户会话已过期，请重新选择客户',
  ADVISOR_IDENTITY_SESSION_EXPIRED: '登录已过期，请重新登录',
  TENANT_IDS_ONLY_FOR_ADVISOR: '只有顾问账号可以勾选多个客户',
  ADVISOR_TENANTS_REQUIRED: '至少勾选 1 个客户',
  ADVISOR_DEFAULT_TENANT_INVALID: '默认客户必须在已勾选的客户内',
}
