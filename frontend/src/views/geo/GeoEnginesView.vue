<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchMonitoringStance,
  fetchVisibilityPatrolOpsStatus,
  listGeoTrackingEngines,
  putGeoTrackingEngines,
  putMonitoringStance,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'
import {
  REPORT_GLOSSARY,
  SAMPLE_MODE_LABEL,
  engineDisplay,
  labelOf,
} from '../../utils/geoReportLabels'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const items = ref([])
const ops = ref(null)
const stance = ref(null)
const stanceSaving = ref(false)

const enabledCount = computed(() => items.value.filter((r) => r.enabled).length)
const realReadyCount = computed(
  () => items.value.filter((r) => isRealReady(r)).length,
)

function isRealReady(row) {
  return (
    row.enabled &&
    (row.sample_mode || 'mock_persona') === 'openai_compat' &&
    !!row.api_key_configured
  )
}

function readinessLabel(row) {
  if (!row.enabled) return { text: '已停用', type: 'info' }
  if ((row.sample_mode || 'mock_persona') === 'mock_persona') {
    return { text: '人设模拟', type: 'warning' }
  }
  if (!row.api_key_configured && !(row.api_key && row.api_key.length >= 8)) {
    return { text: '缺 API Key', type: 'danger' }
  }
  if (!String(row.api_base_url || '').trim() || !String(row.model || '').trim()) {
    return { text: '缺 URL/Model', type: 'danger' }
  }
  return { text: '真采样就绪', type: 'success' }
}

function modeLabel(mode) {
  return labelOf(SAMPLE_MODE_LABEL, mode || 'mock_persona', mode)
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    items.value = []
    ops.value = null
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [data, opsRes, stanceRes] = await Promise.all([
      listGeoTrackingEngines(tenantId.value, false),
      fetchVisibilityPatrolOpsStatus(tenantId.value).catch(() => null),
      fetchMonitoringStance(tenantId.value).catch(() => null),
    ])
    items.value = (data.items || []).map((it) => ({
      ...it,
      sample_mode: it.sample_mode || 'mock_persona',
      api_base_url: it.api_base_url || '',
      model: it.model || '',
      api_key: '',
      clear_api_key: false,
    }))
    ops.value = opsRes
    stance.value = stanceRes
  } catch (e) {
    error.value = e.message || '加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

async function saveStance(key) {
  if (!tenantId.value || !key) return
  stanceSaving.value = true
  try {
    await putMonitoringStance(tenantId.value, key)
    stance.value = await fetchMonitoringStance(tenantId.value)
    ElMessage.success('监测定位已更新')
  } catch (e) {
    ElMessage.error(e.message || '保存定位失败')
  } finally {
    stanceSaving.value = false
  }
}

async function save() {
  if (!tenantId.value) return
  saving.value = true
  try {
    const payload = items.value.map((it, idx) => ({
      engine_key: it.engine_key,
      display_name: it.display_name,
      enabled: !!it.enabled,
      note: it.note || null,
      sort_order: it.sort_order ?? idx * 10,
      sample_mode: it.sample_mode || 'mock_persona',
      api_base_url: it.api_base_url || null,
      model: it.model || null,
      api_key: it.api_key && it.api_key.length >= 8 ? it.api_key : undefined,
      clear_api_key: !!it.clear_api_key,
    }))
    const data = await putGeoTrackingEngines(tenantId.value, payload)
    items.value = (data.items || []).map((it) => ({
      ...it,
      sample_mode: it.sample_mode || 'mock_persona',
      api_base_url: it.api_base_url || '',
      model: it.model || '',
      api_key: '',
      clear_api_key: false,
    }))
    ElMessage.success('已保存引擎配置')
    ops.value = await fetchVisibilityPatrolOpsStatus(tenantId.value).catch(() => ops.value)
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">引擎配置</div>
        <div class="page-desc">
          控制可见度登记与全自动巡检可用的模型通道；真采样需「兼容接口 + Key」。
        </div>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        <router-link class="el-button" to="/geo/visibility/patrol">全自动巡检</router-link>
        <router-link class="el-button" to="/geo/visibility">登记快照</router-link>
        <router-link class="el-button" to="/geo/ai-settings">AI 配置</router-link>
      </div>
    </div>

    <details class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li v-for="(line, i) in REPORT_GLOSSARY.engines" :key="i">{{ line }}</li>
      </ul>
    </details>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <el-card v-if="stance" shadow="never" class="mb stance-card">
      <template #header>
        <div class="stance-head">
          <span>监测商业定位</span>
          <el-tag size="small" type="warning">{{ stance.banner?.badge || stance.monitoring_stance }}</el-tag>
        </div>
      </template>
      <p class="stance-sum">{{ stance.banner?.summary || '' }}</p>
      <ul class="stance-msgs">
        <li v-for="(m, i) in stance.banner?.messages || []" :key="i">{{ m }}</li>
      </ul>
      <div class="stance-options">
        <el-radio-group
          :model-value="stance.monitoring_stance"
          :disabled="stanceSaving"
          @change="saveStance"
        >
          <el-radio
            v-for="opt in stance.options || []"
            :key="opt.key"
            :value="opt.key"
            :label="opt.key"
            border
            class="stance-radio"
          >
            <b>{{ opt.label }}</b>
            <div class="opt-hint">{{ opt.summary }}</div>
          </el-radio>
        </el-radio-group>
      </div>
      <p class="geo-panel-desc mt">
        产品默认 <b>混合模式</b>：有 Key 真采样、无 Key 模拟，报表强制标注样本构成。
        签约交付建议切到「仅真采样」或在交付摘要中披露模拟占比。
      </p>
    </el-card>

    <div class="geo-kpi-grid mb">
      <div class="geo-kpi">
        <div class="kpi-label">引擎总数</div>
        <div class="kpi-value">{{ items.length }}</div>
        <div class="kpi-hint">含已停用</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">已启用</div>
        <div class="kpi-value">{{ enabledCount }}</div>
        <div class="kpi-hint">会出现在巡检默认列表</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">真采样就绪</div>
        <div class="kpi-value">{{ realReadyCount }}</div>
        <div class="kpi-hint">
          与巡检页一致
          <template v-if="ops?.engines">
            · 运维侧 {{ (ops.engines || []).filter((e) => e.ready_for_real).length }}
          </template>
        </div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">今日巡检配额</div>
        <div class="kpi-value">
          {{ ops?.quota?.used_today ?? '—' }}
          <span class="kpi-den">/ {{ ops?.quota?.max_per_day ?? '—' }}</span>
        </div>
        <div class="kpi-hint">剩余 {{ ops?.quota?.remaining ?? '—' }}</div>
      </div>
    </div>

    <div v-if="!items.length && !loading" class="geo-empty mb">
      <div class="empty-title">暂无引擎</div>
      <div>租户初始化后应自动生成默认引擎；刷新或检查 API / 租户选择。</div>
    </div>

    <section v-else class="geo-panel">
      <div class="panel-title">通道列表</div>
      <p class="geo-panel-desc">
        切换为「兼容接口真采样」后请填 Base URL、Model 并粘贴 API Key，再保存。
        Key 仅在提交时写入，页面不会回显原文。
      </p>
      <el-table :data="items" stripe empty-text="暂无引擎">
        <el-table-column label="引擎" width="120">
          <template #default="{ row }">
            <div class="eng-key">{{ row.engine_key }}</div>
            <div class="eng-hint">{{ engineDisplay(row.engine_key) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="显示名" min-width="120">
          <template #default="{ row }">
            <el-input v-model="row.display_name" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" />
          </template>
        </el-table-column>
        <el-table-column label="采样模式" width="150">
          <template #default="{ row }">
            <el-select v-model="row.sample_mode" size="small" style="width: 100%">
              <el-option :label="modeLabel('mock_persona')" value="mock_persona" />
              <el-option :label="modeLabel('openai_compat')" value="openai_compat" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="就绪状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="readinessLabel(row).type">
              {{ readinessLabel(row).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="接口地址 (Base URL)" min-width="180">
          <template #default="{ row }">
            <el-input
              v-model="row.api_base_url"
              size="small"
              :disabled="row.sample_mode !== 'openai_compat'"
              placeholder="真采样时必填"
            />
          </template>
        </el-table-column>
        <el-table-column label="模型名" width="140">
          <template #default="{ row }">
            <el-input
              v-model="row.model"
              size="small"
              :disabled="row.sample_mode !== 'openai_compat'"
              placeholder="真采样时必填"
            />
          </template>
        </el-table-column>
        <el-table-column label="API Key" min-width="160">
          <template #default="{ row }">
            <el-input
              v-model="row.api_key"
              size="small"
              type="password"
              show-password
              :disabled="row.sample_mode !== 'openai_compat'"
              :placeholder="row.api_key_configured ? '已配置 · 留空保留' : '未配置 · 至少 8 位'"
            />
            <el-checkbox
              v-if="row.api_key_configured && row.sample_mode === 'openai_compat'"
              v-model="row.clear_api_key"
              size="small"
            >
              清除 Key
            </el-checkbox>
          </template>
        </el-table-column>
        <el-table-column label="排序" width="100">
          <template #default="{ row }">
            <el-input-number
              v-model="row.sort_order"
              size="small"
              :step="10"
              controls-position="right"
            />
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.mt { margin-top: 10px; }
.kpi-den { font-size: 14px; font-weight: 500; color: #94a3b8; margin-left: 2px; }
.eng-key { font-weight: 600; color: #1f2937; font-size: 13px; }
.eng-hint { font-size: 11px; color: #94a3b8; margin-top: 2px; }
.stance-card { border: 1px solid #fde68a; background: #fffbeb; }
.stance-head { display: flex; align-items: center; gap: 8px; font-weight: 650; }
.stance-sum { font-size: 13px; color: #78350f; margin: 0 0 8px; line-height: 1.5; }
.stance-msgs { font-size: 12px; color: #92400e; margin: 0 0 12px; padding-left: 18px; }
.stance-options :deep(.el-radio-group) {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: stretch;
}
.stance-radio { height: auto !important; margin: 0 !important; padding: 10px 12px !important; white-space: normal; }
.opt-hint { font-size: 11px; color: #78716c; font-weight: 400; margin-top: 4px; line-height: 1.4; }
</style>
