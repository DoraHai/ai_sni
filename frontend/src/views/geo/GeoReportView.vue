<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { fetchGeoProjects } from '../../api/geoProjects'
import {
  listGeoBusinesses, previewGeoPublicationLinks, confirmGeoPublicationLinks,
  fetchGeoMentionTrends, fetchGeoUrlCitations, fetchGeoReportTemplate,
  saveGeoReportTemplate, downloadGeoReport,
} from '../../api/geoContent'
import { reportParams, rateLabel, SOURCE_LABELS, safeFilename } from '../../utils/geoReport'

const { tenantId } = useGeoTenant()
const today = new Date()
const ymd = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const period = ref([ymd(new Date(today.getFullYear(), today.getMonth(), 1)), ymd(today)])
const projectId = ref('')
const businessId = ref('')
const projects = ref([])
const businesses = ref([])
const granularity = ref('day')
const source = ref('real')
const trends = ref([])
const citations = ref([])
const sections = ref([])
const busy = ref(false)
const error = ref('')
const importOpen = ref(false)
const file = ref(null)
const pasted = ref('')
const preview = ref([])
const importBusy = ref(false)
const params = computed(() => reportParams({ from: period.value?.[0], to: period.value?.[1], projectId: projectId.value, businessId: businessId.value, granularity: granularity.value, provenance: source.value }))
const validCount = computed(() => preview.value.filter(row => row.status === '有效').length)
let revision = 0
let templateRevision = 0

async function loadChoices() {
  if (!tenantId.value) return
  try {
    const [p, b] = await Promise.all([fetchGeoProjects(tenantId.value), listGeoBusinesses(tenantId.value)])
    projects.value = p.projects || []
    businesses.value = b.items || b.businesses || []
  } catch (e) { error.value = e.message || '无法加载项目' }
}
async function loadData() {
  if (!tenantId.value || !period.value?.[0] || !period.value?.[1]) return
  const current = ++revision
  busy.value = true
  error.value = ''
  try {
    const [t, c] = await Promise.all([
      fetchGeoMentionTrends(tenantId.value, params.value),
      fetchGeoUrlCitations(tenantId.value, params.value),
    ])
    if (current !== revision) return
    trends.value = t.items || []
    citations.value = c.items || []
  } catch (e) { if (current === revision) error.value = e.message || '报告数据加载失败' }
  finally { if (current === revision) busy.value = false }
}
async function loadTemplate() {
  const current = ++templateRevision
  sections.value = []
  if (!tenantId.value || !projectId.value) return
  try {
    const result = await fetchGeoReportTemplate(tenantId.value, projectId.value)
    if (current === templateRevision) sections.value = result.sections || []
  } catch (e) { if (current === templateRevision) error.value = e.message || '模板加载失败' }
}
async function saveTemplate(reset = false) {
  if (!projectId.value) return
  try {
    sections.value = (await saveGeoReportTemplate(tenantId.value, projectId.value, reset ? null : sections.value)).sections
    ElMessage.success(reset ? '已恢复默认模板' : '模板已保存')
  } catch (e) { ElMessage.error(e.message || '保存失败') }
}
function move(index, delta) {
  const next = index + delta
  if (next < 0 || next >= sections.value.length) return
  const copy = [...sections.value]
  ;[copy[index], copy[next]] = [copy[next], copy[index]]
  sections.value = copy
}
async function download(format) {
  if (!period.value?.[0] || !period.value?.[1]) return
  busy.value = true
  try {
    const targetTenant = tenantId.value
    const targetParams = { ...params.value }
    const blob = await downloadGeoReport(targetTenant, format, targetParams)
    if (targetTenant !== tenantId.value || targetParams.project_id !== params.value.project_id || targetParams.business_id !== params.value.business_id) return
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = safeFilename(period.value[0], period.value[1], format === 'pdf' ? '报告' : '明细')
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) { ElMessage.error(e.message || '下载失败') }
  finally { busy.value = false }
}
async function previewImport() {
  importBusy.value = true
  try {
    preview.value = (await previewGeoPublicationLinks(tenantId.value, businessId.value, file.value, pasted.value)).items || []
  } catch (e) { ElMessage.error(e.message || '预检失败') }
  finally { importBusy.value = false }
}
async function confirmImport() {
  importBusy.value = true
  try {
    const result = await confirmGeoPublicationLinks(tenantId.value, businessId.value, preview.value)
    preview.value = result.items || []
    ElMessage.success(`成功导入 ${result.applied_count} 条`)
    await loadData()
  } catch (e) { ElMessage.error(e.message || '导入失败') }
  finally { importBusy.value = false }
}
watch(tenantId, async () => { ++revision; ++templateRevision; trends.value = []; citations.value = []; sections.value = []; preview.value = []; projectId.value = ''; businessId.value = ''; await loadChoices(); await loadData() })
watch([period, businessId, granularity, source], loadData, { deep: true })
watch(projectId, () => { loadTemplate(); loadData() })
onMounted(async () => { await loadChoices(); await loadData() })
</script>

<template>
  <GeoWorkbenchPage title="GEO 报告" sub="已存回答样本与发布链接；无样本显示无数据" :loading="busy">
    <div class="geo-report">
      <el-alert v-if="error" type="error" :title="error" :closable="false" />
      <div class="report-controls">
        <el-select v-model="projectId" placeholder="全部项目" clearable style="width:180px"><el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" /></el-select>
        <el-select v-model="businessId" placeholder="全部业务" clearable style="width:180px"><el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" /></el-select>
        <el-date-picker v-model="period" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" />
        <el-button @click="download('xlsx')">导出 Excel</el-button>
        <el-button type="primary" @click="download('pdf')">生成 GEO 报告 (PDF)</el-button>
        <el-button @click="importOpen = true">批量上传发布链接</el-button>
      </div>
      <el-alert type="info" :closable="false" title="项目选择用于报告名称与模板；问题和任务数据按客户或所选业务筛选。真实引擎采样是默认主指标，人工、模拟与未知样本单独查看。" />
      <section class="report-card"><h2>各 AI 引擎提及率</h2>
        <div class="report-controls"><el-radio-group v-model="granularity"><el-radio-button value="day">按天</el-radio-button><el-radio-button value="week">按周</el-radio-button><el-radio-button value="month">按月</el-radio-button></el-radio-group>
          <el-select v-model="source" style="width:160px"><el-option v-for="(label, key) in SOURCE_LABELS" :key="key" :label="label" :value="key" /></el-select></div>
        <el-table :data="trends" border max-height="420" empty-text="无数据"><el-table-column prop="engine" label="AI 引擎" /><el-table-column prop="bucket" label="周期" /><el-table-column prop="mentions" label="提及数" /><el-table-column prop="samples" label="样本数" /><el-table-column label="提及率"><template #default="{ row }">{{ rateLabel(row) }}</template></el-table-column></el-table>
      </section>
      <section class="report-card"><h2>已发布 URL 引用追踪</h2><p>精准匹配为规范化 URL 一致；宽松匹配需人工核对。同域名不会计为精准引用。</p>
        <el-table :data="citations" border empty-text="无发布链接"><el-table-column type="expand"><template #default="{ row }"><el-table :data="row.matches" size="small" empty-text="无数据"><el-table-column prop="sample_id" label="样本 ID" /><el-table-column prop="engine" label="引擎" /><el-table-column prop="date" label="日期" /><el-table-column prop="matched_url" label="命中来源 URL" /><el-table-column label="匹配"><template #default="{ row: m }">{{ m.kind === 'exact' ? '精准' : '宽松' }}</template></el-table-column></el-table></template></el-table-column>
          <el-table-column prop="published_url" label="发布 URL" min-width="300" show-overflow-tooltip /><el-table-column prop="channel" label="渠道" /><el-table-column prop="exact_count" label="精准" /><el-table-column prop="loose_count" label="宽松" /></el-table>
      </section>
      <section class="report-card"><h2>报告模板</h2><p v-if="!projectId">选择项目后可调整章节。</p><template v-else><div v-for="(item, index) in sections" :key="item.key" class="section-row"><el-checkbox v-model="item.visible">显示</el-checkbox><el-input v-model="item.title" maxlength="60" /><el-button size="small" :disabled="index === 0" @click="move(index, -1)">上移</el-button><el-button size="small" :disabled="index === sections.length - 1" @click="move(index, 1)">下移</el-button></div><el-button type="primary" @click="saveTemplate()">保存模板</el-button><el-button @click="saveTemplate(true)">恢复默认</el-button></template></section>
    </div>
    <el-dialog v-model="importOpen" title="批量上传发布链接" width="80%"><p>支持 UTF-8 CSV、XLSX 或粘贴表格。列：task_id 或 task_title、channel、url、published_at（可选）。最多 500 行、2 MB。</p>
      <input type="file" accept=".csv,.xlsx,.tsv" @change="file = $event.target.files?.[0] || null; preview = []" />
      <el-input v-model="pasted" type="textarea" :rows="5" placeholder="task_id,channel,url,published_at" @input="preview = []" />
      <el-button :loading="importBusy" @click="previewImport">预检</el-button>
      <el-table :data="preview" border max-height="320"><el-table-column prop="row_number" label="行" width="60" /><el-table-column prop="task_id" label="任务 ID" /><el-table-column prop="channel" label="渠道" /><el-table-column prop="url" label="URL" min-width="240" /><el-table-column prop="status" label="状态" /><el-table-column label="错误"><template #default="{ row }">{{ row.errors?.join('；') || '—' }}</template></el-table-column></el-table>
      <template #footer><el-button @click="importOpen = false">关闭</el-button><el-button type="primary" :disabled="!validCount" :loading="importBusy" @click="confirmImport">确认导入有效行 ({{ validCount }})</el-button></template>
    </el-dialog>
  </GeoWorkbenchPage>
</template>

<style scoped>
.geo-report { display:grid; gap:20px; }.report-controls { display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin-bottom:14px; }.report-card { padding:20px; background:#fff; border:1px solid #dce6eb; border-radius:12px; }.report-card h2 { margin:0 0 12px; font-size:18px; }.section-row { display:flex; align-items:center; gap:8px; margin:8px 0; }.section-row .el-input { max-width:350px; }
</style>
