const STATUS_LABELS = {
  blocked: '系统前置条件未满足',
  blocked_by_h3: '等待发布前置条件',
  awaiting_real_publication: '等待登记真实发布网址',
  awaiting_successful_recheck: '等待成功复查',
  awaiting_human_evidence: '系统检查已完成，等待人工确认',
}

const REASON_LABELS = {
  latest_master_exists: '当前母稿尚未保存',
  customer_review_approved: '当前母稿尚未通过客户确认',
  current_channel_variant_exists: '当前母稿还没有渠道稿',
  published_record_exists: '当前版本尚未登记真实发布网址',
  no_duplicate_registration: '同一渠道和网址存在重复发布登记',
  publication_body_matched: '尚无当前渠道稿正文匹配的成功复查',
}

function requirementFor(summary, stage, key) {
  const requirements = summary?.[stage]?.requirements
  return Array.isArray(requirements) ? requirements.find((item) => item?.key === key) : null
}

function blocker(summary, defaultStage, rawReason) {
  const raw = String(rawReason || '')
  const inherited = raw.startsWith('h3:')
  const stage = inherited ? 'h3' : defaultStage
  const key = inherited ? raw.slice(3) : raw
  const requirement = requirementFor(summary, stage, key)
  return {
    key,
    stage,
    label: REASON_LABELS[key] || requirement?.description || '对应验收条件尚未满足',
    requirement: requirement?.description || null,
  }
}

export function describeAcceptanceSummary(summary) {
  if (!summary) return []
  return ['h3', 'h4'].map((stage) => {
    const data = summary[stage] || {}
    const reasons = Array.isArray(data.blocking_reasons) ? data.blocking_reasons : []
    const humanRequirements = Array.isArray(data.requirements)
      ? data.requirements.filter((item) => item?.source === 'human' && !item?.satisfied)
      : []
    return {
      key: stage,
      title: stage === 'h3' ? 'H3 发布前验收' : 'H4 发布后复查',
      status: data.status || 'unknown',
      statusLabel: STATUS_LABELS[data.status] || '状态待确认',
      systemReady: data.system_ready === true,
      blockers: reasons.map((reason) => blocker(summary, stage, reason)),
      humanRequirements,
    }
  })
}
