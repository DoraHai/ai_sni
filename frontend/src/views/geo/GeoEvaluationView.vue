<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { fetchGeoEvaluationInsights } from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import {
  POSITION_LABEL,
  SENTIMENT_LABEL,
  engineDisplay,
  fmtCaptured,
  labelOf,
} from '../../utils/geoReportLabels'

const { tenantId } = useGeoTenant()
const route = useRoute()
const {
  days: observationDays,
  start: obsStart,
  end: obsEnd,
  label: obsLabel,
} = useObservationPeriod()

const loading = ref(false)
const error = ref('')
const data = ref(null)

function countOrDash(counts, key) {
  return Object.prototype.hasOwnProperty.call(counts || {}, key) ? counts[key] : '—'
}

const distributionRows = computed(() => [
  ...Object.entries(POSITION_LABEL).map(([key, label]) => ({
    dimension: '推荐位置',
    label,
    count: countOrDash(data.value?.position_counts, key),
  })),
  ...Object.entries(SENTIMENT_LABEL).map(([key, label]) => ({
    dimension: '情感倾向',
    label,
    count: countOrDash(data.value?.sentiment_counts, key),
  })),
])

const recentRows = computed(() => {
  const rows = data.value?.recent || []
  const pid = route.query.prompt_id ? Number(route.query.prompt_id) : null
  const scoped = pid ? rows.filter((row) => row.prompt_id === pid) : rows
  return scoped.slice(0, 40)
})

async function load() {
  if (!tenantId.value) {
    data.value = null
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
  } catch (e) {
    data.value = null
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

watch([tenantId, observationDays, obsStart, obsEnd], load)
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="评价分析"
    :sub="`品牌在 AI 回答中的推荐位置与情感分布 · ${obsLabel}`"
    :loading="loading"
  >
    <template #actions>
      <button class="gd-btn" type="button" @click="load">刷新</button>
    </template>
    <div class="geo-dash evaluation-page">
      <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />

      <section class="gd-card">
        <div class="gd-hd"><h3>分布</h3><span class="more">样本 {{ data?.total ?? '—' }}</span></div>
        <div class="gd-bd" style="padding:0">
          <el-table :data="distributionRows" size="small" empty-text="暂无分布数据">
            <el-table-column prop="dimension" label="维度" min-width="120" />
            <el-table-column prop="label" label="类别" min-width="140" />
            <el-table-column prop="count" label="出现次数" width="120" />
          </el-table>
        </div>
      </section>

      <section class="gd-card">
        <div class="gd-hd"><h3>最近快照</h3><span class="more">{{ recentRows.length }} 条</span></div>
        <div class="gd-bd" style="padding:0">
          <el-table :data="recentRows" size="small" empty-text="暂无回答快照">
            <el-table-column label="关联提问" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">{{ row.prompt_question || (row.prompt_id ? `#${row.prompt_id}` : '—') }}</template>
            </el-table-column>
            <el-table-column label="引擎" width="120">
              <template #default="{ row }">{{ row.engine ? engineDisplay(row.engine) : '—' }}</template>
            </el-table-column>
            <el-table-column label="位置" width="120">
              <template #default="{ row }">{{ row.brand_position ? labelOf(POSITION_LABEL, row.brand_position) : '—' }}</template>
            </el-table-column>
            <el-table-column label="情感" width="110">
              <template #default="{ row }">{{ row.sentiment ? labelOf(SENTIMENT_LABEL, row.sentiment) : '—' }}</template>
            </el-table-column>
            <el-table-column label="观测时间" width="160">
              <template #default="{ row }">{{ row.captured_at ? fmtCaptured(row.captured_at) : '—' }}</template>
            </el-table-column>
          </el-table>
        </div>
      </section>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.evaluation-page { display: grid; gap: 16px; }
.mb { margin-bottom: 0; }
</style>
