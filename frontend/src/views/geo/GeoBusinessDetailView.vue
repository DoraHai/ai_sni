<script setup>
/**
 * 优化业务详情一屏：覆盖 / 可见度 / 缺口 / 在产 / 已发 / 效果曲线 + 深化指标
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createTasksFromGaps,
  fetchBusinessDashboard,
  formatGeoError,
  patchGeoBusiness,
} from '../../api/geoContent'
import GeoBusinessProfileForm from '../../components/GeoBusinessProfileForm.vue'
import SampleCredibilityAlert from '../../components/SampleCredibilityAlert.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import { engineDisplay, fmtPct, taskStatusLabel } from '../../utils/geoReportLabels'

const route = useRoute()
const router = useRouter()
const { tenantId } = useGeoTenant()
const { days, label: obsLabel } = useObservationPeriod()

const businessId = computed(() => Number(route.params.businessId))
const loading = ref(false)
const creatingGap = ref(null)
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
const weekActions = computed(() => data.value?.this_week || [])
const profileOpen = ref(false)
const savingProfile = ref(false)
const profileForm = ref({
  product_name: '',
  website: '',
  summary: '',
  honors: '',
  qualifications: '',
  capabilities: '',
  audience: '',
  scenarios: '',
  geo_scope: '',
  industry: '',
  competitors: '',
  recommend_reasons: '',
  banned_claims: '',
  cta: '',
})

function joinList(v) {
  return Array.isArray(v) ? v.join('，') : v || ''
}

function openProfile() {
  const p = biz.value?.profile || {}
  profileForm.value = {
    ...p,
    product_name: p.product_name || '',
    website: p.website || p.website_url || p.official_url || '',
    summary: p.summary || '',
    honors: joinList(p.honors),
    qualifications: joinList(p.qualifications),
    capabilities: joinList(p.capabilities),
    audience: p.audience || '',
    scenarios: joinList(p.scenarios),
    geo_scope: p.geo_scope || '',
    industry: p.industry || '',
    competitors: joinList(p.competitors),
    recommend_reasons: joinList(p.recommend_reasons),
    banned_claims: joinList(p.banned_claims),
    cta: p.cta || '',
  }
  profileOpen.value = true
}

async function saveProfile() {
  if (!tenantId.value || !businessId.value) return
  savingProfile.value = true
  try {
    await patchGeoBusiness(tenantId.value, businessId.value, { profile: profileForm.value })
    ElMessage.success('业务画像已保存')
    profileOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(formatGeoError(e, '保存画像失败'))
  } finally {
    savingProfile.value = false
  }
}

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

async function createFromGap(promptId) {
  if (!tenantId.value || !promptId) return
  creatingGap.value = promptId
  try {
    const res = await createTasksFromGaps(tenantId.value, [promptId])
    const created = res.created || []
    if (created.length === 1) {
      ElMessage.success('已建任务')
      router.push(`/geo/tasks/${created[0].task_id}`)
      return
    }
    const existing = (res.skipped || []).find((s) => s.task_id)
    if (existing?.task_id) {
      ElMessage.info('该缺口已有进行中的任务')
      router.push(`/geo/tasks/${existing.task_id}`)
      return
    }
    await load()
  } catch (e) {
    ElMessage.error(formatGeoError(e, '建任务失败'))
  } finally {
    creatingGap.value = null
  }
}

function goAction(a) {
  if (a?.kind === 'gap_sla' || a?.kind === 'gap') {
    if (a.prompt_id) {
      createFromGap(a.prompt_id)
      return
    }
  }
  if (a?.href) router.push(a.href)
}

watch([tenantId, businessId, days], load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page biz-detail">
    <div class="page-header">
      <div>
        <el-button text type="primary" @click="router.push('/geo/businesses')">← 业务列表</el-button>
        <div class="page-title">{{ biz?.name || `业务 #${businessId}` }}</div>
        <div class="page-desc">
          这条业务现在怎样、本周该做什么。数字跟随顶栏观察期（{{ obsLabel }}）。
        </div>
      </div>
      <div class="header-actions">
        <el-button size="small" @click="load">刷新</el-button>
        <el-button size="small" @click="openProfile">编辑画像</el-button>
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
        <div class="k-hint">品牌没被提到</div>
      </div>
      <div class="kpi">
        <div class="k-label">在产 / 已发</div>
        <div class="k-val">{{ funnel.in_production ?? inProd.length }} / {{ funnel.published ?? published.length }}</div>
        <div class="k-hint">待审 {{ funnel.review_pending ?? 0 }}</div>
      </div>
    </div>

    <SampleCredibilityAlert :composition="sample" :window-label="obsLabel" />

    <section v-if="biz?.profile" class="week-panel mb">
      <div class="panel-title">业务画像（内容生成上下文）</div>
      <div class="week-detail">
        产品 {{ biz.profile.product_name || biz.name }} ·
        客户 {{ biz.profile.audience || '—' }} ·
        行业 {{ biz.profile.industry || '—' }} ·
        CTA {{ biz.profile.cta || '—' }}
      </div>
      <div v-if="biz.profile.summary" class="week-detail">{{ biz.profile.summary }}</div>
    </section>

    <section v-if="weekActions.length" class="week-panel mb">
      <div class="panel-title">本周该做的 {{ weekActions.length }} 件事</div>
      <ol class="week-list">
        <li v-for="(a, i) in weekActions" :key="a.kind + i">
          <div class="week-copy">
            <div class="week-title">{{ a.title }}</div>
            <div class="week-detail">{{ a.detail }}</div>
          </div>
          <el-button
            size="small"
            type="primary"
            :loading="(a.kind === 'gap' || a.kind === 'gap_sla') && creatingGap === a.prompt_id"
            @click="goAction(a)"
          >
            {{ a.kind === 'gap' || a.kind === 'gap_sla' ? '建任务' : '去处理' }}
          </el-button>
        </li>
      </ol>
    </section>

    <details class="detail-fold">
      <summary>覆盖、漏斗与引擎明细</summary>
      <div class="grid">
      <section class="panel">
        <div class="panel-title">意图词覆盖</div>
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
        <div class="panel-title">可见度（本期 vs 上期）</div>
        <p>
          提及 <b>{{ rate(visibility.visibility_mention_rate ?? visibility.rate) }}</b>
          · 样本 {{ visibility.snapshots_visibility ?? visibility.snapshots ?? '—' }}
        </p>
        <p class="muted">
          上期样本 {{ visibility.previous_window?.snapshots_visibility ?? '—' }}
          · 自有域 {{ (visibility.own_domains || citations.own_domains || []).join(', ') || '未配置' }}
        </p>
        <el-button link type="primary" @click="router.push('/geo/visibility')">去可见度</el-button>
        <el-button link type="primary" @click="router.push('/geo/visibility/patrol')">跑巡检</el-button>
      </section>

      <section class="panel">
        <div class="panel-title">缺口清单</div>
        <ul v-if="gaps.length" class="list">
          <li v-for="g in gaps.slice(0, 8)" :key="g.prompt_id" class="gap-row">
            <span class="prio">优先 {{ g.priority }}</span>
            <span class="gap-q">{{ g.question }}</span>
            <el-button
              link
              type="primary"
              :loading="creatingGap === g.prompt_id"
              @click="createFromGap(g.prompt_id)"
            >
              建任务
            </el-button>
          </li>
        </ul>
        <p v-else class="muted">暂无「品牌没被提到」的意图词</p>
        <el-button link type="primary" @click="router.push('/geo/gaps')">批量建任务</el-button>
      </section>

      <section class="panel">
        <div class="panel-title">内容进度</div>
        <p class="muted">任务总数 {{ funnel.total_tasks ?? 0 }}</p>
        <ul v-if="funnel.status_counts" class="list">
          <li v-for="(n, st) in funnel.status_counts" :key="st">{{ taskStatusLabel(st) }} · {{ n }}</li>
        </ul>
        <ul v-if="inProd.length" class="list">
          <li v-for="t in inProd.slice(0, 5)" :key="t.id">
            <router-link :to="`/geo/tasks/${t.id}`">#{{ t.id }} {{ t.title }}</router-link>
            <span class="muted"> · {{ taskStatusLabel(t.status) }}</span>
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
        <div class="panel-title">已发内容与引用域</div>
        <div class="two-col">
          <div>
            <div class="sub-h">发布清单</div>
            <ul v-if="published.length" class="list">
              <li v-for="(p, i) in published.slice(0, 10)" :key="i">
                <router-link :to="`/geo/tasks/${p.task_id}`">
                  {{ p.title || p.channel || ('任务 #' + p.task_id) }}
                </router-link>
                <span class="muted">
                  · {{ p.channel }}
                  · {{ (p.published_at || '').slice(0, 10) }}
                </span>
                <a
                  v-if="p.published_url"
                  :href="p.published_url"
                  target="_blank"
                  rel="noopener"
                  class="muted"
                >原文</a>
              </li>
            </ul>
            <p v-else class="muted">暂无发布回填</p>
            <p class="muted">
              有 {{ citations.snapshots_with_publication_hits ?? 0 }} 条回答点到了已发文章
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
        <div class="panel-title">效果按天</div>
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
          <el-table-column prop="scope_key" label="范围" width="90" />
        </el-table>
        <p v-else class="muted">
          这一期还没有按天的业务数字。先跑巡检或登记快照。
        </p>
        <el-button link type="primary" @click="router.push('/geo/periods')">优化期次</el-button>
        <el-button link type="primary" @click="router.push('/geo/period-diff')">自由对比</el-button>
      </section>
      </div>
    </details>

    <el-dialog v-model="profileOpen" title="编辑业务画像" width="640px">
      <GeoBusinessProfileForm v-model="profileForm" />
      <template #footer>
        <el-button @click="profileOpen = false">取消</el-button>
        <el-button type="primary" :loading="savingProfile" @click="saveProfile">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.biz-detail { padding-bottom: 40px; }
.week-panel {
  background: #fffbeb;
  border: 1px solid #fcd34d;
  border-radius: 10px;
  padding: 14px 16px;
}
.week-list { margin: 0; padding: 0; list-style: none; }
.week-list li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding: 8px 0;
  border-top: 1px solid #fde68a;
}
.week-list li:first-child { border-top: 0; }
.week-title { font-weight: 650; font-size: 13px; }
.week-detail { font-size: 12px; color: #92400e; margin-top: 2px; }
.gap-row { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
.gap-q { flex: 1; min-width: 140px; }
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
.detail-fold {
  margin-top: 8px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 4px 16px 16px;
}
.detail-fold summary {
  cursor: pointer;
  font-weight: 650;
  font-size: 14px;
  color: #334155;
  padding: 12px 0;
  list-style: none;
}
.detail-fold summary::-webkit-details-marker { display: none; }
.detail-fold summary::before { content: '▸ '; color: #64748b; }
.detail-fold[open] summary::before { content: '▾ '; }
.muted { color: #64748b; font-size: 13px; }
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
