<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import {
  createDeliverableArchive,
  downloadGeoDeliverablesMarkdown,
  fetchGeoDeliverablesPack,
  getDeliverableArchive,
  listDeliverableArchives,
  listGeoBusinesses,
  listGeoUnits,
  listOptimizationPeriods,
} from '../../api/geoContent'
import SampleCredibilityAlert from '../../components/SampleCredibilityAlert.vue'
import { useClientPager } from '../../composables/useClientPager'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import { session } from '../../store/session'

const route = useRoute()
const router = useRouter()

const { days: observationDays, start: obsStart, end: obsEnd, label: obsLabel } =
  useObservationPeriod()

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const savingArchive = ref(false)
const error = ref('')
const pack = ref(null)
const range = ref([])
const businesses = ref([])
const units = ref([])
const periods = ref([])
const filterPeriodId = ref(null)
const filterBusinessId = ref(null)
const filterUnitId = ref(null)
const archives = ref([])
const lastShare = ref(null)
const realOnly = ref(true)

const lockedByPeriod = computed(() => !!filterPeriodId.value)
const isFrozenPack = computed(() => !!(pack.value?.frozen || pack.value?.kind === 'geo_period_deliverable_v1'))

const hasSimulated = computed(
  () =>
    !!(
      pack.value?.has_simulated_samples ||
      pack.value?.summary?.has_simulated_samples ||
      pack.value?.sample_composition?.has_simulated
    ),
)
const sampleComposeLabel = computed(
  () =>
    pack.value?.sample_composition?.label ||
    pack.value?.summary?.sample_composition?.label ||
    '',
)

const dailySeriesSrc = computed(() => pack.value?.daily_series || [])
const bizSliceSrc = computed(() => pack.value?.business_slices || [])
const unitSliceSrc = computed(() => pack.value?.unit_slices || [])
const citeSrc = computed(() => pack.value?.citations_top || [])
const taskSrc = computed(() => pack.value?.tasks || [])
const snapSrc = computed(() => pack.value?.snapshots_sample || [])

const dailyPager = useClientPager(dailySeriesSrc, { pageSize: 14 })
const bizSlicePager = useClientPager(bizSliceSrc, { pageSize: 20 })
const unitSlicePager = useClientPager(unitSliceSrc, { pageSize: 20 })
const citePager = useClientPager(citeSrc, { pageSize: 20 })
const taskPager = useClientPager(taskSrc, { pageSize: 20 })
const snapPager = useClientPager(snapSrc, { pageSize: 20 })

const fmtPct = (v) => {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

function defaultRange() {
  // 跟随全局观察期；若无则近 14 天
  if (obsStart.value && obsEnd.value) return [obsStart.value, obsEnd.value]
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - (Number(observationDays.value) || 14) + 1)
  const iso = (d) => d.toISOString().slice(0, 10)
  return [iso(start), iso(end)]
}

const filteredUnits = computed(() => {
  if (!filterBusinessId.value) return units.value
  return units.value.filter((u) => u.business_id === filterBusinessId.value)
})

const scopeParams = computed(() => {
  const p = {}
  if (filterPeriodId.value) {
    p.period_id = filterPeriodId.value
    return p
  }
  if (filterUnitId.value) p.unit_id = filterUnitId.value
  else if (filterBusinessId.value) p.business_id = filterBusinessId.value
  return p
})

async function loadHierarchy() {
  if (!tenantId.value) {
    businesses.value = []
    units.value = []
    periods.value = []
    return
  }
  try {
    const [b, u, p] = await Promise.all([
      listGeoBusinesses(tenantId.value, { status: 'active' }),
      listGeoUnits(tenantId.value, { status: 'active' }),
      listOptimizationPeriods(tenantId.value).catch(() => ({ items: [] })),
    ])
    businesses.value = b.items || []
    units.value = u.items || []
    periods.value = p.items || []
  } catch {
    businesses.value = []
    units.value = []
    periods.value = []
  }
}

function syncPeriodFromRoute() {
  const q = route.query.period_id
  if (q != null && q !== '') {
    const n = Number(q)
    if (Number.isFinite(n) && n > 0) filterPeriodId.value = n
  }
}

function onPeriodChange(id) {
  filterPeriodId.value = id || null
  const q = { ...route.query }
  if (id) q.period_id = String(id)
  else delete q.period_id
  router.replace({ path: route.path, query: q })
  load()
}

async function loadArchives() {
  if (!tenantId.value) {
    archives.value = []
    return
  }
  try {
    const data = await listDeliverableArchives(tenantId.value, 20)
    archives.value = data.items || []
  } catch {
    archives.value = []
  }
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  if (!range.value?.length) range.value = defaultRange()
  loading.value = true
  error.value = ''
  try {
    const params = { ...scopeParams.value }
    if (!filterPeriodId.value && range.value?.length) {
      params.from = `${range.value[0]}T00:00:00`
      params.to = `${range.value[1]}T23:59:59`
    }
    params.real_only = realOnly.value
    pack.value = await fetchGeoDeliverablesPack(tenantId.value, params)
    // mirror period window into date picker when locked
    if (filterPeriodId.value && pack.value?.period?.from && pack.value?.period?.to) {
      range.value = [
        String(pack.value.period.from).slice(0, 10),
        String(pack.value.period.to).slice(0, 10),
      ]
    } else if (pack.value?.window?.starts_at && pack.value?.window?.ends_at) {
      range.value = [
        String(pack.value.window.starts_at).slice(0, 10),
        String(pack.value.window.ends_at).slice(0, 10),
      ]
    }
    await loadArchives()
  } catch (e) {
    error.value = e.message || '加载失败'
    pack.value = null
  } finally {
    loading.value = false
  }
}

async function saveArchive() {
  if (!pack.value || !tenantId.value) return
  savingArchive.value = true
  try {
    const res = await createDeliverableArchive(tenantId.value, {
      pack: pack.value,
      title: `交付摘要 ${range.value[0]} ~ ${range.value[1]}`,
    })
    lastShare.value = res
    ElMessage.success(`已存档 #${res.id}`)
    await loadArchives()
  } catch (e) {
    ElMessage.error(e.message || '存档失败')
  } finally {
    savingArchive.value = false
  }
}

function shareUrl(token) {
  if (!token) return ''
  // History 模式：/geo/deliverables/share/:token（public bare）
  return `${window.location.origin}/geo/deliverables/share/${token}`
}

async function copyShare(token) {
  const url = shareUrl(token)
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success('分享链接已复制')
  } catch {
    ElMessage.info(url)
  }
}

async function openArchive(row) {
  try {
    const data = await getDeliverableArchive(tenantId.value, row.id)
    pack.value = data.pack
    ElMessage.success(`已加载存档 #${row.id}`)
  } catch (e) {
    ElMessage.error(e.message || '加载存档失败')
  }
}

function packQueryParams() {
  const params = { ...scopeParams.value }
  if (!filterPeriodId.value && range.value?.length) {
    params.from = `${range.value[0]}T00:00:00`
    params.to = `${range.value[1]}T23:59:59`
  }
  params.real_only = realOnly.value
  return params
}

const canExportClient = computed(() => {
  if (!pack.value) return false
  if (!realOnly.value) return true
  return pack.value.suitable_for_client !== false
})

async function copyMarkdown() {
  try {
    const md = await downloadGeoDeliverablesMarkdown(tenantId.value, packQueryParams())
    await navigator.clipboard.writeText(md)
    ElMessage.success('Markdown 已复制')
  } catch (e) {
    ElMessage.error(e.message || '复制失败')
  }
}

async function downloadMarkdown() {
  try {
    const md = await downloadGeoDeliverablesMarkdown(tenantId.value, packQueryParams())
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
    const href = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = href
    a.download = `geo-deliverables-${tenantId.value}.md`
    a.click()
    URL.revokeObjectURL(href)
    ElMessage.success('已下载 Markdown')
  } catch (e) {
    ElMessage.error(e.message || '下载失败')
  }
}

function printReport() {
  window.print()
}

function onBusinessChange() {
  if (
    filterUnitId.value &&
    !filteredUnits.value.some((u) => u.id === filterUnitId.value)
  ) {
    filterUnitId.value = null
  }
  load()
}

watch(tenantId, async () => {
  await loadHierarchy()
  await load()
})
watch(range, () => {
  if (!filterPeriodId.value) load()
}, { deep: true })
watch(filterUnitId, () => {
  if (!filterPeriodId.value) load()
})
watch(realOnly, load)
watch([obsStart, obsEnd, observationDays], () => {
  if (!filterPeriodId.value) range.value = defaultRange()
})
watch(
  () => route.query.period_id,
  () => {
    syncPeriodFromRoute()
    load()
  },
)
onMounted(async () => {
  range.value = defaultRange()
  syncPeriodFromRoute()
  await loadHierarchy()
  await load()
})
</script>

<template>
  <div v-loading="loading" class="geo-deliv">
    <div class="page-header">
      <div>
        <div class="page-title">GEO 交付摘要</div>
        <div class="page-desc">
          按周期与业务/单元汇总可见度、引用与优化文章，生成可对外粘贴的 Markdown 周报材料。
        </div>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button :loading="savingArchive" type="success" plain @click="saveArchive" :disabled="!pack">
          存档本报告
        </el-button>
        <el-button :disabled="!canExportClient" @click="copyMarkdown">复制 Markdown</el-button>
        <el-button type="primary" :disabled="!canExportClient" @click="downloadMarkdown">下载 Markdown</el-button>
        <el-button plain @click="printReport">打印</el-button>
      </div>
    </div>

    <details class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li>默认周期跟随顶栏观察期（{{ obsLabel }}），可在下方改日期。</li>
        <li>交付包汇总选定周期内的日指标、任务与引用样本，便于对外说明。</li>
        <li>含模拟样本时必须黄标，不可当作真实引擎效果。</li>
        <li>点「存档本报告」可回看历史与复制分享链接。</li>
      </ul>
    </details>

    <div class="geo-toolbar">
      <el-select
        :model-value="filterPeriodId"
        clearable
        filterable
        placeholder="锁定期次（可选）"
        style="width: 240px"
        @change="onPeriodChange"
      >
        <el-option
          v-for="p in periods"
          :key="p.id"
          :label="`#${p.id} ${p.name} (${p.status})`"
          :value="p.id"
        />
      </el-select>
      <el-date-picker
        v-model="range"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="开始"
        end-placeholder="结束"
        :clearable="false"
        :disabled="lockedByPeriod"
        style="width: 260px"
      />
      <el-select
        v-model="filterBusinessId"
        clearable
        filterable
        placeholder="全部业务"
        style="width: 180px"
        :disabled="lockedByPeriod"
        @change="onBusinessChange"
      >
        <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
      </el-select>
      <el-select
        v-model="filterUnitId"
        clearable
        filterable
        placeholder="全部单元"
        style="width: 200px"
        :disabled="lockedByPeriod"
      >
        <el-option
          v-for="u in filteredUnits"
          :key="u.id"
          :label="`${u.name}${u.keyword ? ' · ' + u.keyword : ''}`"
          :value="u.id"
        />
      </el-select>
      <el-switch v-model="realOnly" active-text="仅真采样" />
      <span class="toolbar-hint">
        <template v-if="lockedByPeriod">期次锁窗 · closed 返回固化交付包</template>
        <template v-else>观察期 {{ obsLabel }} · 改日期后自动刷新</template>
        · 客户交付默认只统计真采样
      </span>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />
    <el-alert
      v-if="pack && isFrozenPack"
      type="success"
      :closable="false"
      show-icon
      class="mb"
      title="期次固化交付包"
      :description="`冻结于 ${pack.frozen_at || '—'} · ${pack.period_name || ''} · 关闭后改窗不影响本快照`"
    />
    <SampleCredibilityAlert
      v-if="pack"
      :composition="pack.sample_composition || pack.summary?.sample_composition"
      :window-label="obsLabel"
      :engines-covered="pack.summary?.visibility_engines_covered"
    />
    <el-alert
      v-if="pack && pack.impact_language"
      type="info"
      :closable="false"
      show-icon
      class="mb"
      :title="pack.impact_language"
      description="客户交付默认只统计真采样。无真采样时显示「未形成有效结论」，不会写成 0%。"
    />

    <section v-if="archives.length" class="geo-panel mb">
      <div class="panel-title">历史存档</div>
      <el-table :data="archives" size="small" max-height="220">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
        <el-table-column label="模拟" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.has_simulated" size="small" type="warning">是</el-tag>
            <span v-else class="muted">否</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="存档时间" width="160" />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openArchive(row)">加载</el-button>
            <el-button
              v-if="row.share_token"
              link
              size="small"
              @click="copyShare(row.share_token)"
            >
              复制分享
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <p v-if="lastShare?.share_token" class="share-hint">
        最近分享：
        <code>{{ shareUrl(lastShare.share_token) }}</code>
      </p>
    </section>

    <template v-if="pack">
      <div id="geo-deliv-print" class="report">
      <div class="meta">
        <strong>{{ pack.tenant_name }}</strong>
        <span>· 周期 {{ pack.period?.from?.slice(0, 10) }} ~ {{ pack.period?.to?.slice(0, 10) }}</span>
        <span>· {{ pack.period?.days }} 天</span>
        <span class="scope-tag">· {{ pack.scope?.label || '租户全量' }}</span>
        <span v-if="sampleComposeLabel" class="scope-tag">· {{ sampleComposeLabel }}</span>
      </div>

      <div class="kpi-row">
        <div class="kpi">
          <div class="kpi-label">品牌提及率</div>
          <div class="kpi-value">{{ fmtPct(pack.summary?.visibility_mention_rate) }}</div>
          <div class="kpi-sub">排除探测题 · 未测记 —</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">首位推荐率</div>
          <div class="kpi-value">{{ fmtPct(pack.summary?.visibility_top1_rate) }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">品牌点名认知率</div>
          <div class="kpi-value">{{ fmtPct(pack.summary?.probe_recognition_rate) }}</div>
          <div class="kpi-sub">仅探测题 · 可选分列</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">周期快照</div>
          <div class="kpi-value">{{ pack.summary?.snapshots ?? '—' }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">优化文章 / 已发布</div>
          <div class="kpi-value">{{ pack.summary?.tasks ?? 0 }} / {{ pack.summary?.published ?? 0 }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">AI 引用次数</div>
          <div class="kpi-value">
            {{ pack.summary?.citation_count ?? pack.summary?.distinct_cited_domains ?? '—' }}
          </div>
          <div class="kpi-sub">
            URL 次数 · 独立域名 {{ pack.summary?.distinct_cited_domains ?? '—' }}
          </div>
        </div>
      </div>

      <section v-if="dailyPager.total" class="panel">
        <div class="panel-title">按天汇总 · {{ pack.scope?.label || '租户' }}</div>
        <el-table :data="dailyPager.pagedItems" size="small">
          <el-table-column prop="metric_date" label="日期" width="110" />
          <el-table-column label="品牌提及率" width="110">
            <template #default="{ row }">{{ fmtPct(row.brand_mention_rate) }}</template>
          </el-table-column>
          <el-table-column label="点名认知率" width="110">
            <template #default="{ row }">{{ fmtPct(row.brand_probe_recognition_rate) }}</template>
          </el-table-column>
          <el-table-column prop="citation_count" label="AI 引用" width="90" />
          <el-table-column prop="distinct_cited_domains" label="独立域名" width="90" />
          <el-table-column prop="snapshots_visibility" label="可见快照" width="90" />
        </el-table>
        <div class="geo-pager">
          <el-pagination
            background
            small
            layout="total, prev, pager, next"
            :total="dailyPager.total"
            :page-size="dailyPager.pageSize"
            :current-page="dailyPager.page"
            @current-change="dailyPager.onPageChange"
          />
        </div>
      </section>

      <section v-if="bizSlicePager.total" class="panel">
        <div class="panel-title">优化业务切片（周期内最近一日）</div>
        <el-table :data="bizSlicePager.pagedItems" size="small">
          <el-table-column label="业务" min-width="140">
            <template #default="{ row }">{{ row.business_name || `业务#${row.business_id}` }}</template>
          </el-table-column>
          <el-table-column prop="metric_date" label="日期" width="110" />
          <el-table-column label="品牌提及率" width="110">
            <template #default="{ row }">{{ fmtPct(row.brand_mention_rate) }}</template>
          </el-table-column>
          <el-table-column prop="citation_count" label="AI 引用" width="90" />
          <el-table-column prop="snapshots_visibility" label="可见快照" width="90" />
        </el-table>
        <div class="geo-pager">
          <el-pagination
            background
            small
            layout="total, prev, pager, next"
            :total="bizSlicePager.total"
            :page-size="bizSlicePager.pageSize"
            :current-page="bizSlicePager.page"
            @current-change="bizSlicePager.onPageChange"
          />
        </div>
      </section>

      <section v-if="unitSlicePager.total" class="panel">
        <div class="panel-title">优化单元切片（周期内最近一日）</div>
        <el-table :data="unitSlicePager.pagedItems" size="small">
          <el-table-column label="单元" min-width="160">
            <template #default="{ row }">
              <span v-if="row.business_name">{{ row.business_name }} / </span>
              {{ row.unit_name || `单元#${row.unit_id}` }}
            </template>
          </el-table-column>
          <el-table-column prop="metric_date" label="日期" width="110" />
          <el-table-column label="品牌提及率" width="110">
            <template #default="{ row }">{{ fmtPct(row.brand_mention_rate) }}</template>
          </el-table-column>
          <el-table-column prop="citation_count" label="AI 引用" width="90" />
          <el-table-column prop="snapshots_visibility" label="可见快照" width="90" />
        </el-table>
        <div class="geo-pager">
          <el-pagination
            background
            small
            layout="total, prev, pager, next"
            :total="unitSlicePager.total"
            :page-size="unitSlicePager.pageSize"
            :current-page="unitSlicePager.page"
            @current-change="unitSlicePager.onPageChange"
          />
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">AI 引用次数 · 域名 Top</div>
        <el-table :data="citePager.pagedItems" size="small" empty-text="本期无引用">
          <el-table-column prop="domain" label="域名" min-width="160" />
          <el-table-column prop="cite_count" label="次数" width="80" />
          <el-table-column label="自有" width="70">
            <template #default="{ row }">{{ row.is_own_domain ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="蓝图" min-width="120">
            <template #default="{ row }">
              {{ row.blueprint_channel_name || row.blueprint_channel_key || '—' }}
            </template>
          </el-table-column>
          <el-table-column label="引擎" min-width="140">
            <template #default="{ row }">{{ (row.engines || []).join(', ') || '—' }}</template>
          </el-table-column>
        </el-table>
        <div class="geo-pager">
          <el-pagination
            background
            small
            layout="total, prev, pager, next"
            :total="citePager.total"
            :page-size="citePager.pageSize"
            :current-page="citePager.page"
            @current-change="citePager.onPageChange"
          />
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">优化文章</div>
        <el-table :data="taskPager.pagedItems" size="small" empty-text="本期无任务">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="status" label="状态" width="110" />
          <el-table-column label="标题" min-width="200">
            <template #default="{ row }">{{ row.title || row.prompt_question || '—' }}</template>
          </el-table-column>
          <el-table-column prop="updated_at" label="更新" width="170" />
        </el-table>
        <div class="geo-pager">
          <el-pagination
            background
            small
            layout="total, prev, pager, next"
            :total="taskPager.total"
            :page-size="taskPager.pageSize"
            :current-page="taskPager.page"
            @current-change="taskPager.onPageChange"
          />
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">可见度快照抽样</div>
        <el-table :data="snapPager.pagedItems" size="small" empty-text="本期无快照">
          <el-table-column prop="captured_at" label="观测时间" width="170" />
          <el-table-column prop="engine" label="引擎" width="100" />
          <el-table-column label="提及" width="70">
            <template #default="{ row }">{{ row.mentions_brand ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="问题" min-width="200">
            <template #default="{ row }">{{ row.prompt_question || `#${row.prompt_id}` }}</template>
          </el-table-column>
        </el-table>
        <div class="geo-pager">
          <el-pagination
            background
            small
            layout="total, prev, pager, next"
            :total="snapPager.total"
            :page-size="snapPager.pageSize"
            :current-page="snapPager.page"
            @current-change="snapPager.onPageChange"
          />
        </div>
      </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 16px; }
.meta {
  font-size: 13px;
  color: #475569;
  margin-bottom: 16px;
  line-height: 1.6;
  padding: 12px 16px;
  background: #f8fafc;
  border-radius: 10px;
}
.scope-tag { color: #2563eb; font-weight: 600; }
.kpi-sub { font-size: 12px; color: #94a3b8; margin-top: 6px; line-height: 1.4; }
.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}
.kpi {
  background: #fff;
  border: 1px solid #e8edf5;
  border-radius: 12px;
  padding: 16px 18px;
  min-height: 96px;
}
.kpi-label { font-size: 12px; color: #64748b; font-weight: 500; }
.kpi-value {
  margin-top: 8px;
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}
.panel {
  background: #fff;
  border: 1px solid #e8edf5;
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 18px;
}
.panel-title { font-size: 15px; font-weight: 650; margin-bottom: 14px; color: #1e293b; }
@media print {
  .page-header .header-actions { display: none; }
  .share-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #64748b;
  word-break: break-all;
}
.share-hint code {
  font-size: 11px;
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
}
.muted { color: #94a3b8; font-size: 12px; }
.mb { margin-bottom: 12px; }
.geo-deliv { padding: 0; }
}
</style>
