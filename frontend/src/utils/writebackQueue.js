export const QUEUE_STAGES = [
  { value: 'reconciliation_required', label: '待人工对账', cls: 'v-bad' },
  { value: 'pending_writeback', label: '演练待回写（未真改）', cls: 'st-pending' },
  { value: 'executed', label: '百度已执行', cls: 'st-ok' },
  { value: 'failed', label: '执行失败', cls: 'v-bad' },
]

export function queueStageMeta(stage) {
  return QUEUE_STAGES.find((item) => item.value === stage)
    || { value: 'unknown', label: '状态未知，请核查', cls: 'v-bad' }
}

export function filterQueue(items, stage) {
  return stage ? items.filter((item) => item.stage === stage) : items
}

export function queueCounts(items) {
  const counts = Object.fromEntries(QUEUE_STAGES.map((item) => [item.value, 0]))
  counts.unknown = 0
  for (const item of items) counts[queueStageMeta(item.stage).value] += 1
  return counts
}

export function coreActionFlow(item) {
  const flow = item?.flow
  if (!flow || flow.version !== 'sem-controlled-action-v1') return null
  if (!['keyword_bid', 'keyword_pause', 'negative_word'].includes(flow.family)) return null
  return flow
}

export function canOpenControlledActionQueue(permissions = {}) {
  return ['view', 'edit'].includes(permissions?.['verify.adjustments'])
}

export function flowControlLabel(flow) {
  if (!flow) return '历史记录，未提供流程明细'
  if (flow.control.recorded_mode === 'dry_run') return '演练留痕，未调用百度写接口'
  if (flow.control.approval_required_for_live) {
    return flow.control.approval_id
      ? `真实执行，资金确认 #${flow.control.approval_id}`
      : '真实执行，历史记录未关联资金确认'
  }
  return '真实执行，已通过账户与动作范围门禁'
}

export function flowAccountScopeLabel(flow) {
  return {
    configured: '账户有效，该动作范围已配置真写',
    scope_disabled: '账户有效，该动作范围未配置真写',
    account_unavailable: '台账账户已停用或当前客户下不存在',
  }[flow?.control?.account_action_scope_state] || '账户动作范围配置未知'
}

export function flowBasisLabel(flow) {
  if (!flow) return '—'
  const basis = flow.check_basis || {}
  return [
    basis.baidu_account_id ? `账户 ${basis.baidu_account_id}` : null,
    basis.keyword_id ? `关键词 ${basis.keyword_id}` : null,
    basis.campaign_id ? `计划 ${basis.campaign_id}` : null,
    basis.adgroup_id ? `单元 ${basis.adgroup_id}` : null,
    basis.match_mode ? `匹配 ${basis.match_mode}` : null,
  ].filter(Boolean).join(' · ') || '台账未保存对象标识'
}
