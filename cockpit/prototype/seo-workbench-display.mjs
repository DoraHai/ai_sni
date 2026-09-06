// Reviewed source 9a33e785a2e447f714a82d2d22bb203d94dd18e7; offline prototype copy.
/**
 * Pure display mapping for the SEO acquisition-workbench read model.
 *
 * Input must already have passed app.seo_workbench_adapter. These helpers do
 * not fetch data, discover page links, or infer publication/check/search
 * outcomes from adjacent fields.
 */

const PUBLICATION_LABELS = {
  preparing: '准备中',
  publishing: '发布中',
  draft_created: '已创建平台草稿',
  manual_required: '待人工处理',
  published: '发布成功',
  failed: '发布失败',
  cancelled: '已取消',
}

const ATTEMPT_LABELS = {
  pending: '等待执行',
  running: '执行中',
  succeeded: '尝试成功',
  success: '尝试成功',
  failed: '尝试失败',
  cancelled: '已取消',
}

const PAGE_MAPPING_LABELS = {
  not_linked: '尚未关联发布页面',
  missing_url: '发布记录缺少页面地址',
  unmapped: '发布地址尚未关联 SEO 页面',
  ambiguous: '存在多个候选页面',
  source_page_only: '只有来源或承接页证据',
  linked_page_unavailable: '已关联页面，但详情不可用',
  matched: '已核对发布页面',
}

const PAGE_CHECK_LABELS = {
  not_checked: '尚未检查',
  assessed: '已完成检查',
  unavailable: '本次检查不可用',
}

function finiteCount(value) {
  return Number.isFinite(value) && value >= 0 ? value : null
}

function positiveId(value) {
  return Number.isInteger(value) && value > 0 ? value : null
}

function latestAttemptDisplay(attempt) {
  if (!attempt || typeof attempt !== 'object') return null
  const state = Object.prototype.hasOwnProperty.call(ATTEMPT_LABELS, attempt.status)
    ? attempt.status
    : 'unknown'
  return {
    id: positiveId(attempt.id),
    state,
    label: ATTEMPT_LABELS[state] || '尝试状态未知',
    action: attempt.action || null,
    error: attempt.error || null,
    startedAt: attempt.started_at || null,
    completedAt: attempt.completed_at || null,
  }
}

export function publicationDisplay(publications, summary) {
  const rowsKnown = Array.isArray(publications)
  const rows = rowsKnown ? publications : []
  return {
    state: rowsKnown ? 'available' : 'unavailable',
    recordCount: finiteCount(summary?.record_count),
    successfulCount: finiteCount(summary?.successful_count),
    failedCount: finiteCount(summary?.failed_count),
    items: rows.map((row) => {
      const state = Object.prototype.hasOwnProperty.call(PUBLICATION_LABELS, row?.state)
        ? row.state
        : 'unknown'
      return {
        id: positiveId(row?.id),
        platformCode: row?.platform_code || null,
        publishMode: row?.publish_mode || null,
        state,
        label: PUBLICATION_LABELS[state] || '发布状态未知',
        successful: state === 'published' ? true : state === 'unknown' ? null : false,
        publishedAt: row?.published_at || null,
        pageUrl: row?.page_url || null,
        failure: row?.failure || null,
        latestAttempt: latestAttemptDisplay(row?.latest_attempt),
      }
    }),
  }
}

export function pageCheckDisplay(evidence) {
  const mappingState = Object.prototype.hasOwnProperty.call(
    PAGE_MAPPING_LABELS,
    evidence?.mapping_state,
  ) ? evidence.mapping_state : 'unknown'
  const pageId = positiveId(evidence?.page_id)
  const bound = mappingState === 'matched' && pageId !== null
  if (!bound) {
    return {
      mappingState,
      mappingLabel: PAGE_MAPPING_LABELS[mappingState] || '页面关联状态未知',
      candidateCount: finiteCount(evidence?.candidate_count),
      pageId: null,
      state: 'unavailable',
      label: '页面检查结果不可用',
      checkedAt: null,
      latestSnapshotId: null,
      httpStatus: null,
      failure: null,
      passed: null,
      outcomeLabel: '未提供整页通过结论',
    }
  }

  const checkState = Object.prototype.hasOwnProperty.call(
    PAGE_CHECK_LABELS,
    evidence?.check_state,
  ) ? evidence.check_state : 'unknown'
  const passed = checkState === 'assessed' && typeof evidence?.passed === 'boolean'
    ? evidence.passed
    : null
  return {
    mappingState,
    mappingLabel: PAGE_MAPPING_LABELS[mappingState],
    candidateCount: finiteCount(evidence?.candidate_count),
    pageId,
    state: checkState,
    label: PAGE_CHECK_LABELS[checkState] || '页面检查状态未知',
    checkedAt: evidence?.checked_at || null,
    latestSnapshotId: positiveId(evidence?.latest_snapshot_id),
    httpStatus: Number.isInteger(evidence?.http_status) ? evidence.http_status : null,
    failure: evidence?.failure || null,
    passed,
    outcomeLabel: passed === true
      ? '页面检查通过'
      : passed === false ? '页面检查未通过' : '未提供整页通过结论',
  }
}

export function searchPerformanceDisplay(performance) {
  const supplied = finiteCount(performance?.article_clicks)
  const available = performance?.state === 'available' && supplied !== null
  return {
    state: available ? 'available' : 'unavailable',
    articleClicks: available ? supplied : null,
    valueText: available ? String(supplied) : '—',
    reason: available ? null : (performance?.reason || '尚未接入可靠的单篇文章点击数据'),
  }
}

export function seoWorkbenchDisplay(view) {
  return {
    publication: publicationDisplay(view?.publications, view?.publication_summary),
    pageCheck: pageCheckDisplay(view?.page_evidence),
    searchPerformance: searchPerformanceDisplay(view?.search_performance),
  }
}
