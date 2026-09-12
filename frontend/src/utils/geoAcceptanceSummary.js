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

const CHANNEL_LABELS = {
  website: '官网',
  wechat: '微信',
  zhihu: '知乎',
  baijiahao: '百家号',
  toutiao: '头条',
  docs: '文档',
  industry_media: '行业媒体',
}

const MONITOR_STATE_LABELS = {
  pending: '等待首次检查',
  healthy: '正文匹配',
  unreachable: '页面暂时无法检查',
  mismatch: '正文与登记稿件不匹配',
  version_changed: '登记后稿件已变化',
}

const EVIDENCE_REASON_LABELS = {
  monitor_not_healthy: '最近保存的监测结论尚未通过',
  fingerprint_missing_or_mismatch: '检查依据与当前渠道稿不一致',
  article_version_mismatch: '检查依据不属于当前母稿版本',
  checked_at_missing_or_invalid: '缺少可信的检查时间',
}

function safeTime(value) {
  if (typeof value !== 'string' || !value.trim()) return null
  if (!/[zZ]$|[+-]\d\d:\d\d$/.test(value.trim())) return null
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return null
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(timestamp)
}

function recoveryGuide(reasons) {
  if (reasons.includes('fingerprint_missing_or_mismatch') || reasons.includes('article_version_mismatch')) {
    return '当前稿件版本已变化；请到“分发记录 → 发布后监测”核对当前版本的发布登记。'
  }
  if (reasons.includes('checked_at_missing_or_invalid')) {
    return '当前记录缺少可信检查时间；请等待后续监测更新，并在“分发记录 → 发布后监测”查看已有记录。'
  }
  return '请等待系统按计划检查，并在“分发记录 → 发布后监测”查看已有记录。'
}

function monitorObservation(row) {
  const reasons = Array.isArray(row?.evidence_reasons)
    ? row.evidence_reasons.map((value) => String(value || '')).filter(Boolean)
    : []
  const id = Number(row?.publication_ref?.id)
  const failures = row?.failures
  const evidenceValid = row?.evidence_valid === true
  const storedStateLabel = MONITOR_STATE_LABELS[row?.state] || '状态待确认'
  return {
    publicationLabel: Number.isSafeInteger(id) && id > 0 ? `发布记录 #${id}` : '发布记录',
    channelLabel: CHANNEL_LABELS[row?.channel] || '渠道未标记',
    stateLabel: row?.state === 'healthy' && !evidenceValid
      ? '历史检查曾匹配，当前证据无效'
      : storedStateLabel,
    evidenceValid,
    evidenceStatusLabel: evidenceValid ? '当前检查依据有效' : '当前检查依据无效',
    checkedAt: safeTime(row?.checked_at),
    nextCheckAt: safeTime(row?.next_check_at),
    failures: typeof failures === 'number' && Number.isSafeInteger(failures) && failures >= 0 ? failures : 0,
    evidenceReasons: reasons.map((reason) => EVIDENCE_REASON_LABELS[reason] || '检查依据尚未满足'),
    checkIncomplete: row?.last_error?.kind === 'check_incomplete',
    recoveryGuide: recoveryGuide(reasons),
  }
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
      observations: stage === 'h4' && Array.isArray(data.monitoring)
        ? data.monitoring.map(monitorObservation)
        : [],
    }
  })
}
