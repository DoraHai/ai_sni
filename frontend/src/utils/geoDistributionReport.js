export async function reportDigest(articleId, variant, subtle = globalThis.crypto.subtle) {
  const bytes = new TextEncoder().encode(JSON.stringify([`geo-article-${articleId}`, variant.title, variant.body_markdown, []]))
  return [...new Uint8Array(await subtle.digest('SHA-256', bytes))].map(v => v.toString(16).padStart(2, '0')).join('')
}
export function reportContext() {
  let epoch = 0
  return { reset: () => ++epoch, capture: () => epoch, current: value => value === epoch }
}
export function reportToggle(settings) {
  const opening = !settings.scope_enabled
  return { enabled: opening ? true : settings.enabled, scope_enabled: opening,
    expected_revision: settings.revision, expected_scope_revision: settings.scope_revision }
}
export const reportOutcomes = { queued: '待回报', running: '处理中', 'awaiting-human': '待人工处理', unknown: '结果未知', failed: '失败', canceled: '已取消', succeeded: '人工报告已发布' }
export const reportCodes = { RISK_CONTROL: '平台风控', CAPTCHA: '需验证', LOGIN_REQUIRED: '需登录', PLATFORM_REVIEW_PENDING: '平台审核中', PAGE_UNVERIFIED: '页面待核对', OFFLINE: '离线', UPLOAD_RESULT_UNKNOWN: '上传结果未知', SUBMISSION_RESULT_UNKNOWN: '提交结果未知', PLATFORM_PUBLISH_FAILED: '平台发布失败', HUMAN_FAILED: '人工确认失败' }
