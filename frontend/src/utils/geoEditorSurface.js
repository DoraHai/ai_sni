/**
 * 母稿编辑页对齐原型主流程：事实绑定 → 生成母稿 → 检查就绪 → Brief / 渠道适配。
 * 渠道成稿：生成、预览、复制；推送 / 回填 / 效果留给分发平台页。
 */
export const GEO_CHANNEL_DRAFT_SCORE_THRESHOLD = 60

export function getGeoChannelDraftGate({
  hasMasterDraft,
  geoScore,
  scoreIsCurrent,
  threshold = GEO_CHANNEL_DRAFT_SCORE_THRESHOLD,
}) {
  if (!hasMasterDraft) return { allowed: false, reason: '请先生成母稿' }
  if (!scoreIsCurrent || geoScore == null) {
    return { allowed: false, reason: '请先完成 GEO 评分' }
  }
  const score = Number(geoScore)
  if (!Number.isFinite(score) || score < threshold) {
    const shown = Number.isFinite(score) ? score : '—'
    return {
      allowed: false,
      reason: `GEO 评分需达到 ${threshold} 分，当前 ${shown} 分`,
    }
  }
  return { allowed: true, reason: '' }
}

export function getGeoPrototypeEditorSurface() {
  return {
    briefFields: [
      'industry',
      'audience',
      'intent',
      'content_type',
      'cta',
      'banned_claims',
    ],
    showProgressHint: false,
    showFactBinding: true,
    showChannelVariants: true,
    showBatchPush: false,
    showImpact: false,
    showAiReview: false,
    actions: [
      'bind_facts',
      'generate_master',
      'save_master',
      'check',
      'suggest_brief',
      'save_brief',
      'generate_channels',
      'copy',
    ],
  }
}

export function getGeoPrototypePageSurface() {
  return {
    showCompetitorAdvancedAnalysis: false,
    showChannelAutomationConsole: false,
    showChannelAccountConsole: true,
    showEvaluationRawMetrics: false,
    showCitationRawMetrics: false,
    showKnowledgeHealth: false,
    showLightweightOperations: false,
  }
}
