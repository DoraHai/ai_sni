import assert from 'node:assert/strict'

import {
  ACTION_TYPES,
  actionAccountLabel,
  actionChangeText,
  actionResultNote,
  formatActionMoney,
} from '../src/utils/actionLedger.js'


const actionCodes = ACTION_TYPES.map((item) => item.code)
assert.equal(new Set(actionCodes).size, actionCodes.length)
for (const code of [
  'negative', 'add_word', 'remove_negative', 'pause', 'enable', 'set_match_type',
  'set_account_budget', 'set_campaign_budget', 'set_campaign_region',
  'campaign_pause', 'campaign_enable', 'campaign_schedule',
  'adgroup_pause', 'adgroup_enable', 'set_adgroup_bid', 'set_adgroup_url',
  'build_campaign', 'build_adgroup', 'build_keyword', 'build_creative',
]) {
  assert.ok(actionCodes.includes(code), `missing action filter: ${code}`)
}

assert.equal(formatActionMoney(null), '—')
assert.equal(formatActionMoney(50), '¥50.00')
assert.equal(
  actionChangeText({ action_type: 'set_campaign_budget', old_value: 50, new_value: 80 }),
  '¥50.00 → ¥80.00',
)
assert.equal(
  actionChangeText({ action_type: 'set_match_type', old_value: 1, new_value: 2 }),
  '匹配类型编码 1 → 2',
)
assert.equal(
  actionChangeText({
    action_type: 'set_match_type', old_value: 1, new_value: 2, match_label: '智能匹配',
  }),
  '匹配类型编码 1 → 2（目标：智能匹配）',
)
assert.equal(
  actionChangeText({ action_type: 'set_campaign_region', old_value: 2, new_value: 5 }),
  '2 个地域 → 5 个地域',
)
assert.equal(
  actionChangeText({ action_type: 'campaign_schedule', old_value: 7, new_value: 9 }),
  '7 个时段 → 9 个时段',
)
assert.equal(
  actionChangeText({ action_type: 'build_campaign', old_value: null, new_value: 100 }),
  '— → ¥100.00',
)
assert.equal(actionChangeText({ action_type: 'pause', old_value: null, new_value: null }), '')

const tenants = [{
  id: 3,
  sem_accounts: [{ id: 7, username: 'Tiger-SEM' }],
}]
assert.equal(actionAccountLabel(tenants, 3, { baidu_account_id: 7 }), 'Tiger-SEM')
assert.equal(actionAccountLabel(tenants, 3, { baidu_account_id: 8 }), '账户 #8')
assert.equal(actionAccountLabel(tenants, 3, { baidu_account_id: null }), '—')

assert.equal(actionResultNote({ error_msg: '百度超时', dry_run: false }), '百度超时')
assert.equal(actionResultNote({ error_msg: null, dry_run: true }), '仅记录台账，未修改百度账户')
assert.equal(actionResultNote({ error_msg: null, dry_run: false, status: 'success' }), '百度执行成功')
assert.equal(actionResultNote({ error_msg: null, dry_run: false, status: 'pending' }), '执行结果待确认')
assert.equal(actionResultNote({ error_msg: null, dry_run: false, status: 'reconcile' }), '需要人工对账')

console.log('SEM action ledger behavior tests passed')
