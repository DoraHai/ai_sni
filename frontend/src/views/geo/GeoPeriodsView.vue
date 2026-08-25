<script setup>
/**
 * 优化期次：交付边界实体（时间窗 + 业务 + 基线 + 期末复测）
 */
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  closeOptimizationPeriod,
  createOptimizationPeriod,
  formatGeoError,
  getOptimizationPeriod,
  listGeoBusinesses,
  listOptimizationPeriods,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { fmtPct } from '../../utils/geoReportLabels'

const router = useRouter()

const { tenantId } = useGeoTenant()

const loading = ref(false)
const items = ref([])
const businesses = ref([])
const detail = ref(null)
const form = ref({
  name: '',
  business_id: null,
  range: [],
  goal_note: '',
  capture_baseline: true,
})

function fmtRate(v) {
  if (v == null) return '—'
  return fmtPct(v)
}

async function load() {
  if (!tenantId.value) return
  loading.value = true
  try {
    const [p, b] = await Promise.all([
      listOptimizationPeriods(tenantId.value),
      listGeoBusinesses(tenantId.value, { status: 'active' }),
    ])
    items.value = p.items || []
    businesses.value = b.items || b || []
  } catch (e) {
    ElMessage.error(formatGeoError(e, '加载期次失败'))
  } finally {
    loading.value = false
  }
}

async function createPeriod() {
  if (!form.value.name?.trim()) {
    ElMessage.warning('请填写期次名称')
    return
  }
  if (!form.value.range?.length || form.value.range.length < 2) {
    ElMessage.warning('请选择起止日期')
    return
  }
  loading.value = true
  try {
    const row = await createOptimizationPeriod({
      tenant_id: tenantId.value,
      name: form.value.name.trim(),
      starts_at: form.value.range[0],
      ends_at: form.value.range[1],
      business_id: form.value.business_id || null,
      goal_note: form.value.goal_note || null,
      capture_baseline: !!form.value.capture_baseline,
    })
    ElMessage.success(`已创建期次 #${row.id}`)
    form.value = {
      name: '',
      business_id: null,
      range: [],
      goal_note: '',
      capture_baseline: true,
    }
    await load()
    await openDetail(row.id)
  } catch (e) {
    ElMessage.error(formatGeoError(e, '创建失败'))
  } finally {
    loading.value = false
  }
}

async function openDetail(id) {
  try {
    detail.value = await getOptimizationPeriod(tenantId.value, id)
  } catch (e) {
    ElMessage.error(formatGeoError(e, '加载详情失败'))
  }
}

async function closePeriod(id) {
  try {
    await ElMessageBox.confirm(
      "关闭后会固化期末指标，不能再当进行中期次改窗。确认关闭？",
      "关闭期次",
      { type: "warning", confirmButtonText: "确认关闭", cancelButtonText: "取消" },
    )
  } catch {
    return
  }
  loading.value = true
  try {
    detail.value = await closeOptimizationPeriod(tenantId.value, id)
    ElMessage.success('已关闭并写入期末复测')
    await load()
  } catch (e) {
    ElMessage.error(formatGeoError(e, '关闭失败'))
  } finally {
    loading.value = false
  }
}

function bizName(id) {
  if (!id) return '全部业务'
  const b = businesses.value.find((x) => x.id === id)
  return b?.name || `#${id}`
}

/** 锁窗对比 / 期次交付（period_id 入参） */
function goPeriodDiff(id) {
  router.push({ path: '/geo/period-diff', query: { period_id: String(id) } })
}
function goPeriodDeliverable(id) {
  router.push({ path: '/geo/deliverables', query: { period_id: String(id) } })
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="periods">
    <div class="page-head">
      <div>
        <h1 class="page-title">优化期次</h1>
        <p class="page-desc">
          一个期次 = 时间范围 + 目标业务 + 期初基线 + 期内发布清单 + 期末复测。对应交付合同颗粒度。
        </p>
      </div>
      <div class="head-actions">
        <router-link class="el-button el-button--small is-plain" to="/geo/period-diff">
          自由日期对比
        </router-link>
      </div>
    </div>

    <el-card shadow="never" class="mb">
      <template #header>新建期次</template>
      <el-form label-width="96px" size="small" class="create-form">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如 2026Q3 品牌可见度" style="max-width: 320px" />
        </el-form-item>
        <el-form-item label="业务线">
          <el-select v-model="form.business_id" clearable placeholder="全部" style="width: 220px">
            <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间范围" required>
          <el-date-picker
            v-model="form.range"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始"
            end-placeholder="结束"
          />
        </el-form-item>
        <el-form-item label="目标说明">
          <el-input v-model="form.goal_note" type="textarea" :rows="2" style="max-width: 480px" />
        </el-form-item>
        <el-form-item label="抓取基线">
          <el-switch v-model="form.capture_baseline" />
          <span class="hint">创建时用期前 14 天窗口写入 baseline_meta</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="createPeriod">创建</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-table :data="items" size="small" @row-click="(r) => openDetail(r.id)">
      <el-table-column prop="id" label="ID" width="64" />
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column label="业务" width="120">
        <template #default="{ row }">{{ bizName(row.business_id) }}</template>
      </el-table-column>
      <el-table-column label="区间" min-width="180">
        <template #default="{ row }">
          {{ (row.starts_at || '').slice(0, 10) }} ~ {{ (row.ends_at || '').slice(0, 10) }}
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="90" />
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click.stop="goPeriodDiff(row.id)">
            查看本期对比
          </el-button>
          <el-button link size="small" @click.stop="goPeriodDeliverable(row.id)">
            期次交付
          </el-button>
          <el-button
            v-if="row.status !== 'closed'"
            link
            type="warning"
            size="small"
            @click.stop="closePeriod(row.id)"
          >
            期末关闭
          </el-button>
          <el-button link size="small" @click.stop="openDetail(row.id)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-card v-if="detail" shadow="never" class="mt">
      <template #header>
        <div class="detail-head">
          <span>
            期次详情 #{{ detail.id }} · {{ detail.name }}
            <el-tag size="small" class="ml">{{ detail.status }}</el-tag>
          </span>
          <span class="detail-actions">
            <el-button size="small" type="primary" plain @click="goPeriodDiff(detail.id)">
              查看本期对比
            </el-button>
            <el-button size="small" plain @click="goPeriodDeliverable(detail.id)">
              期次交付
            </el-button>
          </span>
        </div>
      </template>
      <p class="hint">
        {{ (detail.starts_at || '').slice(0, 10) }} ~ {{ (detail.ends_at || '').slice(0, 10) }}
        · {{ bizName(detail.business_id) }}
      </p>
      <p v-if="detail.goal_note">目标：{{ detail.goal_note }}</p>
      <el-alert
        v-if="detail.status === 'closed' && detail.deliverable_pack"
        type="success"
        :closable="false"
        show-icon
        class="mb-sm"
        title="已固化交付包"
        :description="`冻结于 ${detail.deliverable_pack.frozen_at || '—'} · 关闭后改窗不影响本快照`"
      />
      <div class="meta-grid">
        <div>
          <h4>期初基线</h4>
          <pre v-if="detail.baseline_meta?.metrics">{{
            JSON.stringify(
              {
                mention: fmtRate(detail.baseline_meta.metrics.visibility_mention_rate),
                own_cite: fmtRate(detail.baseline_meta.metrics.own_domain_cite_rate),
                probe: fmtRate(detail.baseline_meta.metrics.probe_recognition_rate),
                n: detail.baseline_meta.sample_count,
              },
              null,
              2,
            )
          }}</pre>
          <p v-else class="hint">无基线</p>
        </div>
        <div>
          <h4>期末结果</h4>
          <pre v-if="detail.result_meta?.metrics">{{
            JSON.stringify(
              {
                mention: fmtRate(detail.result_meta.metrics.visibility_mention_rate),
                own_cite: fmtRate(detail.result_meta.metrics.own_domain_cite_rate),
                probe: fmtRate(detail.result_meta.metrics.probe_recognition_rate),
                delta: detail.result_meta.delta_vs_baseline,
                n: detail.result_meta.sample_count,
              },
              null,
              2,
            )
          }}</pre>
          <p v-else class="hint">未关闭 / 无复测</p>
        </div>
      </div>
      <h4>期内发布 ({{ detail.publication_count ?? detail.publications_in_period?.length ?? 0 }})</h4>
      <ul v-if="detail.publications_in_period?.length" class="pub-list">
        <li v-for="p in detail.publications_in_period" :key="p.id">
          <a :href="p.published_url" target="_blank" rel="noopener">{{ p.channel }}</a>
          · 任务 #{{ p.task_id }} · {{ (p.published_at || '').slice(0, 10) }}
        </li>
      </ul>
      <p v-else class="hint">期内暂无发布回填</p>
    </el-card>
  </div>
</template>

<style scoped>
.periods { padding: 4px 2px 32px; }
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.page-title { margin: 0 0 6px; font-size: 20px; font-weight: 700; }
.page-desc { margin: 0; font-size: 13px; color: #64748b; max-width: 560px; line-height: 1.5; }
.head-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.detail-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.mb { margin-bottom: 16px; }
.mb-sm { margin-bottom: 12px; }
.mt { margin-top: 16px; }
.ml { margin-left: 8px; }
.hint { font-size: 12px; color: #94a3b8; margin-left: 8px; }
.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.meta-grid h4 { margin: 0 0 8px; font-size: 13px; }
.meta-grid pre {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px;
  font-size: 12px;
  overflow: auto;
}
.pub-list { font-size: 13px; padding-left: 18px; }
@media (max-width: 800px) {
  .meta-grid { grid-template-columns: 1fr; }
}
</style>
