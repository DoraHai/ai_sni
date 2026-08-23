<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { backfillAttribution, fetchGeoCitationInsights, formatGeoError } from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useClientPager } from '../../composables/useClientPager'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import { session } from '../../store/session'
import {
  CITATION_ACCURACY_LABEL,
  CITATION_FORMAT_LABEL,
  REPORT_GLOSSARY,
  countsToRows,
  downloadCsv,
  engineDisplay,
  fmtInt,
  fmtPct,
} from '../../utils/geoReportLabels'
import { citationHeatFromItems, heatTone } from '../../utils/geoSnapshotSummary'

const router = useRouter()
const { days: observationDays, start: obsStart, end: obsEnd, label: obsLabel } = useObservationPeriod()
const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const backfilling = ref(false)
const error = ref('')
const data = ref(null)
const ownOnly = ref(false)
const domainQuery = ref('')

const citeItems = computed(() => {
  let rows = data.value?.items || []
  if (ownOnly.value) rows = rows.filter((r) => r.is_own_domain)
  const q = domainQuery.value.trim().toLowerCase()
  if (q) rows = rows.filter((r) => String(r.domain || '').toLowerCase().includes(q))
  return rows
})
const pager = useClientPager(citeItems, { pageSize: 20 })
const heatMap = computed(() => citationHeatFromItems(data.value?.items || []))

const qualityRows = computed(() => {
  if (!data.value) return []
  return [
    ...countsToRows(data.value.format_counts, CITATION_FORMAT_LABEL, '引用格式'),
    ...countsToRows(data.value.accuracy_counts, CITATION_ACCURACY_LABEL, '引用准确性'),
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
    data.value = await fetchGeoCitationInsights(tenantId.value, {
      date_from: obsStart.value,
      date_to: obsEnd.value,
      days: observationDays.value,
    })
    pager.resetPage()
  } catch (e) {
    error.value = e.message || '加载失败'
    data.value = null
  } finally {
    loading.value = false
  }
}

function exportCsv() {
  const rows = citeItems.value.map((r) => [
    r.domain,
    r.cite_count,
    (r.engines || []).map(engineDisplay).join(' / '),
    r.blueprint_channel_name || r.blueprint_channel_key || '',
    r.is_own_domain ? '是' : '否',
    r.prompt_count ?? '',
    r.latest_captured_at || '',
  ])
  downloadCsv(
    `geo-citations-${tenantId.value}.csv`,
    ['域名', '引用次数', '引擎', '蓝图渠道', '自有域', '关联意图词数', '最近观测'],
    rows,
  )
  ElMessage.success('已导出当前筛选结果')
}

async function runBackfill() {
  if (!tenantId.value) return
  backfilling.value = true
  try {
    const res = await backfillAttribution(tenantId.value, { limit: 1000, onlyEmpty: true })
    ElMessage.success(
      `归因回填完成：扫描 ${res.scanned || 0} · 更新 ${res.updated || 0} · 命中 ${res.matched_hits || 0}`,
    )
    await load()
  } catch (e) {
    ElMessage.error(formatGeoError(e, '回填失败'))
  } finally {
    backfilling.value = false
  }
}

/** 域名行 → 可见度快照（用域名作提示；引擎若唯一则带上） */
function openDomain(row) {
  if (!row) return
  const q = { domain: row.domain }
  if ((row.engines || []).length === 1) q.engine = row.engines[0]
  router.push({ path: '/geo/visibility/snapshots', query: q })
}

watch([tenantId, observationDays, obsStart, obsEnd], load)
watch([ownOnly, domainQuery], () => pager.resetPage())
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="信源分析"
    :sub="`AI 回答时到底从哪些平台、哪些文章取数引用 · ${obsLabel}`"
    :loading="loading"
  >
    <template #actions>
      <input v-model="domainQuery" class="gd-search" placeholder="搜索信源 / 文章…" />
      <button class="gd-btn" :disabled="!citeItems.length" @click="exportCsv">数据导出</button>
      <button class="gd-btn primary" :disabled="backfilling" @click="runBackfill">回填归因</button>
    </template>
    <div class="geo-dash geo-page">

    <details class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li v-for="(line, i) in REPORT_GLOSSARY.citations" :key="i">{{ line }}</li>
      </ul>
    </details>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" show-icon />

    <div v-if="heatMap.engines.length" class="gd-card" style="margin-bottom:16px">
      <div class="gd-hd">
        <h3>信源平台 × AI 引擎 引用占比</h3>
        <span class="more">颜色越深引用越多</span>
      </div>
      <div class="gd-bd" style="padding:0;overflow:auto">
        <table class="gd-heat">
          <thead>
            <tr>
              <th>信源平台</th>
              <th v-for="e in heatMap.engines" :key="e">{{ engineDisplay(e) }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in heatMap.rows" :key="r.name">
              <td class="kw">{{ r.name }}</td>
              <td
                v-for="(cell, i) in r.cells"
                :key="i"
                :style="{ background: heatTone(cell).bg, color: heatTone(cell).fg }"
              >{{ fmtPct(cell) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="data" class="geo-kpi-grid">
      <div class="geo-kpi">
        <div class="kpi-label">含引用的快照</div>
        <div class="kpi-value">{{ fmtInt(data.snapshots_with_citations) }}</div>
        <div class="kpi-hint">至少有 1 条 URL 的快照</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">独立被引域名</div>
        <div class="kpi-value">{{ fmtInt(data.distinct_cited_domains) }}</div>
        <div class="kpi-hint">去重后的主机名</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">自有域引用率</div>
        <div class="kpi-value">{{ fmtPct(data.own_domain_cite_rate) }}</div>
        <div class="kpi-hint">
          含引用快照中命中自有域的占比
          <template v-if="!(data.own_domains || []).length"> · 未配置官网渠道</template>
        </div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">快照总量</div>
        <div class="kpi-value">{{ fmtInt(data.total_snapshots) }}</div>
        <div class="kpi-hint">含无 URL 的快照</div>
      </div>
    </div>

    <template v-if="data">
      <section v-if="qualityRows.length" class="geo-panel">
        <div class="panel-title">引用质量分布</div>
        <p class="geo-panel-desc">来自快照标注；未知偏多时请到可见度页补标或「校验引用」。</p>
        <el-table :data="qualityRows" size="small" empty-text="暂无标注">
          <el-table-column prop="dim" label="维度" width="120" />
          <el-table-column prop="value" label="取值" min-width="140" />
          <el-table-column prop="count" label="快照数" width="90" />
        </el-table>
      </section>

      <section class="geo-panel">
        <div class="panel-title-row">
          <div class="panel-title">被引域名明细</div>
        </div>
        <div class="geo-filter-bar">
          <el-input
            v-model="domainQuery"
            clearable
            placeholder="搜索域名"
            style="width: 200px"
          />
          <el-checkbox v-model="ownOnly">仅看自有域</el-checkbox>
          <span class="geo-muted">当前 {{ citeItems.length }} 个域名</span>
        </div>
        <el-table
          :data="pager.pagedItems"
          size="small"
          stripe
          empty-text="暂无引用域名"
          class="clickable-rows"
          @row-click="openDomain"
        >
          <el-table-column prop="domain" label="域名" min-width="170" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="row-link">{{ row.domain }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="cite_count" label="引用次数" width="96" />
          <el-table-column prop="prompt_count" label="意图词数" width="96" />
          <el-table-column label="引擎" min-width="140">
            <template #default="{ row }">
              {{ (row.engines || []).map(engineDisplay).join(' · ') || '—' }}
            </template>
          </el-table-column>
          <el-table-column label="蓝图渠道" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.blueprint_channel_name || row.blueprint_channel_key || '未匹配' }}
            </template>
          </el-table-column>
          <el-table-column label="域名归属" width="100">
            <template #default="{ row }">
              <span :class="row.is_own_domain ? 'geo-tag-own' : 'geo-tag-ext'">
                {{ row.is_own_domain ? '自有' : '外部' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="" width="88" fixed="right">
            <template #default>
              <el-button link type="primary" size="small">看快照</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="!citeItems.length" class="geo-empty" style="margin-top: 12px">
          <div class="empty-title">还没有可聚合的引用</div>
          <div>请先在「AI 可见度」登记含 URL 的回答，或跑巡检后刷新。</div>
          <div class="empty-actions">
            <router-link class="el-button el-button--primary" to="/geo/visibility">去登记</router-link>
            <router-link class="el-button" to="/geo/publishing">配置官网渠道</router-link>
          </div>
        </div>
        <div class="geo-pager">
          <el-pagination
            background
            layout="total, sizes, prev, pager, next"
            :total="pager.total"
            :page-size="pager.pageSize"
            :current-page="pager.page"
            :page-sizes="[10, 20, 50, 100]"
            @current-change="pager.onPageChange"
            @size-change="pager.onSizeChange"
          />
        </div>
      </section>
    </template>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.mb { margin-bottom: 14px; }
.clickable-rows :deep(tbody tr) { cursor: pointer; }
.row-link { color: #185fa5; font-weight: 600; }
</style>
