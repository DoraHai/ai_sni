export function articleVersionLabel(article) {
  if (!article?.id) return '尚无保存版本'
  const meta = article.generation_meta || {}
  const source = {
    ai: 'AI 生成', rules: '规则草稿',
    rules_after_claim_guard: '证据原文稿（模型越界后）', manual_edit: '手动保存',
    article_import: '导入', ai_optimize: 'AI 优化',
  }[meta.source] || '来源未记录'
  const version = article.version_no == null ? '版本未知' : `V${article.version_no}`
  const parent = meta.from_version == null ? '' : ` · 基于 V${meta.from_version}`
  return `${version} · ${source} · 文章 #${article.id}${parent}`
}

function apiTime(value) {
  const raw = String(value || '').trim()
  if (!raw) return NaN
  return Date.parse(/[zZ]$|[+-]\d\d:\d\d$/.test(raw) ? raw : `${raw}Z`)
}

export function formatArticleTime(value) {
  const timestamp = apiTime(value)
  if (!Number.isFinite(timestamp)) return '时间未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(timestamp)
}

export function mergeTaskJobLists(...lists) {
  const rows = lists.flat().filter(Boolean)
  return [...new Map(rows.map((job) => [Number(job.id), job])).values()]
    .sort((a, b) => Number(b.id || 0) - Number(a.id || 0))
}

export function latestGenerationFailure(article, jobs = []) {
  if (!article?.id) return null
  const latest = [...jobs]
    .filter((job) => job?.kind === 'generate_article')
    .sort((a, b) => Number(b.id || 0) - Number(a.id || 0))[0]
  if (!latest || latest.status !== 'failed') return null
  const failedAt = latest.finished_at || latest.created_at
  const articleAt = article.created_at
  if (failedAt && articleAt && apiTime(failedAt) <= apiTime(articleAt)) return null
  return {
    jobId: latest.id,
    title: `最新生成任务 #${latest.id} 失败，当前显示历史稿`,
    detail: latest.error || '生成失败，未创建新版本',
    articleLabel: articleVersionLabel(article),
    articleTime: formatArticleTime(articleAt),
    failedAt: formatArticleTime(failedAt),
  }
}
