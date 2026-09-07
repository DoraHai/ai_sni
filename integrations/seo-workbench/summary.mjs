function count(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value : null
}

function display(value) {
  return value === null ? '—' : new Intl.NumberFormat('zh-CN').format(value)
}

function rowsFromCounts(counts = {}) {
  const labels = {
    planned: '待开始', drafting: '撰写中', review: '审核中', ready: '已审核待发布',
    published: '内容状态为已发布', archived: '已归档',
  }
  return Object.entries(counts)
    .filter(([, value]) => count(value) !== null)
    .map(([status, value]) => ({ status: labels[status] || status, value: display(value) }))
}

function card({ id, label, value, reason, rows, contextRevision, urgentCount = 0 }) {
  return {
    id: `seo-${id}`, moduleCode: 'seo', moduleLabel: 'SEO', label,
    display: display(value), state: value === null ? 'unavailable' : 'available',
    reason, urgentCount, contextRevision, periodLabel: '当前所选网站', sourceLabel: 'SEO 已有只读记录',
    updatedLabel: '接口未提供独立更新时间', series: [],
    columns: rows?.length ? [{ key: 'status', label: '状态' }, { key: 'value', label: '数量' }] : [],
    rows: rows || [],
  }
}

export function seoSummaryCards({ contents = null, pages = null, contextRevision }) {
  const result = []
  if (contents) {
    const total = count(contents.total)
    const statusRows = rowsFromCounts(contents.status_counts)
    result.push(card({ id: 'contents', label: '内容总数', value: total,
      reason: total === 0 ? '当前网站还没有内容记录。' : '按内容当前状态汇总；发布状态不等于页面检查通过。',
      rows: statusRows, contextRevision }))
    const review = count(contents.status_counts?.review) ?? 0
    const ready = count(contents.status_counts?.ready) ?? 0
    result.push(card({ id: 'review', label: '待审核 / 待发布', value: review + ready,
      reason: `审核中 ${review}，已审核待发布 ${ready}。审核、发布和页面检查分别判断。`,
      rows: [{ status: '审核中', value: display(review) }, { status: '已审核待发布', value: display(ready) }],
      urgentCount: review + ready, contextRevision }))
  }
  if (pages) {
    const total = count(pages.stats?.total)
    const healthy = count(pages.stats?.healthy)
    const needsFix = count(pages.stats?.needs_fix)
    const unchecked = count(pages.stats?.unchecked)
    result.push(card({ id: 'pages', label: '已记录页面', value: total,
      reason: total === 0 ? '当前网站还没有页面检查记录。' : '页面记录来自已有抓取与诊断，不代表真人访问量。',
      rows: [
        { status: '检查正常', value: display(healthy) },
        { status: '需要处理', value: display(needsFix) },
        { status: '尚未检查', value: display(unchecked) },
      ], contextRevision }))
    result.push(card({ id: 'page-issues', label: '页面需要处理', value: needsFix,
      reason: '来自页面诊断状态；点击可查看数量依据，具体问题请进入 SEO 页面检查。',
      rows: [], urgentCount: needsFix ?? 0, contextRevision }))
  }
  result.push(card({ id: 'article-clicks', label: '单篇文章搜索点击', value: null,
    reason: '当前没有可靠的单篇文章点击数据，不能从网站总点击或关键词推算。', rows: [], contextRevision }))
  return result
}
