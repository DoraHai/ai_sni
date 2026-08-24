/**
 * 母稿编辑页只承载原型中的主流程；复杂的资料关联和渠道编排仍由
 * 后台流程使用，但不作为运营人员的主界面操作项。
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
    showChannelVariants: false,
    showBatchPush: false,
    showImpact: false,
    showAiReview: false,
    actions: [
      'suggest_brief',
      'save_brief',
      'generate_master',
      'save_master',
      'copy',
      'check',
    ],
  }
}
