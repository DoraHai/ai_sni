<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchSeoSiteDiagnostics, saveSeoIndexReview, fetchSeoIndexReviews } from '../../api/seo'
import SeoRemediationDialog from './SeoRemediationDialog.vue'
import SeoImageEvidenceDialog from './SeoImageEvidenceDialog.vue'
import { session } from '../../store/session'

const props = defineProps({ tenantId: Number, siteId: Number, canEdit: Boolean, refreshKey: Number })
const result = ref({ items: [], total: 0, coverage: {} })
const loading = ref(false)
const error = ref('')
const query = ref('')
const reviewState = ref('all')
const page = ref(1)
const dialog = ref(false)
const remediationOpen = ref(false)
const remediationPage = ref(null)
const imageEvidenceOpen = ref(false)
const imageEvidencePage = ref(null)
const selected = ref(null)
const intent = ref('undecided')
const reason = ref('')
const saving = ref(false)
const history = ref([])
const historyError = ref('')
const historyLoading = ref(false)
const nextBefore = ref(null)
let generation = 0
let dialogGeneration = 0
let disposed = false
const coverage = computed(() => result.value.coverage || {})
const controlLabel = value => ({ unknown: '证据不足', crawl_blocked: 'Robots 阻止抓取', index_restricted: '检测到索引限制', no_restriction_detected: '未发现索引限制' }[value] || '未知')
const intentLabel = value => ({ undecided: '待人工确认', index: '希望参与搜索', noindex: '不希望参与搜索' }[value] || '待人工确认')
const outcomeLabel = value => ({ needs_review: '待确认用途', unverifiable: '无法核实', matches_intent: '设置符合意图', conflict: '设置与意图冲突' }[value] || '待确认用途')
const time = value => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) + ' CST' : '—'
const scope = () => ({ tenantId: props.tenantId, siteId: props.siteId })
const isCurrent = value => !disposed && value.tenantId === props.tenantId && value.siteId === props.siteId

async function load() {
  const token = ++generation
  const current = scope()
  error.value = ''
  if (!current.tenantId || !current.siteId) { loading.value = false; return }
  loading.value = true
  try {
    const response = await fetchSeoSiteDiagnostics({ ...current, q: query.value, reviewState: reviewState.value, page: page.value })
    if (token !== generation || !isCurrent(current)) return
    const lastPage = Math.max(1, Math.ceil(response.total / 25))
    if (page.value > lastPage) { page.value = lastPage; return load() }
    result.value = response
  } catch (e) { if (token === generation && isCurrent(current)) error.value = e.message }
  finally { if (token === generation && isCurrent(current)) loading.value = false }
}

async function loadHistory(append = false) {
  if (!selected.value || historyLoading.value) return
  const token = dialogGeneration
  const current = selected.value.scope
  const pageId = selected.value.id
  historyLoading.value = true; historyError.value = ''
  try {
    const response = await fetchSeoIndexReviews({ ...current, pageId, beforeId: append ? nextBefore.value : undefined })
    if (token !== dialogGeneration || !isCurrent(current)) return
    history.value = append ? [...history.value, ...response.items] : response.items
    nextBefore.value = response.next_before_id
  } catch (e) { if (token === dialogGeneration && isCurrent(current)) historyError.value = e.message }
  finally { if (token === dialogGeneration && isCurrent(current)) historyLoading.value = false }
}

function open(row) {
  ++dialogGeneration
  selected.value = { ...row, scope: scope() }
  intent.value = row.review?.intent || 'undecided'; reason.value = ''
  history.value = []; nextBefore.value = null; historyError.value = ''; historyLoading.value = false
  dialog.value = true
  loadHistory()
}

async function save() {
  if (saving.value || !selected.value || !props.canEdit) return
  if (!reason.value.trim()) return ElMessage.warning('请填写确认原因')
  const current = selected.value.scope
  const token = dialogGeneration
  if (!isCurrent(current)) return
  saving.value = true
  try {
    await saveSeoIndexReview({ tenant_id: current.tenantId, site_id: current.siteId, page_id: selected.value.id,
      expected_review_id: selected.value.review?.id ?? null, intent: intent.value, reason: reason.value.trim() })
    if (token !== dialogGeneration || !isCurrent(current)) return
    dialog.value = false
    ElMessage.success('索引意图已记录，未修改客户网站')
    await load()
  } catch (e) {
    if (token === dialogGeneration && isCurrent(current)) {
      ElMessage.error(e.message)
      // Keep the user's note, but do not silently adopt a new concurrency token.
      // After a 409 the user must reopen the refreshed row and review the change.
      await load()
    }
  } finally { if (token === dialogGeneration && isCurrent(current)) saving.value = false }
}

function search() { page.value = 1; load() }
watch(() => [props.tenantId, props.siteId], () => {
  ++generation; ++dialogGeneration
  result.value = { items: [], total: 0, coverage: {} }; selected.value = null
  history.value = []; dialog.value = false; saving.value = false; historyLoading.value = false
  remediationOpen.value = false; remediationPage.value = null
  imageEvidenceOpen.value = false; imageEvidencePage.value = null
  page.value = 1; query.value = ''; reviewState.value = 'all'
  load()
}, { immediate: true, flush: 'sync' })
watch(() => props.refreshKey, load)
onBeforeUnmount(() => { disposed = true; ++generation; ++dialogGeneration })
</script>

<template>
  <section class="diagnostics" aria-label="诊断依据与索引意图复核">
    <header><h2>诊断依据与索引意图复核</h2><el-button :loading="loading" :disabled="!siteId" @click="load">刷新存档</el-button></header>
    <p class="provenance"><el-tag>程序检测</el-tag> HTTP / 索引指令
      <el-tag type="info">规则建议</el-tag> 整改参考，不调用 AI
      <el-tag type="warning">人工确认</el-tag> 页面是否需要参与搜索</p>
    <p>可评估 {{ coverage.assessed ?? '—' }} / 已纳管 {{ coverage.inventory ?? '—' }} 页；未检测 {{ coverage.not_checked ?? '—' }} 页；无法评估 {{ coverage.unavailable ?? '—' }} 页。</p>
    <p class="muted">仅统计已纳管页面，不代表全站覆盖率。最近一页检测：{{ time(coverage.latest_checked_at) }}，不是全站检测时间。刷新只读取存档，不发起抓取。</p>
    <el-alert title="未发现索引限制 ≠ 已收录。Robots 拦截抓取 ≠ 禁止索引。隐私页等是否需要参与搜索，必须人工确认。" type="info" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="filters">
      <el-input v-model="query" aria-label="诊断页面搜索" placeholder="搜索 URL / 标题" clearable maxlength="200" @keyup.enter="search" @clear="search" />
      <el-select v-model="reviewState" aria-label="索引意图确认状态" @change="search"><el-option label="全部页面" value="all" /><el-option label="待人工确认" value="unreviewed" /><el-option label="已确认意图" value="reviewed" /></el-select>
      <el-button @click="search">查询</el-button>
    </div>
    <el-table v-loading="loading" :data="result.items" max-height="500" :empty-text="error ? '诊断数据未加载，请重试' : '没有符合条件的已纳管页面'">
      <el-table-column label="页面" min-width="240"><template #default="{ row }"><b>#{{ row.id }} {{ row.title || '未读取标题' }}</b><small class="url">{{ row.url }}</small><small>检测时间：{{ time(row.diagnostic.checked_at) }}</small></template></el-table-column>
      <el-table-column label="检测事实（程序）" min-width="210"><template #default="{ row }">
        <div>HTTP {{ row.diagnostic.http_status ?? '未知' }} · {{ controlLabel(row.diagnostic.index_control) }}</div>
        <small>{{ row.diagnostic.assessment_state === 'assessed' ? `规则评分 ${row.diagnostic.audit_score ?? '未提供'}` : row.diagnostic.assessment_state === 'not_checked' ? '未检测，不评分' : '无法评估，不评分' }}</small>
        <small v-if="row.diagnostic.ai_crawler_codes.length">AI 爬虫相关：{{ row.diagnostic.ai_crawler_codes.join(' / ') }}（不作为传统搜索索引结论）</small>
      </template></el-table-column>
      <el-table-column label="人工意图" min-width="180"><template #default="{ row }">{{ intentLabel(row.diagnostic.index_intent) }}<small v-if="row.review">{{ row.review.actor_name }} · {{ time(row.review.created_at) }}</small></template></el-table-column>
      <el-table-column label="整改参考（规则建议）" min-width="290"><template #default="{ row }"><b>{{ outcomeLabel(row.diagnostic.review_outcome) }}</b><p>{{ row.diagnostic.guidance }}</p></template></el-table-column>
      <el-table-column label="操作" width="130"><template #default="{ row }"><el-button link type="primary" :disabled="saving" @click="open(row)">{{ canEdit ? '复核 / 记录' : '查看记录' }}</el-button><el-button link type="primary" @click="imageEvidencePage = row; imageEvidenceOpen = true">图片 Alt 明细</el-button><el-button v-if="canEdit && session.canEdit('seo.content')" link type="primary" @click="remediationPage = row; remediationOpen = true">AI 整改草稿</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :page-size="25" :total="result.total" layout="total, prev, pager, next" @current-change="load" />
    <SeoRemediationDialog v-model:visible="remediationOpen" :tenant-id="tenantId" :site-id="siteId" :page="remediationPage" />
    <SeoImageEvidenceDialog v-model:visible="imageEvidenceOpen" :tenant-id="tenantId" :site-id="siteId" :page="imageEvidencePage" />
    <el-dialog v-model="dialog" title="人工确认索引意图" width="min(680px, 94vw)" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
      <template v-if="selected">
        <p class="url">#{{ selected.id }} {{ selected.url }}</p>
        <el-alert title="这里只记录页面用途，不修改 robots、TDK、官网或发布状态；新检测不会清除人工意图。" type="info" :closable="false" />
        <el-form v-if="canEdit" label-position="top">
          <el-form-item label="期望用途"><el-select v-model="intent" :disabled="saving"><el-option label="待确认 / 撤回原确认" value="undecided" /><el-option label="希望参与自然搜索" value="index" /><el-option label="不希望参与自然搜索" value="noindex" /></el-select></el-form-item>
          <el-form-item label="确认原因（必填，记录页面用途和依据）"><el-input v-model="reason" :disabled="saving" type="textarea" :rows="3" maxlength="2000" show-word-limit placeholder="例如：网站负责人确认该页只用于内部说明，不参与获客。" /></el-form-item>
        </el-form>
        <h3>历史确认（最新在前）</h3>
        <el-alert v-if="historyError" :title="historyError" type="error" :closable="false" />
        <p v-if="historyLoading">读取记录中…</p><p v-else-if="!history.length && !historyError">尚无人工确认记录</p>
        <article v-for="record in history" :key="record.id" class="history"><b>{{ intentLabel(record.intent) }} · {{ record.actor_name }}</b><small>{{ time(record.created_at) }}</small><p>{{ record.reason }}</p><small>确认时检测：{{ time(record.evidence.checked_at) }} · {{ controlLabel(record.evidence.index_control) }}</small></article>
        <el-button v-if="historyError" :disabled="historyLoading" @click="loadHistory(false)">重试读取记录</el-button>
        <el-button v-if="nextBefore" :loading="historyLoading" @click="loadHistory(true)">更多记录</el-button>
      </template>
      <template #footer><el-button :disabled="saving" @click="dialog = false">关闭</el-button><el-button v-if="canEdit" type="primary" :loading="saving" @click="save">保存人工确认</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.diagnostics{margin:16px 0;padding:20px;border:1px solid #e3e8ef;border-radius:15px;background:#fff}.diagnostics header{display:flex;align-items:center;justify-content:space-between;gap:12px}.diagnostics h2{margin:0;font-size:17px}.diagnostics p{font-size:13px;line-height:1.7}.provenance{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.muted,small{color:#657774}small{display:block;margin-top:5px;font-size:12px}.url{overflow-wrap:anywhere;white-space:normal}.filters{display:flex;gap:10px;margin:16px 0}.filters .el-input{max-width:340px}.filters .el-select{width:160px}.el-pagination{margin-top:14px}.history{padding:10px 0;border-bottom:1px solid #e3e8ef}.history p{white-space:pre-wrap;overflow-wrap:anywhere}.el-form{margin-top:16px}@media(max-width:680px){.diagnostics{padding:12px}.filters{flex-wrap:wrap}}
</style>
