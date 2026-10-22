<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import GeoAdvisorProjectPicker from './GeoAdvisorProjectPicker.vue'
import { useGeoTenant } from '../composables/useGeoTenant'
import { session } from '../store/session'
import client from '../api/client'

const props = defineProps({ mode: { type: String, default: 'all' }, taskId: Number })
const { tenantId } = useGeoTenant()
const projectId = ref(null)
const weekEnd = ref('')
const businessId = ref('')
const unitId = ref('')
const query = ref('')
const status = ref('all')
const summary = ref(null)
const basis = ref(null)
const questions = ref([])
const articles = ref([])
const recommendations = ref([])
const options = ref({ businesses: [], units: [] })
const coverage = ref(null)
const questionPage = ref(null)
const articlePage = ref(null)
const recommendationPage = ref(null)
const error = ref('')
const busy = ref(false)
const downloading = ref(false)
const answer = ref(null)
let generation = 0
let detailGeneration = 0
const six = ['豆包', 'DeepSeek', '千问', '元宝', '文心', 'Kimi']
const states = { observed: '已检测', small_sample: '小样本', not_tested: '未检测', not_configured: '未配置',
  failed: '失败', no_publications: '暂无发布文章', insufficient_evidence: '引用证据不足' }
const show = section => props.mode === 'all' || props.mode === section
const units = computed(() => options.value.units.filter(u => !businessId.value || u.business_id === Number(businessId.value)))
const visibleArticles = computed(() => props.taskId ? articles.value.filter(a => a.task_id === props.taskId) : articles.value)
const metricDefs = [
  ['brand_mention_rate', '品牌提及率', '%'], ['brand_mention_answer_count', '品牌提及回答数', ''],
  ['average_recommendation_position', '平均推荐位置（首选=1、备选=2、顺带=3）', ''],
  ['brand_positive_rate', '品牌正向评价率', '%'],
]
const fmt = (v, suffix = '') => v == null ? '暂无' : `${Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}${suffix}`
const time = value => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '暂无'
const resource = (name, params = {}) => client.get(`/api/v1/geo/projects/${projectId.value}/client/${name}`, {
  params: { tenant_id: tenantId.value, ...(name !== 'recommendations' && weekEnd.value ? { week_end: weekEnd.value } : {}), ...params },
})
const questionParams = () => ({ limit: 20, status: status.value,
  ...(businessId.value ? { business_id: businessId.value } : {}), ...(unitId.value ? { unit_id: unitId.value } : {}),
  ...(query.value.trim() ? { q: query.value.trim() } : {}),
})
function clear() {
  ++generation
  ++detailGeneration
  summary.value = basis.value = coverage.value = null
  questions.value = []; articles.value = []; recommendations.value = []
  questionPage.value = articlePage.value = recommendationPage.value = null
  options.value = { businesses: [], units: [] }
  answer.value = null; error.value = ''; busy.value = downloading.value = false
}
async function load() {
  clear()
  if (!tenantId.value || !projectId.value) return
  const current = generation
  busy.value = true
  const jobs = []
  if (show('summary')) jobs.push(resource('summary').then(r => {
    if (current === generation) { summary.value = r.data; basis.value = r.basis }
  }))
  if (show('questions')) jobs.push(resource('questions', questionParams()).then(r => {
    if (current === generation) { questions.value = r.data.items; questionPage.value = r.data.pagination; options.value = r.data.options }
  }))
  if (show('articles')) jobs.push(resource('article-citations', { limit: 20 }).then(r => {
    if (current === generation) { articles.value = r.data.items; articlePage.value = r.data.pagination; coverage.value = r.data.coverage }
  }))
  if (show('recommendations')) jobs.push(resource('recommendations', { limit: 20 }).then(r => {
    if (current === generation) { recommendations.value = r.data.items; recommendationPage.value = r.data.pagination }
  }))
  const results = await Promise.allSettled(jobs)
  if (current !== generation) return
  const failed = results.find(r => r.status === 'rejected')
  if (failed) { clear(); error.value = failed.reason.message || '项目数据读取失败，请刷新' }
  busy.value = false
}
async function more(kind) {
  const config = { questions: [questionPage, questions, questionParams()],
    'article-citations': [articlePage, articles, { limit: 20 }], recommendations: [recommendationPage, recommendations, { limit: 20 }] }[kind]
  const [page, rows, params] = config
  if (!page.value?.next_cursor || busy.value) return
  const current = generation
  busy.value = true
  try {
    const r = await resource(kind, { ...params, cursor: page.value.next_cursor })
    if (current === generation) { rows.value.push(...r.data.items); page.value = r.data.pagination }
  } catch (e) { if (current === generation) { clear(); error.value = e.message || '分页读取失败，请刷新' } }
  finally { if (current === generation) busy.value = false }
}
async function evidence(item) {
  const current = generation, detail = ++detailGeneration
  answer.value = null
  try {
    const r = await resource(`answers/${item.answer_id}`)
    if (current === generation && detail === detailGeneration) answer.value = r.data
  } catch (e) { if (current === generation && detail === detailGeneration) error.value = e.message || '回答证据读取失败' }
}
async function download(format) {
  if (!tenantId.value || !projectId.value || downloading.value) return
  const current = generation, project = projectId.value
  downloading.value = true
  error.value = ''
  try {
    const blob = await client.get(`/api/v1/geo/projects/${project}/client/reports/export.${format}`, {
      params: { tenant_id: tenantId.value, ...(weekEnd.value ? { week_end: weekEnd.value } : {}) },
      responseType: 'blob', timeout: 120000,
    })
    if (current !== generation) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = `GEO-项目${project}-${weekEnd.value || '最近完整周'}.${format}`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) { if (current === generation) error.value = e.message || '下载失败' }
  finally { if (current === generation) downloading.value = false }
}
watch([tenantId, () => session.token], () => {
  clear(); projectId.value = null; businessId.value = unitId.value = query.value = ''; status.value = 'all'
}, { flush: 'sync' })
watch([projectId, weekEnd], () => { businessId.value = unitId.value = ''; load() }, { flush: 'sync' })
onUnmounted(clear)
</script>

<template>
  <section class="project-evidence" aria-label="项目交付数据">
    <header><h2>{{ mode === 'questions' ? '全部问题' : mode === 'articles' ? '已发布文章引用' : '项目交付数据' }}</h2>
      <p>上海时区已结束完整周 · 仅使用已有合格回答</p></header>
    <div class="controls">
      <GeoAdvisorProjectPicker v-model="projectId" :tenant-id="tenantId" />
      <label>周期结束日（周一）<input v-model="weekEnd" type="date" aria-label="周期结束日（周一）"></label>
      <button type="button" :disabled="!projectId || busy" @click="load">刷新</button>
      <template v-if="mode === 'all'"><button :disabled="!projectId || downloading" @click="download('pdf')">下载 PDF</button><button :disabled="!projectId || downloading" @click="download('xlsx')">下载 Excel</button></template>
    </div>
    <p v-if="!projectId">请选择项目；留空周期使用最近已结束的完整周。</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="busy" role="status">正在读取项目数据…</p>
    <template v-if="projectId">
      <template v-if="summary">
        <p>{{ summary.period.start.slice(0, 10) }} 至 {{ summary.period.end.slice(0, 10) }}（右端不含） · 合格 {{ summary.qualified_counts.samples }} 条 / {{ summary.qualified_counts.questions }} 题 / {{ summary.qualified_counts.engines }} 个引擎</p>
        <p v-if="summary.sample_status !== 'ready'" class="notice">样本不足：正式汇总至少需要 8 条回答、3 题、2 个引擎。</p>
        <div class="metrics"><article v-for="[key, title, suffix] in metricDefs" :key="key"><span>{{ title }}</span><strong>{{ fmt(summary.metrics[key], suffix) }}</strong></article></div>
        <p>有效位置 {{ summary.metrics.valid_position_count }} 条；首选 {{ summary.metrics.position_distribution.first }} / 备选 {{ summary.metrics.position_distribution.alternative }} / 顺带 {{ summary.metrics.position_distribution.mentioned }}。情感已标注 {{ summary.metrics.annotated_mention_count }} / 提及 {{ summary.metrics.mention_count }} 条。</p>
        <details><summary>查看分平台汇总</summary><div class="table-scroll"><table><thead><tr><th>平台</th><th v-for="[,title] in metricDefs" :key="title">{{ title }}</th></tr></thead><tbody><tr v-for="r in summary.by_engine" :key="r.engine_key"><th>{{ r.label }}</th><td v-for="[key,,suffix] in metricDefs" :key="key">{{ fmt(r.metrics[key], suffix) }}</td></tr></tbody></table></div></details>
        <p v-if="basis">证据最新时间：{{ time(basis.last_data_at) }}。<span v-for="r in basis.exclusion_counts" :key="r.code">已排除 {{ r.count }} 条（{{ r.code }}）；</span></p>
      </template>
      <section v-if="show('questions')">
        <h3>全部问题 · 国内六家提及率</h3>
        <form class="controls" @submit.prevent="load">
          <label>业务<select v-model="businessId" @change="unitId = ''"><option value="">全部业务</option><option v-for="b in options.businesses" :key="b.id" :value="b.id">{{ b.name }}</option></select></label>
          <label>关键词<select v-model="unitId"><option value="">全部关键词</option><option v-for="u in units" :key="u.id" :value="u.id">{{ u.display_name }}</option></select></label>
          <label>问题文字<input v-model="query" maxlength="100" placeholder="搜索全部问题"></label>
          <label>状态<select v-model="status"><option value="all">全部</option><option value="active">监控中</option><option value="inactive">未启用</option><option value="archived">已归档</option></select></label>
          <button :disabled="busy">筛选</button>
        </form>
        <p>每格 X/Y 为提及回答数/合格回答数；少于 3 条标为小样本，百分比不代表稳定覆盖率。</p>
        <div class="table-scroll"><table><thead><tr><th>业务 / 关键词</th><th>问题</th><th v-for="label in six" :key="label">{{ label }}</th></tr></thead><tbody>
          <tr v-for="q in questions" :key="q.id"><td>{{ q.business.name }}<br>{{ q.unit.display_name }}</td><th>{{ q.question }}</th><td v-for="c in q.by_engine" :key="c.engine_key"><template v-if="c.total != null"><b>{{ c.mentioned }}/{{ c.total }} · {{ fmt(c.percentage, '%') }}</b><small>{{ time(c.last_sample_at) }}</small><small v-if="c.small_sample" class="notice">小样本</small></template><span v-else>{{ states[c.status] || '暂无' }}</span></td></tr>
          <tr v-if="!questions.length"><td colspan="8">暂无符合筛选条件的问题</td></tr>
        </tbody></table></div>
        <p>已读取 {{ questions.length }} / {{ questionPage?.total_count ?? '暂无' }} 题 <button v-if="questionPage?.has_more" :disabled="busy" @click="more('questions')">加载更多问题</button></p>
      </section>
      <section v-if="show('articles')">
        <h3>已发布文章被引覆盖率</h3><p v-if="coverage">{{ coverage.cited_articles ?? '暂无' }}/{{ coverage.published_articles }}（H/U） · {{ fmt(coverage.percentage, '%') }} · {{ states[coverage.status] }}</p>
        <p>只计发布后保存的合格回答精准引用；无可解析引用证据时显示证据不足。{{ taskId ? '下表展示当前文章任务，覆盖率为整个项目。' : '' }}</p>
        <div v-for="a in visibleArticles" :key="a.id" class="article"><h4>{{ a.title }}</h4><a :href="a.url" target="_blank" rel="noopener noreferrer">{{ a.url }}</a>
          <p>发布：{{ time(a.published_at) }} · {{ a.mentioned ?? '暂无' }}/{{ a.total ?? '暂无' }} · {{ fmt(a.percentage, '%') }} · {{ states[a.status] }}</p>
          <details><summary>依据回答（{{ a.evidence.length }}）</summary><ul><li v-for="e in a.evidence" :key="e.answer_id"><button @click="evidence(e)">回答 #{{ e.answer_id }}</button> {{ time(e.captured_at) }} · {{ e.engine_key }}</li></ul></details>
        </div>
        <p v-if="!visibleArticles.length">暂无发布文章引用记录</p><button v-if="articlePage?.has_more" :disabled="busy" @click="more('article-citations')">加载更多文章</button>
      </section>
      <section v-if="show('recommendations')"><h3>站内 GEO 优化建议</h3><article v-for="r in recommendations" :key="r.id" class="article"><h4>{{ r.title }}</h4><p>{{ r.next_action }} · 检查时间 {{ time(r.checked_at) }}</p><ul><li v-for="(item,i) in r.recommendations" :key="i">{{ item.title }}：{{ item.description || '暂无说明' }} · {{ item.priority || '暂无优先级' }} · {{ item.status }}</li></ul></article><p v-if="!recommendations.length">暂无已审核的项目建议。结构扫描未确认项目归属，暂无。</p><button v-if="recommendationPage?.has_more" :disabled="busy" @click="more('recommendations')">加载更多建议</button></section>
      <aside v-if="answer" class="answer"><button @click="answer = null; ++detailGeneration">关闭证据</button><h3>回答依据 #{{ answer.item.id }}</h3><p>{{ time(answer.item.captured_at) }} · {{ answer.item.engine.key }}</p><pre>{{ answer.raw_text }}</pre></aside>
    </template>
    <footer>元宝数据取自腾讯混元模型接口。各平台为模型 API 的已保存回答观测。数据不足显示暂无。</footer>
  </section>
</template>

<style scoped>
.project-evidence{margin:16px 0;padding:24px;border:1px solid #dbe4ed;border-radius:14px;background:#fff;color:#203348}.project-evidence h2{margin:0;font-size:22px}.project-evidence h3{margin-top:26px}.controls{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:18px 0}label{display:grid;gap:6px;font-size:13px}input,select,button{font:inherit;padding:8px 12px;border:1px solid #c5d4e2;border-radius:6px;background:#fff}button{cursor:pointer;color:#245e94}button:disabled{cursor:default;opacity:.5}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.metrics article{padding:18px;background:#f4f8fc;border-radius:10px}.metrics span{display:block;font-size:13px;min-height:40px}.metrics strong{display:block;font-size:30px;margin-top:10px}.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:12px;border:1px solid #dbe4ed;text-align:left;min-width:140px;vertical-align:top}th{background:#f4f8fc}small{display:block;font-size:11px;color:#627386;margin-top:6px}.notice{color:#946017}.error{color:#ae3434}.article{padding:16px 0;border-bottom:1px solid #dbe4ed}.article a{overflow-wrap:anywhere}.answer{padding:20px;background:#f4f8fc}pre{white-space:pre-wrap;overflow-wrap:anywhere}footer{margin-top:22px;font-size:12px;color:#627386}@media(max-width:800px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.project-evidence{padding:16px}}
</style>
