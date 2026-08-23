<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  fetchBrandMentionMetric,
  fetchBusinessDashboard,
  fetchGeoCitationInsights,
  fetchGeoCompetitorInsights,
  fetchGeoContentStats,
  fetchGeoEvaluationInsights,
  fetchVisibilityPatrolOpsStatus,
  listGeoAnswerSnapshots,
  listGeoBusinesses,
  listGeoDailyMetrics,
} from '../../api/geoContent'
import { groupSnapshotsByEngine } from '../../utils/geoSnapshotSummary'
import GeoV2Page from '../../components/GeoV2Page.vue'
import SampleCredibilityAlert from '../../components/SampleCredibilityAlert.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import { engineDisplay, fmtPct } from '../../utils/geoReportLabels'

const router = useRouter()
const { tenantId } = useGeoTenant()
const { days, label: obsLabel } = useObservationPeriod()
const loading = ref(false)
const error = ref('')
const stats = ref(null)
const brand = ref(null)
const cites = ref(null)
const comps = ref(null)
const evals = ref(null)
const patrol = ref(null)
const businesses = ref([])
const daily = ref([])
const dashboards = ref([])
const snapshots = ref([])

const score = computed(() => {
  const v = brand.value?.brand_mention_rate ?? stats.value?.visibility_mention_rate
  if (v == null) return null
  return Math.round(Number(v) * 100)
})
const scoreLabel = computed(() => {
  const s = score.value
  if (s == null) return '待测'
  if (s >= 70) return '良好'
  if (s >= 40) return '一般'
  return '待提升'
})
const mentionDelta = computed(() => {
  const rows = daily.value
  if (rows.length < 2) return null
  const a = Number(rows[0].brand_mention_rate)
  const b = Number(rows[rows.length - 1].brand_mention_rate)
  if (Number.isNaN(a) || Number.isNaN(b) || !a) return null
  return Math.round(((b - a) / Math.abs(a)) * 100)
})

const engines = computed(() => {
  const byEng = groupSnapshotsByEngine(snapshots.value)
  if (byEng.length) {
    return byEng.slice(0, 6).map((e) => ({
      name: engineDisplay(e.engine),
      score: e.mentionRate == null ? '—' : Math.round(e.mentionRate * 100),
      stars: e.firstRate >= 0.4 ? '★★★★★' : e.mentionRate >= 0.3 ? '★★★★' : '★★★',
      delta: e.n ? `${e.n} 条` : '',
    }))
  }
  return (patrol.value?.engines || [])
    .filter((e) => e.enabled)
    .map((e) => ({
      name: engineDisplay(e.engine || e.key || e.name),
      score: '—',
      stars: '☆☆☆☆☆',
      delta: '待采样',
    }))
})

const bizBars = computed(() =>
  (dashboards.value || []).slice(0, 6).map((d) => ({
    name: d.business?.name || '业务',
    value: Math.round(Number(d.visibility?.brand_mention_rate ?? d.coverage?.coverage_rate ?? 0) * 100),
  })),
)

const sourceRows = computed(() => {
  const items = cites.value?.items || []
  const total = items.reduce((s, x) => s + Number(x.cite_count || 0), 0) || 1
  return items.slice(0, 5).map((x) => ({
    label: x.blueprint_channel_name || x.domain,
    value: `${Math.round((Number(x.cite_count || 0) / total) * 100)}%`,
  }))
})

const strengths = computed(() => {
  const sc = evals.value?.sentiment_counts || {}
  const pc = evals.value?.position_counts || {}
  const total = Object.values(pc).reduce((a, b) => a + Number(b || 0), 0) || 1
  const sentTotal = Object.values(sc).reduce((a, b) => a + Number(b || 0), 0) || 1
  const rows = []
  if (pc.first) rows.push({ text: '已进入首位推荐', value: `${Math.round((pc.first / total) * 100)}%` })
  if (sc.positive) rows.push({ text: '正向评价信号', value: `${Math.round((sc.positive / sentTotal) * 100)}%` })
  if (cites.value?.own_domain_cite_rate != null) {
    rows.push({ text: '自有域被引用', value: fmtPct(cites.value.own_domain_cite_rate) })
  }
  rows.push({
    text: '已沉淀事实',
    value: String(stats.value?.facts_verified ?? stats.value?.facts ?? '—'),
  })
  return rows.slice(0, 5)
})

const weaknesses = computed(() => {
  const rows = []
  const pc = evals.value?.position_counts || {}
  const total = Object.values(pc).reduce((a, b) => a + Number(b || 0), 0) || 1
  if (pc.absent) rows.push({ text: '回答中品牌缺席', value: `${Math.round((pc.absent / total) * 100)}%` })
  if (stats.value?.prompts_brand_missing)
    rows.push({ text: '高价值提问品牌未被推荐', value: `${stats.value.prompts_brand_missing} 条` })
  const top = (comps.value?.items || [])[0]
  if (top)
    rows.push({
      text: `${top.name} 出现更频繁`,
      value: `${top.mention_count} 次`,
    })
  if (stats.value?.prompts_unclassified)
    rows.push({ text: '提问未挂到业务/关键词', value: `${stats.value.prompts_unclassified} 条` })
  return rows.slice(0, 5)
})

const suggestions = computed(() => {
  const out = []
  if (stats.value?.prompts_brand_missing)
    out.push({
      title: '补齐未推荐提问的直答内容',
      text: '从 AI 提问管理进入缺口，生成可引用 GEO 文章。',
      priority: '高优先级',
      href: '/geo/questions?tag=brand_missing',
    })
  if (stats.value?.facts_verified != null && Number(stats.value.facts_verified) < 6)
    out.push({
      title: '完善知识库案例与 FAQ',
      text: 'AI 更容易引用有场景、结果数据和更新时间的事实。',
      priority: '高优先级',
      href: '/geo/knowledge',
    })
  out.push({
    title: '优化官网结构化信息',
    text: '补 Organization / Product / FAQPage，提升 AI 解析稳定性。',
    priority: '中优先级',
    href: '/geo/geo-diagnosis',
  })
  out.push({
    title: '追踪发布后的引用',
    text: '把本周文章发到可被引用的页面，并回填 URL。',
    priority: '中优先级',
    href: '/geo/tasks',
  })
  return out
})

const tags = computed(() => {
  const names = (businesses.value || []).map((b) => b.name)
  const compsNames = (comps.value?.items || []).slice(0, 3).map((c) => c.name)
  return [...names, ...compsNames].filter(Boolean).slice(0, 10)
})

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [s, bm, ci, co, ev, po, biz, dm, snaps] = await Promise.all([
      fetchGeoContentStats(tenantId.value),
      fetchBrandMentionMetric(tenantId.value, { days: days.value }).catch(() => null),
      fetchGeoCitationInsights(tenantId.value, { days: days.value }).catch(() => null),
      fetchGeoCompetitorInsights(tenantId.value).catch(() => null),
      fetchGeoEvaluationInsights(tenantId.value, { days: days.value }).catch(() => null),
      fetchVisibilityPatrolOpsStatus(tenantId.value).catch(() => null),
      listGeoBusinesses(tenantId.value, { status: 'active' }).catch(() => ({ items: [] })),
      listGeoDailyMetrics(tenantId.value, { scope_level: 'tenant' }).catch(() => ({ items: [] })),
      listGeoAnswerSnapshots(tenantId.value, { limit: 300 }).catch(() => ({ items: [] })),
    ])
    stats.value = s
    brand.value = bm
    cites.value = ci
    comps.value = co
    evals.value = ev
    patrol.value = po
    businesses.value = biz.items || []
    daily.value = dm.items || []
    snapshots.value = snaps.items || snaps.snapshots || []
    const bizList = businesses.value.slice(0, 6)
    dashboards.value = (
      await Promise.all(
        bizList.map((b) =>
          fetchBusinessDashboard(tenantId.value, b.id, days.value).catch(() => ({
            business: { name: b.name },
            visibility: {},
            coverage: {},
          })),
        ),
      )
    ) || []
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

watch(tenantId, load)
watch(days, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <GeoV2Page
      tag="AI 可见性"
      title="AI 品牌画像不是看一次 AI 回答，而是看 AI 长期如何理解你的品牌。"
      desc="基于观察期内多个模型的回答，综合品牌提及、推荐倾向、引用偏好、优势短板和优化方向。"
      :steps="[
        ['整体认知', '了解 AI 对品牌的总体评价与推荐倾向'],
        ['品牌标签', '发现 AI 提及的关键词与品牌定位'],
        ['优势短板', '识别已建立的优势与需补强领域'],
        ['优化方向', '生成可落地的优化建议'],
      ]"
      :hero-tags="['整体表现', '推荐倾向', '引用偏好', '优化方向']"
      hide-answers
    >
      <template #actions>
        <el-button @click="router.push('/geo/answers')">查看各平台详细表现</el-button>
        <el-button type="primary" @click="router.push('/geo/geo-diagnosis')">查看优化建议</el-button>
      </template>

      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />
      <SampleCredibilityAlert
        :composition="brand?.sample_composition || stats?.sample_composition"
        :window-label="`观察期 ${obsLabel}`"
      />

      <section class="brand-portrait-grid">
        <article class="portrait-card">
          <div class="portrait-head">
            <h2>AI 整体评价</h2>
            <span v-if="mentionDelta != null">较观察期初 {{ mentionDelta > 0 ? '+' : '' }}{{ mentionDelta }}%</span>
          </div>
          <div class="score-ring">
            <strong>{{ score ?? '—' }}</strong>
            <span>/100</span>
            <em>{{ scoreLabel }}</em>
          </div>
          <p>
            品牌提及率 {{ fmtPct(brand?.brand_mention_rate ?? stats?.visibility_mention_rate) }}
            · 首位推荐 {{ fmtPct(brand?.top1_rate ?? stats?.visibility_top1_rate) }}。
          </p>
        </article>

        <article class="portrait-card">
          <div class="portrait-head"><h2>AI 平台认知</h2><span>已开启模型</span></div>
          <div v-for="e in engines.slice(0, 5)" :key="e.name" class="portrait-model">
            <b>{{ e.name }}</b>
            <span>{{ e.stars }}</span>
            <strong>{{ e.score }}</strong>
            <em>{{ e.delta }}</em>
          </div>
          <el-empty v-if="!engines.length" description="还没有开启监测模型" :image-size="48" />
          <el-button class="portrait-link" link type="primary" @click="router.push('/geo/models')">
            管理 AI 模型 →
          </el-button>
        </article>

        <article class="portrait-card">
          <div class="portrait-head"><h2>AI 品牌认知标签</h2><span>业务与定位</span></div>
          <div class="tag-cloud">
            <span v-for="t in tags" :key="t">{{ t }}</span>
          </div>
        </article>

        <article class="portrait-card span-6">
          <div class="portrait-head"><h2>AI 最常提到的业务</h2><span>跨业务线</span></div>
          <div v-for="b in bizBars" :key="b.name" class="portrait-bar">
            <b>{{ b.name }}</b>
            <i><u :style="{ width: Math.max(8, b.value) + '%' }" /></i>
            <span>{{ b.value }}%</span>
          </div>
          <el-empty v-if="!bizBars.length" description="先在业务管理里定义业务线" :image-size="48" />
        </article>

        <article class="portrait-card span-6">
          <div class="portrait-head"><h2>AI 引用偏好</h2><span>内容来源</span></div>
          <div v-for="s in sourceRows" :key="s.label" class="portrait-source-row">
            <span>{{ s.label }}</span>
            <b>{{ s.value }}</b>
          </div>
          <el-empty v-if="!sourceRows.length" description="观察期内还没有引用来源" :image-size="48" />
        </article>

        <article class="portrait-card span-6">
          <div class="portrait-head"><h2>AI 认为的品牌优势</h2><span>正向认知</span></div>
          <div v-for="s in strengths" :key="s.text" class="portrait-trait">
            <span>{{ s.text }}</span>
            <b>{{ s.value }}</b>
          </div>
        </article>

        <article class="portrait-card span-6">
          <div class="portrait-head danger"><h2>AI 认为的品牌短板</h2><span>待补强</span></div>
          <div v-for="s in weaknesses" :key="s.text" class="portrait-trait danger">
            <span>{{ s.text }}</span>
            <b>{{ s.value }}</b>
          </div>
        </article>

        <section class="portrait-card full">
          <div class="portrait-head"><h2>AI 优化建议方向</h2><span>可加入任务</span></div>
          <div class="portrait-suggestion-grid">
            <article
              v-for="s in suggestions"
              :key="s.title"
              class="portrait-suggestion"
              role="button"
              @click="router.push(s.href)"
            >
              <b>{{ s.title }}</b>
              <p>{{ s.text }}</p>
              <span>{{ s.priority }}</span>
            </article>
          </div>
        </section>
      </section>
    </GeoV2Page>
  </div>
</template>
