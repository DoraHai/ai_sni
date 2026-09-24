import { normalizeFindings, isEvaluated, legacyScoreNote } from './diagnosticFindingState.js'

const finite = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
const priority = { critical: 0, high: 1, medium: 2, low: 3 }
export const reportDate = value => {
  if (!value || Number.isNaN(new Date(value).getTime())) return '时间未记录'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short', hour12: false }).format(new Date(value))
}
// One presentation contract for the screen and exported SEO overview.
export function seoReportModel(snapshot = {}, scope = '单页诊断') {
  const metrics = snapshot.external_metrics || {}
  const read = (key, field, unit = '') => {
    const row = metrics[key] || {}, value = field(row)
    return row.status === 'available' && finite(value) ? `${Number(value)}${unit}` : '未检测'
  }
  const note = key => metrics[key]?.reason || (metrics[key]?.status === 'available' ? '已取得检测结果' : '未取得可用结果')
  const pc = read('comprehensive_weight', m => m.baidu_pc?.weight)
  const mobile = read('comprehensive_weight', m => m.baidu_mobile?.weight)
  const keywordRows = ['baidu_pc_keywords', 'baidu_mobile_keywords'].map(key => metrics[key] || {})
  return {
    score: null, scoreText: '未检测', scoreLabel: '暂无独立综合评分', scoreNote: '技术规则结果详见附录一。',
    headline: ['以技术检测证据为起点，', '结合真实搜索数据判断优化方向。'],
    description: `本次范围：${scope}。外部指标缺失时，不推断索引规模、关键词占比或搜索流量。`,
    tags: ['规则证据可追溯', '缺失数据单独标注'],
    facts: [
      { label: '百度索引', value: read('baidu_index', m => m.site_count), note: note('baidu_index') },
      { label: 'PC 关键词', value: read('baidu_pc_keywords', m => m.total), note: note('baidu_pc_keywords') },
      { label: '移动关键词', value: read('baidu_mobile_keywords', m => m.total), note: note('baidu_mobile_keywords') },
      { label: '百度综合权重', value: `${pc === '未检测' ? '—' : pc} / ${mobile === '未检测' ? '—' : mobile}`, unit: 'PC / 移动', note: note('comprehensive_weight') },
      { label: '网站年龄', value: read('whois', m => m.domain_age_years, '年'), note: note('whois') },
    ].map(fact => ({ ...fact, note: ['未检测', '— / —'].includes(fact.value) && fact.note === '已取得检测结果' ? '未取得可用结果' : fact.note })),
    keywordTotal: keywordRows.every(m => m.status === 'available' && finite(m.total)) ? String(keywordRows.reduce((sum,m) => sum + Number(m.total), 0)) : '未检测',
    sampleCount: keywordRows.every(m => m.status === 'available' && finite(m.sample_count)) ? String(keywordRows.reduce((sum,m) => sum + Number(m.sample_count), 0)) : '未检测',
    indexAnalysis: '有限抽样不能确定全站实际页面总量，暂无法据此比较索引规模。',
    keywordAnalysis: '关键词数量不等于词类占比，需补充真实词表与分类证据。',
  }
}
export function reportModel(audit = {}, brand = {}, pageSpeed = null) {
  const snapshot = audit.snapshot || {}
  const competitor = snapshot.audit_mode === 'competitor'
  const profile = snapshot.brand_profile || (competitor ? {} : brand) || {}
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
      note: metric.reason || (metric.status === 'available' ? '已取得检测结果' : '未取得可用结果'), source: metric.source_url || '', time: metric.queried_at }
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
  const scope = snapshot.audit_scope === 'site' ? `全站抽样 · ${snapshot.site_audit?.successful_pages ?? snapshot.site_audit?.pages?.length ?? '未知'} 页` : '单页诊断'
  return {
    seo: seoReportModel(snapshot, scope),
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
