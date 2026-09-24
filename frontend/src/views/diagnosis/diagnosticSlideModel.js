import { reportModel } from './diagnosticReportModel.js'

export const groupsOf = (items, size) => Array.from({ length: Math.ceil(items.length / size) }, (_, i) => items.slice(i * size, (i + 1) * size))
// Preserve every character. Newlines consume a line's space; wide glyphs cost more
// than Latin text. Conservative budgets keep arbitrary saved evidence printable.
export function splitReportText(value, budget = 900, lineWidth = 36) {
  const text = String(value ?? '')
  if (!text) return ['']
  const chunks = []; let chunk = '', used = 0, column = 0
  for (const char of text) {
    let cost = /[^\x00-\xff]/u.test(char) ? 1 : .6
    if (char === '\n') cost = Math.max(1, lineWidth - column)
    if (used + cost > budget && chunk) { chunks.push(chunk); chunk = ''; used = 0; column = 0 }
    chunk += char; used += cost; column = char === '\n' ? 0 : (column + cost) % lineWidth
  }
  if (chunk) chunks.push(chunk)
  return chunks
}
const definitions = [
  ['技术可访问', ['技术基础']], ['页面语义', ['页面语义']],
  ['内容结构', ['内容结构', '内容质量']], ['实体与 Schema', ['结构化数据']],
  ['AI 引用就绪度', ['AI 引用就绪度', 'AI 可引用性', 'AI 可访问性']], ['可信信号', ['可信度']],
]
const escapeRegExp = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
export function slideReportModel(audit, brand, pageSpeed) {
  const report = reportModel(audit, brand, pageSpeed)
  const dimensions = definitions.map(([label, categories]) => {
    const rows = report.evaluated.filter(item => categories.includes(item.category))
    const weight = rows.reduce((sum, item) => sum + Number(item.weight || item.deduction || 0), 0)
    const lost = rows.filter(item => item.passed === false).reduce((sum, item) => sum + Number(item.deduction || 0), 0)
    return { label, score: rows.length && weight > 0 ? Math.max(0, Math.round(100 - lost / weight * 100)) : null }
  })
  // Product keywords in historical matched_terms are not brand identities.
  const names = [...new Set([report.profile?.name, report.profile?.english_name].filter(value => typeof value === 'string' && value.trim()).map(value => value.trim()))]
  const samples = report.sampleRows.map(row => ({ ...row, explicitMention: names.length ? names.some(name => {
    const escaped = escapeRegExp(name)
    return new RegExp(/^[\x00-\x7f]+$/.test(name) ? `(^|[^a-zA-Z0-9])${escaped}($|[^a-zA-Z0-9])` : escaped, 'iu').test(row.response)
  }) : null }))
  const explicitCount = samples.filter(row => row.explicitMention === true).length
  const explicitRate = samples.length && names.length ? Math.round(explicitCount / samples.length * 100) : null
  const seo = report.findings.filter(row => ['技术基础', '页面语义', '内容结构', '内容质量'].includes(row.category))
  const geo = report.findings.filter(row => !seo.includes(row))
  const ruleCards = items => items.flatMap((item, index) => {
    const body = `${String(item.title || '').length > 60 ? `检测项：${item.title}\n` : ''}检测证据：${item.evidence || '证据未记录'}\n判断依据：${item.criterion || '按当前检测规则核对原始证据。'}\n建议 / 维护：${item.recommendation || '修复后复检，已通过项保持当前设置。'}`
    return splitReportText(body, 225, 38).map((text, part) => ({ item, index, text, part }))
  })
  const divider = (title, english, number, subtitle) => ({ kind: 'divider', title, english, number, subtitle })
  const slides = [
    { kind: 'cover' }, divider('概览', 'OVERVIEW', '01', '站点健康度、AI 搜索就绪度与关键诊断信号'),
    { kind: 'overview' }, { kind: 'foundation', title: '基础检查与核心指标', english: 'FOUNDATION & METRICS' }, { kind: 'signals' },
    divider('SEO 诊断', 'SEO DIAGNOSIS', '02', '搜索基础能力、核心指标与优化优先级'),
    { kind: 'seo' }, { kind: 'metrics' }, { kind: 'analysis' },
    divider('GEO / AI 搜索诊断', 'GEO / AI SEARCH', '03', 'AI 品牌提及抽样、问题清单与行动路线'),
    ...groupsOf(samples.length ? samples : [null], 3).map(rows => ({ kind: 'sample', title: 'AI 品牌提及抽样', english: 'LIVE MODEL SAMPLE', rows: rows.filter(Boolean) })),
    ...groupsOf(report.failed.length ? report.failed : [null], 6).map(rows => ({ kind: 'issues', title: '问题清单与行动路线', english: 'ISSUE MATRIX', rows: rows.filter(Boolean) })),
    divider('附录', 'APPENDICES', '04', 'SEO 技术检测明细、GEO 诊断与 AI 抽样原始回答'),
  ]
  for (const [items, title, english] of [[seo, '附录一｜现有 SEO 技术检测明细', 'APPENDIX A / SEO TECHNICAL CHECKS'], [geo, '附录二｜GEO / AI 搜索诊断', 'APPENDIX B / GEO & AI SEARCH']]) {
    for (const rows of groupsOf(ruleCards(items), 4)) slides.push({ kind: 'rules', title, english, rows })
  }
  // Page-level evidence and full source metadata remain available, without
  // forcing an oversized rule card or truncating URLs / multi-page evidence.
  const evidence = [report.scoreNote, `评分口径：通过率仅以已评估规则为分母。未检测不通过也不失败，不计入评分扣分。全站按首页 3、核心页 2、其他页 1 加权。`,
    `检测范围：${report.scope}\n页面标题：${audit.page_title || '未记录'}\n官网：${report.website}`,
    ...report.pages.map(p => `抽样页面：${p.title || p.url}\n${p.url}\n类型 / 权重：${p.page_type ?? '未记录'} / ${p.weight ?? '未记录'}\n评分：${p.score ?? '未检测'}`),
    ...report.findings.flatMap(item => (item.page_evidence || []).map(p => `${item.title} / 逐页证据\n${p.title || ''}\n${p.url || ''}\n${p.evidence || '证据未记录'}`)),
    ...report.external.map(m => `${m.label}：${m.value}\n${m.note}\n${m.source || ''}\n${m.time || ''}`),
    `性能检测说明：${report.performance.methodology || report.performance.reason || '未记录'}`,
    `AI 抽样说明：${report.sample.methodology || '明确品牌名称复核'}\n抽样局限：${report.sample.limitations || '仅代表本次少量问题，不代表所有 AI 平台或长期稳定表现。'}`,
    ...report.performanceRows.map(m => `${m.label}：${m.value}\n${m.source || report.performance.provider || '来源未记录'}`),
    `Schema：${report.snapshot.schema_types?.join('、') || '未记录'}`,
    ...(report.snapshot.headings || []).map(h => `H${h.level} · ${h.text}`),
    ...(report.snapshot.external_links || []).map(link => `外部引用：${typeof link === 'string' ? link : JSON.stringify(link)}`),
  ].join('\n\n')
  splitReportText(evidence, 1000).forEach(text => slides.push({ kind: 'text', title: '附录二｜证据来源与检测范围', english: 'APPENDIX B / EVIDENCE & SCOPE', text }))
  samples.forEach((row, index) => {
    const questionParts = splitReportText(row.question || '问题未记录', 110, 65)
    const parts = splitReportText(row.response + (row.source_urls?.length ? `\n\n回答中的链接\n${row.source_urls.join('\n')}` : ''), 1000)
    for (let i = 1; i < questionParts.length; i++) slides.push({ kind: 'text', title: `附录三｜问题 ${index + 1}（续）`, english: 'APPENDIX C / ORIGINAL RESPONSE', text: questionParts[i] })
    parts.forEach((text, part) => slides.push({ kind: 'answer', title: `附录三｜AI 抽样原始回答 ${index + 1}${part ? `（续 ${part}）` : ''}`, english: 'APPENDIX C / ORIGINAL RESPONSE', question: part ? `问题 ${index + 1} · 原始回答续页` : questionParts[0], row, text }))
  })
  if (!samples.length) slides.push({ kind: 'text', title: '附录三｜AI 抽样原始回答', english: 'APPENDIX C / ORIGINAL RESPONSE', text: '未检测：本次没有保存可用的模型回答。' })
  return { ...report, dimensions, samples, names, explicitCount, explicitRate, slides }
}
