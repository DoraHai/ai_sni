<script setup>
/**
 * 缺口工作台：brand_missing → 批量建任务
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createTasksFromGaps,
  fetchGapWorkbench,
  formatGeoError,
  listGeoBusinesses,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const { tenantId } = useGeoTenant()

const loading = ref(false)
const creating = ref(false)
const error = ref('')
const data = ref(null)
const businesses = ref([])
const businessFilter = ref(null)
const selected = ref([])

const items = computed(() => data.value?.items || [])
const summary = computed(() => ({
  total: data.value?.total ?? 0,
  needs: data.value?.needs_task_total ?? 0,
  open: data.value?.has_open_task_total ?? 0,
  sla: data.value?.sla_breached_total ?? 0,
  slaDays: data.value?.sla_days ?? 7,
  byBiz: data.value?.by_business || [],
}))

async function load() {
  if (!tenantId.value) return
  loading.value = true
  error.value = ''
  try {
    const [wb, biz] = await Promise.all([
      fetchGapWorkbench(tenantId.value, {
        business_id: businessFilter.value || undefined,
      }),
      listGeoBusinesses(tenantId.value, { status: 'active' }),
    ])
    data.value = wb
    businesses.value = biz.items || biz || []
    selected.value = []
  } catch (e) {
    error.value = formatGeoError(e, '加载缺口失败')
    data.value = null
  } finally {
    loading.value = false
  }
}

async function batchCreate(ids) {
  const promptIds = (ids || selected.value || []).map(Number).filter(Boolean)
  if (!promptIds.length) {
    ElMessage.warning('请先勾选需要建任务的意图词')
    return
  }
  creating.value = true
  try {
    const res = await createTasksFromGaps(tenantId.value, promptIds)
    ElMessage.success(
      `已创建 ${res.created_count || 0} 个任务` +
        (res.skipped_count ? `，跳过 ${res.skipped_count}` : ''),
    )
    if (res.created?.length === 1) {
      router.push(`/geo/tasks/${res.created[0].task_id}`)
      return
    }
    await load()
  } catch (e) {
    ElMessage.error(formatGeoError(e, '批量建任务失败'))
  } finally {
    creating.value = false
  }
}

function createAllNeeds() {
  const ids = items.value.filter((i) => i.needs_task).map((i) => i.prompt_id)
  return batchCreate(ids)
}

function createSlaBreached() {
  const ids = items.value.filter((i) => i.sla_breached).map((i) => i.prompt_id)
  if (!ids.length) {
    ElMessage.info('当前没有超 SLA 的待建缺口')
    return
  }
  return batchCreate(ids)
}

function openTask(row) {
  const tid = row.open_task_ids?.[0] || row.last_task_id
  if (tid) router.push(`/geo/tasks/${tid}`)
  else router.push({ path: '/geo/prompts', query: { tag: 'brand_missing' } })
}

watch([tenantId, businessFilter], load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page gap-wb">
    <div class="page-header">
      <div>
        <div class="page-title">缺口工作台</div>
        <div class="page-desc">
          品牌没被提到的问题，按是否超期和优先程度排好。超期默认
          {{ summary.slaDays }} 天，会出现在概览告警里。
        </div>
      </div>
      <div class="header-actions">
        <el-select
          v-model="businessFilter"
          clearable
          placeholder="全部业务"
          style="width: 180px"
        >
          <el-option
            v-for="b in businesses"
            :key="b.id"
            :label="b.name"
            :value="b.id"
          />
        </el-select>
        <el-button @click="load">刷新</el-button>
        <el-button type="primary" :loading="creating" @click="batchCreate()">
          为勾选建任务
        </el-button>
        <el-button type="danger" plain :loading="creating" @click="createSlaBreached">
          超期建任务
        </el-button>
        <el-button type="warning" plain :loading="creating" @click="createAllNeeds">
          全部待办建任务
        </el-button>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <div class="kpi-row">
      <div class="kpi">
        <div class="k-label">品牌缺失</div>
        <div class="k-val">{{ summary.total }}</div>
      </div>
      <div class="kpi warn">
        <div class="k-label">待建任务</div>
        <div class="k-val">{{ summary.needs }}</div>
      </div>
      <div class="kpi danger">
        <div class="k-label">超 SLA</div>
        <div class="k-val">{{ summary.sla }}</div>
        <div class="k-hint">≥{{ summary.slaDays }} 天未建任务</div>
      </div>
      <div class="kpi">
        <div class="k-label">已有在产</div>
        <div class="k-val">{{ summary.open }}</div>
      </div>
    </div>

    <div v-if="summary.byBiz.length" class="biz-chips mb">
      <span v-for="b in summary.byBiz" :key="b.business_id ?? 'u'" class="chip">
        {{ b.business_name }} · 缺口 {{ b.gap_count }}
        <template v-if="b.needs_task_count"> · 待办 {{ b.needs_task_count }}</template>
      </span>
    </div>

    <el-table
      :data="items"
      size="small"
      stripe
      @selection-change="(rows) => (selected = rows.map((r) => r.prompt_id))"
    >
      <el-table-column type="selection" width="42" :selectable="(r) => r.needs_task" />
      <el-table-column prop="priority" label="优先级" width="72" sortable />
      <el-table-column prop="question" label="意图词" min-width="220" />
      <el-table-column prop="business_name" label="业务" width="120">
        <template #default="{ row }">{{ row.business_name || '未分类' }}</template>
      </el-table-column>
      <el-table-column prop="unit_name" label="单元" width="120">
        <template #default="{ row }">{{ row.unit_name || '—' }}</template>
      </el-table-column>
      <el-table-column prop="age_days" label="天数" width="64" sortable />
      <el-table-column label="SLA" width="88">
        <template #default="{ row }">
          <el-tag v-if="row.sla_breached" type="danger" size="small">超期</el-tag>
          <span v-else class="muted">{{ row.age_days }}/{{ row.sla_days }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.needs_task" type="danger" size="small">待建任务</el-tag>
          <el-tag v-else-if="row.has_open_task" type="warning" size="small">
            在产 {{ row.open_task_count }}
          </el-tag>
          <el-tag v-else type="success" size="small">已发 {{ row.published_task_count }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.needs_task"
            link
            type="primary"
            size="small"
            :loading="creating"
            @click="batchCreate([row.prompt_id])"
          >
            建任务
          </el-button>
          <el-button
            v-else
            link
            type="primary"
            size="small"
            @click="openTask(row)"
          >
            打开任务
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <p v-if="!loading && !items.length" class="empty">
      当前没有「品牌没被提到」的缺口。跑一轮巡检或在可见度里录入回答后会出现。
    </p>
  </div>
</template>

<style scoped>
.gap-wb { padding: 4px 2px 32px; }
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.page-title { margin: 0 0 6px; font-size: 20px; font-weight: 700; color: #0f172a; }
.page-desc { margin: 0; font-size: 13px; color: #64748b; max-width: 560px; line-height: 1.5; }
.head-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.kpi-row { display: flex; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.kpi {
  min-width: 120px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px 14px;
}
.kpi.warn { border-color: #fdba74; background: #fff7ed; }
.kpi.danger { border-color: #fca5a5; background: #fef2f2; }
.k-label { font-size: 12px; color: #64748b; }
.k-val { font-size: 22px; font-weight: 700; color: #0f172a; }
.k-hint { font-size: 11px; color: #94a3b8; margin-top: 2px; }
.muted { color: #94a3b8; font-size: 12px; }
.biz-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  font-size: 12px;
  background: #eef2ff;
  color: #3730a3;
  border-radius: 999px;
  padding: 4px 10px;
}
.mb { margin-bottom: 12px; }
.empty { color: #94a3b8; font-size: 13px; margin-top: 24px; text-align: center; }
</style>
