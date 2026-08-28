<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { auditPendingSeoSitePages, auditSeoSitePage, fetchSeoKeywords, fetchSeoSitePages, generateSeoSitePageSuggestions, importSeoSitePages, updateSeoSitePage } from '../../api/seo'
import { fetchSeoSites } from '../../api/moduleAssets'
import { currentTenantId, session } from '../../store/session'
import { formatSeoCsvTime } from './seoRankTime'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const error = ref('')
const sites = ref([])
const siteId = ref(null)
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
const selectedRows = ref([])
const keywordOptions = ref([])
const editForm = reactive({ page_type: '', target_keyword_id: null, title_suggestion: '', description_suggestion: '', status: 'pending' })

const canEdit = computed(() => !session.isLoggedIn || session.canEdit('seo.site'))
const stats = computed(() => result.value.stats || {})
function fmt(value) { return value == null ? '—' : Number(value).toLocaleString('zh-CN') }
function statusLabel(value) { return {pending:'待检测',healthy:'健康',needs_fix:'需优化',proposed:'待确认',approved:'已确认',implemented:'待复检',verified:'已复检',error:'检测失败'}[value] || value }
function statusType(value) { return {pending:'info',healthy:'success',needs_fix:'warning',proposed:'warning',approved:'primary',implemented:'primary',verified:'success',error:'danger'}[value] || 'info' }
function issueLabel(code) { return {title:'Title',description:'Description',canonical:'Canonical',h1:'H1',indexable:'索引',heading_depth:'标题结构',substantial:'内容量',schema:'Schema'}[code] || code }

async function load() {
  if (!currentTenantId.value) { error.value = '请先在右上角选择客户'; result.value = {items:[],total:0,stats:{}}; return }
  if (!siteId.value) { error.value = '请先选择或创建 SEO 网站'; result.value = {items:[],total:0,stats:{}}; return }
  loading.value = true; error.value = ''
  try { result.value = await fetchSeoSitePages({ tenantId: currentTenantId.value, siteId: siteId.value, pageId: Number(route.query.page_id) || undefined, ...filters, pageSize: 100 }) }
  catch (e) { error.value = e.message } finally { loading.value = false }
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
  const next = new Set(auditing.value); next.add(row.id); auditing.value = next
  try { await auditSeoSitePage({ pageId: row.id, tenantId: currentTenantId.value }); ElMessage.success('页面检测完成'); await load() }
  catch (e) { ElMessage.error(e.message); await load() }
  finally { const done = new Set(auditing.value); done.delete(row.id); auditing.value = done }
}
async function auditPending() {
  batchAuditing.value = true
  try {
    const response = await auditPendingSeoSitePages({ tenantId: currentTenantId.value, siteId: siteId.value, maxPages: 10 })
    const message = `已补抓 ${response.completed} 个页面${response.failed?.length ? `，失败 ${response.failed.length} 个` : ''}`
    response.failed?.length ? ElMessage.warning(message) : ElMessage.success(message)
    await load()
  } catch (e) { ElMessage.error(e.message) } finally { batchAuditing.value = false }
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
function csvCell(value) { return `"${String(value ?? '').replace(/"/g, '""')}"` }
function exportHandoff() {
  const rows = selectedRows.value.length ? selectedRows.value : result.value.items
  if (!rows.length) return ElMessage.warning('当前没有可导出的页面')
  const headers = ['页面ID','URL','页面类型','目标关键词ID','问题','当前Title','建议Title','当前Description','建议Description','状态','最近检测时间']
  const body = rows.map((row) => [row.id,row.url,row.page_type,row.target_keyword_id,(row.issue_codes||[]).join('|'),row.title,row.title_suggestion,row.meta_description,row.description_suggestion,statusLabel(row.status),formatSeoCsvTime(row.last_checked_at)])
  const blob = new Blob(['\ufeff' + [headers,...body].map((line) => line.map(csvCell).join(',')).join('\n')], { type: 'text/csv;charset=utf-8' })
  const anchor = document.createElement('a'); anchor.href = URL.createObjectURL(blob); anchor.download = `SEO站内优化交接-${siteId.value}.csv`; anchor.click(); URL.revokeObjectURL(anchor.href)
}
function createContentTask(row) {
  router.push({ path: '/seo/content/editor', query: { site_id: siteId.value, keyword_id: row.target_keyword_id || undefined, source_page_id: row.id } })
}
let timer
watch(() => filters.q, () => { clearTimeout(timer); timer = setTimeout(load, 260) })
async function loadSites() {
  if (!currentTenantId.value) { sites.value = []; siteId.value = null; return }
  try {
    sites.value = (await fetchSeoSites(currentTenantId.value)).sites || []
    const requestedSiteId = Number(route.query.site_id) || null
    const nextSiteId = sites.value.some((site) => site.id === requestedSiteId)
      ? requestedSiteId
      : (sites.value.some((site) => site.id === siteId.value) ? siteId.value : (sites.value.find((site) => site.status === 'active')?.id || sites.value[0]?.id || null))
    if (nextSiteId !== siteId.value) siteId.value = nextSiteId
    else { await load(); await loadKeywordOptions() }
  } catch (e) {
    sites.value = []; siteId.value = null; error.value = e.message
  }
}
watch(() => [filters.status, filters.issueCode], load)
watch(() => route.query.page_id, load)
watch(() => route.query.site_id, loadSites)
watch(siteId, () => { load(); loadKeywordOptions() })
watch(currentTenantId, loadSites)
onMounted(loadSites)
</script>

<template>
  <div class="site-page">
    <section class="site-hero">
      <div><span>SEO / ONSITE OPTIMIZATION</span><h1>站内优化</h1><p>管理页面资产、TDK、H1、Canonical 与索引状态。检测结果保存到页面档案，可用于上线前后复核。</p></div>
      <div class="hero-actions"><el-select v-model="siteId" placeholder="选择 SEO 网站"><el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id"/></el-select><button v-if="canEdit" :disabled="generating||!siteId" @click="generateSuggestions">{{generating?'生成中…':'生成 TDK 建议'}}</button><button :disabled="!siteId" class="secondary" @click="exportHandoff">导出交接单</button><button v-if="canEdit" :disabled="batchAuditing||!siteId" @click="auditPending">{{batchAuditing?'补抓中…':'补抓待检测页面'}}</button><button v-if="canEdit" :disabled="!siteId" @click="importOpen = true">＋ 导入页面</button></div>
    </section>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <section class="metrics">
      <article><span>页面资产</span><strong>{{ fmt(stats.total || 0) }}</strong><small>已纳入持续维护</small></article>
      <article><span>健康页面</span><strong>{{ fmt(stats.healthy || 0) }}</strong><small>最近检测未发现问题</small></article>
      <article><span>待优化</span><strong>{{ fmt(stats.needs_fix || 0) }}</strong><small>存在 TDK 或技术问题</small></article>
      <article><span>平均健康度</span><strong>{{ stats.average_score || 0 }}</strong><small>满分 100</small></article>
    </section>
    <section class="site-panel">
      <header><div><span>01 / PAGE INVENTORY</span><h2>页面资产与 TDK</h2></div><small>检测使用网站公开页面，不会修改客户网站代码</small></header>
      <div class="filters"><el-input v-model="filters.q" clearable placeholder="搜索 URL 或页面标题" /><el-select v-model="filters.issueCode" clearable placeholder="全部问题"><el-option v-for="item in [{v:'title',n:'Title'},{v:'description',n:'Description'},{v:'h1',n:'H1'},{v:'canonical',n:'Canonical'},{v:'indexable',n:'索引'},{v:'schema',n:'Schema'}]" :key="item.v" :label="item.n" :value="item.v" /></el-select><el-select v-model="filters.status" clearable placeholder="全部状态"><el-option v-for="item in [{v:'pending',n:'待检测'},{v:'needs_fix',n:'需优化'},{v:'proposed',n:'待确认'},{v:'approved',n:'已确认'},{v:'implemented',n:'待复检'},{v:'verified',n:'已复检'},{v:'healthy',n:'健康'},{v:'error',n:'检测失败'}]" :key="item.v" :label="item.n" :value="item.v" /></el-select><span>{{ result.total }} 个页面 · 已选 {{ selectedRows.length }} 个</span></div>
      <el-table v-loading="loading" :data="result.items" empty-text="尚未导入站内页面" @selection-change="selectedRows = $event">
        <el-table-column type="selection" width="44" />
        <el-table-column label="页面 / URL" min-width="280"><template #default="{row}"><b class="page-title">{{ row.title || '未读取页面标题' }}</b><small class="page-url">{{ row.url }}</small></template></el-table-column>
        <el-table-column label="目标关键词" width="120"><template #default="{row}">{{ row.target_keyword_id ? `#${row.target_keyword_id}` : '待绑定' }}</template></el-table-column>
        <el-table-column label="健康度" width="100"><template #default="{row}"><strong>{{ row.audit_score ?? '—' }}</strong></template></el-table-column>
        <el-table-column label="检测问题" min-width="210"><template #default="{row}"><div class="issues"><span v-for="code in (row.issue_codes || []).slice(0,4)" :key="code">{{ issueLabel(code) }}</span><small v-if="!(row.issue_codes || []).length">—</small></div></template></el-table-column>
        <el-table-column label="当前 TDK" min-width="220"><template #default="{row}"><div class="suggestion current"><b>{{ row.title || '缺少 Title' }}</b><small>{{ row.meta_description || '缺少 Description' }}</small></div></template></el-table-column>
        <el-table-column label="建议 TDK" min-width="240"><template #default="{row}"><div class="suggestion"><b>{{ row.title_suggestion || '尚未生成 Title 建议' }}</b><small>{{ row.description_suggestion || '尚未生成 Description 建议' }}</small></div></template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{row}"><el-tag :type="statusType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="215" fixed="right"><template #default="{row}"><div class="actions"><button v-if="canEdit" :disabled="auditing.has(row.id)" @click="audit(row)">{{ auditing.has(row.id) ? '检测中…' : (row.status==='implemented'?'复检':'检测') }}</button><button v-if="canEdit" @click="openEdit(row)">优化记录</button><button @click="createContentTask(row)">内容任务</button></div></template></el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="importOpen" title="导入站内页面" width="600px">
      <p class="dialog-tip">每行一个公开页面 URL。导入后可逐页运行真实检测；系统不会自动修改客户网站。</p>
      <el-input v-model="importText" type="textarea" :rows="9" placeholder="https://example.com/&#10;https://example.com/products" />
      <template #footer><el-button @click="importOpen=false">取消</el-button><el-button type="primary" :loading="saving" @click="importPages">导入页面</el-button></template>
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
.hero-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap}.hero-actions button:disabled{cursor:wait;opacity:.6}.hero-actions button.secondary{border:1px solid #b9d4cf;background:#fff;color:var(--teal);box-shadow:none}
.site-page{--ink:#17233d;--teal:#168b83;--line:#e3e8ef;min-height:100%;padding:26px;background:radial-gradient(circle at 78% -16%,rgba(22,139,131,.1),transparent 35%),#f5f8f7;color:var(--ink)}.site-hero{display:flex;align-items:end;justify-content:space-between;gap:28px;padding:27px 30px;border:1px solid #dbe7e4;border-radius:17px;background:#fff;box-shadow:0 16px 45px rgba(29,69,64,.05)}.site-hero>div>span,.site-panel header span{color:var(--teal);font:800 10px ui-monospace,monospace;letter-spacing:.13em}.site-hero h1{margin:9px 0 7px;font:750 34px "Noto Serif SC","Songti SC",serif}.site-hero p{max-width:760px;margin:0;color:#72817e;line-height:1.7}.site-hero button{height:40px;padding:0 18px;border:0;border-radius:9px;background:var(--teal);color:#fff;font-weight:700;cursor:pointer;box-shadow:0 8px 20px rgba(22,139,131,.2)}.el-alert{margin-top:14px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:15px 0}.metrics article{padding:19px 20px;border:1px solid var(--line);border-radius:13px;background:#fff}.metrics span,.metrics small{display:block;color:#768582;font-size:11px}.metrics strong{display:block;margin:10px 0 5px;font-size:28px}.site-panel{overflow:hidden;border:1px solid var(--line);border-radius:15px;background:#fff}.site-panel>header{display:flex;align-items:end;justify-content:space-between;padding:16px 19px;border-bottom:1px solid #edf1ef}.site-panel h2{margin:4px 0 0;font-size:15px}.site-panel header small{color:#82908d}.filters{display:flex;gap:9px;padding:14px 17px}.filters .el-input{max-width:350px}.filters .el-select{width:140px}.filters>span{align-self:center;margin-left:auto;color:#788683;font-size:11px}.page-title,.page-url{display:block}.page-url{max-width:330px;overflow:hidden;margin-top:4px;color:#5d7f79;text-overflow:ellipsis;white-space:nowrap}.issues{display:flex;gap:4px;flex-wrap:wrap}.issues span{padding:3px 6px;border-radius:5px;background:#fff0e3;color:#a65e24;font-size:10px}.suggestion b,.suggestion small{display:block;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.suggestion small{margin-top:4px;color:#899491}.actions{display:flex;gap:5px}.actions button{padding:5px 7px;border:1px solid #dce5e2;border-radius:6px;background:#fff;color:#52736e;font-size:10.5px;cursor:pointer}.actions button:hover{border-color:#7bb3aa;color:var(--teal)}.actions button:disabled{opacity:.55;cursor:wait}.dialog-tip{margin:-6px 0 15px;color:#75827f;font-size:12px;line-height:1.6}.el-form :deep(.el-select){width:100%}@media(max-width:980px){.metrics{grid-template-columns:repeat(2,1fr)}}@media(max-width:680px){.site-page{padding:14px}.site-hero{align-items:flex-start;flex-direction:column}.metrics{grid-template-columns:1fr 1fr}.filters{flex-wrap:wrap}.filters .el-input{max-width:none;width:100%}.filters>span{margin-left:0}}
</style>
