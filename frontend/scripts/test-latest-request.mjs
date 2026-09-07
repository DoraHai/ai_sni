import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createLatestRequestGuard } from '../src/utils/latestRequest.js'
import { canWriteScopedAsset, chooseSemAccount, matchesAccountScope } from '../src/utils/accountScope.js'

let context = { tenantId: 1, accountId: 11 }
const guard = createLatestRequestGuard(() => context)

const first = guard.begin()
const second = guard.begin()
assert.equal(first.isCurrent(), false, 'a newer request must invalidate an older request')
assert.equal(second.isCurrent(), true)

context = { tenantId: 2, accountId: 21 }
assert.equal(second.isCurrent(), false, 'a tenant/account switch must invalidate an old response')

const third = guard.begin()
assert.equal(third.isCurrent(), true)
guard.invalidate()
assert.equal(third.isCurrent(), false, 'explicit invalidation must reject an in-flight response')

const accounts = [
  { id: 11, status: 'active' },
  { id: 12, status: 'active' },
  { id: 13, status: 'disabled' },
  { id: 14, status: 'archived' },
]
assert.equal(chooseSemAccount(accounts), null, 'multiple active accounts must default to all-account read mode')
assert.equal(chooseSemAccount(accounts, 13), 13, 'disabled accounts remain selectable for historical reads')
assert.equal(chooseSemAccount([{ id: 21, status: 'active' }, { id: 22, status: 'disabled' }]), 21)
assert.equal(matchesAccountScope({ mode: 'all', baidu_account_id: null }, null), true)
assert.equal(matchesAccountScope({ mode: 'single', baidu_account_id: 11 }, 12), false)
assert.equal(canWriteScopedAsset({
  scope: { mode: 'all', baidu_account_id: null }, selectedAccountId: null,
  activeAccountIds: new Set([11, 12]), assetAccountId: 11,
}), false, 'all-account reads must not enable writes')

let actionContext = { tenantId: 1, accountId: 11, authRevision: 3 }
const actionGuard = createLatestRequestGuard(() => actionContext)
let resolveConfirmation
const confirmation = new Promise((resolve) => { resolveConfirmation = resolve })
let writes = 0
const protectedAction = (async () => {
  const attempt = actionGuard.begin()
  await confirmation
  if (!attempt.isCurrent()) return
  writes += 1
})()
actionContext = { tenantId: 1, accountId: 12, authRevision: 3 }
resolveConfirmation()
await protectedAction
assert.equal(writes, 0, 'switching account while confirmation is open must produce zero writes')

let resolveUnmountedConfirmation
const unmountedConfirmation = new Promise((resolve) => { resolveUnmountedConfirmation = resolve })
const unmountedAction = (async () => {
  const attempt = actionGuard.begin()
  await unmountedConfirmation
  if (!attempt.isCurrent()) return
  writes += 1
})()
actionGuard.invalidate()
resolveUnmountedConfirmation()
await unmountedAction
assert.equal(writes, 0, 'unmount invalidation while confirmation is open must produce zero writes')

for (const path of [
  '../src/views/optimize/SearchTermsView.vue',
  '../src/views/manage/AccountBudgetView.vue',
  '../src/views/manage/CampaignManageView.vue',
  '../src/views/optimize/KeywordWorkbenchView.vue',
]) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  assert.match(source, /createLatestRequestGuard/)
  assert.match(source, /\.begin\(\)/)
  assert.match(source, /\.isCurrent\(\)/)
}

console.log('latest request guard checks passed')
