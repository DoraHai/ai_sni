export function loginAccountSummary(stats) {
  const valid = value => Number.isSafeInteger(value) && value >= 0;
  if (!stats || !valid(stats.account_count) || !valid(stats.active_count) || stats.active_count > stats.account_count) {
    return {count:'统计未提供', login:'最近登录统计未提供'};
  }
  return {count:`${stats.account_count} 个 · 启用 ${stats.active_count}`,
    login: stats.last_login_at ? `最近登录 ${stats.last_login_at}` : stats.account_count === 0 ? '尚未绑定账号' : '已绑定账号尚无登录记录'};
}
