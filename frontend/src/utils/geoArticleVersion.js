export function articleVersionLabel(article) {
  if (!article?.id) return '尚无保存版本'
  const meta = article.generation_meta || {}
  const source = {
    ai: 'AI 生成', rules: '规则草稿', manual_edit: '手动保存',
    article_import: '导入', ai_optimize: 'AI 优化',
  }[meta.source] || '来源未记录'
  const version = article.version_no == null ? '版本未知' : `V${article.version_no}`
  const parent = meta.from_version == null ? '' : ` · 基于 V${meta.from_version}`
  return `${version} · ${source} · 文章 #${article.id}${parent}`
}
