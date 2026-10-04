export const defaultReportSections = [
  { key: 'cover', enabled: true, title: '封面' },
  { key: 'traffic', enabled: true, title: '本月流量' },
  { key: 'publication_summary', enabled: true, title: '发布汇总' },
  { key: 'publication_detail', enabled: true, title: '发布明细' },
  { key: 'screenshot_appendix', enabled: true, title: '截图附录' },
]

export function moveReportSection(sections, index, direction) {
  const other = index + direction
  if (other < 0 || other >= sections.length) return sections.slice()
  const result = sections.map(item => ({ ...item }))
  ;[result[index], result[other]] = [result[other], result[index]]
  return result
}

export function validReportSections(sections) {
  return sections.length === defaultReportSections.length &&
    new Set(sections.map(item => item.key)).size === defaultReportSections.length &&
    sections.every(item => defaultReportSections.some(spec => spec.key === item.key) &&
      typeof item.enabled === 'boolean' && typeof item.title === 'string' &&
      item.title.trim().length >= 1 && item.title.trim().length <= 40) &&
    sections.some(item => item.enabled)
}

export async function monthlyReportError(error) {
  const data = error.response?.data
  if (data instanceof Blob) {
    try { return JSON.parse(await data.text()).detail?.message || '月报生成失败' } catch { /* use message */ }
  }
  return data?.detail?.message || error.message || '月报生成失败'
}
