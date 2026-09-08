import { semMetric } from '../../../../../integrations/sem-cockpit/display.mjs'

const formatMetric = (metrics, key, unit, coverage = { status: 'observed', missing_dates: [] }) =>
  semMetric(metrics?.[key], unit, coverage).text

function scopeReason(scope = {}) {
  const excluded = Array.isArray(scope.excluded_non_active_account_ids) ? scope.excluded_non_active_account_ids : []
  const notes = ['默认只汇总当前在投的百度推广账户。']
  if (excluded.length) notes.push(`已排除 ${excluded.length} 个非在投账户。`)
  if (scope.includes_unassigned) notes.push('另含未归属到账户的报告，查看明细时需单独核对。')
  return notes.join('')
}

export function semScopeCard(report, contextRevision) {
  const accounts = Array.isArray(report?.accounts) ? report.accounts : []
  const scope = report?.account_scope || {}
  const excluded = Array.isArray(scope.excluded_non_active_account_ids) ? scope.excluded_non_active_account_ids : []
  const partial = scope.includes_unassigned === true
  return {
    id: 'sem-account-scope', moduleCode: 'sem', moduleLabel: 'SEM', label: '当前在投账户',
    display: String(accounts.filter(item => item.baidu_account_id !== null).length), unit: '个',
    state: partial ? 'partial' : 'available', reason: scopeReason(scope), contextRevision,
    periodLabel: `${report.window.start} 至 ${report.window.end}`,
    sourceLabel: '百度推广账户与关键词报告', updatedLabel: report.coverage?.updated_at || '未知',
    series: [],
    columns: [{ key: 'account', label: '账户 ID' }, { key: 'status', label: '状态' },
      { key: 'cost', label: '花费' }, { key: 'click', label: '点击' }],
    rows: [
      ...accounts.map(item => ({
        account: item.baidu_account_id ?? '未归属', status: item.status || '待确认',
        cost: formatMetric(item.metrics, 'cost', 'CNY', item.coverage),
        click: formatMetric(item.metrics, 'click', 'count', item.coverage),
      })),
      ...excluded.map(id => ({ account: id, status: '未纳入默认汇总', cost: '—', click: '—' })),
    ],
  }
}

export function semKeywordCard(payload, contextRevision) {
  const items = Array.isArray(payload?.items) ? payload.items : []
  const observed = items.filter(item => item.coverage?.status === 'observed').length
  return {
    id: 'sem-keywords', moduleCode: 'sem', moduleLabel: 'SEM', label: '关键词资产',
    display: String(payload.total), unit: '个', state: payload.total ? 'available' : 'no_data',
    reason: payload.total
      ? `当前页 ${observed} 个关键词有报告依据；总数是资产数量，不代表全部正在投放。`
      : '当前范围没有可读取的关键词资产。',
    contextRevision, periodLabel: `${payload.window.start} 至 ${payload.window.end}`,
    sourceLabel: '关键词资产与关键词报告', updatedLabel: payload.retrieved_at || '未知', series: [],
    columns: [{ key: 'keyword', label: '关键词' }, { key: 'status', label: '状态' },
      { key: 'cost', label: '花费' }, { key: 'click', label: '点击' }, { key: 'ctr', label: '点击率' }],
    rows: items.map(item => ({
      keyword: item.keyword || `关键词 ${item.keyword_id}`,
      status: item.pause === true ? '已暂停' : item.pause === false ? '在投' : '待确认',
      cost: formatMetric(item.metrics, 'cost', 'CNY', item.coverage),
      click: formatMetric(item.metrics, 'click', 'count', item.coverage),
      ctr: formatMetric(item.metrics, 'ctr', 'ratio', item.coverage),
    })),
  }
}

export function semSearchTermCard(payload, contextRevision) {
  const items = Array.isArray(payload?.items) ? payload.items : []
  const reason = payload.total === 0
    ? '当前同步窗口没有搜索词记录。'
    : payload.mixed_windows
      ? '不同账户的同步窗口不一致，明细按各自窗口展示，不能直接视为同一日期范围的总量。'
      : '展示已保存的搜索词同步快照；触发词不是咨询归因证据。'
  return {
    id: 'sem-search-terms', moduleCode: 'sem', moduleLabel: 'SEM', label: '实际搜索词',
    display: String(payload.total), unit: '条', state: payload.mixed_windows ? 'partial' : payload.total ? 'available' : 'no_data',
    reason, contextRevision, periodLabel: payload.mixed_windows ? '多个账户同步窗口' : (payload.windows?.[0]
      ? `${payload.windows[0].start || '未知'} 至 ${payload.windows[0].end || '未知'}` : '暂无同步窗口'),
    sourceLabel: '搜索词同步快照', updatedLabel: payload.retrieved_at || '未知', series: [],
    columns: [{ key: 'query', label: '客户实际搜索' }, { key: 'keyword', label: '触发关键词' },
      { key: 'account', label: '账户 ID' }, { key: 'cost', label: '花费' }, { key: 'click', label: '点击' }],
    rows: items.map(item => ({
      query: item.query_word, keyword: item.trigger_keyword || '未关联', account: item.baidu_account_id ?? '未归属',
      cost: formatMetric(item.metrics, 'cost', 'CNY'), click: formatMetric(item.metrics, 'click', 'count'),
    })),
  }
}
