<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { copySeoImageRemediation, fetchSeoImageEvidence, fetchSeoImageRemediation, fetchSeoImageRemediationHistory, fetchSeoImageRemediationReusePreview, reuseSeoImageRemediation, saveSeoImageRemediation } from '../../api/seo'

const props = defineProps({ visible: Boolean, tenantId: Number, siteId: Number, page: Object, focusPosition: Number, canEdit: Boolean })
const emit = defineEmits(['update:visible'])
const data = ref(null), loading = ref(false), error = ref(''), filter = ref('all')
const reviewFilter = ref('all'), focusedOnly = ref(false)
const drafts = ref({}), savingPosition = ref(null)
const history = ref([]), currentSnapshotId = ref(null), selectedSnapshotId = ref(null), copying = ref(false)
const reusePreview = ref(null), reusing = ref(false)
let generation = 0
const evidence = computed(() => data.value?.evidence)
const reviewState = row => !drafts.value[row.position]?.id ? 'unreviewed' : drafts.value[row.position].review_status
const reviewStateLabel = row => ({ unreviewed: '未判断', draft: '草稿', approved: '已审核' }[reviewState(row)] || '未判断')
const isAiDraft = row => reviewState(row) === 'draft' && drafts.value[row.position]?.note?.startsWith('由 AI 根据已存档文本线索生成')
const approvalError = row => {
  const draft = drafts.value[row.position]
  if (!draft || draft.review_status !== 'approved') return ''
  if (draft.decision === 'undecided') return '标记已审核前，请先确认图片用途'
  if (draft.decision === 'informative' && !draft.alt_suggestion?.trim()) return '内容图标记已审核前，必须填写 Alt 建议'
  return ''
}
const canSaveReview = row => !approvalError(row)
const items = computed(() => (evidence.value?.items || []).filter(row => (
  (filter.value === 'all' || row.alt_state === filter.value)
  && (reviewFilter.value === 'all' || reviewState(row) === reviewFilter.value)
  && (!focusedOnly.value || !props.focusPosition || row.position === props.focusPosition)
)))
const reviewSummary = computed(() => (evidence.value?.items || []).reduce((summary, row) => {
  summary[reviewState(row)]++
  return summary
}, { unreviewed: 0, draft: 0, approved: 0 }))
const dialogTitle = computed(() => props.focusPosition ? `图片 Alt 核查 · 第 ${props.focusPosition} 张` : '图片 Alt 核查明细（程序证据）')
const isHistorical = computed(() => Boolean(data.value?.snapshot_id && currentSnapshotId.value && data.value.snapshot_id !== currentSnapshotId.value))
const previousReviewedSnapshot = computed(() => history.value.find(row => row.snapshot_id !== currentSnapshotId.value && row.approved_count > 0) || null)
const canReuseAcrossPages = computed(() => Boolean(
  reusePreview.value?.eligible_count
  && reusePreview.value.target_snapshot_id === data.value?.snapshot_id
  && !isHistorical.value,
))
const scope = () => ({ tenantId: props.tenantId, siteId: props.siteId, pageId: props.page?.id, snapshotId: data.value?.snapshot_id })
const scopeIsCurrent = value => value.tenantId === props.tenantId && value.siteId === props.siteId
  && value.pageId === props.page?.id && value.snapshotId === data.value?.snapshot_id
const stateLabel = state => ({ missing: '缺少 Alt 属性', empty: '空 Alt（需判断用途）', whitespace: 'Alt 仅含空白' }[state] || '未知')
const time = value => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) + ' CST' : '—'
const historyLabel = row => `快照 #${row.snapshot_id} · ${time(row.fetched_at)} · 已审核 ${row.approved_count}/${row.candidate_count}`
async function load(snapshotId = null) {
  const token = ++generation
  data.value = null; reusePreview.value = null; error.value = ''; loading.value = false
  if (!props.visible || !props.tenantId || !props.siteId || !props.page?.id) return
  loading.value = true
  try {
    const [response, remediation, historyResponse, reuseResponse] = await Promise.all([
      fetchSeoImageEvidence({ tenantId: props.tenantId, siteId: props.siteId, pageId: props.page.id, snapshotId }),
      fetchSeoImageRemediation({ tenantId: props.tenantId, siteId: props.siteId, pageId: props.page.id, snapshotId }),
      fetchSeoImageRemediationHistory({ tenantId: props.tenantId, siteId: props.siteId, pageId: props.page.id }),
      fetchSeoImageRemediationReusePreview({ tenantId: props.tenantId, siteId: props.siteId, pageId: props.page.id }).catch(() => null),
    ])
    if (token === generation) {
      data.value = response
      history.value = historyResponse.items || []
      currentSnapshotId.value = historyResponse.current_snapshot_id || response.snapshot_id
      selectedSnapshotId.value = response.snapshot_id
      reusePreview.value = reuseResponse
      // The two reads can straddle a new crawl. Never project reviews from one
      // immutable snapshot onto evidence from another snapshot.
      const saved = remediation.snapshot_id === response.snapshot_id
        ? Object.fromEntries((remediation.items || []).map(row => [row.position, row]))
        : {}
      drafts.value = Object.fromEntries((response.evidence?.items || []).map(row => [row.position, {
        id: saved[row.position]?.id || null,
        decision: saved[row.position]?.decision || 'undecided',
        alt_suggestion: saved[row.position]?.alt_suggestion || '',
        note: saved[row.position]?.note || '',
        review_status: saved[row.position]?.review_status || 'draft',
      }]))
    }
  } catch (e) { if (token === generation) error.value = e.message || '读取失败，请重试' }
  finally { if (token === generation) loading.value = false }
}
watch(() => [props.visible, props.tenantId, props.siteId, props.page?.id, props.focusPosition], () => {
  filter.value = 'all'; reviewFilter.value = props.page?.review_status === 'draft' ? 'draft' : 'all'
  focusedOnly.value = Boolean(props.focusPosition)
  history.value = []; reusePreview.value = null; currentSnapshotId.value = null; selectedSnapshotId.value = null; load()
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { ++generation })
async function saveReview(row) {
  const draft = drafts.value[row.position]
  if (!draft || savingPosition.value || isHistorical.value) return
  const active = scope()
  if (!active.snapshotId) return
  savingPosition.value = row.position
  try {
    await saveSeoImageRemediation({ tenant_id: active.tenantId, site_id: active.siteId, page_id: active.pageId,
      expected_snapshot_id: active.snapshotId, expected_review_id: draft.id, position: row.position,
      decision: draft.decision, alt_suggestion: draft.alt_suggestion, note: draft.note, review_status: draft.review_status })
    if (!scopeIsCurrent(active)) return
    ElMessage.success('图片整改记录已保存，未修改客户官网')
    await load(active.snapshotId)
  } catch (e) { if (scopeIsCurrent(active)) ElMessage.error(e.message) }
  finally { savingPosition.value = null }
}
async function copyPrevious() {
  const source = previousReviewedSnapshot.value
  if (!source || !data.value?.snapshot_id || isHistorical.value || copying.value) return
  const active = scope()
  try {
    await ElMessageBox.confirm(
      `仅复制快照 #${source.snapshot_id} 中证据完全一致且唯一匹配的已审核结论；复制后统一为草稿，仍需逐项人工复核。确定继续？`,
      '复制上一快照审核结论',
      { type: 'warning', confirmButtonText: '复制为草稿', cancelButtonText: '取消' },
    )
    if (!scopeIsCurrent(active)) return
    copying.value = true
    const result = await copySeoImageRemediation({
      tenant_id: active.tenantId, site_id: active.siteId, page_id: active.pageId,
      expected_snapshot_id: active.snapshotId, source_snapshot_id: source.snapshot_id,
    })
    if (!scopeIsCurrent(active)) return
    const message = `已复制 ${result.copied} 条为草稿；跳过已有 ${result.skipped_existing} 条、无法唯一匹配 ${result.skipped_ambiguous} 条`
    result.copied ? ElMessage.success(message) : ElMessage.warning(message)
    await load(active.snapshotId)
  } catch (e) {
    if (scopeIsCurrent(active) && e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '复制失败，请重试')
  } finally { copying.value = false }
}
async function reuseAcrossPages() {
  const preview = reusePreview.value
  if (!canReuseAcrossPages.value || !data.value?.snapshot_id || reusing.value) return
  const active = scope()
  try {
    await ElMessageBox.confirm(
      `同一网站内有 ${preview.eligible_count} 条图片结论可从 ${preview.source_page_count} 个页面复用。仅匹配地址和使用上下文完全一致、历史结论无冲突的图片；复用后仍为草稿，必须逐项人工复核。确定继续？`,
      '复用同站图片审核结论',
      { type: 'warning', confirmButtonText: '复用为草稿', cancelButtonText: '取消' },
    )
    if (!scopeIsCurrent(active)) return
    reusing.value = true
    const result = await reuseSeoImageRemediation({
      tenant_id: active.tenantId, site_id: active.siteId, page_id: active.pageId,
      expected_snapshot_id: active.snapshotId,
    })
    if (!scopeIsCurrent(active)) return
    const message = `已复用 ${result.copied} 条为草稿；跳过已有 ${result.skipped_existing} 条、重复或冲突 ${result.skipped_ambiguous} 条`
    result.copied ? ElMessage.success(message) : ElMessage.warning(message)
    await load(active.snapshotId)
  } catch (e) {
    if (scopeIsCurrent(active) && e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '复用失败，请重试')
  } finally { reusing.value = false }
}
function csvCell(value) {
  let text = String(value ?? '')
  if (/^[=+\-@]/.test(text.trimStart())) text = `'${text}`
  return `"${text.replace(/"/g, '""')}"`
}
function exportRows(rows, filename) {
  const headers = ['页面ID','页面URL','快照ID','图片位置','区域','图片地址证据','检测Alt状态','人工用途','Alt建议','审核状态','备注']
  const values = rows.map(row => { const draft = drafts.value[row.position] || {}; return [
    props.page.id, props.page.url, data.value.snapshot_id, row.position, row.section, row.source_url,
    stateLabel(row.alt_state), ({undecided:'待判断',decorative:'装饰图',informative:'内容图'}[draft.decision] || ''),
    draft.alt_suggestion, ({draft:'草稿',approved:'已审核'}[draft.review_status] || ''), draft.note,
  ] })
  const blob = new Blob(['\ufeff' + [headers, ...values].map(line => line.map(csvCell).join(',')).join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url; anchor.download = filename; anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Some browsers start the download asynchronously. Revoking in the same
  // task can invalidate the Blob before the download manager consumes it.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function exportWorklist() {
  const rows = (evidence.value?.items || []).filter(row => {
    const draft = drafts.value[row.position]
    return draft?.decision === 'informative'
      && draft.review_status === 'approved'
      && Boolean(draft.alt_suggestion?.trim())
  })
  if (!rows.length) {
    ElMessage.warning('暂无已审核且需要 Alt 的内容图')
    return
  }
  exportRows(rows, `SEO图片整改-${props.page.id}-snapshot-${data.value.snapshot_id}.csv`)
}
function exportAuditRecords() {
  const rows = evidence.value?.items || []
  if (!rows.length) {
    ElMessage.warning('当前快照没有图片候选记录')
    return
  }
  exportRows(rows, `SEO图片审核记录-${props.page.id}-snapshot-${data.value.snapshot_id}.csv`)
}
</script>

<template>
  <el-dialog :model-value="visible" :title="dialogTitle" width="min(1280px, 96vw)" top="4vh" class="image-evidence-dialog" @update:model-value="emit('update:visible', $event)">
    <p class="wrap">#{{ page?.id }} {{ page?.url }}</p>
    <el-alert title="仅读取抓取存档，不调用 AI、不加载图片、不修改官网。空 Alt 可能用于装饰图片；图片用途及整改文本需人工判断。" type="info" :closable="false" />
    <p v-if="loading" role="status">正在读取图片证据…</p>
    <el-alert v-else-if="error" :title="error" type="error" :closable="false" />
    <template v-else-if="data">
      <p>存档抓取时间：{{ time(data.fetched_at) }}<span v-if="data.snapshot_id"> · 快照 #{{ data.snapshot_id }}</span></p>
      <div v-if="history.length" class="history-toolbar"><span>历史快照</span><el-select v-model="selectedSnapshotId" aria-label="图片整改历史快照" @change="load"><el-option v-for="row in history" :key="row.snapshot_id" :label="historyLabel(row)" :value="row.snapshot_id" /></el-select></div>
      <el-alert v-if="isHistorical" title="当前查看历史快照，仅供追溯和导出；不能修改历史审核记录。" type="info" :closable="false" />
      <el-alert v-if="data.fetch_error" title="最近抓取失败，不能据此判断图片情况；未回退展示旧成功记录。" type="warning" :closable="false" />
      <p v-else-if="!evidence">{{ data.snapshot_id ? '旧存档未记录逐图明细，可对本页执行一次成功检测后补齐，无需全站扫描。' : '尚无抓取存档，可对本页执行检测后查看图片明细。' }}<span v-if="data.legacy_candidate_count != null">旧计数：{{ data.legacy_candidate_count }}（不代表全部需要修改）。</span></p>
      <template v-else>
        <p>静态 HTML 中 {{ evidence.images_count }} 张图片，{{ evidence.candidate_count }} 个待核查项：缺属性 {{ evidence.counts.missing }}、空 Alt {{ evidence.counts.empty }}、仅空白 {{ evidence.counts.whitespace }}。不含脚本动态生成图片。</p>
        <p>位置按静态 HTML 中的图片顺序记录；地址仅为属性证据，不代表浏览器最终选用或已验证可访问的图片。</p>
        <el-alert v-if="evidence.truncated" :title="`仅保存前 ${evidence.limit} 个候选项，以下明细及筛选结果不覆盖全部图片。`" type="warning" :closable="false" />
        <div class="filters">
          <el-select v-if="focusPosition" v-model="focusedOnly" aria-label="图片查看范围"><el-option label="当前选中图片" :value="true"/><el-option label="本页全部候选" :value="false"/></el-select>
          <el-select v-model="reviewFilter" aria-label="审核状态筛选"><el-option label="全部审核状态" value="all"/><el-option :label="`未判断（${reviewSummary.unreviewed}）`" value="unreviewed"/><el-option :label="`草稿（${reviewSummary.draft}）`" value="draft"/><el-option :label="`已审核（${reviewSummary.approved}）`" value="approved"/></el-select>
          <el-select v-model="filter" aria-label="Alt 类型筛选"><el-option label="全部 Alt 类型" value="all" /><el-option label="缺少 Alt 属性" value="missing" /><el-option label="空 Alt" value="empty" /><el-option label="仅空白" value="whitespace" /></el-select>
          <small>当前显示 {{ items.length }} / {{ evidence.candidate_count }} 条</small>
        </div>
        <el-table :data="items" row-key="position" max-height="560" :empty-text="evidence.candidate_count ? '当前筛选下没有候选项，请调整查看范围或筛选条件' : '本次静态 HTML 未发现缺少或空 Alt 的图片；不代表图片描述质量已通过'">
          <el-table-column label="位置" width="165"><template #default="{ row }">第 {{ row.position }} 张 · {{ row.section }}<small v-if="row.element_id">ID：{{ row.element_id }}</small><small>{{ row.in_link ? '位于链接内' : '不在链接内' }}</small><small v-if="row.role">声明 role：{{ row.role }}（非用途结论）</small></template></el-table-column>
          <el-table-column label="图片地址证据" min-width="300"><template #default="{ row }"><div class="source-url">{{ row.source_url || '未取得可展示的 HTTP(S) 地址' }}</div><small v-if="row.source_url_truncated">地址过长，已截断；请按图片位置核对完整地址。</small><small v-if="row.source_attribute">属性：{{ row.source_attribute }}</small><details v-if="row.srcset"><summary>查看 srcset 候选</summary><small class="wrap">{{ row.srcset }}</small></details></template></el-table-column>
          <el-table-column label="Alt 状态" width="185"><template #default="{ row }">{{ stateLabel(row.alt_state) }}</template></el-table-column>
          <el-table-column label="人工整改" min-width="360"><template #default="{ row }"><div v-if="drafts[row.position]" class="review-fields"><div class="review-state"><el-tag :type="reviewState(row) === 'approved' ? 'success' : reviewState(row) === 'draft' ? 'warning' : 'info'">{{ reviewStateLabel(row) }}</el-tag><small v-if="isAiDraft(row)">AI 待审建议</small></div>
            <el-select v-model="drafts[row.position].decision" :disabled="!canEdit || isHistorical || savingPosition === row.position" aria-label="图片用途"><el-option label="待判断" value="undecided"/><el-option label="装饰图（保留空 Alt）" value="decorative"/><el-option label="内容图（需 Alt）" value="informative"/></el-select>
            <el-input v-if="drafts[row.position].decision === 'informative'" v-model="drafts[row.position].alt_suggestion" :disabled="!canEdit || isHistorical || savingPosition === row.position" maxlength="300" placeholder="填写可审核的 Alt 建议" />
            <el-input v-model="drafts[row.position].note" :disabled="!canEdit || isHistorical || savingPosition === row.position" maxlength="1000" placeholder="判断依据 / 备注" />
            <div><el-select v-model="drafts[row.position].review_status" :disabled="!canEdit || isHistorical || savingPosition === row.position" aria-label="审核状态"><el-option label="草稿" value="draft"/><el-option label="已审核" value="approved"/></el-select><el-button v-if="canEdit && !isHistorical" :loading="savingPosition === row.position" :disabled="!canSaveReview(row)" @click="saveReview(row)">保存</el-button></div><small v-if="approvalError(row)" class="validation-error">{{ approvalError(row) }}</small>
          </div></template></el-table-column>
        </el-table>
      </template>
    </template>
    <template #footer><div class="footer-actions"><el-button v-if="canEdit && evidence && canReuseAcrossPages" :loading="reusing" @click="reuseAcrossPages">复用同站图片结论（{{ reusePreview.eligible_count }}）</el-button><el-button v-if="canEdit && evidence && !isHistorical && previousReviewedSnapshot" :loading="copying" @click="copyPrevious">复制上一快照审核结论</el-button><el-button v-if="evidence" @click="exportWorklist">导出图片整改清单</el-button><el-button v-if="evidence" @click="exportAuditRecords">导出全部审核记录</el-button><el-button :loading="loading" @click="load(selectedSnapshotId)">重新读取存档</el-button><el-button @click="emit('update:visible', false)">关闭</el-button></div></template>
  </el-dialog>
</template>

<style scoped>
p{font-size:14px;line-height:1.7}.wrap,small{overflow-wrap:anywhere;white-space:normal}small{display:block;font-size:13px;color:#657774;margin-top:6px}.filters{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:10px 0}.filters .el-select{width:200px}.filters small{margin:0 0 0 auto}.history-toolbar{display:flex;align-items:center;gap:10px;margin:12px 0}.history-toolbar>span{flex:none;color:#657774;font-size:13px}.history-toolbar .el-select{width:min(560px,100%)}.source-url{display:-webkit-box;overflow:hidden;overflow-wrap:anywhere;-webkit-box-orient:vertical;-webkit-line-clamp:3}.review-fields{display:grid;gap:7px}.review-fields>div{display:flex;gap:7px}.review-fields .el-select{width:100%}.review-state{align-items:center}.review-state small{margin:0}.validation-error{margin-top:0;color:#c45656}.footer-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}details{margin-top:7px}summary{cursor:pointer;color:#168b83;font-size:12px}@media(max-width:700px){.filters{align-items:stretch;flex-direction:column}.filters .el-select{width:100%}.filters small{margin-left:0}.footer-actions{justify-content:flex-start}}
</style>
