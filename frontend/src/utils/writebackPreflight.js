const POLICY_REASON_LABELS = {
  configured_grant: '管理员已配置账户动作授权',
  legacy_grant: '服务器旧策略已授权该动作',
  global_dry_run: '环境总闸保持演练',
  legacy_confirmation_gate: '旧确认协议总闸保持演练',
  daily_limit_reached: '今日真实动作额度已用尽',
  legacy_grant_missing: '服务器旧策略未授权该动作',
  grant_missing_or_paused: '账户动作策略未授权或已暂停',
  invalid_policy: '账户动作策略异常，已失败关闭',
  sem_module_unavailable: 'SEM 模块当前不可用',
}

const POLICY_SOURCE_LABELS = {
  policy: '账户执行策略',
  legacy_environment: '服务器旧策略',
}

function positiveInteger(value) {
  return Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : null
}

function reject(reason) {
  return { ok: false, message: `无法核验关键词调价执行范围：${reason}。已禁止提交，请刷新后重试。` }
}

/** Build a fail-closed, account-specific explanation immediately before a keyword bid write. */
export function keywordBidPreflight(payload, { tenantId, accountId }) {
  const expectedTenantId = positiveInteger(tenantId)
  const expectedAccountId = positiveInteger(accountId)
  if (!expectedTenantId || !expectedAccountId) return reject('客户或推广账户标识缺失')
  if (!payload || positiveInteger(payload.tenant_id) !== expectedTenantId) return reject('客户范围不一致')
  if (!Array.isArray(payload.accounts)) return reject('账户策略响应不完整')

  const matches = payload.accounts.filter(item => positiveInteger(item?.baidu_account_id) === expectedAccountId)
  if (matches.length !== 1) return reject(matches.length ? '推广账户策略重复' : '未找到推广账户策略')
  const account = matches[0]
  if (!Array.isArray(account.live_scopes) || account.live_scopes.some(scope => typeof scope !== 'string')) {
    return reject('账户动作范围格式异常')
  }
  const scopes = new Set(account.live_scopes)
  if (scopes.size !== account.live_scopes.length) return reject('账户动作范围重复')

  const reason = POLICY_REASON_LABELS[account.policy_reason] || '当前策略按演练处理'
  const source = POLICY_SOURCE_LABELS[account.policy_source] || '未识别策略来源'
  if (!scopes.has('keyword_bid')) {
    if (account.mode !== 'dry_run') return reject('演练模式与动作范围不一致')
    return {
      ok: true,
      executionMode: 'dry_run',
      confirmButtonText: '确认加入待回写',
      message: `预检结果：演练，不会调用百度写接口。策略来源：${source}；原因：${reason}。本次只写入行动台账，不创建或消费资金确认。此预检不预留额度，提交时服务端会再次校验。`,
    }
  }

  const used = Number(account.daily_live_actions_used)
  const limit = Number(account.daily_live_action_limit)
  const maxBidChangePct = Number(account.max_bid_change_pct)
  if (account.mode !== 'limited_live') return reject('真实动作范围与执行模式不一致')
  if (!POLICY_SOURCE_LABELS[account.policy_source]
      || !['configured_grant', 'legacy_grant'].includes(account.policy_reason)) {
    return reject('真实动作授权依据无法解释')
  }
  if (!Number.isSafeInteger(used) || used < 0 || !Number.isSafeInteger(limit) || limit <= 0) {
    return reject('今日真实动作额度异常')
  }
  if (used >= limit) return reject('今日真实动作额度已经用尽')
  if (!Number.isFinite(maxBidChangePct) || maxBidChangePct <= 0 || maxBidChangePct > 20) {
    return reject('单次调价上限异常')
  }
  return {
    ok: true,
    executionMode: 'live',
    confirmButtonText: '确认资金审批并执行',
    message: `预检结果：真实执行候选，将修改百度账户。策略来源：${source}；依据：${reason}。今日真实动作额度 ${used}/${limit}，单次调价上限 ±${maxBidChangePct}%。服务端最终复核通过后，会创建并消费一条与当前参数绑定的一次性资金确认。此预检不预留额度，提交时服务端会再次校验。`,
  }
}

export function writebackTrace(writeback) {
  const ledgerId = positiveInteger(writeback?.id)
  const approvalId = positiveInteger(writeback?.approval_id)
  return [
    ledgerId ? `行动台账 #${ledgerId}` : null,
    approvalId ? `资金确认 #${approvalId}` : null,
  ].filter(Boolean).join('，')
}
