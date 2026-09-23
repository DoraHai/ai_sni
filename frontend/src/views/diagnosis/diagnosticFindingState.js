// Present old indeterminate crawler records honestly without rewriting saved scores.
const unknownCrawlerEvidence = /robots\.txt.*(?:不可读|无法读取|无法审计|无法确认)/i
export function normalizeFinding(item) {
  const legacyCrawler = !item.status && item.code === 'ai_crawlers' && (
    unknownCrawlerEvidence.test(item.evidence || '') ||
    (item.page_evidence || []).some(page => unknownCrawlerEvidence.test(page.evidence || ''))
  )
  const unavailable = item.passed == null || item.status === 'unavailable' || legacyCrawler
  return {
    ...item,
    ...(item.page_evidence ? { page_evidence: item.page_evidence.map(page => normalizeFinding({ ...page, code: item.code })) } : {}),
    passed: unavailable ? null : item.passed,
    status: unavailable ? 'unavailable' : item.passed === true ? 'passed' : 'failed',
    deduction: unavailable ? 0 : item.deduction,
    title: unavailable && item.code === 'ai_crawlers' ? '无法确认主流 AI 爬虫访问规则' : item.title,
    legacyIndeterminate: legacyCrawler && item.passed !== null && item.status !== 'unavailable',
  }
}
export const normalizeFindings = rows => (rows || []).map(normalizeFinding)
export const isEvaluated = item => item.passed === true || item.passed === false
export const statusLabel = item => item.passed == null ? '未检测 / 无法确认' : item.passed ? '通过' : '未通过'
export const legacyScoreNote = '历史记录包含无法确认的 AI 爬虫规则，原评分可能包含该项扣分；当前保留原评分供追溯，请重新诊断获取修正后的评分。'
