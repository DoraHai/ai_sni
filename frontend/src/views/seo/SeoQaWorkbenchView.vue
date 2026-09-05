<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { seoQaGet, seoQaPost, seoQaPatch, assistSeoContent, submitSeoContentReview, decideSeoContentReview } from '../../api/seo'
import { currentTenantId, session } from '../../store/session'
import { currentSeoSiteId as siteId } from './seoSiteContext'
import './seo-suite.css'
import SeoQaPlanning from './SeoQaPlanning.vue'

const router = useRouter()
const canEdit = computed(() => session.canEdit('seo.content'))
const scope = computed(() => ({ tenant_id: Number(currentTenantId.value), site_id: Number(siteId.value) }))
const scopeKey = computed(() => `${scope.value.tenant_id}:${scope.value.site_id}`)
const tab = ref('questions'), busy = ref(false), loading = ref(false), error = ref('')
const items = ref([]), facts = ref([]), placements = ref([]), maintenance = ref([]), platforms = ref([])
const total = ref(0), page = ref(1), query = ref(''), status = ref('')
const selected = ref(null), answerItems = ref([]), dialog = ref(''), importing = ref('')
const sourceKind = ref('manual'), sourceName = ref('人工录入'), sourceUrl = ref('')
const factForm = reactive({ id: null, title: '', statement: '', source_name: '', source_url: '', expires_at: null, status: 'active', version: 1 })
const questionForm = reactive({ topic: '', intent: 'learn', relevance: 3, owner: '', status: 'open', version: 1 })
const answerForm = reactive({ id: null, content_id: null, content_version: null, body: '', format: 'short', fact_ids: [], status: 'drafting' })
const placementForm = reactive({ answer_id: null, platform: 'zhihu', question_url: '', scheduled_at: null })
const receiptForm = reactive({ id: null, answer_url: '', version: 1 })
const metricsForm = reactive({ id: null, version: 1, views: null, likes: null, comments: null, source_url: '', as_of: null })
const reviewNote = ref('')
const planningRevision = ref(0)
const followupOnly = ref(false)
const followupCount = computed(() => placements.value.filter(row => row.followup?.needed).length)
const visiblePlacements = computed(() => followupOnly.value ? placements.value.filter(row => row.followup?.needed) : placements.value)
const batchRunning = ref(false), batchStop = ref(false), batchResults = ref([])
const batchCandidates = computed(() => visiblePlacements.value.filter(row => row.answer_url).slice(0, 20))
function latestBacklink(row) {
  return [...(row.observations || [])].reverse().find(o => o.backlink_discovery && o.backlink_discovery.state !== 'not_checked')
}
async function verifyBatch() {
  if (busy.value || !canEdit.value || !scope.value.tenant_id || !scope.value.site_id) return
  const key = scopeKey.value, params = { ...scope.value }, candidates = [...batchCandidates.value]
  busy.value = true; batchRunning.value = true; batchStop.value = false; batchResults.value = []; error.value = ''
  try {
    for (const row of candidates) {
      if (batchStop.value || key !== scopeKey.value) break
      try {
        const result = await seoQaPost(`placements/${row.id}/verify`, params)
        if (key !== scopeKey.value) break
        batchResults.value.push({ id: row.id, message: labels[result.status] || '核验完成', failed: false })
      } catch (e) {
        if (key !== scopeKey.value) break
        batchResults.value.push({ id: row.id, message: messageOf(e), failed: true })
        if ([401, 403].includes(e?.response?.status)) break
      }
    }
    if (key === scopeKey.value) await load()
  } finally { busy.value = false; batchRunning.value = false }
}
function csvCell(value) {
  let text = String(value ?? '')
  if (/^[\s\u0000-\u001f]*[=+@-]/.test(text)) text = "'" + text
  return '"' + text.replaceAll('"', '""') + '"'
}
function resultsCsv() {
  const rows = [['记录编号', '平台', '回答网址', '正文状态', '最近核验时间', '外链结果', '外链观测时间', '待跟进原因']]
  for (const row of visiblePlacements.value) {
    const link = latestBacklink(row)
    rows.push([row.id, platformName(row.platform), row.answer_url, labels[row.status] || row.status,
      row.observations?.at(-1)?.checked_at, backlinkSummary(link), link?.checked_at, row.followup?.reasons?.join('；')])
  }
  return '\ufeff' + rows.map(row => row.map(csvCell).join(',')).join('\r\n')
}
function exportResults() {
  const blob = new Blob([resultsCsv()], {type:'text/csv;charset=utf-8'}), url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = `问答核验-${scope.value.site_id}.csv`; a.click(); URL.revokeObjectURL(url)
}
function backlinkSummary(observation) {
  const result = observation?.backlink_discovery
  if (!result || result.state === 'not_checked') return '外链尚未检查'
  if (result.state === 'permission_required') return '外链未检查：需要外链编辑权限'
  if (result.state === 'internal') return '本站页面，不计入站外外链'
  if (result.state !== 'readable') return '外链暂时无法核验，可稍后重试'
  return `回答所在页面发现 ${result.found} 条官网链接，本次新增 ${result.created} 条外链资产`
}
const labels = { open: '待选题', selected: '已选题', archived: '已归档', planned: '草稿', drafting: '草稿', review: '待审核', ready: '已审核', published: '已发布', prepared: '待人工发布', reported: '已回填 · 待核验', content_observed: '页面正文匹配', not_observed: '未观测到正文', unavailable: '暂时无法核验' }
const kinds = { manual: '人工录入', customer: '客服/销售', import: 'CSV 导入', suggestion: '建议问题', serp: '搜索结果' }
const formats = { short: '直接短答', detailed: '详细解答', steps: '操作步骤', comparison: '条件对比', faq: '官网 FAQ' }
const dirtyAnswer = computed(() => {
  const saved = answerItems.value.find(a => a.id === answerForm.id)
  return !!saved && (saved.body !== answerForm.body || saved.format !== answerForm.format || JSON.stringify(saved.fact_snapshots.map(f=>f.id).sort((a,b)=>a-b)) !== JSON.stringify([...answerForm.fact_ids].sort((a,b)=>a-b)))
})
let loadSequence = 0, answerSequence = 0

function messageOf(e) { const detail = e?.response?.data?.detail; return typeof detail === 'string' ? detail : e?.message || '操作失败，请重试' }
function date(value) { return value ? new Date(value).toLocaleString('zh-CN') : '未知' }
function href(value) { try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) ? u.href : null } catch { return null } }
function platformName(key) { return platforms.value.find(p => p.key === key)?.name || key }

async function load() {
  const seq = ++loadSequence, key = scopeKey.value, params = { ...scope.value }
  if (!params.tenant_id || !params.site_id) { loading.value = false; return }
  loading.value = true; error.value = ''
  try {
    const [questions, fs, ps, ms, cs] = await Promise.all([
      seoQaGet('questions', { ...params, q: query.value, status: status.value || undefined, page: page.value }),
      seoQaGet('facts', params), seoQaGet('placements', params), seoQaGet('maintenance', params), seoQaGet('capabilities', params),
    ])
    if (seq !== loadSequence || key !== scopeKey.value) return
    items.value = questions.items; total.value = questions.total; facts.value = fs
    placements.value = ps; maintenance.value = ms.items; platforms.value = cs.platforms; planningRevision.value++
  } catch (e) { if (seq === loadSequence && key === scopeKey.value) error.value = messageOf(e) }
  finally { if (seq === loadSequence) loading.value = false }
}

async function act(work, success) {
  if (busy.value || !canEdit.value || !scope.value.tenant_id || !scope.value.site_id) return
  const key = scopeKey.value, params = { ...scope.value }
  busy.value = true; error.value = ''
  try {
    const result = await work(params)
    if (key !== scopeKey.value) return
    if (success) await success(result)
    await load()
  } catch (e) { if (key === scopeKey.value) error.value = messageOf(e) }
  finally { busy.value = false }
}

function resetAnswer() { Object.assign(answerForm, { id: null, content_id: null, content_version: null, body: '', format: 'short', fact_ids: [], status: 'drafting' }); reviewNote.value = '' }
async function openQuestion(row) {
  if (busy.value) return
  selected.value = row; Object.assign(questionForm, row); resetAnswer(); answerItems.value = []
  const seq = ++answerSequence, key = scopeKey.value
  try {
    const result = await seoQaGet('answers', { ...scope.value, question_id: row.id })
    if (seq === answerSequence && key === scopeKey.value) answerItems.value = result
  } catch (e) { if (seq === answerSequence && key === scopeKey.value) error.value = messageOf(e) }
}
function editAnswer(row) { Object.assign(answerForm, row, { fact_ids: row.fact_snapshots.map(f => f.id) }); reviewNote.value = '' }
async function refreshAnswers(id) {
  if (!selected.value) return
  const key = scopeKey.value, questionId = selected.value.id
  const result = await seoQaGet('answers', { ...scope.value, question_id: questionId })
  if (key !== scopeKey.value || selected.value?.id !== questionId) return
  answerItems.value = result
  if (id) { const answer = result.find(a => a.id === id); if (answer) editAnswer(answer) }
}
function importQuestions() {
  const payload = dialog.value === 'csv' ? { csv: importing.value } : { items: importing.value.split('\n').map(t => t.trim()).filter(Boolean).map(title => ({ title, source: { kind: sourceKind.value, name: sourceName.value, url: sourceUrl.value || null } })) }
  return act(p => seoQaPost('questions/import', { ...p, ...payload }), result => { dialog.value = ''; importing.value = ''; ElMessage.success(`新增 ${result.created} 个，合并 ${result.merged} 个`) })
}
function discover() { return act(p => seoQaPost('questions/discover', p), r => ElMessage.success(`新增 ${r.created} 个问题；检查了 ${r.examined} 条已采集结果`)) }
function saveQuestion() {
  const id = selected.value.id
  const payload = Object.fromEntries(['topic', 'intent', 'relevance', 'owner', 'status', 'version'].map(k => [k, questionForm[k]]))
  return act(p => seoQaPatch(`questions/${id}`, { ...p, ...payload }), row => { selected.value = row; Object.assign(questionForm, row) })
}
function openFact(row) {
  Object.assign(factForm, row || { id: null, title: '', statement: '', source_name: '', source_url: '', expires_at: null, status: 'active', version: 1 })
  dialog.value = 'fact'
}
function saveFact() {
  const { id, version, title, statement, source_name, source_url, expires_at, status } = factForm
  const payload = { title, statement, source_name, source_url: source_url || null, expires_at: expires_at ? new Date(expires_at).toISOString() : null, status }
  return act(p => id ? seoQaPatch(`facts/${id}`, { ...p, ...payload, version }) : seoQaPost('facts', { ...p, ...payload }), () => { dialog.value = '' })
}
function saveAnswer() {
  const id = answerForm.id
  const payload = { question_id: selected.value.id, format: answerForm.format, body: answerForm.body, fact_ids: [...answerForm.fact_ids], content_version: answerForm.content_version }
  return act(p => id ? seoQaPatch(`answers/${id}`, { ...p, ...payload }) : seoQaPost('answers', { ...p, ...payload }), row => refreshAnswers(row.id))
}
function generate() {
  const payload = { action: 'generate', mode: 'qa', qa_question_id: selected.value.id, qa_fact_ids: [...answerForm.fact_ids], qa_format: answerForm.format, keyword_ids: [] }
  return act(p => assistSeoContent({ ...p, ...payload }), result => { answerForm.body = result.content || ''; ElMessage.success('草稿已生成，请核对事实并保存') })
}
function review(decision) {
  if (dirtyAnswer.value) { error.value = '请先保存回答修改，再进入审核或分发'; return }
  const id = answerForm.id, contentId = answerForm.content_id, note = reviewNote.value || null
  return act(p => decision === 'submit' ? submitSeoContentReview({ contentId, tenantId: p.tenant_id, note }) : decideSeoContentReview({ contentId, tenantId: p.tenant_id, decision, note }), () => refreshAnswers(id))
}
function openPlacement() {
  if (dirtyAnswer.value) { error.value = '请先保存回答修改并重新审核'; return }
  Object.assign(placementForm, { answer_id: answerForm.id, platform: 'zhihu', question_url: '', scheduled_at: null })
  dialog.value = 'placement'
}
function prepare() {
  const payload = { ...placementForm, question_url: placementForm.question_url || null, scheduled_at: placementForm.scheduled_at ? new Date(placementForm.scheduled_at).toISOString() : null }
  return act(p => seoQaPost('placements', { ...p, ...payload }), () => { dialog.value = ''; selected.value = null; tab.value = 'placements' })
}
function saveReceipt() {
  const { id, answer_url, version } = receiptForm
  return act(p => seoQaPost(`placements/${id}/receipt`, { ...p, answer_url, version }), () => { dialog.value = '' })
}
function verify(row) { return act(p => seoQaPost(`placements/${row.id}/verify`, p)) }
function saveMetrics() {
  const { id, version, views, likes, comments, source_url, as_of } = metricsForm
  if (!as_of) { error.value = '请填写数据观测时间'; return }
  return act(p => seoQaPost(`placements/${id}/metrics`, { ...p, version, views, likes, comments, source_url, as_of: new Date(as_of).toISOString() }), () => { dialog.value = '' })
}
async function copy(row) {
  const key = scopeKey.value
  try {
    const draft = await seoQaGet(`placements/${row.id}/draft`, { ...scope.value })
    if (key !== scopeKey.value) return
    await navigator.clipboard.writeText(draft.body); ElMessage.success('已复制审核稿')
  } catch (e) { if (key === scopeKey.value) error.value = messageOf(e) }
}
async function download(row) {
  const key = scopeKey.value
  try {
    const draft = await seoQaGet(`placements/${row.id}/draft`, { ...scope.value })
    if (key !== scopeKey.value) return
    const blob = new Blob([draft.body], { type: 'text/plain;charset=utf-8' }), url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = `问答-${row.id}.txt`; a.click(); URL.revokeObjectURL(url)
  } catch (e) { if (key === scopeKey.value) error.value = messageOf(e) }
}
async function readCsv(event) {
  const file = event.target.files[0], key = scopeKey.value
  if (!file || file.size > 500000) { error.value = 'CSV 最大 500 KB'; return }
  const value = await file.text()
  if (key === scopeKey.value && dialog.value === 'csv') importing.value = value
}
function search() { page.value = 1; return load() }
function findMaintenanceQuestion(item) {
  if (busy.value) return
  tab.value = 'questions'; query.value = item.title; status.value = ''
  return search()
}
watch(scopeKey, () => {
  batchStop.value = true; batchResults.value = []; followupOnly.value = false
  ++answerSequence; selected.value = null; items.value = []; facts.value = []; placements.value = []; maintenance.value = []; platforms.value = []
  total.value = 0; page.value = 1; dialog.value = ''; resetAnswer(); load()
}, { immediate: true })
</script>

<template>
  <main class="qa-workbench">
    <header class="qa-header"><div><span class="qa-eyebrow">问题 · 证据 · 回答</span><h1>问答运营工作台</h1><p>从值得回答的问题开始，让每个答案有依据、有去向、可持续更新。</p></div><el-button @click="router.push({path:'/seo/content/qa-legacy',query:{site_id:siteId}})">历史问答资产</el-button></header>
    <el-alert v-if="!siteId" title="请先选择一个 SEO 网站" type="info" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div class="qa-tabs"><button v-for="[key,label] in [['questions','问题库'],['planning','选题规划'],['facts','事实与证据'],['placements','分发与效果'],['maintenance','待更新回答']]" :key="key" :class="{active:tab===key}" @click="tab=key">{{ label }}<span v-if="key==='maintenance' && maintenance.length">{{ maintenance.length }}</span></button><el-button text :loading="loading" @click="load">刷新</el-button></div>

    <section v-if="tab==='questions'" class="qa-panel" :aria-busy="loading">
      <div class="qa-toolbar"><el-input v-model="query" placeholder="搜索问题或主题" clearable @keyup.enter="search" /><el-select v-model="status" placeholder="全部状态" clearable @change="search"><el-option v-for="s in ['open','selected','archived']" :key="s" :label="labels[s]" :value="s" /></el-select><el-button @click="search">搜索</el-button><div class="qa-spacer"/><el-button :disabled="!canEdit || busy || !siteId" @click="discover">从国内搜索结果发现</el-button><el-button :disabled="!canEdit || busy || !siteId" @click="dialog='csv';importing=''">导入 CSV</el-button><el-button type="primary" :disabled="!canEdit || busy || !siteId" @click="dialog='import';importing=''">录入问题</el-button></div>
      <p class="qa-hint">按业务相关性排序。搜索发现使用近 30 天已有采集结果；暂无平台热度数据，建议问题单独标注。</p>
      <el-table :data="items" empty-text="还没有问题。录入客户常问的问题，或从已有搜索结果提取。" @row-click="openQuestion" class="qa-question-table">
        <el-table-column label="问题 / 来源" min-width="340"><template #default="{row}"><strong>{{ row.title }}</strong><div class="qa-source"><el-tag v-for="kind in [...new Set(row.sources.map(s=>s.kind))]" :key="kind" size="small" :type="kind==='suggestion'?'warning':'info'">{{ kinds[kind] }}</el-tag><span>{{ row.topic }}</span></div></template></el-table-column>
        <el-table-column label="相关性" width="130"><template #default="{row}"><span :title="row.priority_reason">{{ row.relevance }} / 5</span></template></el-table-column>
        <el-table-column label="回答" prop="answer_count" width="80"/><el-table-column label="状态" width="110"><template #default="{row}">{{ labels[row.status] }}</template></el-table-column><el-table-column label="负责人" prop="owner" width="130"/>
      </el-table>
      <el-pagination v-model:current-page="page" :page-size="30" :total="total" layout="prev, pager, next, total" @current-change="load" />
    </section>

    <SeoQaPlanning v-if="tab==='planning'" :tenant-id="scope.tenant_id" :site-id="scope.site_id" :can-edit="canEdit" :revision="planningRevision" @open="openQuestion" @changed="load"/>
    <section v-if="tab==='facts'" class="qa-panel">
      <div class="qa-toolbar"><div><h2>可追溯的事实资料</h2><p class="qa-hint">保存原文和资料出处。录入不代表系统已验证其真实性；过期或修改后，相关回答需要重新确认。</p></div><div class="qa-spacer"/><el-button type="primary" :disabled="!canEdit || busy || !siteId" @click="openFact()">添加事实</el-button></div>
      <el-table :data="facts" empty-text="添加产品手册、服务说明或可核实案例中的事实。"><el-table-column label="编号" width="80"><template #default="{row}">F{{ row.id }}</template></el-table-column><el-table-column prop="title" label="事实" min-width="190"/><el-table-column prop="source_name" label="出处" min-width="190"/><el-table-column label="有效性" width="140"><template #default="{row}"><el-tag :type="row.current?'success':'warning'">{{ row.current?'可引用':'已过期 / 停用' }}</el-tag></template></el-table-column><el-table-column label="操作" width="90"><template #default="{row}"><el-button text :disabled="!canEdit || busy" @click="openFact(row)">查看编辑</el-button></template></el-table-column></el-table>
    </section>

    <section v-if="tab==='placements'" class="qa-panel">
      <h2>分发与效果</h2><p class="qa-hint">平台回答由真人发布，计划时间用于安排工作。回填网址后抓取核验正文；正文匹配不代表账号归属或平台阅读量。最近 200 条记录。</p>
      <div class="qa-capabilities"><div v-for="p in platforms" :key="p.key"><strong>{{ p.name }}</strong><p>{{ p.description }}</p></div></div>
      <div class="qa-toolbar"><el-button :disabled="!canEdit || busy || !batchCandidates.length" @click="verifyBatch">批量核验当前列表（最多 20 条）</el-button><el-button v-if="batchRunning" @click="batchStop=true">停止后续核验</el-button><el-button :disabled="busy || !visiblePlacements.length" @click="exportResults">导出当前筛选结果</el-button></div>
      <div v-if="batchResults.length" class="qa-hint"><p>本次已返回 {{ batchResults.length }} 条结果；失败记录可单独重试。</p><p v-for="r in batchResults" :key="r.id" :class="{'qa-warning':r.failed}">#{{ r.id }} · {{ r.message }}</p></div>
      <div class="qa-toolbar"><el-checkbox v-model="followupOnly">仅看待跟进（{{ followupCount }}）</el-checkbox><span class="qa-hint">已核验的回答满 7 天进入后台正文复查队列，每小时最多 20 条。首次核验由人工触发；外链资产由外链模块定期核验。</span></div>
      <el-empty v-if="placements.length && !visiblePlacements.length" description="当前列表范围内没有待跟进记录"/>
      <el-empty v-if="!placements.length" description="回答审核通过后，点击“准备分发”建立记录。"/>
      <article class="qa-placement" v-for="row in visiblePlacements" :key="row.id">
        <div class="qa-toolbar"><strong>#{{ row.id }} · {{ platformName(row.platform) }}</strong><el-tag>{{ labels[row.status] }}</el-tag><span class="qa-hint">稿件版本 {{ row.content_version }} · 计划 {{ row.scheduled_at?date(row.scheduled_at):'未设置' }}</span></div>
        <div class="qa-toolbar"><a v-if="href(row.question_url)" :href="href(row.question_url)" target="_blank" rel="noopener noreferrer">打开指定问题 ↗</a><a v-if="href(row.answer_url)" :href="href(row.answer_url)" target="_blank" rel="noopener noreferrer">查看回答 ↗</a><el-button :disabled="!row.publishable" @click="copy(row)">复制审核稿</el-button><el-button :disabled="!row.publishable" @click="download(row)">下载文本</el-button><el-button :disabled="!canEdit || busy" @click="Object.assign(receiptForm,{id:row.id,answer_url:row.answer_url||'',version:row.version});dialog='receipt'">回填网址</el-button><el-button :disabled="!canEdit || busy || !row.answer_url" @click="verify(row)">核验正文与外链</el-button><el-button :disabled="!canEdit || busy" @click="Object.assign(metricsForm,{id:row.id,version:row.version,views:null,likes:null,comments:null,source_url:row.answer_url||'',as_of:null});dialog='metrics'">录入平台数据</el-button></div>
        <p class="qa-hint">{{ row.reported_metrics ? `人工录入：阅读 ${row.reported_metrics.views ?? '未知'} · 赞同 ${row.reported_metrics.likes ?? '未知'} · 评论 ${row.reported_metrics.comments ?? '未知'} · ${date(row.reported_metrics.as_of)}` : '阅读 / 赞同 / 评论：未知' }}</p>
        <p v-for="reason in row.followup?.reasons || []" :key="reason" class="qa-warning">{{ reason }}</p>
        <p>{{ backlinkSummary(latestBacklink(row)) }}<span v-if="latestBacklink(row)" class="qa-hint"> · 外链观测 {{ date(latestBacklink(row).checked_at) }}</span></p><p class="qa-hint">外链按页面中的真实链接统计；不代表链接属于该回答，也不保证传递排名权重。链接属性保存在外链核验记录中。</p>
        <p v-if="row.problems?.length" class="qa-warning">{{ row.problems.join('；') }}</p><details><summary>查看审核稿与核验记录</summary><pre>{{ row.body }}</pre><p v-for="(o,i) in row.observations" :key="i">{{ date(o.checked_at) }} · {{ o.source === 'scheduled' ? '后台复查' : '人工核验' }} · {{ labels[o.state] }} · {{ o.reason }} · {{ backlinkSummary(o) }}</p></details>
      </article>
    </section>

    <section v-if="tab==='maintenance'" class="qa-panel"><h2>需要重新确认的回答</h2><p class="qa-hint">检查最近更新的 200 个回答，识别证据过期、来源版本变化和正文引用问题。</p><el-empty v-if="!maintenance.length" description="当前检查范围内没有发现待修复的证据问题"/><div v-for="m in maintenance" :key="m.answer_id" class="qa-maintenance"><strong>{{ m.title }}</strong><p>{{ m.problems.join('；') }}</p><el-button :disabled="busy" @click="findMaintenanceQuestion(m)">找到问题并更新</el-button></div></section>

    <el-drawer :model-value="!!selected" title="问题与回答" size="min(960px, 96vw)" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" @close="selected=null;++answerSequence">
      <template v-if="selected"><el-alert v-if="error" :title="error" type="error" :closable="false"/><h2>{{ selected.title }}</h2><div class="qa-provenance" v-for="(source,i) in selected.sources" :key="i"><el-tag size="small">{{ kinds[source.kind] }}</el-tag> {{ source.name }} · {{ date(source.captured_at) }} <a v-if="href(source.url)" :href="href(source.url)" target="_blank" rel="noopener noreferrer">查看来源 ↗</a></div>
        <el-form label-position="top" :disabled="!canEdit || busy" class="qa-metadata"><el-form-item label="主题"><el-input v-model="questionForm.topic" maxlength="120"/></el-form-item><el-form-item label="意图"><el-select v-model="questionForm.intent"><el-option v-for="[key,label] in [['learn','了解'],['compare','对比'],['buy','购买'],['troubleshoot','排障']]" :key="key" :value="key" :label="label"/></el-select></el-form-item><el-form-item label="业务相关性 0–5"><el-input-number v-model="questionForm.relevance" :min="0" :max="5"/></el-form-item><el-form-item label="负责人"><el-input v-model="questionForm.owner" maxlength="120"/></el-form-item><el-form-item label="状态"><el-select v-model="questionForm.status"><el-option v-for="s in ['open','selected','archived']" :key="s" :value="s" :label="labels[s]"/></el-select></el-form-item><el-form-item label="选题管理"><el-button @click="saveQuestion">保存选题</el-button></el-form-item></el-form>
        <div class="qa-toolbar"><h3>回答版本</h3><el-button :disabled="!canEdit || busy" @click="resetAnswer">新建回答</el-button></div><div class="qa-answer-list"><button v-for="a in answerItems" :key="a.id" :disabled="busy" :class="{active:answerForm.id===a.id}" @click="editAnswer(a)">#{{ a.id }} {{ formats[a.format] }} · {{ labels[a.status] }}<span v-if="a.problems.length"> · 需修复</span></button></div>
        <el-form label-position="top" :disabled="!canEdit || busy || answerForm.status==='review'">
          <el-form-item label="回答形式"><el-select v-model="answerForm.format"><el-option v-for="(label,key) in formats" :key="key" :value="key" :label="label"/></el-select></el-form-item>
          <el-form-item label="事实证据（最多 20 条）"><el-select v-model="answerForm.fact_ids" multiple filterable :multiple-limit="20" placeholder="选择事实资料"><el-option v-for="f in facts" :key="f.id" :label="`[F${f.id}] ${f.title}${f.current?'':'（需更新）'}`" :value="f.id" :disabled="!f.current"/></el-select></el-form-item>
          <div class="qa-evidence" v-for="f in facts.filter(x=>answerForm.fact_ids.includes(x.id))" :key="f.id"><strong>[F{{ f.id }}] {{ f.title }}</strong><p>{{ f.statement }}</p><small>{{ f.source_name }}</small></div>
          <el-button :disabled="!answerForm.fact_ids.length" :loading="busy" @click="generate">根据证据生成草稿</el-button>
          <el-form-item label="回答正文 · 关键事实后使用 [F编号] 引用"><el-input v-model="answerForm.body" type="textarea" :rows="14" maxlength="80000" placeholder="先直接回答，再说明条件与步骤。字数不计分，事实与相关性优先。"/></el-form-item>
          <el-button type="primary" :disabled="!answerForm.body.trim()" @click="saveAnswer">{{ answerForm.id?'保存并重新进入草稿':'保存回答草稿' }}</el-button>
        </el-form>
        <div v-if="answerForm.id" class="qa-review"><p v-if="dirtyAnswer" class="qa-warning">有未保存的修改。请保存后再提交审核或准备分发。</p><p v-for="p in answerItems.find(a=>a.id===answerForm.id)?.problems||[]" :key="p" class="qa-warning">{{ p }}</p><el-input v-model="reviewNote" placeholder="审核意见，退回时必填" :disabled="!canEdit || busy"/><div class="qa-toolbar"><el-button v-if="['planned','drafting'].includes(answerForm.status)" :disabled="!canEdit || busy" @click="review('submit')">提交已保存版本审核</el-button><template v-if="answerForm.status==='review'"><el-button type="success" :disabled="!canEdit || busy" @click="review('approve')">审核通过</el-button><el-button :disabled="!canEdit || busy || !reviewNote.trim()" @click="review('reject')">退回修改</el-button></template><el-button v-if="['ready','published'].includes(answerForm.status)" type="primary" :disabled="!canEdit || busy" @click="openPlacement">准备分发</el-button></div></div>
      </template>
    </el-drawer>

    <el-dialog :model-value="!!dialog" :title="({import:'录入问题',csv:'批量导入问题',fact:'事实证据',placement:'准备问答分发',receipt:'回填回答网址',metrics:'录入平台数据'})[dialog]" width="min(680px,94vw)" :close-on-click-modal="false" :show-close="!busy" :close-on-press-escape="!busy" @close="dialog=''">
      <el-alert v-if="error" :title="error" type="error" :closable="false"/><el-form label-position="top" :disabled="busy || !canEdit">
        <template v-if="['import','csv'].includes(dialog)"><p>{{ dialog==='csv'?'列名：title,source_url,source_name,topic。最多 200 行，UTF-8 编码。':'每行一个问题，同类重复问题会合并来源。' }}</p><input v-if="dialog==='csv'" type="file" accept=".csv" @change="readCsv"/><el-form-item v-if="dialog==='import'" label="来源类型"><el-select v-model="sourceKind"><el-option v-for="k in ['manual','customer','suggestion']" :key="k" :value="k" :label="kinds[k]"/></el-select></el-form-item><el-form-item v-if="dialog==='import'" label="出处名称"><el-input v-model="sourceName" maxlength="240"/></el-form-item><el-form-item v-if="dialog==='import'" label="来源网址（可选）"><el-input v-model="sourceUrl"/></el-form-item><el-input v-model="importing" type="textarea" :rows="10"/><el-button type="primary" @click="importQuestions">导入问题</el-button></template>
        <template v-if="dialog==='fact'"><el-form-item label="事实标题"><el-input v-model="factForm.title" maxlength="240"/></el-form-item><el-form-item label="事实原文"><el-input v-model="factForm.statement" type="textarea" :rows="6" maxlength="10000"/></el-form-item><el-form-item label="出处名称 / 文档版本"><el-input v-model="factForm.source_name" maxlength="240"/></el-form-item><el-form-item label="来源网址（可选）"><el-input v-model="factForm.source_url"/></el-form-item><el-form-item label="有效期（可选）"><el-date-picker v-model="factForm.expires_at" type="datetime"/></el-form-item><el-form-item label="使用状态"><el-select v-model="factForm.status"><el-option value="active" label="启用"/><el-option value="retired" label="停用"/></el-select></el-form-item><el-button type="primary" @click="saveFact">保存事实</el-button></template>
        <template v-if="dialog==='placement'"><el-form-item label="发布平台"><el-select v-model="placementForm.platform"><el-option v-for="p in platforms" :key="p.key" :value="p.key" :label="p.name"/></el-select></el-form-item><p>{{ platforms.find(p=>p.key===placementForm.platform)?.description }}</p><el-form-item v-if="placementForm.platform!=='website'" label="要回答的问题网址"><el-input v-model="placementForm.question_url"/></el-form-item><el-form-item label="计划发布时间（不会自动代发）"><el-date-picker v-model="placementForm.scheduled_at" type="datetime"/></el-form-item><el-button type="primary" @click="prepare">生成审核稿与发布记录</el-button></template>
        <template v-if="dialog==='receipt'"><p>回填后状态为待核验，不会直接记为发布成功。</p><el-form-item label="回答网址"><el-input v-model="receiptForm.answer_url"/></el-form-item><el-button type="primary" @click="saveReceipt">保存网址</el-button></template>
        <template v-if="dialog==='metrics'"><p>数据标注为人工录入；没有的数据留空。</p><el-form-item v-for="[key,label] in [['views','阅读量'],['likes','赞同数'],['comments','评论数']]" :key="key" :label="label"><el-input-number v-model="metricsForm[key]" :min="0" :precision="0"/></el-form-item><el-form-item label="数据来源网址"><el-input v-model="metricsForm.source_url"/></el-form-item><el-form-item label="观测时间"><el-date-picker v-model="metricsForm.as_of" type="datetime"/></el-form-item><el-button type="primary" @click="saveMetrics">保存观测值</el-button></template>
      </el-form>
    </el-dialog>
  </main>
</template>

<style scoped>
.qa-workbench{padding:28px;max-width:1600px;margin:auto;color:#18334a}.qa-header{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:28px}.qa-eyebrow{font-size:12px;letter-spacing:3px;color:#087f8c;font-weight:700}.qa-header h1{font-size:29px;margin:10px 0}.qa-header p,.qa-hint{color:#6a7d8d;font-size:13px;line-height:1.7}.qa-tabs{display:flex;gap:12px;border-bottom:1px solid #dde5ed;margin:22px 0}.qa-tabs>button,.qa-answer-list button{border:0;background:transparent;padding:13px 16px;color:#5b6e81;cursor:pointer}.qa-tabs>button.active{color:#087f8c;border-bottom:3px solid #087f8c;font-weight:700}.qa-tabs span{margin-left:8px;color:#b97418}.qa-panel{background:#fff;border:1px solid #e0e7ed;border-radius:14px;padding:24px}.qa-panel h2{margin:0;font-size:19px}.qa-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:16px}.qa-toolbar>.el-input{width:230px}.qa-toolbar>.el-select{width:140px}.qa-spacer{flex:1}.qa-source{display:flex;gap:8px;align-items:center;margin-top:9px;font-size:12px;color:#718292}.qa-question-table{cursor:pointer}.el-pagination{margin-top:22px}.qa-capabilities{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}.qa-capabilities>div{background:#f5f9fa;padding:16px;border-radius:9px}.qa-capabilities p{font-size:12px;line-height:1.7;color:#65798c}.qa-placement,.qa-maintenance{border-top:1px solid #e5ebef;padding:22px 0}.qa-placement a,.qa-provenance a{color:#087f8c;font-size:13px;margin-right:12px}.qa-placement pre{white-space:pre-wrap;line-height:1.8;background:#f7fafc;padding:18px}.qa-placement details{font-size:13px;color:#62768a}.qa-provenance{font-size:12px;line-height:2.2;color:#6b7b8a}.qa-metadata{display:grid;grid-template-columns:repeat(3,1fr);gap:0 14px;margin-top:20px}.qa-answer-list{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}.qa-answer-list button{border:1px solid #dae4ed;border-radius:8px}.qa-answer-list button.active{background:#e9f6f5;color:#087f8c}.qa-evidence{padding:12px;background:#f6f9fb;border-left:3px solid #b1d9d9;margin-bottom:12px;font-size:13px}.qa-evidence p{white-space:pre-wrap}.qa-review{border-top:1px solid #e2e8ef;margin-top:24px;padding-top:18px}.qa-review .qa-toolbar{margin-top:12px}.qa-warning{font-size:13px;color:#a96d19}.el-form .el-button{margin:8px 0}.el-form-item .el-select{width:100%}@media(max-width:900px){.qa-workbench{padding:14px}.qa-header{align-items:flex-start}.qa-capabilities{grid-template-columns:repeat(2,1fr)}.qa-tabs{gap:0;overflow:auto}.qa-tabs>button{white-space:nowrap;padding:12px}.qa-panel{padding:16px}.qa-metadata{grid-template-columns:repeat(2,1fr)}}
</style>
