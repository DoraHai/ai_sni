const count = value => Number.isSafeInteger(value) && value >= 0;
const positive = value => Number.isSafeInteger(value) && value > 0;
const timestamp = value => typeof value === 'string' && /^\d{4}-\d\d-\d\dT/.test(value) && Number.isFinite(Date.parse(value));
const zero = () => ({account_count:0,active_count:0,last_login_at:null});

// /users is an unpaginated list in the deployed contract. Reject explicit partial
// responses, pagination and invalid rows rather than manufacturing a complete count.
export function groupLoginAccounts(response) {
  if (!response || !Array.isArray(response.users) ||
      response.truncated || response.partial || response.has_more || response.next_cursor || response.next ||
      response.pagination != null || response.state != null && response.state !== 'available' ||
      response.total != null && response.total !== response.users.length) return null;
  const groups = new Map(), ids = new Set();
  for (const user of response.users) {
    if (!positive(user?.id) || ids.has(user.id) ||
        user.tenant_id !== null && !positive(user.tenant_id) ||
        typeof user.is_active !== 'boolean' ||
        user.last_login_at !== null && !timestamp(user.last_login_at)) return null;
    ids.add(user.id);
    if (user.tenant_id === null) continue;
    const stats = groups.get(user.tenant_id) || zero();
    stats.account_count++;
    if (user.is_active) stats.active_count++;
    if (user.last_login_at && (!stats.last_login_at || Date.parse(user.last_login_at) > Date.parse(stats.last_login_at))) stats.last_login_at = user.last_login_at;
    groups.set(user.tenant_id, stats);
  }
  return groups;
}

export function loginAccountSummary(stats, groups = null, tenantId = null) {
  const fallback = groups instanceof Map && positive(tenantId) ? groups.get(tenantId) || zero() : null;
  const provided = key => stats != null && Object.hasOwn(stats, key);
  const serverZero = provided('account_count') && stats.account_count === 0;
  const value = key => provided(key) ? stats[key] : serverZero ? zero()[key] : fallback?.[key];
  const accountCount = value('account_count'), activeCount = value('active_count'), lastLogin = value('last_login_at');
  const usedList = fallback && !serverZero && ['account_count','active_count','last_login_at'].some(key => !provided(key));
  if (!count(accountCount) || !count(activeCount) || activeCount > accountCount) {
    return {count:'统计未提供',login:'最近登录统计未提供',source:''};
  }
  return {count:`${accountCount} 个 · 启用 ${activeCount}`,
    login: accountCount === 0 ? '尚未绑定账号' : timestamp(lastLogin) ? `最近登录 ${lastLogin}` : lastLogin === null ? '已绑定账号尚无登录记录' : '最近登录统计未提供',
    source: usedList ? '按账号清单统计' : ''};
}
