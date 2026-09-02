export const ACTION_TYPES = [
  { code: '', label: '全部动作' },
  { code: 'negative', label: '加否词' },
  { code: 'add_word', label: '转拓词' },
  { code: 'remove_negative', label: '删否词' },
  { code: 'pause', label: '暂停关键词' },
  { code: 'enable', label: '启用关键词' },
  { code: 'set_match_type', label: '改匹配模式' },
  { code: 'set_account_budget', label: '账户预算' },
  { code: 'set_campaign_budget', label: '计划预算' },
  { code: 'set_campaign_region', label: '计划投放地域' },
  { code: 'campaign_pause', label: '暂停计划' },
  { code: 'campaign_enable', label: '启用计划' },
  { code: 'campaign_schedule', label: '计划投放时段' },
  { code: 'adgroup_pause', label: '暂停单元' },
  { code: 'adgroup_enable', label: '启用单元' },
  { code: 'set_adgroup_bid', label: '单元出价' },
  { code: 'set_adgroup_url', label: '单元落地页' },
  { code: 'build_campaign', label: '智能搭建计划' },
  { code: 'build_adgroup', label: '智能搭建单元' },
  { code: 'build_keyword', label: '智能搭建关键词' },
  { code: 'build_creative', label: '智能搭建创意' },
]

const MONEY_ACTIONS = new Set([
  'set_account_budget',
  'set_campaign_budget',
  'set_adgroup_bid',
  'build_campaign',
])

export const formatActionMoney = (value) => (
  value == null ? '—' : `¥${Number(value).toFixed(2)}`
)

export function actionChangeText(row) {
  if (row.old_value == null && row.new_value == null) return ''
  if (MONEY_ACTIONS.has(row.action_type)) {
    return `${formatActionMoney(row.old_value)} → ${formatActionMoney(row.new_value)}`
  }
  if (row.action_type === 'set_match_type') {
    const codes = `${row.old_value ?? '—'} → ${row.new_value ?? '—'}`
    return row.match_label ? `匹配类型编码 ${codes}（目标：${row.match_label}）` : `匹配类型编码 ${codes}`
  }
  if (row.action_type === 'set_campaign_region') {
    return `${row.old_value ?? '—'} 个地域 → ${row.new_value ?? '—'} 个地域`
  }
  if (row.action_type === 'campaign_schedule') {
    return `${row.old_value ?? '—'} 个时段 → ${row.new_value ?? '—'} 个时段`
  }
  return `${row.old_value ?? '—'} → ${row.new_value ?? '—'}`
}

export function actionAccountLabel(tenants, tenantId, row) {
  const tenant = tenants.find((item) => item.id === tenantId)
  const account = (tenant?.sem_accounts || []).find(
    (item) => Number(item.id) === Number(row.baidu_account_id),
  )
  return account?.username || (row.baidu_account_id ? `账户 #${row.baidu_account_id}` : '—')
}

export function actionResultNote(row) {
  if (row.error_msg) return row.error_msg
  if (row.dry_run) return '仅记录台账，未修改百度账户'
  if (row.status === 'success') return '百度执行成功'
  if (row.status === 'pending') return '执行结果待确认'
  if (row.status === 'reconcile') return '需要人工对账'
  return '—'
}
