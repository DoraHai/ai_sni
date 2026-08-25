<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { geoSnapshotLink } from '../../utils/geoRoutes'
import GeoEmptyState from '../../components/GeoEmptyState.vue'
import GeoVisibilityNav from '../../components/GeoVisibilityNav.vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchGeoEvaluationInsights } from '../../api/geoContent'
import { useClientPager } from '../../composables/useClientPager'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import { session } from '../../store/session'
import {
  CITATION_ACCURACY_LABEL,
  CITATION_FORMAT_LABEL,
  POSITION_LABEL,
  REPORT_GLOSSARY,
  SENTIMENT_LABEL,
  countsToRows,
  downloadCsv,
  engineDisplay,
  fmtCaptured,
  fmtInt,
  labelOf,
} from '../../utils/geoReportLabels'
import { getGeoPrototypePageSurface } from '../../utils/geoEditorSurface'

const router = useRouter()
const prototypeSurface = getGeoPrototypePageSurface()
const { days: observationDays, start: obsStart, end: obsEnd, label: obsLabel } = useObservationPeriod()

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const error = ref('')
const data = ref(null)
const dimFilter = ref('all')

const recentItems = computed(() => data.value?.recent || [])
const recentPager = useClientPager(recentItems, { pageSize: 20 })

const distRows = computed(() => {
  if (!data.value) return []
  const all = [
    ...countsToRows(data.value.sentiment_counts, SENTIMENT_LABEL, '情感倾向'),
    ...countsToRows(data.value.position_counts, POSITION_LABEL, '本品位置'),
    ...countsToRows(data.value.format_counts, CITATION_FORMAT_LABEL, '引用格式'),
    ...countsToRows(data.value.accuracy_counts, CITATION_ACCURACY_LABEL, '引用准确性'),
  ]
  if (dimFilter.value === 'all') return all
  return all.filter((r) => r.dim === dimFilter.value)
})

const kpiCards = computed(() => {
  const total = data.value?.total || 0
  const pos = data.value?.position_counts || {}
  const sent = data.value?.sentiment_counts || {}
  return [
    { label: '快照样本', value: fmtInt(total), hint: '评价分析统计基数' },
    {
      label: '首位推荐',
      value: fmtInt(pos.first),
      hint: total ? `约占 ${((pos.first || 0) / total * 100).toFixed(0)}%` : '—',
    },
    {
      label: '备选/次选',
      value: fmtInt(pos.alternative),
      hint: '次优推荐位',
    },
    {
      label: '正面评价',
      value: fmtInt(sent.positive),
      hint: '对本品情感为正',
    },
  ]
})

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchGeoEvaluationInsights(tenantId.value, {
      date_from: obsStart.value,
      date_to: obsEnd.value,
      days: observationDays.value,
    })
    recentPager.resetPage()
  } catch (e) {
    error.value = e.message || '加载失败'
    data.value = null
  } finally {
    loading.value = false
  }
}

function openVisibility(promptId) {
  router.push(geoSnapshotLink(promptId ? { prompt_id: promptId } : {}))
}

function exportRecent() {
  const rows = recentItems.value.map((r) => [
    r.prompt_question || `#${r.prompt_id}`,
    engineDisplay(r.engine),
    labelOf(POSITION_LABEL, r.brand_position),
    labelOf(SENTIMENT_LABEL, r.sentiment),
    labelOf(CITATION_FORMAT_LABEL, r.citation_format),
    labelOf(CITATION_ACCURACY_LABEL, r.citation_accuracy),
    r.captured_at || '',
  ])
  downloadCsv(
    `geo-evaluation-recent-${tenantId.value}.csv`,
    ['意图词', '引擎', '本品位置', '情感', '引用格式', '引用准确性', '观测时间'],
    rows,
  )
  ElMessage.success('已导出最近快照')
}

watch([tenantId, observationDays, obsStart, obsEnd], load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">AI 可见度</div>
        <div class="page-desc">
          登记快照里标过的位置、情感、引用，在这里按观察期汇总。不另采样本。
          跟随顶栏观察期（{{ obsLabel }}）。
        </div>
        <GeoVisibilityNav />
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <details v-if="prototypeSurface.showEvaluationRawMetrics" class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li v-for="(line, i) in REPORT_GLOSSARY.evaluation" :key="i">{{ line }}</li>
      </ul>
    </details>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" show-icon />

    <GeoEmptyState
      v-if="!loading && !error && !data"
      icon="◉"
      title="还没有可分析的快照"
      desc="先在「登记快照」或「全自动巡检」落库，再看这边的位置、情感、引用分布。"
    >
      <template #action>
        <router-link class="el-button el-button--primary" :to="geoSnapshotLink()">去登记</router-link>
        <router-link class="el-button" to="/geo/visibility/patrol">去巡检</router-link>
      </template>
    </GeoEmptyState>

    <div v-if="prototypeSurface.showEvaluationRawMetrics && data" class="geo-kpi-grid">
      <div v-for="c in kpiCards" :key="c.label" class="geo-kpi">
        <div class="kpi-label">{{ c.label }}</div>
        <div class="kpi-value">{{ c.value }}</div>
        <div class="kpi-hint">{{ c.hint }}</div>
      </div>
    </div>

    <div v-if="data" class="geo-split-2">
      <section v-if="prototypeSurface.showEvaluationRawMetrics" class="geo-panel">
        <div class="panel-title-row">
          <div class="panel-title">标注分布</div>
          <el-select v-model="dimFilter" size="small" style="width: 140px">
            <el-option label="全部维度" value="all" />
            <el-option label="情感倾向" value="情感倾向" />
            <el-option label="本品位置" value="本品位置" />
            <el-option label="引用格式" value="引用格式" />
            <el-option label="引用准确性" value="引用准确性" />
          </el-select>
        </div>
        <p class="geo-panel-desc">快照总数 {{ fmtInt(data.total) }}；「未标注/未知」偏高时优先补标。</p>
        <div class="geo-table-shell">
        <el-table :data="distRows" size="small" empty-text="暂无分布">
          <el-table-column prop="dim" label="维度" width="110" />
          <el-table-column prop="value" label="取值" min-width="120" />
          <el-table-column prop="count" label="快照数" width="88" />
        </el-table>
        </div>
      </section>

      <section class="geo-panel">
        <div class="panel-title">待处理信号</div>
        <p class="geo-panel-desc">按意图词查看近期 AI 回答信号，并回到可见度页处理。</p>
        <div class="geo-table-shell">
        <el-table
          :data="recentPager.pagedItems"
          size="small"
          stripe
          empty-text="暂无快照"
        >
          <el-table-column label="意图词" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">
              <button type="button" class="linkish" @click="openVisibility(row.prompt_id)">
                {{ row.prompt_question || `意图词 #${row.prompt_id}` }}
              </button>
            </template>
          </el-table-column>
          <el-table-column label="引擎" width="100">
            <template #default="{ row }">{{ engineDisplay(row.engine) }}</template>
          </el-table-column>
          <el-table-column label="本品位置" width="100">
            <template #default="{ row }">{{ labelOf(POSITION_LABEL, row.brand_position) }}</template>
          </el-table-column>
          <el-table-column label="情感" width="72">
            <template #default="{ row }">{{ labelOf(SENTIMENT_LABEL, row.sentiment) }}</template>
          </el-table-column>
          <el-table-column label="引用格式" width="110">
            <template #default="{ row }">{{ labelOf(CITATION_FORMAT_LABEL, row.citation_format) }}</template>
          </el-table-column>
          <el-table-column label="准确性" width="88">
            <template #default="{ row }">{{ labelOf(CITATION_ACCURACY_LABEL, row.citation_accuracy) }}</template>
          </el-table-column>
          <el-table-column label="观测时间" width="140">
            <template #default="{ row }">{{ fmtCaptured(row.captured_at) }}</template>
          </el-table-column>
        </el-table>
        </div>
        <GeoEmptyState
          v-if="!recentItems.length"
          icon="◌"
          title="还没有可分析的快照"
          desc="先在「AI 可见度」登记或巡检落库，再回来看分布。"
        >
          <template #action>
            <router-link class="el-button el-button--primary" :to="geoSnapshotLink()">去登记</router-link>
          </template>
        </GeoEmptyState>
        <div class="geo-pager">
          <el-pagination
            background
            small
            layout="total, prev, pager, next"
            :total="recentPager.total"
            :page-size="recentPager.pageSize"
            :current-page="recentPager.page"
            @current-change="recentPager.onPageChange"
          />
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 14px; }
.linkish {
  border: 0;
  background: none;
  color: #2563eb;
  cursor: pointer;
  padding: 0;
  text-align: left;
  font: inherit;
}
.linkish:hover { text-decoration: underline; }
</style>
