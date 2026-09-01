import assert from 'node:assert/strict'
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

const roles = await source('src/views/settings/AccountsRolesView.vue')
assert.match(roles, /:data="tenantOptions"/)
assert.doesNotMatch(roles, /session\.setTenants/)
assert.doesNotMatch(roles, /GEO 开户向导/)
const submitTenant = roles.slice(roles.indexOf('async function submitTenant'), roles.indexOf('function openCreateUser'))
assert.doesNotMatch(submitTenant, /await fetchTenants\(\)/)
assert.match(submitTenant, /session\.requestTenantReload\(\)/)
assert.match(submitTenant, /tenantDialog\.value = false\s+await load\(\)/)

const client = await source('src/api/client.js')
assert.doesNotMatch(client, /Docker Desktop|数据库未启动/)
assert.match(client, /服务暂时不可用/)

const addToPlan = await source('src/components/AddToPlanDialog.vue')
assert.match(addToPlan, /<el-radio label="smart">智能匹配<\/el-radio>/)
assert.match(addToPlan, /matchMode: row\?\.preset_match_mode \|\| 'phrase'/)
assert.match(addToPlan, /matchMode: dialog\.matchMode/)

const keywordExpand = await source('src/views/optimize/KeywordExpandView.vue')
assert.match(keywordExpand, /<el-radio label="smart">智能匹配<\/el-radio>/)

const expansionApi = await source('src/api/expansion.js')
assert.match(expansionApi, /match_mode: matchMode/)

console.log('SEM UI contracts passed')
