<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchGeoEvaluationInsights,
  fetchVisibilityPatrolOpsStatus,
  getVisibilityPatrolRun,
  listGeoAnswerSnapshots,
  listGeoBusinesses,
  listGeoDailyMetrics,
  startVisibilityPatrolRun,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import GeoVisibilityNav from '../../components/GeoVisibilityNav.vue'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { geoSnapshotLink } from '../../utils/geoRoutes'
import {
  POSITION_LABEL,
  SENTIMENT_LABEL,
  engineDisplay,
  engineKeyOf,
  engineLabelOf,
  fmtCaptured,
  fmtPct,
  labelOf,
} from '../../utils/geoReportLabels'
import {
  groupSnapshotsByEngine,
  groupSnapshotsByPrompt,
  highlightParts,
  mentionManner,
  pctDelta,
  sentimentShare,
  visibilityScore,
} from '../../utils/geoSnapshotSummary'

const route = useRoute()
const router = useRouter()
const { tenantId, session } = useGeoTenant()
const {
  days: observationDays,
  start: obsStart,
  end: obsEnd,
  label: obsLabel,
  allowedDays: observationAllowedDays,
  setDays: setObservationDays,
} = useObservationPeriod()

const ENGINE_COLORS = {
  deepseek: '#4d6bfe',
  doubao: '#ff6a00',
  kimi: '#111827',
  qwen: '#615ced',
  tongyi: '#615ced',
  yuanbao: '#0ea5e9',
  hunyuan: '#0ea5e9',
  chatgpt: '#10a37f',
  claude: '#d97706',
  gemini: '#4285f4',
  perplexity: '#1d4ed8',
  wenxin: '#2932e1',
}
function engineColor(key) {
  const k = String(key || '').toLowerCase()
  for (const [id, c] of Object.entries(ENGINE_COLORS)) {
    if (k.includes(id)) return c
  }
  return '#7c3aed'
}

const loading = ref(false)
const refreshing = ref(false)
const error = ref('')
const helpOpen = ref(false)
const snapshots = ref([])
const evaluation = ref(null)
const patrol = ref(null)
const businesses = ref([])
const engineDaily = ref([])

const tenantName = computed(() => {
  const hit = (session.tenants || []).find((t) => t.id === tenantId.value)
  return hit?.name || (tenantId.value ? `客户 #${tenantId.value}` : '未选择客户')
})

const brandNames = computed(() => {
  const names = []
  if (tenantName.value && !/^客户 #/.test(tenantName.value)) names.push(tenantName.value)
  for (const b of businesses.value) {
    if (b?.name) names.push(b.name)
    const p = b?.profile || {}
    if (p.product_name) names.push(p.product_name)
  }
  return [...new Set(names.map((n) => String(n).trim()).filter(Boolean))]
})

const dashEngines = computed(() => {
  const fromPatrol = (patrol.value?.engines || [])
    .filter((e) => e.enabled !== false && e.enabled !== 0)
    .map((e) => {
      const key = engineKeyOf(e)
      if (!key) return null
      return { key, name: engineLabelOf(e), color: engineColor(key) }
    })
    .filter(Boolean)
  if (fromPatrol.length) return fromPatrol
  return groupSnapshotsByEngine(snapshots.value).map((g) => ({
    key: g.engine,
    name: engineDisplay(g.engine),
    color: engineColor(g.engine),
  }))
})

const engineCards = computed(() => {
  const grouped = groupSnapshotsByEngine(snapshots.value)
  const byKey = new Map(grouped.map((g) => [String(g.engine || '').toLowerCase(), g]))
  const base = dashEngines.value.length
    ? dashEngines.value
    : grouped.map((g) => ({
        key: g.engine,
        name: engineDisplay(g.engine),
        color: engineColor(g.engine),
      }))
  return base.slice(0, 5).map((e) => {
    const key = String(e.key || '').toLowerCase()
    const g =
      byKey.get(key) ||
      grouped.find((x) => String(x.engine).toLowerCase().includes(key))
    const rows = engineDaily.value
      .filter((r) => {
        const sk = String(r.scope_key || '')
        const eng = String(r.engine || sk.split('@')[1] || '').toLowerCase()
        return sk.startsWith('t@') && eng === key
      })
      .sort((a, b) => String(a.metric_date).localeCompare(String(b.metric_date)))
    const latestRate = rows.length
      ? rows[rows.length - 1].brand_mention_rate
      : null
    const score = g?.visScore ?? g?.mentionRate ?? latestRate ?? null
    let delta = null
    if (rows.length >= 2) {
      delta = pctDelta(
        rows[rows.length - 1].brand_mention_rate,
        rows[0].brand_mention_rate,
      )
    }
    return { ...e, score, delta, n: g?.n || rows.length || 0 }
  })
})

const sent = computed(() => {
  const fromSnaps = sentimentShare(snapshots.value)
  if (fromSnaps.n) return fromSnaps
  const sc = evaluation.value?.sentiment_counts || {}
  const total =
    Number(sc.positive || 0) + Number(sc.neutral || 0) + Number(sc.negative || 0)
  if (!total) return { n: 0, positive: null, neutral: null, negative: null }
  return {
    n: total,
    positive: Number(sc.positive || 0) / total,
    neutral: Number(sc.neutral || 0) / total,
    negative: Number(sc.negative || 0) / total,
  }
})

const ringOffset = computed(() => {
  const p = sent.value.positive
  if (p == null) return 314
  return 314 * (1 - p)
})

const pendingSignals = computed(() => (evaluation.value?.recent || []).slice(0, 8))

const manner = computed(() => mentionManner(snapshots.value))

const mentionInsight = computed(() => {
  const groups = groupSnapshotsByPrompt(snapshots.value)
  const rows = [...groups.entries()]
    .map(([id, sum]) => {
      const q = snapshots.value.find((s) => s.prompt_id === id)?.prompt_question || ''
      return { q, firstRate: sum.firstRate, n: sum.n }
    })
    .filter((r) => r.n >= 2 && r.q)
  if (rows.length < 2) return ''
  rows.sort((a, b) => (b.firstRate || 0) - (a.firstRate || 0))
  const best = rows[0]
  const worst = rows[rows.length - 1]
  const clip = (s) => (s.length > 18 ? `${s.slice(0, 18)}…` : s)
  return `在「${clip(best.q)}」中 ${Math.round((best.firstRate || 0) * 100)}% 被列为首选；「${clip(worst.q)}」仅 ${Math.round((worst.firstRate || 0) * 100)}%，建议加强该方向内容。`
})

const sample = computed(() => {
  const qid = route.query.prompt_id ? Number(route.query.prompt_id) : null
  const rows = snapshots.value.filter((s) => s.raw_text)
  if (qid) {
    const hit = rows.find((s) => s.prompt_id === qid)
    if (hit) return hit
  }
  return rows.find((s) => s.mentions_brand) || rows[0] || null
})

const sampleParts = computed(() =>
  highlightParts(sample.value?.raw_text || '', brandNames.value),
)

const sampleCite = computed(() => {
  const urls = sample.value?.cited_urls || []
  if (!urls.length) return ''
  try {
    const u = new URL(urls[0])
    return u.hostname + u.pathname
  } catch {
    return String(urls[0]).slice(0, 48)
  }
})

function rankLabel(pos) {
  if (pos === 'first') return '本品牌 · 顺位 1'
  if (pos === 'alternative') return '本品牌 · 备选'
  if (pos === 'mentioned') return '本品牌 · 顺带提及'
  if (sample.value?.mentions_brand) return '本品牌 · 已提及'
  return '本品牌未出现'
}

const overallScore = computed(() => visibilityScore(snapshots.value))
const promptFocusId = computed(() =>
  route.query.prompt_id ? Number(route.query.prompt_id) : null,
)
const promptFocusRows = computed(() => {
  if (!promptFocusId.value) return []
  return snapshots.value
    .filter((s) => s.prompt_id === promptFocusId.value)
    .map((s) => {
      let badge = '未提及'
      let tone = 'red'
      if (s.mentions_brand) {
        badge = '已提及'
        tone = 'green'
      } else if ((s.competitors || []).length) {
        badge = '竞品提及'
        tone = 'amber'
      }
      let rank = '—'
      if (s.brand_position === 'first') rank = '1'
      else if (s.brand_position === 'alternative') rank = '2'
      else if (s.brand_position === 'mentioned') rank = '3'
      return {
        engine: engineDisplay(s.engine),
        badge,
        tone,
        rank,
        at: s.captured_at,
        question: s.prompt_question || `提问 #${s.prompt_id}`,
      }
    })
})

function deltaText(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return `${n < 0 ? '▼' : '▲'} ${Math.abs(n).toFixed(1)}%`
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [sn, ev, po, biz, ed] = await Promise.all([
      listGeoAnswerSnapshots(tenantId.value).catch(() => ({ items: [] })),
      fetchGeoEvaluationInsights(tenantId.value, {
        date_from: obsStart.value,
        date_to: obsEnd.value,
        days: observationDays.value,
      }).catch(() => null),
      fetchVisibilityPatrolOpsStatus(tenantId.value).catch(() => null),
      listGeoBusinesses(tenantId.value, { status: 'active' }).catch(() => ({ items: [] })),
      listGeoDailyMetrics(tenantId.value, {
        date_from: obsStart.value,
        date_to: obsEnd.value,
        include_engines: true,
      }).catch(() => ({ items: [] })),
    ])
    const items = sn.items || sn.snapshots || []
    const lo = Date.parse(`${obsStart.value}T00:00:00`)
    const hi = Date.parse(`${obsEnd.value}T23:59:59`)
    snapshots.value = items.filter((s) => {
      const t = Date.parse(s.captured_at || '')
      if (!Number.isFinite(t) || !Number.isFinite(lo) || !Number.isFinite(hi)) return true
      return t >= lo && t <= hi
    })
    evaluation.value = ev
    patrol.value = po
    businesses.value = biz.items || []
    engineDaily.value = ed.items || []
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function refreshDetect() {
  if (!tenantId.value) return
  refreshing.value = true
  try {
    const res = await startVisibilityPatrolRun({
      tenant_id: tenantId.value,
      auto_persist: true,
      prefer_real: true,
      run_async: true,
    })
    const id = res.run?.id
    ElMessage.success(id ? `巡检 #${id} 进行中…` : '巡检已启动')
    if (id) {
      for (let i = 0; i < 24; i += 1) {
        await new Promise((r) => setTimeout(r, 2500))
        const run = await getVisibilityPatrolRun(tenantId.value, id).catch(() => null)
        const st = String(run?.status || run?.run?.status || '').toLowerCase()
        if (['succeeded', 'success', 'done', 'completed', 'failed', 'error', 'cancelled'].includes(st)) {
          break
        }
      }
    }
    await load()
    ElMessage.success('检测结果已更新')
  } catch (e) {
    ElMessage.error(e.message || '启动失败')
  } finally {
    refreshing.value = false
  }
}

watch(tenantId, load)
watch([observationDays, obsStart, obsEnd], load)
onMounted(() => {
  if (route.query.domain) {
    router.replace({ path: '/geo/visibility/snapshots', query: { ...route.query } })
    return
  }
  load()
})
</script>

<template>
  <GeoWorkbenchPage
    title="AI 可见度"
    :sub="`你的品牌在各 AI 引擎中的曝光表现 · ${tenantName} · ${obsLabel}`"
    :loading="loading"
  >
    <template #actions>
      <button type="button" class="gd-help" @click="helpOpen = true">ⓘ 可见度得分怎么算</button>
      <button class="gd-btn" @click="router.push('/geo/models')">引擎设置</button>
      <button class="gd-btn primary" :disabled="refreshing" @click="refreshDetect">
        {{ refreshing ? '启动中…' : '🔄 刷新检测' }}
      </button>
    </template>
  <div class="geo-dash">
    <GeoVisibilityNav />

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />

    <div v-if="pendingSignals.length" class="gd-card" style="margin-bottom:16px">
      <div class="gd-hd">
        <h3>待处理信号</h3>
        <a class="more" @click="router.push(geoSnapshotLink())">去采集与判断</a>
      </div>
      <div class="gd-bd" style="padding:0">
        <table>
          <thead>
            <tr>
              <th>意图词</th>
              <th>引擎</th>
              <th>本品位置</th>
              <th>情感</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in pendingSignals" :key="row.id || i">
              <td>
                <button
                  type="button"
                  class="linkish"
                  @click="router.push(geoSnapshotLink({ prompt_id: row.prompt_id }))"
                >
                  {{ row.prompt_question || `意图词 #${row.prompt_id}` }}
                </button>
              </td>
              <td>{{ engineDisplay(row.engine) }}</td>
              <td>{{ labelOf(POSITION_LABEL, row.brand_position) }}</td>
              <td>{{ labelOf(SENTIMENT_LABEL, row.sentiment) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="promptFocusRows.length" class="gd-card" style="margin-bottom:16px">
      <div class="gd-hd">
        <h3>该提问各引擎表现</h3>
        <span class="more">{{ promptFocusRows[0]?.question }}</span>
      </div>
      <div class="gd-bd" style="padding:0">
        <table>
          <thead><tr><th>引擎</th><th>是否提及</th><th>顺位</th><th>检测时间</th></tr></thead>
          <tbody>
            <tr v-for="(r, i) in promptFocusRows" :key="i">
              <td>{{ r.engine }}</td>
              <td><span class="gd-badge" :class="r.tone">{{ r.badge }}</span></td>
              <td>{{ r.rank }}</td>
              <td>{{ fmtCaptured(r.at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="gd-engine-kpis">
      <div v-for="e in engineCards" :key="e.key" class="gd-card gd-stat">
        <div class="label"><i class="gd-dot" :style="{ background: e.color }" /> {{ e.name }}</div>
        <div class="value">{{ fmtPct(e.score) }}</div>
        <div class="delta" :class="e.delta == null ? 'hint' : e.delta < 0 ? 'down' : 'up'">
          {{ deltaText(e.delta) }}
        </div>
      </div>
      <div v-if="!engineCards.length" class="gd-card gd-stat">
        <div class="label">监测引擎</div>
        <div class="value">—</div>
        <div class="delta hint">先到「AI 引擎管理」开启引擎</div>
      </div>
    </div>

    <div class="gd-vis-mid">
      <div class="gd-card">
        <div class="gd-hd"><h3>情感倾向</h3></div>
        <div class="gd-bd gd-sent">
          <svg class="gd-ring" viewBox="0 0 120 120" width="120" height="120">
            <circle cx="60" cy="60" r="50" fill="none" stroke="#eef0f5" stroke-width="12" />
            <circle
              cx="60"
              cy="60"
              r="50"
              fill="none"
              stroke="#16a34a"
              stroke-width="12"
              stroke-linecap="round"
              stroke-dasharray="314"
              :stroke-dashoffset="ringOffset"
              transform="rotate(-90 60 60)"
            />
            <text x="60" y="58" text-anchor="middle" font-size="24" font-weight="700" fill="#1e2330">
              {{ sent.positive == null ? '—' : Math.round(sent.positive * 100) + '%' }}
            </text>
            <text x="60" y="78" text-anchor="middle" font-size="11" fill="#6b7280">正面</text>
          </svg>
          <div class="gd-sent-list">
            <div class="gd-sent-row"><span class="gd-badge green">正面</span><b>{{ fmtPct(sent.positive) }}</b></div>
            <div class="gd-sent-row"><span class="gd-badge">中性</span><b>{{ fmtPct(sent.neutral) }}</b></div>
            <div class="gd-sent-row"><span class="gd-badge red">负面</span><b>{{ fmtPct(sent.negative) }}</b></div>
          </div>
        </div>
      </div>
      <div class="gd-card">
        <div class="gd-hd">
          <h3>品牌被提及的方式</h3>
          <span class="more">{{ obsLabel }}</span>
        </div>
        <div class="gd-bd">
          <div v-if="manner.n" class="gd-mention-types">
            <div>
              <div class="gd-sub" style="margin:0">作为首选推荐</div>
              <div class="value">{{ fmtPct(manner.first) }}</div>
              <div class="gd-bar green"><span :style="{ width: manner.first * 100 + '%' }" /></div>
            </div>
            <div>
              <div class="gd-sub" style="margin:0">作为备选之一</div>
              <div class="value">{{ fmtPct(manner.alternative) }}</div>
              <div class="gd-bar"><span :style="{ width: manner.alternative * 100 + '%' }" /></div>
            </div>
            <div>
              <div class="gd-sub" style="margin:0">仅顺带提及</div>
              <div class="value">{{ fmtPct(manner.mentioned) }}</div>
              <div class="gd-bar amber"><span :style="{ width: manner.mentioned * 100 + '%' }" /></div>
            </div>
          </div>
          <div v-else class="gd-sub">观察期内还没有带提及标注的快照。</div>
          <p v-if="mentionInsight" class="gd-insight">💡 {{ mentionInsight }}</p>
        </div>
      </div>
    </div>

    <div class="gd-card">
      <div class="gd-hd">
        <h3>AI 回答示例 · 实时抓取</h3>
        <span v-if="sample" class="more">{{ engineDisplay(sample.engine) }} · 「{{ sample.prompt_question || '提问' }}」</span>
      </div>
      <div class="gd-bd">
        <div v-if="sample" class="gd-sample">
          <template v-for="(part, i) in sampleParts" :key="i">
            <mark v-if="part.hit">{{ part.text }}</mark>
            <template v-else>{{ part.text }}</template>
          </template>
        </div>
        <div v-else class="gd-sub">暂无带正文的回答快照。点「刷新检测」跑一轮巡检。</div>
        <div v-if="sample" class="gd-sample-meta">
          <span v-if="sampleCite" class="gd-badge blue">引用来源：{{ sampleCite }}</span>
          <span class="gd-badge green">{{ rankLabel(sample.brand_position) }}</span>
          <span
            v-for="(c, i) in (sample.competitors || []).slice(0, 3)"
            :key="c + i"
            class="gd-badge"
          >竞品 · {{ c }}</span>
          <span v-if="sample.sentiment && sample.sentiment !== 'unknown'" class="gd-badge">情感：{{ sample.sentiment === 'positive' ? '正面' : sample.sentiment === 'negative' ? '负面' : '中性' }}</span>
          <span class="gd-badge">检测时间：{{ fmtCaptured(sample.captured_at) }}</span>
        </div>
      </div>
    </div>

    <div v-if="helpOpen" class="gd-modal-mask" @click.self="helpOpen = false">
      <div class="gd-modal">
        <div class="gd-modal-hd">
          <h3>AI 可见度得分怎么算</h3>
          <button type="button" class="gd-modal-x" @click="helpOpen = false">×</button>
        </div>
        <div class="gd-modal-bd">
          <p class="gd-sub" style="margin:0 0 16px">
            可见度得分 = 在监控提问集里，AI 主动提及/推荐你品牌的<b>加权占比</b>。分越高，代表越多用户向 AI 提问时会看见你。
          </p>
          <div class="gd-flow">
            <div class="gd-step"><span class="n">1</span><b>取监控提问集</b></div>
            <span class="gd-arrow">→</span>
            <div class="gd-step"><span class="n">2</span><b>问各引擎多轮</b></div>
            <span class="gd-arrow">→</span>
            <div class="gd-step"><span class="n">3</span><b>统计提及与位次</b></div>
            <span class="gd-arrow">→</span>
            <div class="gd-step"><span class="n">4</span><b>加权汇总得分</b></div>
          </div>
          <table>
            <thead><tr><th>构成因子</th><th>说明</th></tr></thead>
            <tbody>
              <tr><td>提及率</td><td>回答中出现你品牌的提问占比</td></tr>
              <tr><td>推荐顺位</td><td>第 1 位权重 1.0 · 备选 0.6 · 顺带提及 0.3</td></tr>
              <tr><td>引擎覆盖</td><td>上方按引擎分别展示，总分为该引擎样本的加权平均</td></tr>
            </tbody>
          </table>
          <p class="gd-sub" style="margin:14px 0 0">
            单引擎得分即该引擎下的加权占比。巡检设置见「引擎」。当前页得分 {{ fmtPct(overallScore) }}。
          </p>
        </div>
      </div>
    </div>
  </div>
  </GeoWorkbenchPage>
</template>
