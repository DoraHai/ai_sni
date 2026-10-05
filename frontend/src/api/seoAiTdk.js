export const aiTdkStatus = status => ({ ai_draft: 'AI草稿', confirmed: '已确认', modified: '已修改', rejected: '已驳回' })[status] || status
export const aiTdkFields = [
  { key: 'title', label: 'Title', current: 'title' },
  { key: 'description', label: 'Description', current: 'meta_description' },
  { key: 'keywords', label: 'Keywords', current: 'meta_keywords' },
]
export const aiTdkCount = value => [...String(value || '')].length
export const aiTdkResultText = items => (items || []).map(item => `#${item.page_id}：${item.status === 'generated' ? '已生成' : item.status === 'skipped' ? '输入未变，已跳过' : item.error || '生成失败'}`).join('\n')
