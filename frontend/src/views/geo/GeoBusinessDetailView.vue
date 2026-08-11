<script setup>
/**
 * 优化业务详情一屏：覆盖 / 可见度 / 缺口 / 在产 / 已发 / 效果曲线 + 深化指标
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  fetchBusinessDashboard,
  formatGeoError,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { engineDisplay, fmtPct } from '../../utils/geoReportLabels'

const route = useRoute()
const router = useRouter()
const { tenantId } = useGeoTenant()

const businessId = computed(() => Number(route.params.businessId))
const loading = ref(false)
const days = ref(14)
const data = ref(null)
const error = ref('')

const biz = computed(() => data.value?.business)
const coverage = computed(() => data.value?.coverage || {})
const visibility = computed(() => data.value?.visibility || {})
const sample = computed(() => data.value?.sample_composition || {})
const gaps = computed(() => data.value?.gaps || [])
const inProd = computed(() => data.value?.in_production || [])
const published = computed(() => data.value?.published || [])
const series = computed(() => data.value?.effect_series || [])
const byEngine = computed(() => data.value?.by_engine || [])
const citations = computed(() => data.value?.citations || {})
const competitors = computed(() => data.value?.competitors || {})
const funnel = computed(() => data.value?.content_funnel || {})
const delta = computed(() => visibility.value?.delta_vs_previous || {})

function rate(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return fmtPct(v)
}

function deltaText(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v) * 100
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}pp`
}

function deltaType(v) {
  if (v == null) return 'info'
  if (v > 0.001) return 'success'
  if (v < -0.001) return 'danger'
  return 'info'
}

async function load() {
  if (!tenantId.value || !businessId.value) return
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchBusinessDashboard(tenantId.value, businessId.value, days.value)
  } catch (e) {
    error.value = formatGeoError(e, '加载业务详情失败')
    data.value = null
  } finally {
    loading.value = false
  }
}

watch([tenantId, businessId, days], load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="biz-detail">
    <div class="page-head">
      <div>
        <el-button text type="primary" @click="router.push('/geo/businesses')">← 业务列表</el-button>
        <h1 class="page-title">{{ biz?.name || `业务 #${businessId}` }}</h1>
        <p class="page-desc">
          主轴一屏：意图覆盖 → 可见度（含环比）→ 缺口 → 在产 → 已发 → 效果曲线 · 引擎/引用/竞品
        </p>
      </div>
      <div class="head-actions">
        <el-select v-model="days" style="width: 110px" size="small">
          <el-option :value="7" label="近 7 天" />
          <el-option :value="14" label="近 14 天" />
          <el-option :value="30" label="近 30 天" />
        </el-select>
        <el-button size="small" @click="load">刷新</el-button>
        <el-button size="small" type="primary" @click="router.push('/geo/gaps')">缺口工作台</el-button>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <div class="kpi-row">
      <div class="kpi">
        <div class="k-label">意图词</div>
        <div class="k-val">{{ coverage.prompt_count ?? 0 }}</div>
        <div class="k-hint">覆盖率 {{ rate(coverage.coverage_rate) }}</div>
      </div>
      <div class="kpi">
        <div class="k-label">品牌提及率</div>
        <div class="k-val">{{ rate(visibility.visibility_mention_rate ?? visibility.rate) }}</div>
        <div class="k-hint">
          环比
          <el-tag size="small" :type="deltaType(delta.visibility_mention_rate)">
            {{ deltaText(delta.visibility_mention_rate) }}
          </el-tag>
        </div>
      </div>
      <div class="kpi">
        <div class="k-label">首位推荐</div>
        <div class="k-val">{{ rate(visibility.visibility_top1_rate) }}</div>
        <div class="k-hint">Δ {{ deltaText(delta.visibility_top1_rate) }}</div>
      </div>
      <div class="kpi">
        <div class="k-label">自有域引用</div>
        <div class="k-val">{{ rate(visibility.own_domain_cite_rate) }}</div>
        <div class="k-hint">Δ {{ deltaText(delta.own_domain_cite_rate) }}</div>
      </div>
      <div class="kpi">
        <div class="k-label">点名认知</div>
        <div class="k-val">{{ rate(visibility.probe_recognition_rate) }}</div>
        <div class="k-hint">Δ {{ deltaText(delta.probe_recognition_rate) }}</div>
      </div>
      <div class="kpi warn">
        <div class="k-label">缺口</div>
        <div class="k-val">{{ coverage.gap_count ?? 0 }}</div>
        <div class="k-hint">brand_missing</div>
      </div>
      <div class="kpi">
        <div class="k-label">在产 / 已发</div>
        <div class="k-val">{{ funnel.in_production ?? inProd.length }} / {{ funnel.published ?? published.length }}</div>
        <div class="k-hint">待审 {{ funnel.review_pending ?? 0 }}</div>
      </div>
    </div>

    <el-alert
      v-if="sample.has_simulated"
      type="warning"
      show-icon
      class="mb"
      :title="`样本含模拟：真 ${sample.real || 0} · 模拟 ${sample.simulated || 0} · 人工 ${sample.manual || 0}`"
    />

    <div class="grid">
      <section class="panel">
        <div class="panel-title">1 · 意图词覆盖</div>
        <p class="muted">
          单元 {{ coverage.unit_count ?? (data?.units?.length || 0) }} · 覆盖
          {{ coverage.covered_count ?? 0 }} / {{ coverage.prompt_count ?? 0 }}
        </p>
        <ul v-if="coverage.by_unit?.length" class="list">
          <li v-for="u in coverage.by_unit" :key="u.unit_id">
            {{ u.unit_name }} · 意图 {{ u.prompt_count }} · 缺口 {{ u.gap_count }}
          </li>
        </ul>
        <el-button link type="primary" @click="router.push('/geo/prompts')">管理意图词</el-button>
      </section>

      <section class="panel">
        <div class="panel-title">2 · 可见度（当前窗 vs 前窗）</div>
        <p>
          提及 <b>{{ rate(visibility.visibility_mention_rate ?? visibility.rate) }}</b>
          · 样本 n={{ visibility.snapshots_visibility ?? visibility.snapshots ?? '—' }}
        </p>
        <p class="muted">
          前窗 n={{ visibility.previous_window?.snapshots_visibility ?? '—' }}
          · 自有域 {{ (visibility.own_domains || citations.own_domains || []).join(', ') || '未配置' }}
        </p>
        <el-button link type="primary" @click="router.push('/geo/visibility')">去可见度</el-button>
        <el-button link type="primary" @click="router.push('/geo/visibility/patrol')">跑巡检</el-button>
      </section>

      <section class="panel">
        <div class="panel-title">3 · 缺口清单</div>
        <ul v-if="gaps.length" class="list">
          <li v-for="g in gaps.slice(0, 8)" :key="g.prompt_id">
            <span class="prio">P{{ g.priority }}</span> {{ g.question }}
          </li>
        </ul>
        <p v-else class="muted">暂无 brand_missing</p>
        <el-button link type="primary" @click="router.push('/geo/gaps')">批量建任务</el-button>
      </section>

      <section class="panel">
        <div class="panel-title">4 · 内容漏斗</div>
        <p class="muted">任务总数 {{ funnel.total_tasks ?? 0 }}</p>
        <ul v-if="funnel.status_counts" class="list">
          <li v-for="(n, st) in funnel.status_counts" :key="st">{{ st }} · {{ n }}</li>
        </ul>
        <ul v-if="inProd.length" class="list">
          <li v-for="t in inProd.slice(0, 5)" :key="t.id">
            <router-link :to="`/geo/tasks/${t.id}`">#{{ t.id }} {{ t.title }}</router-link>
            <span class="muted"> · {{ t.status }}</span>
          </li>
        </ul>
        <el-button link type="primary" @click="router.push('/geo/tasks')">全部文章</el-button>
      </section>

      <section class="panel">
        <div class="panel-title">引擎切片</div>
        <el-table v-if="byEngine.length" :data="byEngine" size="small" max-height="220">
          <el-table-column label="引擎" min-width="100">
            <template #default="{ row }">{{ engineDisplay(row.engine) || row.engine }}</template>
          </el-table-column>
          <el-table-column prop="snapshots" label="样本" width="64" />
          <el-table-column label="提及率" width="80">
            <template #default="{ row }">{{ rate(row.mention_rate) }}</template>
          </el-table-column>
          <el-table-column prop="simulated" label="模拟" width="56" />
        </el-table>
        <p v-else class="muted">暂无引擎样本</p>
      </section>

      <section class="panel">
        <div class="panel-title">竞品提及</div>
        <ul v-if="competitors.top?.length" class="list">
          <li v-for="c in competitors.top.slice(0, 8)" :key="c.name">
            {{ c.name }} · {{ c.mentions }}
          </li>
        </ul>
        <p v-else class="muted">近窗无竞品标签</p>
        <el-button link type="primary" @click="router.push('/geo/competitors')">竞品监测</el-button>
      </section>

      <section class="panel wide">
        <div class="panel-title">5 · 已发内容 &amp; 引用域</div>
        <div class="two-col">
          <div>
            <div class="sub-h">发布清单</div>
            <ul v-if="published.length" class="list">
              <li v-for="(p, i) in published.slice(0, 10)" :key="i">
                <a :href="p.published_url" target="_blank" rel="noopener">{{ p.channel }}</a>
                · 任务 #{{ p.task_id }} · {{ (p.published_at || '').slice(0, 10) }}
              </li>
            </ul>
            <p v-else class="muted">暂无发布回填</p>
            <p class="muted">
              快照命中已发 publication：{{ citations.snapshots_with_publication_hits ?? 0 }}
            </p>
          </div>
          <div>
            <div class="sub-h">被引域名 Top</div>
            <ul v-if="citations.top_domains?.length" class="list">
              <li v-for="d in citations.top_domains.slice(0, 10)" :key="d.domain">
                {{ d.domain }} · {{ d.cite_count }}
                <el-tag v-if="d.is_own" size="small" type="success">自有</el-tag>
              </li>
            </ul>
            <p v-else class="muted">暂无引用域名</p>
            <el-button link type="primary" @click="router.push('/geo/citations')">引用分析</el-button>
          </div>
        </div>
      </section>

      <section class="panel wide">
        <div class="panel-title">6 · 效果曲线</div>
        <el-table v-if="series.length" :data="series" size="small" max-height="280">
          <el-table-column prop="date" label="日期" width="110" />
          <el-table-column label="提及率" width="90">
            <template #default="{ row }">{{ rate(row.brand_mention_rate) }}</template>
          </el-table-column>
          <el-table-column label="首位" width="80">
            <template #default="{ row }">{{ rate(row.top1_rate) }}</template>
          </el-table-column>
          <el-table-column label="点名认知" width="90">
            <template #default="{ row }">{{ rate(row.probe_recognition_rate) }}</template>
          </el-table-column>
          <el-table-column prop="citation_count" label="引用次数" width="80" />
          <el-table-column prop="top_competitor" label="Top竞品" min-width="100" />
          <el-table-column prop="scope_key" label="scope" width="90" />
        </el-table>
        <p v-else class="muted">
          暂无业务 scope 日指标；可能回退租户级或为空。可在业务页触发日指标重建。
        </p>
        <el-button link type="primary" @click="router.push('/geo/periods')">优化期次</el-button>
        <el-button link type="primary" @click="router.push('/geo/period-diff')">自由对比</el-button>
      </section>
    </div>
  </div>
</template>

<style scoped>
.biz-detail { padding: 4px 2px 40px; }
.page-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.page-title { margin: 4px 0 6px; font-size: 20px; font-weight: 700; }
.page-desc { margin: 0; font-size: 13px; color: #64748b; }
.head-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.kpi-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.kpi {
  min-width: 118px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px;
}
.kpi.warn { border-color: #fdba74; background: #fff7ed; }
.k-label { font-size: 12px; color: #64748b; }
.k-val { font-size: 20px; font-weight: 700; }
.k-hint { font-size: 11px; color: #94a3b8; margin-top: 2px; display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.panel {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
}
.panel.wide { grid-column: 1 / -1; }
.panel-title { font-weight: 700; margin-bottom: 8px; font-size: 14px; }
.sub-h { font-size: 12px; font-weight: 650; color: #475569; margin-bottom: 6px; }
.list { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.55; }
.prio { color: #b45309; font-size: 11px; margin-right: 4px; }
.muted { color: #94a3b8; font-size: 12px; }
.mb { margin-bottom: 12px; }
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 900px) {
  .grid, .two-col { grid-template-columns: 1fr; }
  .panel.wide { grid-column: auto; }
}
</style>
