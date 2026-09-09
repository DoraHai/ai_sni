<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getGeoReadAnswer, getGeoReadAnswers, getGeoReadCapabilities,
  getGeoReadContentTask, getGeoReadContentTasks, getGeoReadDemoSummary, getGeoReadQuestions,
} from '../../api/geoReadModel'
import { useGeoTenant } from '../../composables/useGeoTenant'

const route = useRoute()
const router = useRouter()
const { tenantId } = useGeoTenant()
const loading = ref(true)
const error = ref('')
const summary = ref(null)
const questions = ref([])
const answers = ref([])
const tasks = ref([])
const engines = ref([])
const detail = ref(null)
let loadGeneration = 0

const section = computed(() => route.path.includes('/questions') ? 'questions'
  : route.path.includes('/answers') ? 'answers'
    : route.path.includes('/tasks') ? 'tasks' : 'overview')
const detailId = computed(() => Number(route.params.answerId || route.params.taskId) || null)
const current = computed(() => summary.value?.window?.current || {})
const trend = computed(() => summary.value?.trend_7d || {})
const pageTitle = computed(() => ({ overview: 'GEO 演示总览', questions: '问题监测', answers: '回答与引用', tasks: '内容任务' }[section.value]))
const pageDescription = computed(() => ({
  overview: '查看完整周趋势、样本和任务概况。', questions: '固定演示题库；问题不会触发真实采集。',
  answers: '查看回答原文、供应商、模型、品牌提及、引用和正式准入原因。',
  tasks: '查看内容任务、版本和渠道稿关系；不执行生成、审核或发布。',
}[section.value]))
const periodLabel = computed(() => current.value.start && current.value.end
  ? `${current.value.start} 至 ${current.value.end}（Asia/Shanghai）` : '—')

function deltaLabel(item, unit = '') {
  if (!item || item.direction == null) return '历史不足'
  const sign = item.change_abs > 0 ? '+' : ''
  return `较前一周 ${sign}${item.change_abs}${unit}`
}
function refId(row) { return row?.ref?.id }
function openAnswer(row) { router.push(`/geo/demo/answers/${refId(row)}`) }
function openTask(row) { router.push(`/geo/demo/tasks/${refId(row)}`) }
function closeDetail() { router.push(`/geo/demo/${section.value}`) }

async function load() {
  const generation = ++loadGeneration
  const requestedSection = section.value
  const requestedDetailId = detailId.value
  const tenant = tenantId.value
  loading.value = true
  error.value = ''
  detail.value = null
  try {
    const summaryData = await getGeoReadDemoSummary(tenant)
    if (generation !== loadGeneration) return
    const window = summaryData.window?.current || {}
    const [questionData, answerData, taskData, capabilityData] = await Promise.all([
      getGeoReadQuestions(tenant, { limit: 50 }),
      getGeoReadAnswers(tenant, { limit: 50, week_end: window.end,
        captured_from: `${window.start}T00:00:00+08:00`, captured_to: `${window.end}T00:00:00+08:00` }),
      getGeoReadContentTasks(tenant, { limit: 50 }), getGeoReadCapabilities(tenant),
    ])
    if (generation !== loadGeneration) return
    summary.value = summaryData
    questions.value = questionData.items || []
    answers.value = answerData.items || []
    tasks.value = taskData.items || []
    engines.value = capabilityData.engines || []
    if (requestedDetailId && requestedSection === 'answers') {
      const result = await getGeoReadAnswer(tenant, requestedDetailId, { week_end: window.end })
      if (generation !== loadGeneration) return
      detail.value = result.item
    }
    if (requestedDetailId && requestedSection === 'tasks') {
      const result = await getGeoReadContentTask(tenant, requestedDetailId)
      if (generation !== loadGeneration) return
      detail.value = result
    }
  } catch (err) {
    if (generation !== loadGeneration) return
    error.value = err?.message || '演示数据读取失败'
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

onMounted(load)
watch(() => route.fullPath, load)
</script>

<template>
  <div class="demo-page">
    <header class="demo-hero">
      <div><p class="eyebrow">GEO READ-ONLY DEMO</p><h1>{{ pageTitle }}</h1><p>{{ pageDescription }}</p></div>
      <span class="demo-badge">模拟数据 · 不进入正式指标</span>
    </header>
    <div v-if="loading" class="state-card">正在读取演示数据…</div>
    <div v-else-if="error" class="state-card error">{{ error }}</div>
    <template v-else>
      <section class="period-bar"><span>完整周：{{ periodLabel }}</span><span>数据集：{{ summary?.dataset?.version }}</span></section>

      <template v-if="section === 'overview'">
        <section class="metric-grid">
          <article><span>监测问题</span><strong>{{ questions.length }}</strong><small>固定演示题库</small></article>
          <article><span>本周回答样本</span><strong>{{ current.sample_count }}</strong><small>{{ engines.length }} 个演示引擎</small></article>
          <article><span>品牌提及</span><strong>{{ current.mention_count }}</strong><small>{{ deltaLabel(trend.mention_count, ' 次') }}</small></article>
          <article><span>提及率</span><strong>{{ current.mention_rate }}%</strong><small>{{ deltaLabel(trend.mention_rate, ' 个百分点') }}</small></article>
          <article><span>官网引用</span><strong>{{ current.own_domain_citation_count }}</strong><small>{{ deltaLabel(trend.own_domain_citation_count, ' 次') }}</small></article>
        </section>
        <section class="overview-grid">
          <article class="panel"><div class="panel-title"><div><h2>最近回答</h2><p>点击进入原文和准入详情。</p></div><button @click="router.push('/geo/demo/answers')">查看全部</button></div>
            <button v-for="row in answers.slice(0, 6)" :key="refId(row)" class="list-row" @click="openAnswer(row)"><span><b>{{ row.question.current_text }}</b><small>{{ row.engine.provider }} · {{ row.engine.model }}</small></span><em>{{ row.mentions_brand ? '已提及' : '未提及' }}</em></button>
          </article>
          <article class="panel"><div class="panel-title"><div><h2>内容任务</h2><p>固定演示版本与渠道稿。</p></div><button @click="router.push('/geo/demo/tasks')">查看全部</button></div>
            <button v-for="row in tasks" :key="refId(row)" class="list-row" @click="openTask(row)"><span><b>{{ row.title }}</b><small>{{ row.pipeline_step }} · {{ row.review_status }}</small></span><em>#{{ refId(row) }}</em></button>
          </article>
        </section>
      </template>

      <article v-else-if="section === 'questions'" class="panel content-panel">
        <div class="panel-title"><div><h2>演示问题（{{ questions.length }}）</h2><p>问题来源、语言、优先级和监测标签。</p></div></div>
        <div class="table-wrap"><table><thead><tr><th>ID</th><th>问题</th><th>语言</th><th>优先级</th><th>品牌探针</th><th>标签</th></tr></thead><tbody>
          <tr v-for="row in questions" :key="refId(row)"><td>#{{ refId(row) }}</td><td>{{ row.current_text }}</td><td>{{ row.language }}</td><td>{{ row.priority }}</td><td>{{ row.is_brand_probe ? '是' : '否' }}</td><td>{{ row.tags.join('、') || '—' }}</td></tr>
        </tbody></table></div>
      </article>

      <article v-else-if="section === 'answers'" class="panel content-panel">
        <div class="panel-title"><div><h2>本周回答（{{ answers.length }}）</h2><p>每条均标记模拟来源和正式指标排除原因。</p></div></div>
        <div class="table-wrap"><table><thead><tr><th>问题</th><th>平台 / 模型</th><th>回答原文</th><th>品牌</th><th>引用</th><th>时间</th></tr></thead><tbody>
          <tr v-for="row in answers" :key="refId(row)" class="clickable" @click="openAnswer(row)"><td>{{ row.question.current_text }}</td><td>{{ row.engine.provider }}<small>{{ row.engine.model }}</small></td><td class="answer-copy">{{ row.raw_text }}</td><td><span :class="['mention', row.mentions_brand ? 'yes' : 'no']">{{ row.mentions_brand ? '已提及' : '未提及' }}</span></td><td>{{ row.cited_urls.length }} 条</td><td>{{ row.captured_at_local }}</td></tr>
        </tbody></table></div>
      </article>

      <article v-else class="panel content-panel">
        <div class="panel-title"><div><h2>演示内容任务（{{ tasks.length }}）</h2><p>点击查看文章版本与渠道稿关系。</p></div></div>
        <button v-for="row in tasks" :key="refId(row)" class="task-row" @click="openTask(row)"><span><b>{{ row.title }}</b><small>{{ row.pipeline_step }} · {{ row.review_status }}</small></span><span><em>#{{ refId(row) }}</em><small>查看详情 →</small></span></button>
      </article>

      <div v-if="detail" class="detail-mask" @click.self="closeDetail">
        <article class="detail-panel">
          <button class="detail-close" aria-label="关闭详情" @click="closeDetail">×</button>
          <template v-if="section === 'answers'">
            <p class="eyebrow">ANSWER DETAIL · #{{ refId(detail) }}</p><h2>{{ detail.question.current_text }}</h2>
            <dl><dt>供应商 / 模型</dt><dd>{{ detail.engine.provider }} / {{ detail.engine.model }}</dd><dt>回答时间</dt><dd>{{ detail.captured_at_local }}</dd><dt>数据来源</dt><dd>{{ detail.source.kind }} / {{ detail.sample_mode }}</dd><dt>正式指标</dt><dd>不采纳：{{ detail.formal_exclusion_reasons.map(item => item.code).join('、') }}</dd></dl>
            <h3>回答原文</h3><pre>{{ detail.raw_text }}</pre><h3>引用地址</h3><a v-for="url in detail.cited_urls" :key="url" :href="url" target="_blank" rel="noopener noreferrer">{{ url }}</a><p v-if="!detail.cited_urls.length">无引用</p>
          </template>
          <template v-else>
            <p class="eyebrow">CONTENT TASK · #{{ refId(detail) }}</p><h2>{{ detail.title }}</h2><dl><dt>任务状态</dt><dd>{{ detail.stored_status }}</dd><dt>审核状态</dt><dd>{{ detail.review_status }}</dd></dl>
            <h3>文章版本</h3><div v-for="version in detail.versions" :key="refId(version)" class="version-row"><b>V{{ version.version_no }} · {{ version.title }}</b><span>{{ version.source }} · 来源版本 {{ version.from_version ?? '—' }}</span></div>
            <h3>渠道稿</h3><div v-for="variant in detail.variants" :key="refId(variant)" class="version-row"><b>{{ variant.channel }}</b><span>{{ variant.stored_status }} · 不可发布</span></div>
          </template>
          <div class="guard-note"><b>只读保护已开启</b><p>采集、再次检查、生成、发布、OAuth 和定时任务均不会真实执行，也不会写入数据库。</p></div>
        </article>
      </div>
    </template>
  </div>
</template>

<style scoped>
.demo-page{min-height:100%;padding:28px;background:#f6f7fb;color:#202737}.demo-hero{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;padding:26px 28px;border:1px solid #e5def2;border-radius:18px;background:linear-gradient(135deg,#fff 0%,#f7f1ff 100%);box-shadow:0 10px 30px rgba(65,45,94,.06)}.eyebrow{margin:0 0 8px;color:#7c3aed;font-size:11px;font-weight:800;letter-spacing:.12em}h1{margin:0;color:#31233f;font-size:26px}.demo-hero p:last-child{margin:8px 0 0;color:#717785}.demo-badge{flex:none;padding:8px 12px;border:1px solid #f1c978;border-radius:999px;background:#fff9e9;color:#8a5b00;font-size:12px;font-weight:700}
.state-card,.period-bar{margin-top:18px;padding:16px 18px;border:1px solid #e3e6ed;border-radius:12px;background:#fff}.state-card.error{color:#b42318}.period-bar{display:flex;justify-content:space-between;color:#6a7180;font-size:12px}.metric-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin:16px 0}.metric-grid article{display:flex;min-height:112px;flex-direction:column;padding:18px;border:1px solid #e3e6ed;border-radius:14px;background:#fff}.metric-grid span{color:#747b89;font-size:12px}.metric-grid strong{margin:8px 0 5px;color:#30233e;font-size:27px}.metric-grid small{color:#7c3aed}
.overview-grid{display:grid;grid-template-columns:1.35fr 1fr;gap:16px}.panel{min-width:0;padding:20px;border:1px solid #e3e6ed;border-radius:14px;background:#fff}.content-panel{margin-top:16px}.panel-title{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:16px}.panel-title h2{margin:0;font-size:17px}.panel-title p{margin:5px 0 0;color:#7b8290;font-size:12px}.panel-title button{border:0;background:transparent;color:#7c3aed;cursor:pointer}.list-row,.task-row{width:100%;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:13px 4px;border:0;border-top:1px solid #eceef2;background:transparent;text-align:left;cursor:pointer}.list-row span,.task-row span{display:flex;min-width:0;flex-direction:column;gap:5px}.list-row small,.task-row small{color:#858c98}.list-row em,.task-row em{color:#7c3aed;font-style:normal;white-space:nowrap}
.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px}th{padding:10px;background:#f8f7fa;color:#777e8c;text-align:left;white-space:nowrap}td{max-width:260px;padding:12px 10px;border-top:1px solid #eceef2;vertical-align:top}td small{display:block;margin-top:4px;color:#8c93a0}.clickable{cursor:pointer}.clickable:hover{background:#faf8fd}.answer-copy{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mention{display:inline-block;padding:3px 7px;border-radius:999px;white-space:nowrap}.mention.yes{background:#eaf8f0;color:#178354}.mention.no{background:#f1f2f4;color:#747b86}
.detail-mask{position:fixed;inset:0;z-index:100;display:flex;justify-content:flex-end;background:rgba(24,19,32,.38)}.detail-panel{position:relative;width:min(680px,92vw);height:100%;overflow:auto;padding:30px;background:#fff;box-shadow:-16px 0 44px rgba(25,19,34,.2)}.detail-close{position:absolute;top:18px;right:20px;border:0;background:transparent;color:#777;font-size:28px;cursor:pointer}.detail-panel h2{padding-right:34px}.detail-panel dl{display:grid;grid-template-columns:110px 1fr;gap:9px 14px;padding:15px;border-radius:10px;background:#f7f5fa;font-size:13px}.detail-panel dt{color:#7f8692}.detail-panel dd{margin:0}.detail-panel pre{white-space:pre-wrap;font:inherit;line-height:1.7}.detail-panel a{display:block;overflow-wrap:anywhere;margin:6px 0;color:#6f3eb1}.version-row{display:flex;flex-direction:column;gap:5px;padding:11px 0;border-top:1px solid #eceef2}.version-row span{color:#7e8592;font-size:12px}.guard-note{margin-top:18px;padding:14px;border-radius:10px;background:#f4f0fa;color:#5f3d89}.guard-note p{margin:6px 0 0;font-size:12px;line-height:1.65}@media(max-width:1100px){.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.overview-grid{grid-template-columns:1fr}}@media(max-width:680px){.demo-page{padding:16px}.demo-hero,.period-bar{flex-direction:column}.metric-grid{grid-template-columns:1fr}}
</style>
