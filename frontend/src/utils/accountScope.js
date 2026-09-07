export function chooseSemAccount(accounts, currentAccountId = null) {
  const readable = (accounts || []).filter((row) => row.status !== 'archived')
  if (readable.some((row) => Number(row.id) === Number(currentAccountId))) return currentAccountId
  const active = readable.filter((row) => row.status === 'active')
  return active.length === 1 ? active[0].id : null
}

export function matchesAccountScope(scope, accountId) {
  if (!scope) return false
  return accountId == null
    ? scope.mode === 'all' && scope.baidu_account_id == null
    : scope.mode === 'single' && Number(scope.baidu_account_id) === Number(accountId)
}

export function canWriteScopedAsset({ scope, selectedAccountId, activeAccountIds, assetAccountId }) {
  return matchesAccountScope(scope, selectedAccountId)
    && selectedAccountId != null
    && activeAccountIds.has(Number(selectedAccountId))
    && Number(assetAccountId) === Number(selectedAccountId)
}
