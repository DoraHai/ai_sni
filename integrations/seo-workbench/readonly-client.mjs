/**
 * SEO phase-one readonly consumer.
 *
 * The host provides an authenticated GET-only transport. This client never
 * logs in, stores credentials, starts collection, generates content, publishes
 * content, or infers a URL-to-page relationship.
 */

const resources = Object.freeze({
  contents: '/api/v1/seo/content-assets',
  reviewHistory: '/api/v1/seo/content-assets/',
  publications: '/api/v1/seo/content-distribution/publications',
  attempts: '/api/v1/seo/content-distribution/publications/',
  pages: '/api/v1/seo/site-pages',
  imageEvidence: '/api/v1/seo/site-pages/image-evidence',
})

const allowedParams = Object.freeze({
  contents: new Set(['contentId', 'sourcePageId', 'status', 'contentType', 'contentTypes', 'q', 'page', 'pageSize']),
  reviewHistory: new Set(['contentId']),
  // A snapshot needs the complete per-content publication set. A filtered
  // subset cannot safely drive record_count or the pending-publication label.
  publications: new Set(['contentId']),
  attempts: new Set(['publicationId']),
  pages: new Set(['pageId', 'q', 'status', 'issueCode', 'page', 'pageSize']),
  imageEvidence: new Set(['pageId', 'snapshotId']),
})

export class SeoReadonlyError extends Error {
  constructor(code, message) { super(message); this.name = 'SeoReadonlyError'; this.code = code }
}

function fail(code, message) { throw new SeoReadonlyError(code, message) }
function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value) }
function positive(value) { return Number.isSafeInteger(value) && value > 0 }
function nonnegative(value) { return Number.isSafeInteger(value) && value >= 0 }
function nullableString(value) { return value === null || typeof value === 'string' }
function timestamp(value) {
  return value === null || (typeof value === 'string' && value.includes('T') && Number.isFinite(Date.parse(value)))
}
function contract(condition) {
  if (!condition) fail('CONTRACT_MISMATCH', 'SEO 只读响应字段、范围或空值契约不匹配')
}
function validateEnvelope(data) { contract(object(data) && Array.isArray(data.items)) }
function validateCounts(value) {
  contract(object(value) && Object.values(value).every(nonnegative))
}

function validateContent(item, context) {
  contract(object(item) && positive(item.id))
  contract(item.tenant_id === context.tenantId && item.site_id === context.siteId)
  contract(typeof item.status === 'string' && nullableString(item.title) && nullableString(item.page_url))
  contract(timestamp(item.reviewed_at) && timestamp(item.updated_at) && timestamp(item.published_at))
  for (const key of ['review_submitted_by', 'reviewed_by']) {
    contract(item[key] === null || positive(item[key]))
  }
  return item
}

function validatePage(item, context) {
  contract(object(item) && positive(item.id))
  contract(item.tenant_id === context.tenantId && item.site_id === context.siteId)
  contract(typeof item.url === 'string' && item.url.length > 0)
  contract(item.http_status === null || nonnegative(item.http_status))
  contract(object(item.diagnostic) && typeof item.diagnostic.assessment_state === 'string')
  contract(timestamp(item.diagnostic.checked_at))
  contract(item.diagnostic.http_status === null || nonnegative(item.diagnostic.http_status))
  contract(timestamp(item.last_checked_at) && nullableString(item.last_error))
  return item
}

function validatePagination(data, params) {
  contract(nonnegative(data.total) && positive(data.page) && positive(data.page_size))
  contract(data.page === (params.page ?? 1) && data.page_size === (params.pageSize ?? 50))
  contract(data.items.length <= data.page_size && data.items.length <= data.total)
}

function queryFor(resource, context, params) {
  const query = new URLSearchParams({ tenant_id: String(context.tenantId) })
  if (resource !== 'reviewHistory') query.set('site_id', String(context.siteId))
  const names = {
    contentId: 'content_id', sourcePageId: 'source_page_id', contentType: 'content_type',
    contentTypes: 'content_types', pageId: 'page_id', snapshotId: 'snapshot_id',
    issueCode: 'issue_code', pageSize: 'page_size', publicationId: 'publication_id',
    q: 'q', status: 'status', page: 'page',
  }
  for (const [key, value] of Object.entries(params)) {
    const pathParameter = (resource === 'reviewHistory' && key === 'contentId') ||
      (resource === 'attempts' && key === 'publicationId')
    if (value !== undefined && !pathParameter) query.set(names[key], String(value))
  }
  return query
}

function routeFor(resource, params) {
  if (resource === 'reviewHistory') return `${resources.reviewHistory}${params.contentId}/review-history`
  if (resource === 'attempts') return `${resources.attempts}${params.publicationId}/attempts`
  return resources[resource]
}

function reviewView(content) {
  const approved = ['ready', 'published'].includes(content.status) && timestamp(content.reviewed_at) && content.reviewed_at !== null
  const independent = approved && positive(content.review_submitted_by) && positive(content.reviewed_by) &&
    content.review_submitted_by !== content.reviewed_by
  return {
    state: approved ? 'approved' : content.status === 'review' ? 'in_review' : 'not_reviewed',
    label: approved ? (independent ? '审核通过' : '历史审核，独立性未确认') : content.status === 'review' ? '审核中' : '未审核',
    independent: Boolean(independent),
    reviewed_at: approved ? content.reviewed_at : null,
  }
}

function publicationView(row, latestAttempt) {
  return {
    id: row.id,
    platform_code: row.platform_code,
    platform_name: row.platform_name,
    publish_mode: row.publish_mode,
    state: row.status,
    published_at: row.published_at,
    page_url: row.page_url,
    failure: row.last_error,
    latest_attempt: latestAttempt ? {
      id: latestAttempt.id,
      action: latestAttempt.action,
      status: latestAttempt.status,
      error: latestAttempt.error,
      started_at: latestAttempt.started_at,
      completed_at: latestAttempt.completed_at,
    } : null,
  }
}

export function createSeoReadonlyClient({ transport, onClear }) {
  if (typeof transport !== 'function' || typeof onClear !== 'function') {
    throw new TypeError('Authenticated transport and a clearing callback are required')
  }
  let context = null
  let revision = 0
  const pending = new Map()
  const contents = new Map()
  const publications = new Map()
  const publicationsByContent = new Map()
  const attempts = new Map()
  const pages = new Map()
  const imageEvidence = new Map()

  function clearData() {
    contents.clear(); publications.clear(); publicationsByContent.clear()
    attempts.clear(); pages.clear(); imageEvidence.clear()
  }

  function abortPending(prefixes) {
    for (const [key, controller] of pending) {
      if (prefixes.some(prefix => key.startsWith(prefix))) {
        controller.abort()
        pending.delete(key)
      }
    }
  }

  function revokePublicationSet(contentId) {
    const priorIds = publicationsByContent.get(contentId) ?? []
    for (const id of priorIds) {
      const pendingAttempt = pending.get(`attempts:${id}`)
      pendingAttempt?.abort()
      pending.delete(`attempts:${id}`)
      publications.delete(id)
      attempts.delete(id)
    }
    publicationsByContent.delete(contentId)
  }

  function beginContentRefresh() {
    // The client represents the currently visible content result, not an
    // unbounded identity cache. Paging or changing filters revokes the old set.
    abortPending(['reviewHistory:', 'publications:', 'attempts:'])
    contents.clear()
    publications.clear()
    publicationsByContent.clear()
    attempts.clear()
  }

  function beginPageRefresh() {
    abortPending(['imageEvidence:'])
    pages.clear()
    imageEvidence.clear()
  }

  function invalidate() {
    revision++
    context = null
    for (const controller of pending.values()) controller.abort()
    pending.clear()
    clearData()
    onClear()
  }

  function setContext(next) {
    invalidate()
    if (next === null) return
    if (!object(next) || !positive(next.tenantId) || !positive(next.siteId) || !positive(next.userId) ||
        typeof next.authorizationRevision !== 'string' || !next.authorizationRevision.trim() ||
        !Array.isArray(next.allowedReads) || next.allowedReads.some(key => !Object.hasOwn(resources, key))) {
      fail('INVALID_CONTEXT', '需要已核验的客户、SEO 站点、用户、权限版本和只读范围')
    }
    context = Object.freeze({ ...next, allowedReads: Object.freeze([...next.allowedReads]) })
  }

  function requireReference(resource, params) {
    if (resource === 'reviewHistory' || resource === 'publications') {
      if (!positive(params.contentId)) fail('INVALID_FILTER', 'contentId 必须是正整数')
      if (!contents.has(params.contentId)) fail('UNVERIFIED_REFERENCE', '须先从当前站点内容列表核验 contentId')
    }
    if (resource === 'attempts') {
      if (!positive(params.publicationId)) fail('INVALID_FILTER', 'publicationId 必须是正整数')
      if (!publications.has(params.publicationId)) fail('UNVERIFIED_REFERENCE', '须先核验当前内容的 publicationId')
    }
    if (resource === 'imageEvidence') {
      if (!positive(params.pageId)) fail('INVALID_FILTER', 'pageId 必须是正整数')
      if (!pages.has(params.pageId)) fail('UNVERIFIED_REFERENCE', '须先从当前站点页面列表核验 pageId')
    }
  }

  function validateFilters(resource, params) {
    if (!object(params) || Object.keys(params).some(key => !allowedParams[resource].has(key))) {
      fail('UNSUPPORTED_FILTER', '存在未审核的 SEO 只读筛选')
    }
    for (const key of ['contentId', 'sourcePageId', 'pageId', 'snapshotId', 'publicationId', 'page', 'pageSize']) {
      if (Object.hasOwn(params, key) && !positive(params[key])) fail('INVALID_FILTER', `${key} 必须是正整数`)
    }
    if (params.pageSize > 200 || (params.q !== undefined && (typeof params.q !== 'string' || params.q.length > 200))) {
      fail('INVALID_FILTER', '筛选超出接口限制')
    }
    for (const key of ['status', 'contentType', 'contentTypes', 'issueCode']) {
      if (Object.hasOwn(params, key) && (typeof params[key] !== 'string' || !params[key].trim())) {
        fail('INVALID_FILTER', `${key} 必须是非空字符串`)
      }
    }
  }

  function accept(resource, data, params, active) {
    if (resource === 'contents') {
      validateEnvelope(data); validatePagination(data, params); validateCounts(data.status_counts)
      for (const item of data.items) {
        validateContent(item, active)
        if (params.contentId !== undefined) contract(item.id === params.contentId)
        if (params.sourcePageId !== undefined) contract(item.source_page_id === params.sourcePageId)
        contents.set(item.id, item)
      }
    } else if (resource === 'reviewHistory') {
      contract(contents.has(params.contentId))
      validateEnvelope(data); contract(data.total === data.items.length && nonnegative(data.total))
      for (const item of data.items) {
        contract(object(item) && positive(item.id) && typeof item.action === 'string')
        contract(item.actor_id === null || positive(item.actor_id)); contract(timestamp(item.created_at))
      }
    } else if (resource === 'publications') {
      contract(contents.has(params.contentId))
      validateEnvelope(data); contract(nonnegative(data.total) && data.total === data.items.length); validateCounts(data.status_counts)
      const rows = []
      for (const item of data.items) {
        contract(object(item) && positive(item.id) && item.tenant_id === active.tenantId)
        contract(item.content_id === params.contentId && contents.has(item.content_id))
        contract(typeof item.status === 'string' && nullableString(item.page_url) && nullableString(item.last_error))
        if (params.status !== undefined) contract(item.status === params.status)
        contract(timestamp(item.published_at) && timestamp(item.updated_at))
        publications.set(item.id, item); rows.push(item.id)
      }
      publicationsByContent.set(params.contentId, rows)
    } else if (resource === 'attempts') {
      contract(publications.has(params.publicationId))
      validateEnvelope(data)
      for (const item of data.items) {
        contract(object(item) && positive(item.id) && typeof item.action === 'string' && typeof item.status === 'string')
        contract(nullableString(item.error) && timestamp(item.started_at) && timestamp(item.completed_at))
      }
      attempts.set(params.publicationId, data.items)
    } else if (resource === 'pages') {
      validateEnvelope(data); validatePagination(data, params); contract(object(data.stats))
      for (const item of data.items) {
        validatePage(item, active)
        if (params.pageId !== undefined) contract(item.id === params.pageId)
        if (params.status !== undefined) contract(item.status === params.status)
        pages.set(item.id, item)
      }
    } else if (resource === 'imageEvidence') {
      const page = pages.get(params.pageId)
      contract(page && object(data) && data.page_id === params.pageId && data.url === page.url)
      contract(data.snapshot_id === null || positive(data.snapshot_id))
      if (params.snapshotId !== undefined) contract(data.snapshot_id === params.snapshotId)
      contract(timestamp(data.fetched_at) && nullableString(data.fetch_error))
      contract(data.evidence === null || object(data.evidence))
      imageEvidence.set(params.pageId, data)
    }
    return data
  }

  async function read(resource, params = {}) {
    if (!Object.hasOwn(resources, resource)) fail('UNSUPPORTED_RESOURCE', '不支持的 SEO 只读资源')
    if (!context || !context.allowedReads.includes(resource)) fail('NOT_AUTHORIZED', '尚未确认该 SEO 读取权限')
    validateFilters(resource, params)
    requireReference(resource, params)
    if (resource === 'contents') beginContentRefresh()
    else if (resource === 'pages') beginPageRefresh()
    else if (resource === 'publications') revokePublicationSet(params.contentId)
    const active = context
    const atRevision = revision
    const key = resource === 'reviewHistory' || resource === 'publications' ? `${resource}:${params.contentId}` :
      resource === 'attempts' ? `${resource}:${params.publicationId}` :
      resource === 'imageEvidence' ? `${resource}:${params.pageId}` : resource
    pending.get(key)?.abort()
    const controller = new AbortController()
    pending.set(key, controller)
    const stale = () => revision !== atRevision || controller.signal.aborted || pending.get(key) !== controller
    const path = `${routeFor(resource, params)}?${queryFor(resource, active, params)}`
    try {
      const response = await transport(path, { method: 'GET', cache: 'no-store', signal: controller.signal })
      if (stale()) fail('STALE_RESPONSE', '已丢弃旧客户、站点或筛选结果')
      if (response.status === 401 || response.status === 403) {
        invalidate(); fail('ACCESS_REVOKED', 'SEO 只读权限、租户或模块资格已失效')
      }
      if (response.status === 404) fail('NOT_FOUND', '当前 SEO 关联对象不存在')
      if (!response.ok) fail('READ_FAILED', `SEO 只读接口失败（${response.status}），未回退为演示或零值`)
      let data
      try { data = await response.json() } catch (error) {
        if (stale()) fail('STALE_RESPONSE', '已丢弃旧 SEO 响应')
        invalidate(); fail('CONTRACT_MISMATCH', 'SEO 响应不是有效 JSON')
      }
      if (stale()) fail('STALE_RESPONSE', '已丢弃旧客户、站点或筛选结果')
      try { return accept(resource, data, params, active) } catch (error) {
        invalidate()
        if (error instanceof SeoReadonlyError) throw error
        fail('CONTRACT_MISMATCH', 'SEO 响应字段、范围或空值契约不匹配')
      }
    } catch (error) {
      if (!(error instanceof SeoReadonlyError) && stale()) fail('STALE_RESPONSE', '已丢弃旧 SEO 请求错误')
      if (!(error instanceof SeoReadonlyError)) fail('READ_FAILED', 'SEO 只读网络不可用，未回退为演示或零值')
      throw error
    } finally {
      if (pending.get(key) === controller) pending.delete(key)
    }
  }

  function snapshot(contentId, { pageBinding = null } = {}) {
    if (!context || !contents.has(contentId)) fail('UNVERIFIED_REFERENCE', '当前站点没有已核验的内容记录')
    if (!publicationsByContent.has(contentId)) fail('DATA_NOT_LOADED', '须先读取该内容的分平台发布记录')
    const content = contents.get(contentId)
    const rows = publicationsByContent.get(contentId).map(id => publications.get(id))
    const publicationRows = rows.map(row => publicationView(row, attempts.get(row.id)?.[0] ?? null))
    const review = reviewView(content)
    const summary = {
      record_count: publicationRows.length,
      successful_count: publicationRows.filter(row => row.state === 'published').length,
      failed_count: publicationRows.filter(row => row.state === 'failed').length,
    }
    let page = null
    let evidence = null
    let mappingState = 'not_linked'
    if (pageBinding !== null) {
      contract(object(pageBinding) && positive(pageBinding.pageId) && typeof pageBinding.pageUrl === 'string')
      page = pages.get(pageBinding.pageId)
      if (!page) fail('DATA_NOT_LOADED', '须先读取明确关联的页面')
      contract(page.url === pageBinding.pageUrl)
      if (pageBinding.targetKind === 'content_page_url') contract(content.page_url === pageBinding.pageUrl)
      else if (pageBinding.targetKind === 'publication_page_url') {
        contract(positive(pageBinding.publicationId))
        const publication = rows.find(row => row.id === pageBinding.publicationId)
        contract(Boolean(publication) && publication.page_url === pageBinding.pageUrl)
      } else contract(false)
      evidence = imageEvidence.get(page.id) ?? null
      mappingState = 'matched'
    } else {
      const published = publicationRows.filter(row => row.state === 'published')
      const urls = published.filter(row => row.page_url)
      if (published.length > 0 && urls.length === 0) mappingState = 'missing_url'
      else if (urls.length > 0) mappingState = 'unmapped'
      else if (content.source_page_id !== null && content.source_page_id !== undefined) mappingState = 'source_page_only'
    }
    return {
      content: { id: content.id, title: content.title, state: content.status,
        label: review.state === 'approved' && summary.successful_count === 0 ? '已审核待发布' :
          summary.successful_count > 0 ? '已有发布记录' : review.state === 'in_review' ? '审核中' : '未审核',
        version: content.version_count, updated_at: content.updated_at },
      review,
      publications: publicationRows,
      publication_summary: summary,
      page_evidence: {
        mapping_state: mappingState, page_id: page?.id ?? null, candidate_count: page ? 1 : 0,
        check_state: page?.diagnostic?.assessment_state ?? 'not_checked',
        checked_at: page?.diagnostic?.checked_at ?? null,
        latest_snapshot_id: evidence?.snapshot_id ?? null,
        http_status: page?.diagnostic?.http_status ?? null,
        failure: page?.last_error ?? evidence?.fetch_error ?? null,
        passed: null,
      },
      search_performance: { article_clicks: null, state: 'unavailable',
        reason: 'SEO 当前没有可靠的单篇文章点击数据，不能从业务总点击或关键词推断。' },
    }
  }

  return Object.freeze({ setContext, invalidate, read, snapshot })
}
