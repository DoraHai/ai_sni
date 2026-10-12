<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { currentTenantId, session } from '../../store/session'
import { currentSeoSiteId } from './seoSiteContext'
import { auditSeoSitePage, fetchSeoCustomerVerificationQueue, fetchSeoSitePageDetail, fetchSeoTaskCenter, recoverSeoAiOperation, retrySeoImageVerification, retrySeoTask } from '../../api/seo'

const router = useRouter()
const data = ref({ items: [], total: 0, summary: {}, schedules: [] })
const verification = ref({ items: [], total: 0, summary: {} })
const verificationError = ref('')
const verificationRetrying = ref('')
const verificationRechecking = ref('')
const queueFilters = reactive({ kind: '', state: '', page: 1 })
const detailOpen = ref(false), detailRow = ref(null), pageDetail = ref(null), detailLoading = ref(false), detailError = ref('')
let detailSequence = 0
const queuePages = computed(() => Math.max(1, Math.ceil(verification.value.total / 20)))
const filters = reactive({ kind: '', status: '', page: 1 })
const loading = ref(false)
const error = ref('')
const refreshing = ref(true)
const retrying = ref('')
const resultOpen = ref(false)
const resultLoading = ref(false)
const resultText = ref('')
const resultError = ref('')
let sequence = 0
let resultSequence = 0
let timer
const scope = () => `${session.user?.id || 'api_key'}:${currentTenantId.value || ''}:${currentSeoSiteId.value || ''}`
const kinds = { ranking: '自然排名', competitor: '竞品监控', backlink: '外链核验', crawl: '页面抓取', ai: 'AI 内容操作' }
const statuses = { queued: '排队中', running: '运行中', completed: '已完成', partial: '部分完成', failed: '失败', refunded: '已退还额度', expired: '结果已到期' }
const time = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const totalPages = computed(() => Math.max(1, Math.ceil(data.value.total / 20)))
const attentionCount = computed(() => (data.value.summary.failed || 0) + (data.value.summary.partial || 0))
const busyCount = computed(() => (data.value.summary.running || 0) + (data.value.summary.queued || 0))
const rowKey = row => `${row.source}:${row.id}`
const verificationStates = { pending_customer_action: '待客户执行', pending_system_check: '待系统核验', verified: '已核实', failed_retry: '失败可重试' }
const verificationKinds = { image_repair: '图片修复', publication_url: '发布地址', page_recheck: '页面重查', backlink_verification: '外链核验' }
const publicationActions = { draft: '创建草稿', publish: '发布', manual_complete: '人工回填', sync: '同步', retry_publish: '重试发布', retry_draft: '重建草稿' }
const publicationAttemptStates = { started: '处理中', succeeded: '成功', failed: '失败' }
const publicationAttempt = row => row.kind === 'publication_url' ? row.evidence?.latest_attempt : null
const publicationAttemptLabel = attempt => {
  if (!attempt) return ''
  const action = publicationActions[attempt.action] || '发布处理'
  const status = publicationAttemptStates[attempt.status] || attempt.status
  const actor = attempt.created_by == null ? '系统任务' : `操作人 #${attempt.created_by}`
  return `${action} #${attempt.id} · ${status} · ${actor} · ${time(attempt.started_at)}`
}

function publicUrl(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : '' } catch { return '' }
}
function processingUrl(row) {
  if (!row?.action_url || (row.site_id && Number(row.site_id) !== Number(currentSeoSiteId.value))) return ''
  try {
    const url = new URL(row.action_url, 'https://seo.invalid')
    if (url.origin !== 'https://seo.invalid' || !url.pathname.startsWith('/seo/')) return ''
    url.searchParams.set('site_id', String(currentSeoSiteId.value))
    if (row.kind === 'page_recheck') url.searchParams.set('page_id', String(row.source_id))
    return url.pathname + url.search
  } catch { return '' }
}
const detailLinks = computed(() => {
  const evidence = detailRow.value?.evidence || {}
  return [['页面地址', pageDetail.value?.page?.url || evidence.url || evidence.page_url],
    ['来源页面', evidence.source_url], ['目标地址', evidence.target_url], ['涉及图片', evidence.current_observation?.source_url]]
    .map(([label, value]) => ({ label, url: publicUrl(value) })).filter(item => item.url)
})
const steps = computed(() => {
  const row = detailRow.value
  if (!row || row.source) return []
  if (row.state === 'verified') return ['本项已有系统核验记录，请核对检测时间；如网站之后有改动，可进入对应模块重新检查。']
  if (row.kind === 'page_recheck' && row.state === 'pending_system_check') return ['打开对应页面，核对当前是否已发布以及是否可以正常访问。', row.recheck_action ? '点击“发起页面复检”，系统会重新抓取页面并保存检测结果；复检不会修改网站。' : '进入站内优化查看检测入口；如没有编辑权限，请由网站维护人员执行检测。']
  if (row.kind === 'page_recheck') return [
    '核对下方页面地址、检测时间和具体问题，确认需要修改的页面。',
    '在网站后台修改对应页面的标题、描述、正文或设置；下方建议需人工核对后再采用。涉及模板、索引或服务器配置时，请交给网站维护人员。',
    '保存并发布网站修改后，打开公开页面确认已生效。进入“站内优化”的“优化记录”，将处理状态设为“已实施，待复检”并保存，再发起页面复检。检测失败时先按失败原因处理。']
  if (row.kind === 'image_repair') return ['进入该页面的站内优化，核对具体图片及已审核的修复建议。', '在网站后台修改对应图片或 Alt 描述，保存发布后确认公开页面已更新。', '返回本页点击“重新核实”；若缺少有效审核或快照，请先在站内优化重新检测并审核。']
  if (row.kind === 'publication_url') return ['进入分发平台，按本项内容标题查找发布记录，并核对最近一次操作结果。', '若尚未发布，请在目标平台完成发布；若发布失败，先检查平台后台是否已有文章，避免重复发布。', '将真实、公开可访问的文章地址回填到对应发布记录，保存后等待系统核验。']
  return ['核对来源页面与目标地址，确认来源页是否仍包含指向目标页的链接。', '如链接丢失，请联系来源网站维护人员恢复链接；如无法访问，请先处理公开访问或地址问题。', '进入内外链管理核对记录，等待后续系统核验；不要仅凭人工确认标记为已核实。']
})
async function openDetails(row) {
  const token = ++detailSequence, requestedScope = scope()
  detailRow.value = row; detailOpen.value = true; pageDetail.value = null; detailError.value = ''; detailLoading.value = false
  if (row.kind !== 'page_recheck') return
  detailLoading.value = true
  try {
    const result = await fetchSeoSitePageDetail({ pageId: row.source_id, tenantId: currentTenantId.value })
    if (token !== detailSequence || scope() !== requestedScope || !detailOpen.value) return
    if (Number(result.page?.site_id) !== Number(currentSeoSiteId.value) || Number(result.page?.id) !== Number(row.source_id)) throw new Error('页面范围已变化，请刷新任务列表后重试')
    pageDetail.value = result
  } catch (e) { if (token === detailSequence && scope() === requestedScope) detailError.value = e.message || '详情读取失败' }
  finally { if (token === detailSequence) detailLoading.value = false }
}
function goToProcessing(row) { const url = processingUrl(row); if (url) { detailOpen.value = false; router.push(url) } }

async function load() {
  const token = ++sequence
  const requestedScope = scope()
  if (!currentTenantId.value) { data.value = { items: [], total: 0, summary: {}, schedules: [] }; loading.value = false; error.value = ''; return }
  loading.value = true
  error.value = ''
  try {
    const [taskResult, queueResult] = await Promise.allSettled([
      fetchSeoTaskCenter({ tenant_id: currentTenantId.value, site_id: currentSeoSiteId.value || undefined,
        kind: filters.kind || undefined, status: filters.status || undefined, page: filters.page, page_size: 20 }),
      currentSeoSiteId.value ? fetchSeoCustomerVerificationQueue({ tenant_id: currentTenantId.value,
        site_id: currentSeoSiteId.value, kind: queueFilters.kind || undefined, state: queueFilters.state || undefined, page: queueFilters.page, page_size: 20 }) : Promise.resolve({ items: [], total: 0, summary: {} }),
    ])
    if (token !== sequence || scope() !== requestedScope) return
        if (queueResult.status === 'fulfilled') { verification.value = queueResult.value; verificationError.value = '' }
    else { verification.value = { items: [], total: 0, summary: {} }; verificationError.value = queueResult.reason?.message || '核验队列读取失败' }
    if (taskResult.status === 'rejected') throw taskResult.reason
    data.value = taskResult.value
  } catch (e) {
    if (token === sequence && scope() === requestedScope) error.value = e.message
  } finally { if (token === sequence) loading.value = false }
}

async function retryVerification(row) {
  if (!row.retry_action || verificationRetrying.value) return
  const requestedScope = scope()
  const tenantId = currentTenantId.value
  const siteId = currentSeoSiteId.value
  if (row.retry_action.tenant_id !== tenantId || row.retry_action.site_id !== siteId) return
  verificationRetrying.value = row.id
  try {
    await retrySeoImageVerification({ verificationId: row.retry_action.verification_id,
      tenantId, siteId })
    if (scope() === requestedScope) { ElMessage.success('图片重新核实已进入队列'); await load() }
  } catch (e) { if (scope() === requestedScope) ElMessage.error(e?.message || '重新核实失败') }
  finally { verificationRetrying.value = '' }
}

async function recheckPage(row) {
  if (row.kind !== 'page_recheck' || row.state !== 'pending_system_check' || !row.can_recheck || !row.recheck_action || verificationRechecking.value) return
  const requestedScope = scope()
  const tenantId = currentTenantId.value
  const siteId = currentSeoSiteId.value
  if (row.recheck_action.method !== 'POST' || row.recheck_action.tenant_id !== tenantId || row.recheck_action.site_id !== siteId) return
  verificationRechecking.value = row.id
  try {
    await ElMessageBox.confirm('系统将重新抓取该公开页面并保存本次检测证据，不会修改客户网站。', '发起页面复检', { confirmButtonText: '开始复检', cancelButtonText: '取消', type: 'warning' })
    if (scope() !== requestedScope) return
    await auditSeoSitePage({ pageId: row.recheck_action.page_id, tenantId, siteId })
    if (scope() === requestedScope) { ElMessage.success('页面复检已完成，队列已更新'); await load() }
  } catch (e) {
    if (e?.message && e.message !== 'cancel' && scope() === requestedScope) { ElMessage.error(e.message); await load() }
  }
  finally { verificationRechecking.value = '' }
}

async function retry(row) {
  if (!row.can_retry || retrying.value) return
  const requestedScope = scope()
  const tenantId = currentTenantId.value
  retrying.value = rowKey(row)
  try {
    await ElMessageBox.confirm(`将为网站 #${row.retry_site_id} 新建一次${kinds[row.kind]}任务，仍受现有额度和冷却限制。`, '确认重试', { confirmButtonText: '新建重试任务', cancelButtonText: '取消', type: 'warning' })
    if (scope() !== requestedScope) return
    await retrySeoTask(row.id, { tenant_id: tenantId, site_id: row.retry_site_id, job_type: row.kind })
    if (scope() === requestedScope) { ElMessage.success('重试任务已进入队列'); await load() }
  } catch (e) { if (e?.message && scope() === requestedScope) ElMessage.error(e.message) }
  finally { retrying.value = '' }
}

async function recover(row) {
  if (!row.has_result) return
  const token = ++resultSequence
  const requestedScope = scope()
  resultOpen.value = true; resultLoading.value = true; resultText.value = ''; resultError.value = ''
  try {
    const result = await recoverSeoAiOperation(row.id, currentTenantId.value)
    if (token !== resultSequence || requestedScope !== scope() || !resultOpen.value) return
    resultText.value = [['标题', result.title], ['大纲', result.outline], ['正文', result.content || result.content_html],
      ['反馈', result.feedback], ['建议', result.suggestions?.join('\n')]].filter(([, value]) => value)
      .map(([label, value]) => `${label}\n${value}`).join('\n\n') || JSON.stringify(result, null, 2)
  } catch (e) { if (token === resultSequence && requestedScope === scope()) resultError.value = e.message }
  finally { if (token === resultSequence) resultLoading.value = false }
}

async function copyResult() {
  try { await navigator.clipboard.writeText(resultText.value); ElMessage.success('已复制，可粘贴到编辑器继续核对') }
  catch { ElMessage.warning('复制失败，请选择下方文字手动复制') }
}

function openSource(row) {
  router.push({ path: row.source === 'crawl' ? '/seo/site' : '/seo/content/articles',
    query: row.site_id ? { site_id: row.site_id } : {} })
}

watch(() => [currentTenantId.value, currentSeoSiteId.value, session.user?.id], () => {
  sequence++; resultSequence++; detailSequence++; detailOpen.value = false; detailRow.value = null; pageDetail.value = null; detailError.value = ''; detailLoading.value = false; queueFilters.page = 1; resultOpen.value = false; resultText.value = ''; resultError.value = ''
  data.value = { items: [], total: 0, summary: {}, schedules: [] }
  verification.value = { items: [], total: 0, summary: {} }; verificationError.value = ''; verificationRetrying.value = ''; verificationRechecking.value = ''
  filters.page = 1; load()
})
watch(() => [queueFilters.kind, queueFilters.state], () => { queueFilters.page = 1; load() })
watch(() => queueFilters.page, load)
watch(detailOpen, value => { if (!value) { detailSequence++; detailRow.value = null; pageDetail.value = null; detailLoading.value = false; detailError.value = '' } })
watch(() => [filters.kind, filters.status], () => { filters.page = 1; load() })
watch(() => filters.page, load)
watch(resultOpen, value => { if (!value) { resultSequence++; resultText.value = ''; resultLoading.value = false } })
onMounted(() => {
  load()
  timer = setInterval(() => { if (refreshing.value && !loading.value && !document.hidden) load() }, 15000)
})
onUnmounted(() => { sequence++; resultSequence++; detailSequence++; clearInterval(timer) })
</script>

<template>
  <main class="task-center">
    <header class="task-heading">
      <div><p class="eyebrow">SEO / 运行记录</p><h1>自动任务中心</h1><p>查看执行结果、处理失败任务，找回尚未保存的 AI 内容。</p></div>
      <div class="refresh-controls"><label><input v-model="refreshing" type="checkbox"> 自动刷新</label><button :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新记录' }}</button></div>
    </header>
    <div v-if="!currentTenantId" class="empty">请先在顶部选择客户。</div>
    <template v-else>
      <section class="task-summary" aria-label="任务概况">
        <article><span>运行与排队</span><strong>{{ busyCount }}</strong><small>进行中的任务不会重复执行</small></article>
        <article><span>需要关注</span><strong class="attention">{{ attentionCount }}</strong><small>失败或部分完成的任务</small></article>
        <article><span>AI 已退还额度</span><strong>{{ data.summary.refunded || 0 }}</strong><small>中断操作会自动补偿</small></article>
      </section>
      <section v-if="data.schedules.length" class="schedules" aria-label="下次调度检查">
        <div v-for="item in data.schedules" :key="item.job_type"><span>{{ kinds[item.job_type] }}</span><b>{{ time(item.next_check_at) }}</b><small>下次调度检查</small></div>
        <p>实际执行还取决于配置、采集间隔、额度及服务运行状态。页面抓取和 AI 操作按需发起。</p>
      </section>
      <section class="task-history verification-queue">
        <div class="task-filters"><h2>客户执行与系统核验</h2><label>事项类型 <select v-model="queueFilters.kind"><option value="">全部类型</option><option v-for="(label, key) in verificationKinds" :key="key" :value="key">{{ label }}</option></select></label><label>处理状态 <select v-model="queueFilters.state"><option value="">全部状态</option><option v-for="(label, key) in verificationStates" :key="key" :value="key">{{ label }}</option></select></label></div>
        <p class="scope-note">汇总已有记录；读取不会启动采集、发布或修改客户网站。已审核、已发布和已核实分别判断。</p>
        <div v-if="!currentSeoSiteId" class="empty">请选择网站后查看核验队列。</div>
        <div v-else-if="verificationError" class="error" role="alert">核验队列加载失败：{{ verificationError }} <button @click="load">重试加载</button></div>
        <div v-else-if="!verification.items.length" class="empty">当前没有待处理或已核实记录。</div>
        <div v-else class="table-wrap"><table><thead><tr><th>事项</th><th>状态</th><th>依据</th><th>更新时间</th><th>入口</th></tr></thead>
          <tbody><tr v-for="row in verification.items" :key="row.id"><td><strong>{{ verificationKinds[row.kind] }}</strong><small>{{ row.title }}</small><button class="detail-link" @click="openDetails(row)">查看详情与操作步骤</button></td>
            <td><span class="status" :class="row.state">{{ verificationStates[row.state] }}</span></td><td>{{ row.detail }}<small v-if="publicationAttempt(row)">{{ publicationAttemptLabel(publicationAttempt(row)) }}<template v-if="publicationAttempt(row).completed_at"><br>结束 {{ time(publicationAttempt(row).completed_at) }}</template></small></td><td>{{ time(row.updated_at) }}</td>
            <td><button v-if="row.retry_action" :disabled="!!verificationRetrying || !!verificationRechecking" @click="retryVerification(row)">{{ verificationRetrying === row.id ? '提交中…' : '重新核实' }}</button><button v-if="row.recheck_action" :disabled="!!verificationRechecking || !!verificationRetrying" @click="recheckPage(row)">{{ verificationRechecking === row.id ? '复检中…' : '发起页面复检' }}</button><button v-if="row.action_url" @click="goToProcessing(row)">查看处理</button><small v-if="row.retry_reason">{{ row.retry_reason }}</small><small v-if="row.recheck_reason">{{ row.recheck_reason }}</small></td></tr></tbody></table></div>
        <footer v-if="currentSeoSiteId && !verificationError" class="pagination"><span>共 {{ verification.total }} 项</span><button :disabled="queueFilters.page <= 1 || loading" @click="queueFilters.page--">上一页</button><span>{{ queueFilters.page }} / {{ queuePages }}</span><button :disabled="queueFilters.page >= queuePages || loading" @click="queueFilters.page++">下一页</button></footer>
        <p v-if="verification.truncated" class="scope-note">当前仅展示已读取的 {{ verification.scanned_count }} 条来源记录，{{ verification.truncated_sources.join('、') }} 仍有更多记录，请按类型分批查看。</p>
      </section>
      <section class="task-history">
        <div class="task-filters">
          <h2>任务历史</h2>
          <label>任务类型 <select v-model="filters.kind"><option value="">全部类型</option><option v-for="(label, key) in kinds" :key="key" :value="key">{{ label }}</option></select></label>
          <label>状态 <select v-model="filters.status"><option value="">全部状态</option><option v-for="(label, key) in statuses" :key="key" :value="key">{{ label }}</option></select></label>
        </div>
        <p class="scope-note">仅展示有权限的记录。AI 内容仅本人可取回，保存期限为 30 天；取回不扣额度。全客户定时汇总会单独标明。</p>
        <div v-if="error" class="error" role="alert">加载失败：{{ error }} <button @click="load">重试加载</button></div>
        <div v-else-if="!data.items.length" class="empty">{{ loading ? '正在读取记录…' : '当前筛选下暂无任务记录' }}</div>
        <div v-else class="table-wrap">
          <table><thead><tr><th>任务 / 范围</th><th>状态</th><th>执行情况</th><th>时间</th><th>操作</th></tr></thead>
            <tbody><tr v-for="row in data.items" :key="rowKey(row)">
              <td><strong>{{ kinds[row.kind] }}</strong><small>{{ row.site_id ? `网站 #${row.site_id}` : row.source === 'automation' ? '全客户（定时汇总）' : '未指定网站' }}</small><small class="task-id">#{{ row.id }}</small><button class="detail-link" @click="openDetails(row)">查看任务详情</button></td>
              <td><span class="status" :class="row.status">{{ statuses[row.status] || row.status }}</span><small v-if="row.stale" class="attention">长时间未结束，请检查任务</small></td>
              <td><span v-if="row.source !== 'ai'">{{ row.succeeded }} 成功 · {{ row.failed }} 失败 · {{ row.skipped }} 跳过 / {{ row.planned }} 计划</span><span v-else>{{ row.detail }}</span>
                <details v-if="row.source !== 'ai' && row.detail"><summary>查看失败详情</summary><p>{{ row.detail }}</p></details>
              </td>
              <td><time>{{ time(row.started_at) }}</time><small>{{ row.completed_at ? `结束 ${time(row.completed_at)}` : '尚未结束' }}</small></td>
              <td><button v-if="row.has_result" class="primary" @click="recover(row)">取回结果</button>
                <button v-if="row.source === 'automation' && ['failed','partial'].includes(row.status)" :disabled="!row.can_retry || !!retrying" :title="!row.retry_site_id ? '请先选择要重试的网站' : !row.can_retry ? '没有重试权限' : ''" @click="retry(row)">{{ retrying === rowKey(row) ? '提交中…' : '重试任务' }}</button>
                <button v-if="row.source === 'crawl'" @click="openSource(row)">打开站内优化</button>
                <button v-if="row.source === 'ai' && ['refunded','expired'].includes(row.status)" @click="openSource(row)">返回内容列表</button>
              </td>
            </tr></tbody>
          </table>
        </div>
        <footer class="pagination"><span>共 {{ data.total }} 条</span><button :disabled="filters.page <= 1 || loading" @click="filters.page--">上一页</button><span>{{ filters.page }} / {{ totalPages }}</span><button :disabled="filters.page >= totalPages || loading" @click="filters.page++">下一页</button></footer>
      </section>
    </template>
    <el-dialog v-model="detailOpen" title="任务详情与处理指引" width="min(820px, 94vw)">
      <div v-if="detailRow" class="task-detail">
        <header><h3>{{ detailRow.title || kinds[detailRow.kind] }}</h3><span class="status" :class="detailRow.state || detailRow.status">{{ verificationStates[detailRow.state] || statuses[detailRow.status] || detailRow.status }}</span></header>
        <p class="detail-summary">{{ detailRow.detail || '当前没有额外执行说明。' }}</p>
        <p class="detail-meta">记录 #{{ detailRow.id }} · 更新时间 {{ time(detailRow.updated_at || detailRow.completed_at || detailRow.started_at) }}</p>
        <template v-if="detailRow.source">
          <p>开始：{{ time(detailRow.started_at) }} · 结束：{{ time(detailRow.completed_at) }}</p>
          <p v-if="detailRow.source !== 'ai'">计划 {{ detailRow.planned }} · 成功 {{ detailRow.succeeded }} · 失败 {{ detailRow.failed }} · 跳过 {{ detailRow.skipped }}</p>
          <p v-if="detailRow.stale" class="attention">任务长时间未结束，请核对运行情况后再重试。</p>
        </template>
        <p v-if="detailLoading" role="status">正在读取页面问题与优化建议…</p>
        <div v-if="detailError" role="alert" class="error">{{ detailError }} <button @click="openDetails(detailRow)">重新读取详情</button></div>
        <div v-if="detailLinks.length" class="detail-addresses"><p v-for="link in detailLinks" :key="link.label"><b>{{ link.label }}</b><a :href="link.url" target="_blank" rel="noopener noreferrer">{{ link.url }}</a></p></div>
        <section v-if="pageDetail"><h4>具体问题与修改建议</h4><p class="detail-meta">最近检测 {{ time(pageDetail.page.last_checked_at) }} · HTTP {{ pageDetail.page.http_status ?? '—' }} · 健康度 {{ pageDetail.page.audit_score ?? '—' }}</p>
          <ol v-if="pageDetail.issue_details?.length" class="issue-guidance"><li v-for="issue in pageDetail.issue_details" :key="issue.code"><strong>{{ issue.label }}</strong><p>{{ issue.guidance }}</p></li></ol>
          <p v-else>暂无具体检测问题记录，请进入站内优化核对优化建议或执行检测；这不代表修改已经生效。</p>
          <div class="detail-comparison"><article><h4>页面标题</h4><p>当前：{{ pageDetail.page.title || '未读取到标题' }}</p><p>建议：{{ pageDetail.page.title_suggestion || '暂无已保存建议' }}</p></article><article><h4>页面描述</h4><p>当前：{{ pageDetail.page.meta_description || '未读取到描述' }}</p><p>建议：{{ pageDetail.page.description_suggestion || '暂无已保存建议' }}</p></article></div>
        </section>
        <section v-if="steps.length"><h4>{{ detailRow.state === 'verified' ? '核验后续' : '接下来怎么做' }}</h4><ol class="action-steps"><li v-for="step in steps" :key="step">{{ step }}</li></ol></section>
        <section v-if="detailRow.kind === 'image_repair' && detailRow.evidence?.current_observation"><h4>图片最近核验结果</h4><p>实际读取到的 Alt：{{ detailRow.evidence.current_observation.actual_alt || '未读取到有效描述' }}</p><p>请进入对应页面的站内优化，核对该图片已审核的具体修复方案。</p></section>
        <p v-if="publicationAttempt(detailRow)">{{ publicationAttemptLabel(publicationAttempt(detailRow)) }}</p>
        <p v-if="detailRow.retry_reason || detailRow.recheck_reason" class="attention">{{ detailRow.retry_reason || detailRow.recheck_reason }}</p>
      </div>
      <template #footer><div class="detail-actions" v-if="detailRow"><button v-if="processingUrl(detailRow)" class="primary" @click="goToProcessing(detailRow)">{{ detailRow.kind === 'page_recheck' || detailRow.kind === 'image_repair' ? '打开对应页面的站内优化' : '前往处理' }}</button><button v-if="detailRow.recheck_action" :disabled="!!verificationRechecking || !!verificationRetrying" @click="recheckPage(detailRow)">发起页面复检</button><button v-if="detailRow.retry_action" :disabled="!!verificationRetrying || !!verificationRechecking" @click="retryVerification(detailRow)">重新核实</button><button v-if="detailRow.has_result" @click="recover(detailRow)">取回 AI 结果</button><button @click="detailOpen = false">关闭</button></div></template>
    </el-dialog>
    <el-dialog v-model="resultOpen" title="取回 AI 结果" width="min(760px, 92vw)">
      <p>这份结果不会自动保存或发布。复制后可回到编辑器继续核对。</p>
      <p v-if="resultLoading">正在取回…</p><p v-else-if="resultError" role="alert">{{ resultError }}</p><pre v-else class="recovered-result">{{ resultText }}</pre>
      <template #footer><button :disabled="!resultText || resultLoading" @click="copyResult">复制结果</button><button @click="resultOpen = false">关闭</button></template>
    </el-dialog>
  </main>
</template>

<style scoped>
.task-center{min-width:0;box-sizing:border-box;width:100%;max-width:1440px;margin:auto;padding:26px;color:#223047}.task-heading{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:24px}.eyebrow{font-size:11px;letter-spacing:2px;color:#71829c;margin:0 0 7px}h1{font-size:26px;margin:0 0 10px}.task-heading p:not(.eyebrow){font-size:13px;color:#728197;margin:0}.refresh-controls{display:flex;align-items:center;gap:14px;font-size:12px}.refresh-controls label{display:flex;align-items:center;gap:5px}button,select{font:inherit;border:1px solid #dbe2eb;background:white;border-radius:7px;padding:8px 12px;color:#315274}button{cursor:pointer;font-size:12px;white-space:nowrap}button:disabled{opacity:.45;cursor:not-allowed}button.primary{background:#2864e8;color:white;border-color:#2864e8}.task-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:18px}.task-summary article{background:white;border:1px solid #e0e6ee;border-radius:12px;padding:19px 23px;display:grid;gap:7px}.task-summary span{font-size:12px;color:#66788e}.task-summary strong{font-size:30px}.task-summary small,.schedules small{color:#8591a2;font-size:11px}.attention{color:#c97617!important}.schedules{display:flex;flex-wrap:wrap;gap:14px 35px;background:#edf3fa;border:1px solid #dbe5f1;border-radius:10px;padding:15px 20px;margin-bottom:22px}.schedules div{display:grid;gap:4px}.schedules span{font-size:11px;color:#67788c}.schedules b{font-size:12px}.schedules p{width:100%;margin:0;color:#75879c;font-size:11px}.task-history{background:white;border:1px solid #e0e6ee;border-radius:12px;overflow:hidden}.task-filters{display:flex;gap:18px;align-items:center;flex-wrap:wrap;padding:18px 20px 8px}.task-filters h2{font-size:15px;margin:0 auto 0 0}.task-filters label{font-size:12px;color:#63768e;display:flex;gap:8px;align-items:center}.scope-note{font-size:11px;color:#7e8ca0;margin:0;padding:8px 20px 16px}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;text-align:left;font-size:12px}th{background:#f6f8fb;font-size:11px;font-weight:500;color:#7b899b;padding:12px 16px}td{padding:17px 16px;border-top:1px solid #edf0f4;vertical-align:top;min-width:110px}td:nth-child(3){max-width:300px;overflow-wrap:anywhere}td strong{font-size:13px}td small{display:block;color:#8995a5;font-size:10px;margin-top:5px}.task-id{max-width:180px;overflow:hidden;text-overflow:ellipsis}.status{display:inline-block;border-radius:12px;padding:4px 9px;background:#f0f3f7;color:#64748b;white-space:nowrap}.status.running,.status.queued,.status.partial,.status.pending_customer_action,.status.pending_system_check{background:#fff3da;color:#ac751e}.status.completed,.status.verified{background:#e7f6ed;color:#218654}.status.failed,.status.failed_retry{background:#fff0ee;color:#c45846}.verification-queue{margin-bottom:22px}details{margin-top:8px}summary{cursor:pointer;color:#a4612c}details p{white-space:pre-wrap;line-height:1.6}.pagination{display:flex;align-items:center;justify-content:flex-end;gap:14px;border-top:1px solid #edf0f4;padding:14px 20px;font-size:12px;color:#7e8ca0}.pagination>span:first-child{margin-right:auto}.empty{padding:60px 20px;text-align:center;color:#8592a5;font-size:13px}.error{padding:20px;color:#bb5348}.recovered-result{white-space:pre-wrap;overflow-wrap:anywhere;max-height:55vh;overflow:auto;font:13px/1.8 inherit;padding:15px;background:#f5f7fa;border-radius:8px}td button+button{margin-left:5px}@media(max-width:800px){.task-center{padding:16px}.task-heading{align-items:flex-start;flex-direction:column}.task-summary{grid-template-columns:1fr;gap:8px}.task-summary article{padding:12px 16px;grid-template-columns:1fr auto;align-items:center}.task-summary small{grid-column:1/-1}.task-summary strong{font-size:24px}.task-filters{gap:12px}.task-filters h2{width:100%}.schedules{gap:14px}.schedules div{flex:1;min-width:160px}}
.detail-link{display:block;margin-top:10px;color:#245bc1;border-color:#cdddf8;background:#f5f8ff}.verification-queue table{table-layout:fixed;min-width:760px}.verification-queue th:first-child{width:25%}.verification-queue th:nth-child(2){width:12%}.verification-queue th:nth-child(3){width:28%}.verification-queue td{min-width:0;overflow-wrap:anywhere}.verification-queue td button{white-space:normal;margin:4px 4px 0 0}.task-detail{line-height:1.7;overflow-wrap:anywhere;max-height:65vh;overflow:auto}.task-detail header{display:flex;align-items:start;gap:16px;justify-content:space-between}.task-detail h3{font-size:18px;margin:0}.task-detail h4{margin:20px 0 8px;color:#223047}.detail-summary{white-space:pre-wrap}.detail-meta{font-size:12px;color:#728197}.detail-addresses{background:#f5f8fc;padding:2px 16px;border-radius:8px}.detail-addresses b{display:block;font-size:12px}.detail-addresses a{color:#245bc1}.issue-guidance,.action-steps{padding-left:24px}.issue-guidance li,.action-steps li{margin:12px 0}.issue-guidance p{margin:4px 0}.detail-comparison{display:grid;grid-template-columns:1fr 1fr;gap:12px}.detail-comparison article{padding:0 14px;background:#f5f8fc;border-radius:8px}.detail-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap}@media(max-width:600px){.detail-comparison{grid-template-columns:1fr}.task-detail header{flex-direction:column}}
</style>
