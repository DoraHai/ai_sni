import assert from 'node:assert/strict'
import './test-sem-channel-reservations.mjs'
import { readFile } from 'node:fs/promises'


async function source(path) {
  return readFile(new URL(`../${path}`, import.meta.url), 'utf8')
}

const app = await source('src/App.vue')
assert.match(app, /label: '单元管理', path: '\/manage\/adgroups', key: 'manage\.adgroups'/)

const accounts = await source('src/views/manage/SemAccountsView.vue')
assert.match(accounts, /formatUtcTimestamp\(value\)/)
assert.doesNotMatch(accounts, /last_synced_at\.slice|value\.slice\(0, 16\)/)

const adjustmentLog = await source('src/views/verify/AdjustmentLogView.vue')
assert.match(adjustmentLog, /formatLocalDate\(new Date\(today\.getFullYear\(\), today\.getMonth\(\), 1\)\)/)
assert.doesNotMatch(adjustmentLog, /toISOString\(\)\.slice\(0, 10\)/)
assert.match(adjustmentLog, /syncOperationRecords/)
assert.match(adjustmentLog, /每日 02:00 自动增量同步，可手动同步近 3 天/)
assert.match(adjustmentLog, /\['ok', 'partial'\]\.includes\(result\.status\)/)
assert.match(adjustmentLog, /accounts_succeeded/)
assert.doesNotMatch(adjustmentLog, /getOperationRecord 实时抓取/)
assert.match(adjustmentLog, /平台已写回不等于百度操作记录已同步/)
assert.match(adjustmentLog, /同步百度记录（只读）/)
assert.match(adjustmentLog, /最近平台成功回写/)
assert.match(adjustmentLog, /百度暂未返回新操作记录/)
assert.match(adjustmentLog, /Promise\.all\(\[load\(\), loadWb\(\)\]\)/)
assert.match(adjustmentLog, /generation !== operationLoadGeneration \|\| tenantId !== TENANT_ID\.value/)
assert.match(adjustmentLog, /generation !== wbLoadGeneration \|\| tenantId !== TENANT_ID\.value/)
assert.match(adjustmentLog, /data\.value = null[\s\S]*wbData\.value = null[\s\S]*approvalData\.value = null[\s\S]*actData\.value = null/)

const operationApi = await source('src/api/operations.js')
assert.match(operationApi, /client\.post\('\/api\/v1\/admin\/sync-operation-records', null,/)

const keywordWorkbench = await source('src/views/optimize/KeywordWorkbenchView.vue')
assert.match(keywordWorkbench, /const writebackMode = await fetchWritebackMode\(tenantId\)/)
assert.match(keywordWorkbench, /keywordWritebackModeState = ref\('loading'\)/)
assert.match(keywordWorkbench, /account\.live_scopes\?\.includes\('keyword_bid'\)/)
assert.match(keywordWorkbench, /确认并真实执行/)
assert.match(keywordWorkbench, /\{\{ keywordWritebackButtonLabel\(row\) \}\}/)
assert.match(keywordWorkbench, /:disabled="!keywordWritebackReady\(row\)"/)
assert.match(keywordWorkbench, /:disabled="!batchWritebackReady"/)
assert.match(keywordWorkbench, /当前关键词的回写模式尚未确认，已禁止提交/)
assert.match(keywordWorkbench, /已禁止修改匹配模式/)
assert.match(keywordWorkbench, /已禁止暂停或启用/)
assert.match(keywordWorkbench, /已禁止批量暂停或启用/)
assert.match(keywordWorkbench, /generation !== writebackModeGeneration \|\| tenantId !== TENANT_ID\.value/)
assert.match(keywordWorkbench, /watch\(TENANT_ID,[\s\S]*tableRef\.value\?\.clearSelection\(\)[\s\S]*selection\.value = \[\]/)

const roles = await source('src/views/settings/AccountsRolesView.vue')
assert.match(roles, /tenantOptions\.value = tenants\.tenants \|\| \[\]/)
assert.doesNotMatch(roles, /session\.setTenants/)
assert.doesNotMatch(roles, /GEO 开户向导/)
assert.match(roles, /formatUtcTimestamp\(v, \{ fallback: '从未登录' \}\)/)
if (roles.includes('async function submitTenant')) {
  const submitTenant = roles.slice(roles.indexOf('async function submitTenant'), roles.indexOf('function openCreateUser'))
  assert.doesNotMatch(submitTenant, /await fetchTenants\(\)/)
  assert.match(submitTenant, /session\.requestTenantReload\(\)/)
  assert.match(submitTenant, /tenantDialog\.value = false\s+await load\(\)/)
}

const client = await source('src/api/client.js')
assert.doesNotMatch(client, /Docker Desktop|数据库未启动/)
assert.match(client, /服务暂时不可用/)

const addToPlan = await source('src/components/AddToPlanDialog.vue')
assert.match(addToPlan, /<el-radio label="smart">智能匹配<\/el-radio>/)
assert.match(addToPlan, /matchMode: row\?\.preset_match_mode \|\| 'phrase'/)
assert.match(addToPlan, /matchMode: dialog\.matchMode/)
assert.match(addToPlan, /res\.writeback_status === 'failed'/)
assert.match(addToPlan, /res\.writeback_status === 'success'/)

const keywordExpand = await source('src/views/optimize/KeywordExpandView.vue')
assert.match(keywordExpand, /smart: '智能匹配'/)
assert.match(keywordExpand, /<el-option label="智能匹配" value="smart" \/>/)
assert.doesNotMatch(keywordExpand, /planDialog = reactive/)
assert.doesNotMatch(keywordExpand, /function submitAddToPlan/)
assert.match(keywordExpand, /待重试 \$\{progress\.failedIds\.length\} 条候选记录/)
assert.match(keywordExpand, /重试失败候选/)
assert.match(keywordExpand, /resp\.successful_candidate_ids/)
assert.match(keywordExpand, /round\.failedIds\.filter\(id => !completedIds\.has\(id\)\)/)

const idempotency = await source('src/api/idempotency.js')
const keywordApi = await source('src/api/keywords.js')
const manageApi = await source('src/api/manage.js')
const keywordWriteback = await source('src/composables/useKeywordWriteback.js')
assert.match(idempotency, /crypto\?\.randomUUID/)
assert.match(idempotency, /pendingWritebacks\.get\(operationKey\)/)
assert.match(keywordApi, /runIdempotentWriteback\(operationKey/)
assert.match(keywordApi, /idempotency_key: requestKey/)
assert.equal((manageApi.match(/idempotency_key: requestKey/g) || []).length, 3)
assert.equal((manageApi.match(/runIdempotentWriteback\(operationKey/g) || []).length, 3)
assert.match(keywordWriteback, /pendingBidWrites\.has\(writeKey\)/)
assert.match(keywordWriteback, /idempotencyKey = createWritebackIdempotencyKey\(\)/)

const idempotencyModule = await import(new URL('../src/api/idempotency.js', import.meta.url))
let releaseWrite
let writeCalls = 0
const firstWrite = idempotencyModule.runIdempotentWriteback('same-write', () => {
  writeCalls += 1
  return new Promise(resolve => { releaseWrite = resolve })
})
const duplicateWrite = idempotencyModule.runIdempotentWriteback('same-write', () => {
  writeCalls += 1
  return Promise.resolve()
})
assert.equal(firstWrite, duplicateWrite)
await Promise.resolve()
assert.equal(writeCalls, 1)
releaseWrite('ok')
await firstWrite
await idempotencyModule.runIdempotentWriteback('same-write', () => {
  writeCalls += 1
  return Promise.resolve('next')
})
assert.equal(writeCalls, 2)

const expansionApi = await source('src/api/expansion.js')
assert.match(expansionApi, /match_mode: matchMode/)
for (const route of [
  'batch-set-preset',
  'batch-set-category',
  'batch-status',
  'batch-negative',
]) {
  assert.match(expansionApi, new RegExp(`/api/v1/expansion/candidates/${route}`))
}
assert.match(
  expansionApi,
  /batch-negative'[\s\S]*?\}, \{ timeout: 60000 \}\)/,
)

await import('./test-sem-expansion-small-batch.mjs')
await import('./test-sem-writeback-queue.mjs')
await import('./test-sem-effect-verification.mjs')
console.log('SEM UI contracts passed')
