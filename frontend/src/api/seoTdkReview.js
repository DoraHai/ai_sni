export const defaultTdkReviewSections = [
  { key: 'header', enabled: true, title: '页面信息' },
  { key: 'screenshot', enabled: true, title: '页面截图' },
  { key: 'tdk_compare', enabled: true, title: 'TDK 对比' },
  { key: 'keyword_layout', enabled: true, title: '关键词布局' },
  { key: 'internal_links', enabled: true, title: '内链数据' },
  { key: 'client_comment', enabled: true, title: '客户意见' },
]

export function validTdkReviewTemplate(sections, columns) {
  return Array.isArray(sections) && sections.length === defaultTdkReviewSections.length &&
    new Set(sections.map(item => item.key)).size === defaultTdkReviewSections.length &&
    sections.every(item => defaultTdkReviewSections.some(spec => spec.key === item.key) &&
      typeof item.enabled === 'boolean' && typeof item.title === 'string' &&
      item.title.trim().length >= 1 && item.title.trim().length <= 40) &&
    sections.some(item => item.enabled) && columns && Object.keys(columns).length === 2 &&
    typeof columns.char_counts === 'boolean' && typeof columns.rationale === 'boolean'
}

export function moveTdkReviewSection(sections, index, direction) {
  const result = sections.map(item => ({ ...item }))
  const other = index + direction
  if (other >= 0 && other < result.length) [result[index], result[other]] = [result[other], result[index]]
  return result
}

export function reviewPageIds(rows) {
  return [...new Set(rows.map(row => row.id))]
}

export function reviewFilename(header, fallback) {
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header || '')?.[1]
  if (!encoded) return fallback
  try { return decodeURIComponent(encoded) } catch { return fallback }
}
