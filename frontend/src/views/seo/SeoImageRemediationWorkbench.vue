<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchSeoImageRemediationWorkbench, generateSeoImageAltDrafts, saveSeoImageRemediation } from '../../api/seo'
import SeoImageEvidenceDialog from './SeoImageEvidenceDialog.vue'

const props = defineProps({ tenantId: Number, siteId: Number, canEdit: Boolean, refreshKey: Number })
const loading = ref(false)
const error = ref('')
const result = ref({ items: [], total: 0, stats: {} })
const filters = reactive({ q: '', reviewState: 'all', decision: 'all' })
const page = ref(1)
const pageSize = ref(50)
const selected = ref([])
const approving = ref(false)
const generating = ref(false)
const exporting = ref(false)
const dialogOpen = ref(false)
const dialogPage = ref(null)
let generation = 0
let timer
let disposed = false

const stats = computed(() => result.value.stats || {})
const eligible = computed(() => selected.value.filter(row => row.review_status === 'draft' && row.decision !== 'undecided' && (row.decision !== 'informative' || row.alt_suggestion?.trim())))
const aiEligible = computed(() => selected.value.filter(row => row.review_status === 'unreviewed' && row.decision === 'undecided' && !row.review?.id).slice(0, 20))
const coverage = computed(() => {
  const total = Number(stats.value.candidate_count || 0)
  return total ? Math.round(Number(stats.value.approved_count || 0) * 100 / total) : 0
})
function stateLabel(row) { return row.review_status === 'approved' ? '已审核' : row.review_status === 'draft' ? '草稿' : '未判断' }
function decisionLabel(value) { return { undecided: '未判断', decorative: '装饰图', informative: '内容图' }[value] || value }
function isEligible(row) { return props.canEdit && row.review_status === 'draft' && row.decision !== 'undecided' && (row.decision !== 'informative' || row.alt_suggestion?.trim()) }
function isSelectable(row) { return props.canEdit && (isEligible(row) || (row.review_status === 'unreviewed' && row.decision === 'undecided' && !row.review?.id)) }

async function load() {
  const token = ++generation
  selected.value = []
  const tenantId = props.tenantId
  const siteId = props.siteId
  if (!tenantId || !siteId) { result.value = { items: [], total: 0, stats: {} }; error.value = ''; return }
  loading.value = true; error.value = ''
  try {
    const response = await fetchSeoImageRemediationWorkbench({ tenantId, siteId, ...filters, page: page.value, pageSize: pageSize.value })
    if (disposed || token !== generation || tenantId !== props.tenantId || siteId !== props.siteId) return
    const lastPage = Math.max(1, Math.ceil(Number(response.total || 0) / pageSize.value))
    if (page.value > lastPage) { page.value = lastPage; return load() }
    result.value = response
  } catch (e) { if (!disposed && token === generation) error.value = e.message }
  finally { if (!disposed && token === generation) loading.value = false }
}
function openReview(row) {
  dialogPage.value = { id: row.page_id, title: row.page_title, url: row.page_url }
  dialogOpen.value = true
}
async function generateAiDrafts() {
  if (loading.value || generating.value || approving.value) return
  const rows = aiEligible.value
  if (!rows.length) return ElMessage.warning('请勾选尚未人工处理的图片（每次最多 20 条）')
  try {
    await ElMessageBox.confirm(`AI 只会根据存档的文件名、页面标题等文本线索，为 ${rows.length} 条图片生成待审草稿；不读取图片、不自动通过、不修改官网。确认继续？`, 'AI 生成 Alt 草稿', { type: 'warning' })
  } catch { return }
  const tenantId = props.tenantId
  const siteId = props.siteId
  generating.value = true
  try {
    const response = await generateSeoImageAltDrafts({
      tenant_id: tenantId, site_id: siteId,
      items: rows.map(row => ({ page_id: row.page_id, expected_snapshot_id: row.snapshot_id, position: row.position, expected_review_id: null })),
    })
    if (tenantId !== props.tenantId || siteId !== props.siteId) return
    if (response.generated) ElMessage.success(`AI 已生成 ${response.generated} 条待审草稿；AI 明确跳过 ${response.skipped_ai || 0} 条，状态变化 ${response.skipped_changed || 0} 条，不可处理 ${response.skipped_ineligible || 0} 条`)
    else if (response.skipped_changed || response.skipped_ineligible) ElMessage.warning(`未保存草稿：状态变化 ${response.skipped_changed || 0} 条，不可处理 ${response.skipped_ineligible || 0} 条；请刷新后重试`)
    else ElMessage.warning(`AI 明确跳过 ${response.skipped_ai || 0} 条证据不足项，未生成草稿`)
    await load()
  } catch (e) { ElMessage.error(e.message) }
  finally { generating.value = false }
}
async function batchApprove() {
  const rows = eligible.value
  if (!rows.length) return ElMessage.warning('请勾选已完成人工判断的草稿')
  try {
    await ElMessageBox.confirm(`仅将 ${rows.length} 条完整草稿标记为已审核，不会修改客户官网。确认继续？`, '批量审核图片整改', { type: 'warning' })
  } catch { return }
  approving.value = true
  let completed = 0
  const failures = []
  for (const row of rows) {
    try {
      await saveSeoImageRemediation({
        tenant_id: props.tenantId, site_id: props.siteId, page_id: row.page_id,
        expected_snapshot_id: row.snapshot_id, expected_review_id: row.review?.id || null,
        position: row.position, decision: row.decision, alt_suggestion: row.alt_suggestion,
        note: row.note, review_status: 'approved',
      })
      completed++
    } catch (e) { failures.push(`#${row.page_id} 图片 ${row.position}: ${e.message}`) }
  }
  approving.value = false
  failures.length ? ElMessage.warning(`已通过 ${completed} 条，失败 ${failures.length} 条；请刷新后逐项处理`) : ElMessage.success(`已审核通过 ${completed} 条图片整改记录`)
  await load()
}
function safeCsv(value) {
  let text = String(value ?? '')
  if (/^[=+\-@]/.test(text)) text = `'${text}`
  return `"${text.replace(/"/g, '""')}"`
}
async function exportApproved() {
  if (!props.tenantId || !props.siteId) return
  exporting.value = true
  try {
    const rows = []
    let cursor = 1
    while (true) {
      const response = await fetchSeoImageRemediationWorkbench({ tenantId: props.tenantId, siteId: props.siteId, q: filters.q, reviewState: 'approved', decision: 'informative', page: cursor, pageSize: 100 })
      rows.push(...(response.items || []))
      if (rows.length >= Number(response.total || 0)) break
      cursor++
    }
    const actionable = rows.filter(row => row.alt_suggestion?.trim())
    if (!actionable.length) return ElMessage.warning('暂无全站已审核的内容图 Alt 整改记录')
    const headers = ['页面ID','页面标题','页面URL','快照ID','图片位置','区块','图片URL','检测状态','用途','Alt建议','备注','审核人','审核时间']
    const body = actionable.map(row => [row.page_id,row.page_title,row.page_url,row.snapshot_id,row.position,row.section,row.source_url,row.observed_alt_state,decisionLabel(row.decision),row.alt_suggestion,row.note,row.review?.actor_name,row.review?.updated_at])
    const blob = new Blob(['\ufeff' + [headers, ...body].map(line => line.map(safeCsv).join(',')).join('\n')], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `SEO全站图片Alt整改-${props.siteId}.csv`; anchor.style.display = 'none'
    document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) { ElMessage.error(e.message) }
  finally { exporting.value = false }
}
function dialogClosed() { dialogPage.value = null; load() }
watch(() => filters.q, () => { selected.value = []; clearTimeout(timer); timer = setTimeout(() => { page.value = 1; load() }, 260) })
watch([() => props.tenantId, () => props.siteId, () => props.refreshKey], () => { selected.value = []; page.value = 1; load() }, { immediate: true })
watch([() => filters.reviewState, () => filters.decision], () => { selected.value = []; page.value = 1; load() })
watch(dialogOpen, value => { if (!value && dialogPage.value) dialogClosed() })
onBeforeUnmount(() => { disposed = true; ++generation; clearTimeout(timer) })
</script>

<template>
  <section class="image-workbench">
    <header>
      <div><span>IMAGE ALT WORKBENCH</span><h2>全站图片整改</h2><p>程序汇总最新抓取证据；图片用途与 Alt 文案由人工确认，不会自动修改官网。</p></div>
      <div class="header-actions"><el-button :loading="exporting" :disabled="!stats.informative_approved_count" @click="exportApproved">导出已审核整改</el-button><el-button v-if="canEdit" :loading="generating" :disabled="loading || approving || !aiEligible.length" @click="generateAiDrafts">AI 生成 Alt 草稿（{{ aiEligible.length }}）</el-button><el-button v-if="canEdit" type="primary" :loading="approving" :disabled="loading || generating || !eligible.length" @click="batchApprove">批量审核通过（{{ eligible.length }}）</el-button></div>
    </header>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <div class="summary">
      <article><strong>{{ stats.page_count || 0 }}</strong><span>涉及页面</span></article>
      <article><strong>{{ stats.candidate_count || 0 }}</strong><span>Alt 待判断证据</span></article>
      <article><strong>{{ stats.unreviewed_count || 0 }}</strong><span>尚未人工判断</span></article>
      <article><strong>{{ coverage }}%</strong><span>人工审核覆盖率</span></article>
    </div>
    <div class="filters"><el-input v-model="filters.q" clearable placeholder="搜索页面标题或 URL"/><el-select v-model="filters.reviewState"><el-option label="全部审核状态" value="all"/><el-option label="未判断" value="unreviewed"/><el-option label="草稿" value="draft"/><el-option label="已审核" value="approved"/></el-select><el-select v-model="filters.decision"><el-option label="全部图片用途" value="all"/><el-option label="未判断" value="undecided"/><el-option label="装饰图" value="decorative"/><el-option label="内容图" value="informative"/></el-select><small>{{ result.total }} 条证据 · 草稿 {{ stats.draft_count || 0 }} · 已审核 {{ stats.approved_count || 0 }}</small></div>
    <el-table v-loading="loading" :data="result.items" empty-text="当前筛选下没有图片整改证据" @selection-change="selected = $event">
      <el-table-column type="selection" width="44" :selectable="isSelectable"/>
      <el-table-column label="页面" min-width="250"><template #default="{row}"><b>{{ row.page_title || `页面 #${row.page_id}` }}</b><small class="url">{{ row.page_url }}</small></template></el-table-column>
      <el-table-column label="图片证据" min-width="250"><template #default="{row}"><span>位置 {{ row.position }} · {{ row.section || '未知区块' }}</span><small class="url">{{ row.source_url || '未记录图片地址' }}</small></template></el-table-column>
      <el-table-column label="检测" width="90"><template #default="{row}">{{ {missing:'缺少 Alt',empty:'空 Alt',whitespace:'空白 Alt'}[row.observed_alt_state] || row.observed_alt_state }}</template></el-table-column>
      <el-table-column label="人工结论" min-width="210"><template #default="{row}"><el-tag :type="row.review_status === 'approved' ? 'success' : row.review_status === 'draft' ? 'warning' : 'info'">{{ stateLabel(row) }}</el-tag><b class="decision">{{ decisionLabel(row.decision) }}</b><small v-if="row.alt_suggestion" class="suggestion">{{ row.alt_suggestion }}</small></template></el-table-column>
      <el-table-column label="操作" width="110" fixed="right"><template #default="{row}"><el-button link type="primary" @click="openReview(row)">进入逐图审核</el-button></template></el-table-column>
    </el-table>
    <footer><span>AI 只生成草稿且不读取图片像素；批量通过只处理已填写完整的草稿，仍需人工核对。</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[25,50,100]" :total="result.total" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="page = 1; load()"/></footer>
    <SeoImageEvidenceDialog v-model:visible="dialogOpen" :tenant-id="tenantId" :site-id="siteId" :page="dialogPage" :can-edit="canEdit"/>
  </section>
</template>

<style scoped>
.image-workbench{margin:15px 0;overflow:hidden;border:1px solid #e3e8ef;border-radius:15px;background:#fff}.image-workbench>header{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;padding:18px 20px;border-bottom:1px solid #edf1ef}.image-workbench header span{color:#168b83;font:800 10px ui-monospace,monospace;letter-spacing:.13em}.image-workbench h2{margin:5px 0 3px;font-size:16px}.image-workbench header p{margin:0;color:#7a8885;font-size:12px}.header-actions{display:flex;gap:8px}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:#edf1ef}.summary article{padding:14px 20px;background:#fafcfb}.summary strong,.summary span{display:block}.summary strong{font-size:22px}.summary span{margin-top:3px;color:#778581;font-size:11px}.filters{display:flex;gap:9px;align-items:center;padding:14px 17px}.filters .el-input{max-width:310px}.filters .el-select{width:145px}.filters small{margin-left:auto;color:#778581}.url,.suggestion{display:block;max-width:360px;overflow:hidden;margin-top:4px;color:#70817d;text-overflow:ellipsis;white-space:nowrap}.decision{margin-left:8px;font-size:12px}.image-workbench footer{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:13px 17px;border-top:1px solid #edf1ef}.image-workbench footer>span{color:#788683;font-size:11px}@media(max-width:900px){.summary{grid-template-columns:1fr 1fr}.filters,.image-workbench>header,.image-workbench footer{align-items:flex-start;flex-direction:column}.filters .el-input,.filters .el-select{width:100%;max-width:none}.filters small{margin-left:0}}
</style>
