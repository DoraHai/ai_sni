<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { auditPendingSeoSitePages, auditSeoSitePage, cleanupSeoNonHtmlSitePages, fetchSeoBrokenLinkReport, fetchSeoContentAssets, fetchSeoKeywords, fetchSeoSitePageDetail, fetchSeoSitePageIssues, fetchSeoSitePages, generateSeoSitePageSuggestions, importSeoSitePages, updateSeoContentAsset, updateSeoSitePage } from '../../api/seo'
import { fetchSeoSites } from '../../api/moduleAssets'
import { currentTenantId, session } from '../../store/session'
import { formatSeoCsvTime } from './seoRankTime'
import { runSeoBatch } from './seoBatchOperations'
import { currentSeoSiteId as siteId } from './seoSiteContext'
import SeoSiteDiagnosticsPanel from './SeoSiteDiagnosticsPanel.vue'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const diagnosticRefreshKey = ref(0)
const error = ref('')
const sites = ref([])
const result = ref({ items: [], total: 0, stats: {} })
const filters = reactive({ q: '', status: '', issueCode: '' })
const importOpen = ref(false)
const editOpen = ref(false)
const importText = ref('')
const editing = ref(null)
const saving = ref(false)
const auditing = ref(new Set())
const batchAuditing = ref(false)
const generating = ref(false)
const cleaningNonHtml = ref(false)
const exportingBrokenLinks = ref(false)
const selectedRows = ref([])
const page = ref(1)
const pageSize = ref(50)
const keywordOptions = ref([])
const linkDialogOpen = ref(false)
const linkPage = ref(null)
const linkCandidates = ref([])
const selectedContentId = ref(null)
const linkingContent = ref(false)
const issueLoading = ref(false)
const issueResult = ref({ items: [], summary: {} })
const issueDialogOpen = ref(false)
const activeIssue = ref(null)
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailResult = ref(null)
const editForm = reactive({ page_type: '', target_keyword_id: null, title_suggestion: '', description_suggestion: '', status: 'pending' })

const canEdit = computed(() => !session.isLoggedIn || session.canEdit('seo.site'))
const stats = computed(() => result.value.stats || {})
const emptyStateText = computed(() => Number(stats.value.total || 0) > 0 ? '没有符合当前筛选条件的页面' : '尚未导入站内页面')
const actionScopeLabel = computed(() => selectedRows.value.length ? `已选 ${selectedRows.value.length} 条` : `当前页 ${result.value.items.length} 条`)
function fmt(value) { return value == null ? '—' : Number(value).toLocaleString('zh-CN') }
function statusLabel(value) { return {pending:'待检测',healthy:'健康',needs_fix:'需优化',proposed:'待确认',approved:'已确认',implemented:'待复检',verified:'已复检',error:'检测失败'}[value] || value }
function statusType(value) { return {pending:'info',healthy:'success',needs_fix:'warning',proposed:'warning',approved:'primary',implemented:'primary',verified:'success',error:'danger'}[value] || 'info' }
function severityLabel(value) { return {high:'严重',medium:'一般',low:'提示'}[value] || value }
function severityType(value) { return {high:'danger',medium:'warning',low:'info'}[value] || 'info' }
function displayValue(value) {
  if (value == null || value === '') return '—'
  if (Array.isArray(value)) return value.length ? value.join('、') : '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}
function formatTime(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
function issueLabel(code) { return {
  title:'Title 需优化',title_missing:'缺少 Title',title_too_long:'Title 过长',
  description:'Description 需优化',description_missing:'缺少 Description',
  canonical:'Canonical 需优化',h1:'H1 需优化',h1_missing:'缺少 H1',h1_multiple:'H1 过多',
  indexable:'索引设置',noindex:'禁止索引',robots_blocked:'Robots 拦截',
  heading_depth:'标题结构',substantial:'内容量不足',thin_content:'内容过少',
  schema:'缺少 Schema',entity_schema:'缺少实体 Schema',schema_invalid:'Schema 无效',
  faq:'缺少 FAQ',citations:'缺少引用',freshness:'缺少更新信息',
  block_definition:'缺少定义块',block_numbers:'缺少数字事实',block_comparison:'缺少对比块',block_howto:'缺少操作步骤',block_faq:'缺少 FAQ 块',
  NO_DEFINITION:'缺少定义块',NO_NUMBERS:'缺少数字事实',NO_COMPARISON:'缺少对比块',NO_HOWTO:'缺少操作步骤',NO_FAQ:'缺少 FAQ 块',
  image_alt_missing:'图片缺少 Alt',language:'语言未声明',html_lang_missing:'缺少 HTML lang',
  https:'HTTPS 异常',robots:'Robots 不可用',ai_crawlers:'AI 爬虫受限',llms:'缺少 llms.txt',http_4xx:'HTTP 4xx',http_5xx:'HTTP 5xx',empty_response:'页面无响应',
  non_html:'非 HTML 响应',timeout:'请求超时',too_many_redirects:'重定向过多',dns_error:'DNS 解析失败',tls_error:'TLS 连接失败',blocked_address:'地址被安全策略拦截',connection_error:'连接失败'
}[code] || '其他检测问题' }

async function load() {
  if (!currentTenantId.value) { error.value = '请先在右上角选择客户'; result.value = {items:[],total:0,stats:{}}; return }
  if (!siteId.value) { error.value = '请先选择或创建 SEO 网站'; result.value = {items:[],total:0,stats:{}}; return }
  loading.value = true; error.value = ''
  try {
    const response = await fetchSeoSitePages({ tenantId: currentTenantId.value, siteId: siteId.value, pageId: Number(route.query.page_id) || undefined, ...filters, page: page.value, pageSize: pageSize.value })
    const lastPage = Math.max(1, Math.ceil((response.total || 0) / pageSize.value))
    if (page.value > lastPage) { page.value = lastPage; return await load() }
    result.value = response
    diagnosticRefreshKey.value++
    selectedRows.value = []
    void loadIssues()
  }
  catch (e) { error.value = e.message } finally { loading.value = false }
}
async function loadIssues() {
  if (!currentTenantId.value || !siteId.value) { issueResult.value = { items: [], summary: {} }; return }
  const requestedSiteId = siteId.value
  issueLoading.value = true
  try {
    const response = await fetchSeoSitePageIssues({ tenantId: currentTenantId.value, siteId: requestedSiteId })
    if (requestedSiteId === siteId.value) issueResult.value = response
  } catch (e) {
    if (requestedSiteId === siteId.value) error.value = e.message
  } finally { if (requestedSiteId === siteId.value) issueLoading.value = false }
}
function openIssue(item) { activeIssue.value = item; issueDialogOpen.value = true }
async function openPageDetail(row) {
  detailOpen.value = true
  detailLoading.value = true
  detailResult.value = null
  try { detailResult.value = await fetchSeoSitePageDetail({ pageId: row.id, tenantId: currentTenantId.value }) }
  catch (e) { ElMessage.error(e.message); detailOpen.value = false }
  finally { detailLoading.value = false }
}
async function loadKeywordOptions() {
  if (!currentTenantId.value) { keywordOptions.value = []; return }
  try {
    const response = await fetchSeoKeywords({ tenantId: currentTenantId.value, siteId: siteId.value, status: 'active', pageSize: 200 })
    keywordOptions.value = response.items || []
  } catch { keywordOptions.value = [] }
}
async function importPages() {
  const urls = importText.value.split(/\r?\n/).map((v) => v.trim()).filter(Boolean)
  if (!urls.length) return ElMessage.warning('请至少填写一个页面 URL')
  saving.value = true
  try {
    const r = await importSeoSitePages({ tenant_id: currentTenantId.value, site_id: siteId.value, urls })
    importOpen.value = false; importText.value = ''
    ElMessage.success(`已导入 ${r.created} 个页面${r.skipped?.length ? `，跳过 ${r.skipped.length} 个` : ''}`)
    await load()
  } catch (e) { ElMessage.error(e.message) } finally { saving.value = false }
}
function openEdit(row) {
  editing.value = row
  Object.assign(editForm, { page_type: row.page_type || '', target_keyword_id: row.target_keyword_id, title_suggestion: row.title_suggestion || '', description_suggestion: row.description_suggestion || '', status: row.status })
  editOpen.value = true
}
async function saveEdit() {
  saving.value = true
  try {
    await updateSeoSitePage({ pageId: editing.value.id, tenantId: currentTenantId.value, payload: { ...editForm, page_type: editForm.page_type || null, title_suggestion: editForm.title_suggestion || null, description_suggestion: editForm.description_suggestion || null } })
    editOpen.value = false; ElMessage.success('页面优化记录已保存'); await load()
  } catch (e) { ElMessage.error(e.message) } finally { saving.value = false }
}
async function audit(row) {
  if (batchAuditing.value || auditing.value.has(row.id)) return ElMessage.warning('页面检测正在进行，请勿重复提交')
  const next = new Set(auditing.value); next.add(row.id); auditing.value = next
  try { await auditSeoSitePage({ pageId: row.id, tenantId: currentTenantId.value, siteId: row.site_id }); ElMessage.success('单页检测完成，图片明细已保存'); await load() }
  catch (e) { ElMessage.error(e.message); await load() }
  finally { const done = new Set(auditing.value); done.delete(row.id); auditing.value = done }
}
async function auditPending() {
  if (batchAuditing.value || auditing.value.size > 0) return ElMessage.warning('页面检测正在进行，请勿重复提交')
  batchAuditing.value = true
  try {
    if (selectedRows.value.length) {
      const rows = [...selectedRows.value]
      const ids = new Set(rows.slice(0, 50).map((row) => row.id))
      auditing.value = new Set([...auditing.value, ...ids])
      const response = await runSeoBatch(
        rows,
        (row) => auditSeoSitePage({ pageId: row.id, tenantId: currentTenantId.value }),
        { concurrency: 3, limit: 50 },
      )
      const message = `批量检测完成：成功 ${response.completed.length}，失败 ${response.failed.length}，跳过 ${response.skipped.length}`
      response.failed.length || response.skipped.length ? ElMessage.warning(message) : ElMessage.success(message)
      await load()
      return
    }
    const response = await auditPendingSeoSitePages({ tenantId: currentTenantId.value, siteId: siteId.value, maxPages: 10 })
    const message = `已补抓 ${response.completed} 个页面${response.failed?.length ? `，失败 ${response.failed.length} 个` : ''}${response.skipped ? `，跳过 ${response.skipped} 个已更新页面` : ''}${response.deferred ? `，${response.deferred} 个留待下次补抓` : ''}`
    response.failed?.length || response.deferred ? ElMessage.warning(message) : ElMessage.success(message)
    await load()
  } catch (e) { ElMessage.error(e.message) } finally { batchAuditing.value = false; auditing.value = new Set() }
}
async function generateSuggestions() {
  const pageIds = selectedRows.value.length ? selectedRows.value.map((row) => row.id) : result.value.items.map((row) => row.id)
  if (!pageIds.length) return ElMessage.warning('当前没有可生成建议的页面')
  generating.value = true
  try {
    const response = await generateSeoSitePageSuggestions({ tenant_id: currentTenantId.value, site_id: siteId.value, page_ids: pageIds })
    ElMessage.success(`已生成 ${response.generated} 个页面的 TDK 建议${response.skipped ? `，跳过 ${response.skipped} 个已有建议` : ''}`)
    await load()
  } catch (e) { ElMessage.error(e.message) } finally { generating.value = false }
}
async function cleanupNonHtmlAssets() {
  const tenantId = currentTenantId.value
  const selectedSiteId = siteId.value
  if (!tenantId || !selectedSiteId) return ElMessage.warning('请先选择客户和 SEO 网站')
  cleaningNonHtml.value = true
  try {
    const preview = await cleanupSeoNonHtmlSitePages({ tenant_id: tenantId, site_id: selectedSiteId, dry_run: true, page_ids: [] })
    if (!preview.deletable) {
      const skipped = preview.skipped?.length ? `；另有 ${preview.skipped.length} 条已关联内容任务，未纳入清理` : ''
      return ElMessage.info(`没有可安全清理的非网页资源${skipped}`)
    }
    const sample = preview.items.slice(0, 4).map((item) => item.url).join('\n')
    const extra = preview.items.length > 4 ? `\n另有 ${preview.items.length - 4} 条` : ''
    await ElMessageBox.confirm(
      `将删除 ${preview.deletable} 条误入页面库的文件/媒体资源及其 TDK 记录：\n${sample}${extra}\n已关联内容任务的记录会被阻止删除。此操作不可恢复。`,
      '清理非网页资源',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
    if (tenantId !== currentTenantId.value || selectedSiteId !== siteId.value) {
      return ElMessage.warning('客户或网站已切换，请重新预览')
    }
    const response = await cleanupSeoNonHtmlSitePages({
      tenant_id: tenantId,
      site_id: selectedSiteId,
      dry_run: false,
      page_ids: preview.items.map((item) => item.id),
    })
    ElMessage.success(`已清理 ${response.deleted} 条非网页资源`)
    selectedRows.value = []
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || String(e))
  } finally {
    cleaningNonHtml.value = false
  }
}
function csvCell(value) { return `"${String(value ?? '').replace(/"/g, '""')}"` }
async function exportBrokenLinks() {
  if (!currentTenantId.value || !siteId.value) return ElMessage.warning('请先选择客户和 SEO 网站')
  exportingBrokenLinks.value = true
  try {
    const response = await fetchSeoBrokenLinkReport({ tenantId: currentTenantId.value, siteId: siteId.value })
    if (!response.items?.length) return ElMessage.info('当前没有 HTTP 4xx 页面')
    const headers = ['失效页面ID','失效URL','HTTP状态','失败原因','最近检测时间','来源页面ID','来源页面URL','来源页面标题','锚文本','关系发现时间','处理建议']
    const rows = response.items.map((item) => [
      item.target_page_id,item.target_url,item.http_status,item.last_error,formatSeoCsvTime(item.last_checked_at),
      item.source?.source_page_id,item.source?.source_url,item.source?.source_title,item.source?.anchor_text,
      formatSeoCsvTime(item.source?.discovered_at),item.action,
    ])
    const blob = new Blob(['\ufeff' + [headers,...rows].map((line) => line.map(csvCell).join(',')).join('\n')], { type: 'text/csv;charset=utf-8' })
    const anchor = document.createElement('a'); anchor.href = URL.createObjectURL(blob); anchor.download = `SEO-404修复清单-${siteId.value}.csv`; anchor.click(); URL.revokeObjectURL(anchor.href)
    const summary = `已导出 ${response.stats.broken_pages} 个失效页面、${response.stats.linked_sources} 条来源关系`
    response.stats.untraced_pages ? ElMessage.warning(`${summary}；${response.stats.untraced_pages} 个页面待下次全站扫描补齐来源`) : ElMessage.success(summary)
  } catch (e) { ElMessage.error(e.message) } finally { exportingBrokenLinks.value = false }
}
function exportHandoff() {
  const rows = selectedRows.value.length ? selectedRows.value : result.value.items
  if (!rows.length) return ElMessage.warning('当前没有可导出的页面')
  const headers = ['页面ID','URL','页面类型','目标关键词ID','问题','当前Title','建议Title','当前Description','建议Description','状态','最近检测时间']
  const body = rows.map((row) => [row.id,row.url,row.page_type,row.target_keyword_id,(row.issue_codes||[]).join('|'),row.title,row.title_suggestion,row.meta_description,row.description_suggestion,statusLabel(row.status),formatSeoCsvTime(row.last_checked_at)])
  const blob = new Blob(['\ufeff' + [headers,...body].map((line) => line.map(csvCell).join(',')).join('\n')], { type: 'text/csv;charset=utf-8' })
  const anchor = document.createElement('a'); anchor.href = URL.createObjectURL(blob); anchor.download = `SEO站内优化交接-${siteId.value}.csv`; anchor.click(); URL.revokeObjectURL(anchor.href)
}
async function createContentTask(row) {
  if (row.content_task_id) return router.push({ path: '/seo/content/editor', query: { site_id: siteId.value, id: row.content_task_id, source_page_id: row.id } })
  try {
    const response = await fetchSeoContentAssets({ tenantId: currentTenantId.value, siteId: siteId.value, status: 'planned,drafting', pageSize: 200 })
    const candidates = (response.items || []).filter((item) => !item.source_page_id && ['planned', 'drafting'].includes(item.status))
    if (!candidates.length) return openNewContentTask(row)
    linkPage.value = row
    linkCandidates.value = candidates
    selectedContentId.value = null
    linkDialogOpen.value = true
  } catch (e) { ElMessage.error(e.message) }
}
function openNewContentTask(row = linkPage.value) {
  if (!row) return
  linkDialogOpen.value = false
  router.push({ path: '/seo/content/editor', query: { site_id: siteId.value, keyword_id: row.target_keyword_id || undefined, source_page_id: row.id } })
}
async function linkExistingContentTask() {
  if (!linkPage.value || !selectedContentId.value) return ElMessage.warning('请选择需要关联的现有内容任务')
  linkingContent.value = true
  try {
    await updateSeoContentAsset({ contentId: selectedContentId.value, tenantId: currentTenantId.value, payload: { source_page_id: linkPage.value.id } })
    const linkedPageId = linkPage.value.id
    const linkedContentId = selectedContentId.value
    linkDialogOpen.value = false
    ElMessage.success('现有内容任务已关联来源页面')
    await load()
    router.push({ path: '/seo/content/editor', query: { site_id: siteId.value, id: linkedContentId, source_page_id: linkedPageId } })
  } catch (e) { ElMessage.error(e.message) } finally { linkingContent.value = false }
}
let timer
let disposed = false
let sitesGeneration = 0
watch(() => filters.q, () => { clearTimeout(timer); timer = setTimeout(() => { page.value = 1; load() }, 260) })
async function loadSites() {
  const token = ++sitesGeneration
  const tenantId = currentTenantId.value
  const requestedScopeSite = siteId.value
  const isCurrent = () => !disposed && token === sitesGeneration && tenantId === currentTenantId.value && requestedScopeSite === siteId.value
  if (!currentTenantId.value) { sites.value = []; siteId.value = null; return }
  try {
    const response = await fetchSeoSites(tenantId)
    if (!isCurrent()) return
    sites.value = response.sites || []
    const requestedSiteId = Number(route.query.site_id) || null
    const nextSiteId = sites.value.some((site) => site.id === requestedSiteId)
      ? requestedSiteId
      : (sites.value.some((site) => site.id === siteId.value) ? siteId.value : (sites.value.find((site) => site.status === 'active')?.id || sites.value[0]?.id || null))
    if (nextSiteId !== siteId.value) siteId.value = nextSiteId
    else { await load(); await loadKeywordOptions() }
  } catch (e) {
    if (!isCurrent()) return
    sites.value = []; siteId.value = null; error.value = e.message
  }
}
watch(() => [filters.status, filters.issueCode], () => { page.value = 1; load() })
watch(() => route.query.page_id, () => { page.value = 1; load() })
watch(() => route.query.site_id, loadSites)
watch(siteId, () => { page.value = 1; load(); loadKeywordOptions() })
watch(currentTenantId, loadSites)
onMounted(loadSites)
onBeforeUnmount(() => { disposed = true; ++sitesGeneration; clearTimeout(timer) })
</script>

<template>
  <div class="site-page">
    <section class="site-hero">
      <div><span>SEO / ONSITE OPTIMIZATION</span><h1>站内优化</h1><p>管理页面资产、TDK、H1、Canonical 与索引状态。检测结果保存到页面档案，可用于上线前后复核。</p></div>
      <div class="hero-actions"><el-select v-model="siteId" placeholder="选择 SEO 网站"><el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id"/></el-select><button v-if="canEdit" :disabled="generating||batchAuditing||cleaningNonHtml||!siteId" :title="`作用范围：${actionScopeLabel}`" @click="generateSuggestions">{{generating?'生成中…':`生成 TDK（${actionScopeLabel}）`}}</button><button :disabled="batchAuditing||cleaningNonHtml||!siteId" class="secondary" :title="`作用范围：${actionScopeLabel}`" @click="exportHandoff">导出交接单（{{ actionScopeLabel }}）</button><button class="secondary" :disabled="exportingBrokenLinks||!siteId" @click="exportBrokenLinks">{{ exportingBrokenLinks ? '导出中…' : '导出 404 修复清单' }}</button><button v-if="canEdit" :disabled="batchAuditing||auditing.size>0||cleaningNonHtml||!siteId" :title="selectedRows.length ? '最多处理已选的前 50 个页面' : '补抓最多 10 个待检测页面'" @click="auditPending">{{batchAuditing?'检测中…':(selectedRows.length?`批量检测（已选 ${selectedRows.length}）`:'补抓待检测页面')}}</button><button v-if="canEdit" class="secondary" :disabled="batchAuditing||cleaningNonHtml||!siteId" @click="cleanupNonHtmlAssets">{{ cleaningNonHtml ? '检查中…' : '清理非网页资源' }}</button><button v-if="canEdit" :disabled="batchAuditing||cleaningNonHtml||!siteId" @click="importOpen = true">＋ 导入页面</button></div>
    </section>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <section class="metrics">
      <article><span>页面资产</span><strong>{{ fmt(stats.total || 0) }}</strong><small>已纳入持续维护</small></article>
      <article><span>健康页面</span><strong>{{ fmt(stats.healthy || 0) }}</strong><small>最近检测未发现问题</small></article>
      <article><span>待优化</span><strong>{{ fmt(stats.needs_fix || 0) }}</strong><small>存在 TDK 或技术问题</small></article>
      <article><span>平均规则评分</span><strong>{{ stats.average_score ?? '—' }}</strong><small>仅计可评估页面；不代表收录或排名</small></article>
    </section>
    <SeoSiteDiagnosticsPanel :tenant-id="Number(currentTenantId) || undefined" :site-id="Number(siteId) || undefined" :can-edit="session.isLoggedIn && session.canEdit('seo.site')" :refresh-key="diagnosticRefreshKey" />
    <section class="site-panel issue-centre">
      <header><div><span>01 / ISSUE CENTRE</span><h2>站内问题中心</h2></div><small>严重 {{ issueResult.summary?.high || 0 }} · 一般 {{ issueResult.summary?.medium || 0 }} · 影响 {{ issueResult.summary?.affected_pages || 0 }} 个页面</small></header>
      <el-table v-loading="issueLoading" :data="issueResult.items" empty-text="最近检测没有发现站内问题">
        <el-table-column label="级别" width="82"><template #default="{row}"><el-tag :type="severityType(row.severity)" effect="light">{{ severityLabel(row.severity) }}</el-tag></template></el-table-column>
        <el-table-column prop="label" label="问题类型" min-width="155" />
        <el-table-column label="影响页面" width="105"><template #default="{row}"><strong>{{ row.affected_pages }}</strong> 个</template></el-table-column>
        <el-table-column label="修复建议（规则）" min-width="420"><template #default="{row}"><span class="guidance">{{ row.guidance }}</span></template></el-table-column>
        <el-table-column label="操作" width="100"><template #default="{row}"><button class="table-action" @click="openIssue(row)">查看页面</button></template></el-table-column>
      </el-table>
    </section>
    <section class="site-panel">
      <header><div><span>02 / PAGE INVENTORY</span><h2>页面资产与 TDK</h2></div><small>程序检测 · TDK 规则生成，可人工编辑（非 AI）· 不修改客户官网</small></header>
      <div class="filters"><el-input v-model="filters.q" clearable placeholder="搜索 URL 或页面标题" /><el-select v-model="filters.issueCode" clearable placeholder="全部问题"><el-option v-for="item in [{v:'title',n:'Title'},{v:'description',n:'Description'},{v:'h1',n:'H1'},{v:'canonical',n:'Canonical'},{v:'indexable',n:'索引'},{v:'schema',n:'Schema'},{v:'content',n:'内容质量'},{v:'image',n:'图片'},{v:'language',n:'语言'},{v:'crawl',n:'抓取/可访问性'}]" :key="item.v" :label="item.n" :value="item.v" /></el-select><el-select v-model="filters.status" clearable placeholder="全部状态"><el-option v-for="item in [{v:'pending',n:'待检测'},{v:'needs_fix',n:'需优化'},{v:'proposed',n:'待确认'},{v:'approved',n:'已确认'},{v:'implemented',n:'待复检'},{v:'verified',n:'已复检'},{v:'healthy',n:'健康'},{v:'error',n:'检测失败'}]" :key="item.v" :label="item.n" :value="item.v" /></el-select><span>{{ result.total }} 个页面 · 已选 {{ selectedRows.length }} 个</span></div>
      <el-table v-loading="loading" :data="result.items" :empty-text="emptyStateText" @selection-change="selectedRows = $event">
        <el-table-column type="selection" width="44" />
        <el-table-column label="页面 / URL" min-width="280"><template #default="{row}"><b class="page-title">{{ row.title || '未读取页面标题' }}</b><small class="page-url">{{ row.url }}</small></template></el-table-column>
        <el-table-column label="目标关键词" width="120"><template #default="{row}">{{ row.target_keyword_id ? `#${row.target_keyword_id}` : '待绑定' }}</template></el-table-column>
        <el-table-column label="规则评分" width="100"><template #default="{row}"><strong>{{ row.audit_score ?? '—' }}</strong><small v-if="row.diagnostic?.assessment_state !== 'assessed'">{{ row.diagnostic?.assessment_state === 'not_checked' ? '未检测' : '无法评估' }}</small></template></el-table-column>
        <el-table-column label="检测问题" min-width="210"><template #default="{row}"><div class="issues"><span v-for="code in (row.issue_codes || []).slice(0,4)" :key="code">{{ issueLabel(code) }}</span><small v-if="!(row.issue_codes || []).length">—</small></div></template></el-table-column>
        <el-table-column label="当前 TDK" min-width="220"><template #default="{row}"><div class="suggestion current"><b>{{ row.title || '缺少 Title' }}</b><small>{{ row.meta_description || '缺少 Description' }}</small></div></template></el-table-column>
        <el-table-column label="建议 TDK" min-width="240"><template #default="{row}"><div class="suggestion"><b>{{ row.title_suggestion || '尚未生成 Title 建议' }}</b><small>{{ row.description_suggestion || '尚未生成 Description 建议' }}</small></div></template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{row}"><el-tag :type="statusType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="280" fixed="right"><template #default="{row}"><div class="actions"><button @click="openPageDetail(row)">诊断详情</button><button v-if="canEdit" :disabled="batchAuditing||auditing.has(row.id)" @click="audit(row)">{{ auditing.has(row.id) ? '检测中…' : (row.status==='implemented'?'复检':'检测') }}</button><button v-if="canEdit" :disabled="batchAuditing" @click="openEdit(row)">优化记录</button><button :disabled="batchAuditing" @click="createContentTask(row)">{{ row.content_task_id ? '查看内容任务' : '创建内容任务' }}</button></div></template></el-table-column>
      </el-table>
      <div class="pagination"><span>批量生成和导出默认作用于当前页；批量检测需先勾选，单次最多 50 条。未勾选时仅补抓待检测页面。</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[25,50,100]" :total="result.total" layout="total, sizes, prev, pager, next, jumper" @current-change="load" @size-change="page = 1; load()" /></div>
    </section>

    <el-dialog v-model="issueDialogOpen" :title="activeIssue?.label || '受影响页面'" width="760px">
      <p class="dialog-tip">{{ activeIssue?.guidance }}<template v-if="activeIssue?.affected_pages > 100"> 当前先展示前 100 个受影响页面。</template></p>
      <div v-if="activeIssue?.codes?.length" class="issue-codes"><span v-for="item in activeIssue.codes" :key="item.code">{{ issueLabel(item.code) }} × {{ item.count }}</span></div>
      <el-table :data="activeIssue?.pages || []" max-height="430">
        <el-table-column label="页面" min-width="400"><template #default="{row}"><b class="page-title">{{ row.title || '未读取页面标题' }}</b><small class="page-url">{{ row.url }}</small></template></el-table-column>
        <el-table-column prop="audit_score" label="健康度" width="85" />
        <el-table-column label="状态" width="95"><template #default="{row}"><el-tag :type="statusType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="90"><template #default="{row}"><el-button link type="primary" @click="issueDialogOpen=false; openPageDetail(row)">详情</el-button></template></el-table-column>
      </el-table>
    </el-dialog>

    <el-drawer v-model="detailOpen" title="页面诊断详情" size="760px">
      <div v-loading="detailLoading" class="detail-drawer">
        <template v-if="detailResult">
          <section class="detail-head">
            <div><h3>{{ detailResult.page.title || '未读取页面标题' }}</h3><a :href="detailResult.page.url" target="_blank" rel="noopener noreferrer">{{ detailResult.page.url }}</a></div>
            <el-tag :type="statusType(detailResult.page.status)" effect="light">{{ statusLabel(detailResult.page.status) }}</el-tag>
          </section>
          <section class="detail-metrics">
            <article><span>健康度</span><strong>{{ detailResult.page.audit_score ?? '—' }}</strong></article>
            <article><span>HTTP</span><strong>{{ detailResult.page.http_status ?? detailResult.latest_snapshot?.status_code ?? '—' }}</strong></article>
            <article><span>入链</span><strong>{{ detailResult.internal_links.incoming }}</strong></article>
            <article><span>出链</span><strong>{{ detailResult.internal_links.outgoing }}</strong></article>
          </section>
          <section class="detail-block"><h4>当前值与优化建议</h4><div class="tdk-compare">
            <div><span>当前 Title</span><b>{{ displayValue(detailResult.page.title) }}</b></div><div class="suggested"><span>建议 Title</span><b>{{ displayValue(detailResult.page.title_suggestion) }}</b></div>
            <div><span>当前 Description</span><b>{{ displayValue(detailResult.page.meta_description) }}</b></div><div class="suggested"><span>建议 Description</span><b>{{ displayValue(detailResult.page.description_suggestion) }}</b></div>
          </div></section>
          <section class="detail-block"><h4>当前问题与处理建议</h4><el-empty v-if="!detailResult.issue_details.length" description="当前没有检测问题" :image-size="54"/><div v-else class="detail-issues"><article v-for="item in detailResult.issue_details" :key="item.code"><el-tag :type="severityType(item.severity)" size="small">{{ severityLabel(item.severity) }}</el-tag><div><b>{{ issueLabel(item.code) }}</b><p>{{ item.guidance }}</p></div></article></div></section>
          <section v-if="detailResult.page.issue_codes?.includes('http_4xx')" class="detail-block"><h4>失效链接来源</h4><el-table :data="detailResult.internal_links.incoming_sources || []" empty-text="来源关系待下次全站扫描补齐" max-height="300"><el-table-column label="来源页面" min-width="330"><template #default="{row}"><b class="page-title">{{ row.source_title || '未读取页面标题' }}</b><a class="page-url" :href="row.source_url" target="_blank" rel="noopener noreferrer">{{ row.source_url }}</a></template></el-table-column><el-table-column prop="anchor_text" label="锚文本" min-width="150"><template #default="{row}">{{ row.anchor_text || '—' }}</template></el-table-column></el-table></section>
          <section class="detail-block"><h4>最近抓取证据</h4><div v-if="detailResult.latest_snapshot" class="evidence-grid">
            <div><span>抓取时间</span><b>{{ formatTime(detailResult.latest_snapshot.fetched_at) }}</b></div><div><span>最终地址</span><b>{{ displayValue(detailResult.latest_snapshot.final_url) }}</b></div>
            <div><span>Canonical</span><b>{{ displayValue(detailResult.latest_snapshot.canonical_url) }}</b></div><div><span>可索引</span><b>{{ displayValue(detailResult.latest_snapshot.indexable) }}</b></div>
            <div><span>Title / 长度</span><b>{{ displayValue(detailResult.latest_snapshot.title) }} / {{ displayValue(detailResult.latest_snapshot.title_length) }}</b></div><div><span>Description 长度</span><b>{{ displayValue(detailResult.latest_snapshot.description_length) }}</b></div>
            <div><span>H1</span><b>{{ displayValue(detailResult.latest_snapshot.h1_texts) }}</b></div><div><span>正文词数</span><b>{{ displayValue(detailResult.latest_snapshot.word_count) }}</b></div>
            <div><span>Schema</span><b>{{ displayValue(detailResult.latest_snapshot.schema_types) }}</b></div><div><span>缺 Alt 图片</span><b>{{ displayValue(detailResult.latest_snapshot.images_missing_alt_count) }}</b></div>
            <div><span>响应时间</span><b>{{ detailResult.latest_snapshot.response_time_ms == null ? '—' : `${detailResult.latest_snapshot.response_time_ms} ms` }}</b></div><div><span>重定向次数</span><b>{{ detailResult.latest_snapshot.redirect_chain?.length || 0 }}</b></div>
          </div><el-empty v-else description="暂无全站扫描证据，请先运行网站技术扫描" :image-size="54"/></section>
          <section class="detail-block"><h4>修复前后对比</h4><template v-if="detailResult.comparison.available"><div class="compare-summary"><span class="resolved">已解决 {{ detailResult.comparison.resolved_issues.length }}</span><span class="new-issue">新增 {{ detailResult.comparison.new_issues.length }}</span><span>字段变化 {{ detailResult.comparison.changed_fields.length }}</span></div><el-table :data="detailResult.comparison.changed_fields" empty-text="两次扫描的主要字段没有变化" max-height="330"><el-table-column prop="label" label="字段" width="130"/><el-table-column label="上次"><template #default="{row}">{{ displayValue(row.before) }}</template></el-table-column><el-table-column label="本次"><template #default="{row}">{{ displayValue(row.after) }}</template></el-table-column></el-table></template><el-empty v-else description="至少完成两次全站扫描后才能生成修复前后对比" :image-size="54"/></section>
        </template>
      </div>
    </el-drawer>

    <el-dialog v-model="importOpen" title="导入站内页面" width="600px">
      <p class="dialog-tip">每行一个公开页面 URL。导入后可逐页运行真实检测；系统不会自动修改客户网站。</p>
      <el-input v-model="importText" type="textarea" :rows="9" placeholder="https://example.com/&#10;https://example.com/products" />
      <template #footer><el-button @click="importOpen=false">取消</el-button><el-button type="primary" :loading="saving" @click="importPages">导入页面</el-button></template>
    </el-dialog>

    <el-dialog v-model="linkDialogOpen" title="创建或关联内容任务" width="560px">
      <p class="dialog-tip">该页面尚未关联内容任务。可选择一个现有未关联草稿，或创建新任务。</p>
      <el-select v-model="selectedContentId" filterable clearable placeholder="选择现有未关联内容任务">
        <el-option v-for="item in linkCandidates" :key="item.id" :label="`${item.title}（#${item.id}）`" :value="item.id" />
      </el-select>
      <template #footer><el-button @click="openNewContentTask()">创建新任务</el-button><el-button type="primary" :loading="linkingContent" @click="linkExistingContentTask">关联并打开</el-button></template>
    </el-dialog>
    <el-dialog v-model="editOpen" title="页面优化记录" width="680px">
      <p class="dialog-tip">{{ editing?.url }}</p>
      <el-form label-position="top">
        <el-form-item label="页面类型"><el-select v-model="editForm.page_type" clearable><el-option v-for="type in ['首页','产品页','解决方案','案例','文章','其他']" :key="type" :label="type" :value="type" /></el-select></el-form-item>
        <el-form-item label="目标关键词"><el-select v-model="editForm.target_keyword_id" clearable filterable placeholder="选择该页面主攻关键词"><el-option v-for="item in keywordOptions" :key="item.id" :label="item.keyword" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="建议 Title"><el-input v-model="editForm.title_suggestion" maxlength="300" show-word-limit /></el-form-item>
        <el-form-item label="建议 Description"><el-input v-model="editForm.description_suggestion" type="textarea" :rows="4" maxlength="1000" show-word-limit /></el-form-item>
        <el-form-item label="处理状态"><el-select v-model="editForm.status"><el-option label="待检测" value="pending" /><el-option label="需优化" value="needs_fix" /><el-option label="待确认" value="proposed" /><el-option label="已确认" value="approved" /><el-option label="已实施，待复检" value="implemented" /><el-option label="已复检" value="verified" /><el-option label="健康" value="healthy" /><el-option label="检测失败" value="error" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="editOpen=false">取消</el-button><el-button type="primary" :loading="saving" @click="saveEdit">保存记录</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.pagination{padding:14px 17px;display:flex;align-items:center;justify-content:space-between;gap:16px;border-top:1px solid #edf1ef}.pagination>span{color:#788683;font-size:11px}
.hero-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap}.hero-actions button:disabled{cursor:wait;opacity:.6}.hero-actions button.secondary{border:1px solid #b9d4cf;background:#fff;color:var(--teal);box-shadow:none}
.site-page{--ink:#17233d;--teal:#168b83;--line:#e3e8ef;min-height:100%;padding:26px;background:radial-gradient(circle at 78% -16%,rgba(22,139,131,.1),transparent 35%),#f5f8f7;color:var(--ink)}.site-hero{display:flex;align-items:end;justify-content:space-between;gap:28px;padding:27px 30px;border:1px solid #dbe7e4;border-radius:17px;background:#fff;box-shadow:0 16px 45px rgba(29,69,64,.05)}.site-hero>div>span,.site-panel header span{color:var(--teal);font:800 10px ui-monospace,monospace;letter-spacing:.13em}.site-hero h1{margin:9px 0 7px;font:750 34px "Noto Serif SC","Songti SC",serif}.site-hero p{max-width:760px;margin:0;color:#72817e;line-height:1.7}.site-hero button{height:40px;padding:0 18px;border:0;border-radius:9px;background:var(--teal);color:#fff;font-weight:700;cursor:pointer;box-shadow:0 8px 20px rgba(22,139,131,.2)}.el-alert{margin-top:14px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:15px 0}.metrics article{padding:19px 20px;border:1px solid var(--line);border-radius:13px;background:#fff}.metrics span,.metrics small{display:block;color:#768582;font-size:11px}.metrics strong{display:block;margin:10px 0 5px;font-size:28px}.site-panel{overflow:hidden;margin-bottom:15px;border:1px solid var(--line);border-radius:15px;background:#fff}.site-panel>header{display:flex;align-items:end;justify-content:space-between;padding:16px 19px;border-bottom:1px solid #edf1ef}.site-panel h2{margin:4px 0 0;font-size:15px}.site-panel header small{color:#82908d}.filters{display:flex;gap:9px;padding:14px 17px}.filters .el-input{max-width:350px}.filters .el-select{width:140px}.filters>span{align-self:center;margin-left:auto;color:#788683;font-size:11px}.page-title,.page-url{display:block}.page-url{max-width:430px;overflow:hidden;margin-top:4px;color:#5d7f79;text-overflow:ellipsis;white-space:nowrap}.issues{display:flex;gap:4px;flex-wrap:wrap}.issues span,.issue-codes span{padding:3px 6px;border-radius:5px;background:#fff0e3;color:#a65e24;font-size:10px}.suggestion b,.suggestion small{display:block;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.suggestion small{margin-top:4px;color:#899491}.actions{display:flex;gap:5px}.actions button,.table-action{padding:5px 7px;border:1px solid #dce5e2;border-radius:6px;background:#fff;color:#52736e;font-size:10.5px;cursor:pointer}.actions button:hover,.table-action:hover{border-color:#7bb3aa;color:var(--teal)}.actions button:disabled{opacity:.55;cursor:wait}.dialog-tip{margin:-6px 0 15px;color:#75827f;font-size:12px;line-height:1.6}.issue-codes{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:13px}.guidance{color:#556963;line-height:1.6}.detail-drawer{min-height:300px}.detail-head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding-bottom:16px;border-bottom:1px solid #edf1ef}.detail-head h3{margin:0 0 7px;font-size:18px}.detail-head a{display:block;max-width:610px;overflow-wrap:anywhere;color:var(--teal);font-size:12px}.detail-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin:15px 0}.detail-metrics article{padding:13px;border:1px solid var(--line);border-radius:10px;background:#f8fbfa}.detail-metrics span{display:block;color:#7a8985;font-size:11px}.detail-metrics strong{display:block;margin-top:6px;font-size:20px}.detail-block{margin-top:14px;padding:16px;border:1px solid var(--line);border-radius:12px}.detail-block h4{margin:0 0 13px}.detail-issues{display:grid;gap:8px}.detail-issues article{display:flex;align-items:flex-start;gap:10px;padding:10px;border-radius:9px;background:#faf8f4}.detail-issues b{font-size:13px}.detail-issues p{margin:4px 0 0;color:#687873;font-size:12px;line-height:1.55}.tdk-compare{display:grid;grid-template-columns:1fr 1fr;gap:9px}.tdk-compare>div{padding:11px;border-radius:9px;background:#f7f9f8}.tdk-compare>div.suggested{background:#edf8f5}.tdk-compare span,.tdk-compare b{display:block}.tdk-compare span{color:#7c8986;font-size:10px}.tdk-compare b{overflow-wrap:anywhere;margin-top:5px;font-size:12px;line-height:1.55}.evidence-grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--line)}.evidence-grid>div{min-width:0;padding:10px;background:#fff}.evidence-grid span,.evidence-grid b{display:block}.evidence-grid span{color:#7c8986;font-size:10px}.evidence-grid b{overflow-wrap:anywhere;margin-top:4px;font-size:12px}.compare-summary{display:flex;gap:8px;margin-bottom:11px}.compare-summary span{padding:5px 8px;border-radius:6px;background:#f0f3f2;color:#5e706c;font-size:11px}.compare-summary .resolved{background:#e8f7f1;color:#187a5d}.compare-summary .new-issue{background:#fff0e8;color:#b55f2c}.el-form :deep(.el-select){width:100%}@media(max-width:980px){.metrics{grid-template-columns:repeat(2,1fr)}.pagination{align-items:flex-start;flex-direction:column}}@media(max-width:680px){.site-page{padding:14px}.site-hero{align-items:flex-start;flex-direction:column}.metrics,.detail-metrics,.evidence-grid,.tdk-compare{grid-template-columns:1fr 1fr}.filters{flex-wrap:wrap}.filters .el-input{max-width:none;width:100%}.filters>span{margin-left:0}.pagination{overflow-x:auto}}
:deep(.el-drawer){max-width:100%}
</style>
