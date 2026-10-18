export function isAdvisorRole(role) {
  if (!role || (role.is_system && role.name === '管理员')) return false
  if (typeof role.is_advisor === 'boolean') return role.is_advisor
  const p = role.permissions || {}
  if (Object.entries(p).some(([k, v]) => k.startsWith('settings.') && v === 'edit')) return false
  return (p['seo.site'] === 'edit' && p['seo.content'] === 'edit')
    || (p['geo.assets'] === 'edit' && p['geo.content'] === 'edit')
}

export function advisorTenantPatch(ids, defaultId) {
  const tenantIds = [...new Set(ids)]
  if (!tenantIds.length) throw Error('至少勾选 1 个客户')
  if (tenantIds.some(id => !Number.isSafeInteger(id) || id <= 0)) throw Error('请选择有效客户')
  if (!tenantIds.includes(defaultId)) throw Error('默认客户必须在已勾选的客户内')
  return { tenant_ids: tenantIds, default_tenant_id: defaultId }
}

export function advisorTenantLabel(row, tenants, advisor = row.is_advisor) {
  if (!advisor) return row.tenant_name || '全部客户'
  const name = id => tenants.find(t => t.id === id)?.name || `客户 #${id}`
  if (!row.tenant_ids?.length) return '未分配客户'
  return `${row.tenant_ids.map(name).join('、')}（默认：${name(row.default_tenant_id)}）`
}
