import { semMetric } from '../../../../../integrations/sem-cockpit/display.mjs'

const formatMetric = (metrics, key, unit, coverage = { status: 'observed', missing_dates: [] }) =>
  semMetric(metrics?.[key], unit, coverage).text

function scopeReason(scope = {}, accounts = []) {
  const excluded = Array.isArray(scope.excluded_non_active_account_ids) ? scope.excluded_non_active_account_ids : []
  const nonActive = accounts.filter(item => item.baidu_account_id !== null && item.status !== 'active')
  const notes = []
  if (nonActive.length) notes.push(`本次返回包含 ${nonActive.length} 个非在投账户，汇总数字不能视为当前在投口径。`)
  else if (Array.isArray(scope.excluded_non_active_account_ids)) notes.push('本次默认范围仅纳入接口标记为在投的百度推广账户。')
  else notes.push('接口未提供非在投账户排除清单，账户范围仍需核对。')
  if (excluded.length) notes.push(`已排除 ${excluded.length} 个非在投账户。`)
  if (scope.includes_unassigned) notes.push('另含未归属到账户的报告，查看明细时需单独核对。')
  return notes.join('')
}

export function semScopeCard(report, contextRevision) {
  const accounts = Array.isArray(report?.accounts) ? report.accounts : []
  const scope = report?.account_scope || {}
  const excluded = Array.isArray(scope.excluded_non_active_account_ids) ? scope.excluded_non_active_account_ids : []
  const partial = scope.includes_unassigned === true || !Array.isArray(scope.excluded_non_active_account_ids)
    || accounts.some(item => item.baidu_account_id !== null && item.status !== 'active')
  return {
    id: 'sem-account-scope', moduleCode: 'sem', moduleLabel: 'SEM', label: '账户范围',
    display: String(accounts.filter(item => item.baidu_account_id !== null).length), unit: '个',
    state: partial ? 'partial' : 'available', reason: scopeReason(scope, accounts), contextRevision,
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
  const mismatched = items.filter(item => item.report_association?.status === 'account_mismatch').length
  const pageScope = items.length < payload.total ? `本页展示 ${items.length} 个；` : ''
  return {
    id: 'sem-keywords', moduleCode: 'sem', moduleLabel: 'SEM', label: '关键词资产',
    display: String(payload.total), unit: '个', state: mismatched ? 'partial' : payload.total ? 'available' : 'no_data',
    reason: payload.total
      ? `${pageScope}当前页 ${observed} 个关键词有同账户报告依据；${mismatched ? `${mismatched} 个仅观察到其他账户的同 ID 报告，未合并其指标；` : ''}总数是资产数量，不代表全部正在投放。`
      : '当前范围没有可读取的关键词资产。',
    contextRevision, periodLabel: `${payload.window.start} 至 ${payload.window.end}`,
    sourceLabel: '关键词资产与关键词报告', updatedLabel: newestStamp(items.flatMap(item =>
      [item.coverage?.updated_at, item.asset_updated_at])) || '未知', series: [],
    columns: [{ key: 'keyword', label: '关键词' }, { key: 'status', label: '状态' }, { key: 'report', label: '报告关联' },
      { key: 'cost', label: '花费' }, { key: 'click', label: '点击' }, { key: 'ctr', label: '点击率' }],
    rows: items.map(item => ({
      keyword: item.keyword || `关键词 ${item.keyword_id}`,
      status: item.pause === true ? '关键词已暂停' : item.pause === false ? '关键词未暂停' : '待确认',
      report: item.report_association?.status === 'matched' ? '同账户报告已关联'
        : item.report_association?.status === 'account_mismatch' ? '仅其他账户有同 ID 报告' : '窗口内无报告',
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
    sourceLabel: '搜索词同步快照', updatedLabel: newestStamp((payload.windows || []).flatMap(item =>
      [item.updated_at, item.oldest_updated_at])) || '未知', series: [],
    columns: [{ key: 'query', label: '客户实际搜索' }, { key: 'keyword', label: '触发关键词' },
      { key: 'account', label: '账户 ID' }, { key: 'cost', label: '花费' }, { key: 'click', label: '点击' }],
    rows: items.map(item => ({
      query: item.query_word, keyword: item.trigger_keyword || '未关联', account: item.baidu_account_id ?? '未归属',
      cost: formatMetric(item.metrics, 'cost', 'CNY'), click: formatMetric(item.metrics, 'click', 'count'),
    })),
  }
}

function newestStamp(values) {
  return values.filter(value => typeof value === 'string' && Number.isFinite(Date.parse(value)))
    .reduce((latest, value) => latest === null || Date.parse(value) > Date.parse(latest) ? value : latest, null)
}

const invalidatingPriority = new Map([
  ['ACCESS_REVOKED', 3], ['NOT_AUTHORIZED', 3], ['CONTRACT_MISMATCH', 2],
  ['STALE_SESSION', 1], ['STALE_AUTHORIZATION', 1], ['STALE_RESPONSE', 1],
])

// A permission/identity failure invalidates the whole concurrent batch. Never republish a
// successful sibling after the client has already cleared evidence for the revoked context.
export function resolveSemDetailBatch(results) {
  const invalidating = results.filter(result => result.status === 'rejected' && invalidatingPriority.has(result.reason?.code))
    .sort((left, right) => invalidatingPriority.get(right.reason.code) - invalidatingPriority.get(left.reason.code))[0]
  if (invalidating) throw invalidating.reason
  return results.map(result => result.status === 'fulfilled'
    ? { value: result.value, error: null }
    : { value: null, error: result.reason })
}
