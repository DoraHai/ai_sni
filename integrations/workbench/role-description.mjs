// Describe the permissions supplied by the server; never infer or grant access.
const labels = {'sem.assets':'推广账号','seo.assets':'网站管理','geo.assets':'项目管理'};
export function roleDescription(role, menus = []) {
  if (role.name !== '品牌方客户') return role.description || '';
  const editable = Object.entries(role.permissions || {}).filter(([, level]) => level === 'edit')
    .map(([key]) => menus.find(menu => menu.key === key)?.label || labels[key] || key);
  return editable.length
    ? `通常绑定单客户；可编辑：${editable.join('、')}；其余已授权项仅查看。具体操作仍受业务权限限制。`
    : '通常绑定单客户；已授权项仅查看。具体操作仍受业务权限限制。';
}
