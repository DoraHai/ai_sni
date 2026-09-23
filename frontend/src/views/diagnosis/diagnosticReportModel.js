import { normalizeFindings, isEvaluated, legacyScoreNote } from './diagnosticFindingState.js'

const finite = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
const priority = { critical: 0, high: 1, medium: 2, low: 3 }
export const reportDate = value => {
  if (!value || Number.isNaN(new Date(value).getTime())) return '时间未记录'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short', hour12: false }).format(new Date(value))
}
export function reportModel(audit = {}, brand = {}, pageSpeed = null) {
  const snapshot = audit.snapshot || {}
  const competitor = snapshot.audit_mode === 'competitor'
  const profile = snapshot.brand_profile || (competitor ? {} : brand)
  const findings = normalizeFindings(audit.findings)
  const evaluated = findings.filter(isEvaluated)
  const failed = findings.filter(item => item.passed === false).sort((a,b) =>
    (priority[a.severity] ?? 4) - (priority[b.severity] ?? 4) || (b.deduction || 0) - (a.deduction || 0))
  const legacy = findings.some(item => item.legacyIndeterminate)
  const website = audit.final_url || audit.url || '网址未记录'
  let host = website
  try { host = new URL(website).hostname } catch { /* Preserve recorded URL. */ }
  const metrics = snapshot.external_metrics || {}
  const external = [
    ['百度收录量', 'baidu_index', row => row.site_count, '页'],
    ['PC 关键词', 'baidu_pc_keywords', row => row.total, '个'],
    ['移动关键词', 'baidu_mobile_keywords', row => row.total, '个'],
    ['域名年龄', 'whois', row => row.domain_age_years, '年'],
    ['百度 PC 权重', 'comprehensive_weight', row => row.baidu_pc?.weight, ''],
    ['百度移动权重', 'comprehensive_weight', row => row.baidu_mobile?.weight, ''],
  ].map(([label, key, read, unit]) => {
    const metric = metrics[key] || {}
    const value = read(metric)
    return { label, value: metric.status === 'available' && finite(value) ? `${value}${unit}` : '未检测',
      note: metric.reason || '未取得可用结果', source: metric.source_url || '', time: metric.queried_at }
  })
  const performance = pageSpeed || snapshot.pagespeed || {}
  const performanceRows = [
    { label: 'Performance', value: performance.performance_score, unit: '/100' },
    ...['lcp','cls','inp'].map(key => ({ label: key.toUpperCase(), value: performance.metrics?.[key]?.value, unit: performance.metrics?.[key]?.unit || '', source: performance.metrics?.[key]?.source })),
  ].map(row => ({ ...row, value: performance.status === 'available' && finite(row.value) ? `${row.value}${row.unit}` : '未检测' }))
  const sample = snapshot.ai_sampling || {}
  const sampleRows = (sample.results || []).filter(row => typeof row.response === 'string' && row.response.trim())
  const assessedSamples = sampleRows.filter(row => typeof row.mentioned === 'boolean')
  const mentionCount = assessedSamples.filter(row => row.mentioned).length
  return {
    name: profile.name || host, host, website, competitor, findings, evaluated, failed, legacy,
    score: finite(audit.score) && evaluated.length ? audit.score : null,
    scoreNote: legacy ? legacyScoreNote : '规则评分用于描述本次检测范围内的基础准备情况，不代表搜索排名、流量或所有 AI 平台的推荐表现。',
    passed: findings.filter(item => item.passed === true).length,
    unavailable: findings.filter(item => item.passed == null),
    passRate: evaluated.length ? Math.round(findings.filter(item => item.passed === true).length / evaluated.length * 100) : null,
    high: failed.filter(item => ['critical','high'].includes(item.severity)).length,
    scope: snapshot.audit_scope === 'site' ? `全站抽样 · ${snapshot.site_audit?.successful_pages ?? snapshot.site_audit?.pages?.length ?? '未知'} 页` : '单页诊断',
    pages: snapshot.site_audit?.pages || [],
    external, performance, performanceRows, sample, sampleRows,
    mentionRate: assessedSamples.length ? Math.round(mentionCount / assessedSamples.length * 100) : null,
    mentionCount, sampleCount: assessedSamples.length,
    version: audit.rule_version || snapshot.rule_version || '未记录', date: reportDate(audit.created_at),
    profile, snapshot,
  }
}
