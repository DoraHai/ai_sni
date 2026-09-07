import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createLatestRequestGuard } from '../src/utils/latestRequest.js'

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
