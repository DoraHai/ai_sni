<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchGeoCitationInsights } from '../../api/geoContent'
import { useClientPager } from '../../composables/useClientPager'
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

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
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
    data.value = await fetchGeoCitationInsights(tenantId.value)
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

watch(tenantId, load)
watch([ownOnly, domainQuery], () => pager.resetPage())
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">AI 引用分析</div>
        <div class="page-desc">
          看 AI 回答引用了哪些域名、自有站是否被带到，以及引用格式/准确性标注分布。
        </div>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button :disabled="!citeItems.length" @click="exportCsv">导出 CSV</el-button>
        <router-link class="el-button" to="/geo/visibility">登记快照</router-link>
        <router-link class="el-button" to="/geo/evaluation">评价分析</router-link>
      </div>
    </div>

    <details class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li v-for="(line, i) in REPORT_GLOSSARY.citations" :key="i">{{ line }}</li>
      </ul>
    </details>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" show-icon />

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
        >
          <el-table-column prop="domain" label="域名" min-width="170" show-overflow-tooltip />
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
</template>

<style scoped>
.mb { margin-bottom: 14px; }
</style>
