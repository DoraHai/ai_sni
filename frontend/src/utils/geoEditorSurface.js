/**
 * 母稿编辑页对齐原型主流程：Brief → 母稿 → 渠道稿 → 检查。
 * 渠道稿只保留勾选、生成、预览、复制；推送 / 回填 / 效果留给后台页。
 */
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
    showFactBinding: false,
    showChannelVariants: true,
    showBatchPush: false,
    showImpact: false,
    showAiReview: false,
    actions: [
      'suggest_brief',
      'save_brief',
      'generate_master',
      'save_master',
      'generate_channels',
      'copy',
      'check',
    ],
  }
}

export function getGeoPrototypePageSurface() {
  return {
    showCompetitorAdvancedAnalysis: false,
    showChannelAutomationConsole: false,
    showChannelAccountConsole: false,
    showEvaluationRawMetrics: false,
    showCitationRawMetrics: false,
    showKnowledgeHealth: false,
    showLightweightOperations: false,
  }
}
