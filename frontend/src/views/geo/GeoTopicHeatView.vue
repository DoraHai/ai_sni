<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchGeoTopicHeat } from '../../api/geoContent'
import { useClientPager } from '../../composables/useClientPager'
import { useGeoTenant } from '../../composables/useGeoTenant'
import {
  HEAT_LABEL,
  REPORT_GLOSSARY,
  downloadCsv,
  engineDisplay,
  fmtDeltaPct,
  fmtInt,
  labelOf,
} from '../../utils/geoReportLabels'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const days = ref(14)
const groupBy = ref('prompt')
const heatFilter = ref('all')
const items = ref([])
const timeline = ref([])
const dayTotals = ref([])
const dayTotalsRaw = ref([])
const summary = ref(null)
const period = ref(null)
const metric = ref(null)

const filteredItems = computed(() => {
  if (heatFilter.value === 'all') return items.value
  return items.value.filter((i) => i.heat === heatFilter.value)
})
const pager = useClientPager(filteredItems, { pageSize: 20 })

const maxBar = computed(() => Math.max(1, ...dayTotals.value, 1))
const maxBarRaw = computed(() => Math.max(1, ...dayTotalsRaw.value, 1))

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    items.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await fetchGeoTopicHeat(tenantId.value, {
      days: days.value,
      group_by: groupBy.value,
    })
    items.value = data.items || []
    timeline.value = data.timeline || []
    dayTotals.value = data.day_totals || []
    dayTotalsRaw.value = data.day_totals_raw || []
    summary.value = data.summary || null
    period.value = data.period || null
    metric.value = data.metric || null
    pager.resetPage()
  } catch (e) {
    error.value = e.message || '加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

function heatType(h) {
  if (h === 'rising') return 'danger'
  if (h === 'falling') return 'info'
  return 'success'
}

function exportCsv() {
  const rows = filteredItems.value.map((r) => [
    r.label,
    r.question_group || '',
    r.recent_count,
    r.earlier_count,
    r.delta_pct,
    labelOf(HEAT_LABEL, r.heat),
    r.coverage_count,
    r.brand_mentions,
    r.snapshot_count,
    r.patrol_snapshot_count,
    r.manual_snapshot_count,
    (r.engines || []).map(engineDisplay).join(' / '),
  ])
  downloadCsv(
    `geo-topic-heat-${tenantId.value}.csv`,
    [
      '话题',
      '问题组',
      '近期覆盖',
      '前期覆盖',
      '变化%',
      '热度',
      '覆盖格',
      '品牌覆盖格',
      '监测条数',
      '巡检条数',
      '人工条数',
      '引擎',
    ],
    rows,
  )
  ElMessage.success('已导出')
}

watch([tenantId, days, groupBy], () => {
  pager.resetPage()
  load()
})
watch(heatFilter, () => pager.resetPage())
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">话题覆盖热度</div>
        <div class="page-desc">
          {{ metric?.heat_label || '按意图词×引擎×日去重后的覆盖变化' }}。
          用于发现近期测得多 / 动得猛的意图词，不是市场搜索热度。
        </div>
      </div>
      <div class="header-actions">
        <el-select v-model="groupBy" style="width: 140px">
          <el-option label="按意图词" value="prompt" />
          <el-option label="按问题组" value="group" />
        </el-select>
        <el-select v-model="days" style="width: 120px">
          <el-option :value="7" label="近 7 天" />
          <el-option :value="14" label="近 14 天" />
          <el-option :value="30" label="近 30 天" />
        </el-select>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button :disabled="!filteredItems.length" @click="exportCsv">导出 CSV</el-button>
        <router-link class="el-button" to="/geo/ai-trends">AI 动态</router-link>
        <router-link class="el-button" to="/geo/prompts">意图词</router-link>
      </div>
    </div>

    <details class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li v-for="(line, i) in REPORT_GLOSSARY.topicHeat" :key="i">{{ line }}</li>
        <li v-if="metric?.activity_label">{{ metric.activity_label }}</li>
      </ul>
    </details>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <div v-if="summary" class="geo-kpi-grid">
      <div class="geo-kpi">
        <div class="kpi-label">话题数</div>
        <div class="kpi-value">{{ fmtInt(summary.topic_count) }}</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">覆盖上升</div>
        <div class="kpi-value">{{ fmtInt(summary.rising) }}</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">覆盖格数</div>
        <div class="kpi-value">{{ fmtInt(summary.coverage_total) }}</div>
        <div class="kpi-hint">意图词×引擎×日</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">监测活跃度</div>
        <div class="kpi-value">{{ fmtInt(summary.snapshot_total) }}</div>
        <div class="kpi-hint">
          巡检 {{ fmtInt(summary.patrol_snapshot_total) }} · 人工 {{ fmtInt(summary.manual_snapshot_total) }}
          <template v-if="period"> · {{ period.from }} ~ {{ period.to }}</template>
        </div>
      </div>
    </div>

    <section v-if="timeline.length" class="geo-panel">
      <div class="panel-title">每日覆盖格（去重后）</div>
      <p class="geo-panel-desc">越高表示当天覆盖了更多「话题×引擎」组合。</p>
      <div class="spark-row">
        <div
          v-for="(n, i) in dayTotals"
          :key="`c-${timeline[i]}`"
          class="spark-col"
          :title="`${timeline[i]}: 覆盖 ${n}`"
        >
          <i :style="{ height: `${Math.round((n / maxBar) * 64)}px` }" />
          <span>{{ timeline[i]?.slice(5) }}</span>
        </div>
      </div>
    </section>

    <section v-if="timeline.length && dayTotalsRaw.length" class="geo-panel">
      <div class="panel-title">每日监测条数（原始快照）</div>
      <p class="geo-panel-desc">含巡检重复；与上方覆盖热度对照，避免把“测得多”当成“话题热”。</p>
      <div class="spark-row">
        <div
          v-for="(n, i) in dayTotalsRaw"
          :key="`r-${timeline[i]}`"
          class="spark-col raw"
          :title="`${timeline[i]}: 快照 ${n}`"
        >
          <i :style="{ height: `${Math.round((n / maxBarRaw) * 64)}px` }" />
          <span>{{ timeline[i]?.slice(5) }}</span>
        </div>
      </div>
    </section>

    <section class="geo-panel">
      <div class="panel-title-row">
        <div class="panel-title">话题排行</div>
        <el-select v-model="heatFilter" size="small" style="width: 130px">
          <el-option label="全部热度" value="all" />
          <el-option label="覆盖上升" value="rising" />
          <el-option label="覆盖回落" value="falling" />
          <el-option label="覆盖平稳" value="stable" />
        </el-select>
      </div>
      <el-table
        :data="pager.pagedItems"
        size="small"
        stripe
        empty-text="暂无数据"
      >
        <el-table-column label="话题" min-width="200">
          <template #default="{ row }">
            <div class="title">{{ row.label }}</div>
            <div class="muted" v-if="row.question_group && groupBy === 'prompt'">
              问题组 · {{ row.question_group }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="近期覆盖" width="92" prop="recent_count" />
        <el-table-column label="前期覆盖" width="92" prop="earlier_count" />
        <el-table-column label="变化" width="92">
          <template #default="{ row }">
            <span :class="row.delta_pct > 0 ? 'geo-delta-up' : row.delta_pct < 0 ? 'geo-delta-down' : ''">
              {{ fmtDeltaPct(row.delta_pct) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="热度" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="heatType(row.heat)">{{ labelOf(HEAT_LABEL, row.heat) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="覆盖格" width="80" prop="coverage_count" />
        <el-table-column label="品牌覆盖" width="88" prop="brand_mentions" />
        <el-table-column label="监测（巡/人）" width="130">
          <template #default="{ row }">
            {{ row.snapshot_count || 0 }}
            <span class="muted">（{{ row.patrol_snapshot_count || 0 }}/{{ row.manual_snapshot_count || 0 }}）</span>
          </template>
        </el-table-column>
        <el-table-column label="引擎" min-width="120">
          <template #default="{ row }">
            {{ (row.engines || []).map(engineDisplay).join(' · ') || '—' }}
          </template>
        </el-table-column>
      </el-table>
      <div v-if="!items.length" class="geo-empty" style="margin-top: 12px">
        <div class="empty-title">暂无覆盖数据</div>
        <div>请先跑巡检或登记可见度快照，再刷新本页。</div>
        <div class="empty-actions">
          <router-link class="el-button el-button--primary" to="/geo/visibility/patrol">去巡检</router-link>
          <router-link class="el-button" to="/geo/visibility">登记快照</router-link>
        </div>
      </div>
      <div class="geo-pager">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="pager.total"
          :page-size="pager.pageSize"
          :current-page="pager.page"
          :page-sizes="[10, 20, 50]"
          @current-change="pager.onPageChange"
          @size-change="pager.onSizeChange"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 16px; }
.title { font-weight: 600; font-size: 13px; }
.muted { font-size: 12px; color: #94a3b8; }
.spark-row {
  display: flex; align-items: flex-end; gap: 4px; min-height: 88px; overflow-x: auto; padding-top: 8px;
}
.spark-col {
  flex: 1; min-width: 28px; display: flex; flex-direction: column; align-items: center; gap: 4px;
}
.spark-col i {
  display: block; width: 100%; max-width: 18px; background: #3b82f6; border-radius: 3px 3px 0 0; min-height: 2px;
}
.spark-col.raw i { background: #94a3b8; }
.spark-col span { font-size: 10px; color: #94a3b8; }
</style>
