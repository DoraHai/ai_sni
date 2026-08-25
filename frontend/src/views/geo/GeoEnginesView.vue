<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchMonitoringStance,
  fetchVisibilityPatrolOpsStatus,
  fetchVisibilityPatrolSettings,
  listGeoTrackingEngines,
  putGeoTrackingEngines,
  putMonitoringStance,
  putVisibilityPatrolSettings,
} from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { engineColor } from '../../utils/geoSnapshotSummary'
import NeedHintAlert from '../../components/NeedHintAlert.vue'
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
const editing = ref(null)
const configOpen = computed({
  get: () => !!editing.value,
  set: (open) => {
    if (!open) editing.value = null
  },
})
const ops = ref(null)
const stance = ref(null)
const stanceSaving = ref(false)
const patrol = ref({
  enabled: false,
  window_start_hour: 8,
  window_end_hour: 22,
  interval_hours: 24,
  prompt_limit: 20,
})

const enabledCount = computed(() => items.value.filter((r) => r.enabled).length)
const realReadyCount = computed(
  () => items.value.filter((r) => isRealReady(r)).length,
)
const skipPreviewItems = computed(() => stance.value?.skip_preview?.items || [])
const skipPreviewSummary = computed(
  () => stance.value?.skip_preview?.summary || '',
)
const skipCount = computed(
  () => stance.value?.skip_preview?.enabled_will_skip ?? 0,
)
// 监测定位 / 通道大表仍收起；每引擎只露出模型、地址、Key。
const showAdvancedConfig = false
const BAILIAN_PRESET = {
  api_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  model: 'deepseek-v3',
}

function isDeepseekEngine(key) {
  return String(key || '').toLowerCase().includes('deepseek')
}

function isDashscopeUrl(url) {
  const u = String(url || '').toLowerCase()
  return u.includes('dashscope') || u.includes('aliyuncs.com')
}

function dashscopeBlocked(row) {
  return !!(row && !isDeepseekEngine(row.engine_key) && isDashscopeUrl(row.api_base_url))
}

function applyBailian(row) {
  if (!isDeepseekEngine(row.engine_key)) {
    ElMessage.warning('阿里云百炼只用于 DeepSeek')
    return
  }
  row.sample_mode = 'openai_compat'
  row.api_base_url = BAILIAN_PRESET.api_base_url
  row.model = BAILIAN_PRESET.model
}

function isRealReady(row) {
  return (
    row.enabled &&
    (row.sample_mode || 'mock_persona') === 'openai_compat' &&
    !!row.api_key_configured &&
    !dashscopeBlocked(row)
  )
}

function readinessLabel(row) {
  if (!row.enabled) return { text: '已停用', type: 'info' }
  if (dashscopeBlocked(row)) return { text: '百炼仅 DeepSeek', type: 'danger' }
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
    const [data, opsRes, stanceRes, patrolRes] = await Promise.all([
      listGeoTrackingEngines(tenantId.value, false),
      fetchVisibilityPatrolOpsStatus(tenantId.value).catch(() => null),
      fetchMonitoringStance(tenantId.value).catch(() => null),
      fetchVisibilityPatrolSettings(tenantId.value).catch(() => null),
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
    if (patrolRes) {
      patrol.value = {
        enabled: !!patrolRes.enabled,
        window_start_hour: patrolRes.window_start_hour ?? 8,
        window_end_hour: patrolRes.window_end_hour ?? 22,
        interval_hours: patrolRes.interval_hours ?? 24,
        prompt_limit: patrolRes.prompt_limit ?? 20,
      }
    }
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
  const blocked = items.value.filter((row) => row.enabled && dashscopeBlocked(row))
  if (blocked.length) {
    for (const row of blocked) row.enabled = false
    ElMessage.warning(
      `已关闭 ${blocked.map((r) => engineDisplay(r.engine_key)).join('、')}：百炼只用于 DeepSeek`,
    )
  }
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
    return true
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
    return false
  } finally {
    saving.value = false
  }
}

function openConfig(row) {
  editing.value = row
}

function closeConfig() {
  editing.value = null
}

async function saveConfig() {
  const ok = await save()
  if (ok) closeConfig()
}

async function savePatrol(patch = {}) {
  if (!tenantId.value) return
  const next = { ...patrol.value, ...patch }
  patrol.value = next
  try {
    const saved = await putVisibilityPatrolSettings({
      tenant_id: tenantId.value,
      enabled: next.enabled,
      window_start_hour: next.window_start_hour,
      window_end_hour: next.window_end_hour,
      interval_hours: next.interval_hours,
      prompt_limit: next.prompt_limit,
    })
    patrol.value = {
      enabled: !!saved.enabled,
      window_start_hour: saved.window_start_hour ?? next.window_start_hour,
      window_end_hour: saved.window_end_hour ?? next.window_end_hour,
      interval_hours: saved.interval_hours ?? next.interval_hours,
      prompt_limit: saved.prompt_limit ?? next.prompt_limit,
    }
    ElMessage.success('巡检设置已保存')
  } catch (e) {
    ElMessage.error(e.message || '保存巡检失败')
  }
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="引擎"
    :show-period="false"
    sub="点卡片配置模型。阿里云百炼只调用 DeepSeek"
    :loading="loading"
  >
    <template #actions>
      <button class="gd-btn" @click="load">刷新</button>
      <button class="gd-btn primary" :disabled="saving" @click="save">保存</button>
    </template>
    <div class="geo-dash">
    <div class="geo-eng-grid">
      <button
        v-for="row in items"
        :key="row.engine_key"
        type="button"
        class="gd-card geo-eng-card"
        @click="openConfig(row)"
      >
        <span class="geo-plogo" :style="{ background: engineColor(row.engine_key) }">
          {{ engineDisplay(row.engine_key).slice(0, 1) }}
        </span>
        <div class="geo-eng-copy">
          <b>{{ row.display_name || engineDisplay(row.engine_key) }}</b>
          <div class="gd-sub" style="margin:0">{{ row.engine_key }} · 点击配置</div>
        </div>
        <div class="geo-eng-flags">
          <span
            class="gd-badge"
            :class="row.enabled && dashscopeBlocked(row) ? 'red' : row.enabled ? 'green' : 'amber'"
          >
            {{ row.enabled && dashscopeBlocked(row) ? '需改配置' : row.enabled ? '监测中' : '未开启' }}
          </span>
          <span class="gd-badge" :class="readinessLabel(row).type === 'success' ? 'green' : readinessLabel(row).type === 'danger' ? 'red' : 'amber'">
            {{ readinessLabel(row).text }}
          </span>
        </div>
      </button>
    </div>

    <el-dialog
      v-model="configOpen"
      :title="editing ? `配置 ${editing.display_name || engineDisplay(editing.engine_key)}` : '配置引擎'"
      width="520px"
      class="geo-form-dialog"
      @closed="closeConfig"
    >
      <el-form v-if="editing" label-width="96px" label-position="right">
        <el-form-item label="监测">
          <el-switch v-model="editing.enabled" />
        </el-form-item>
        <el-form-item label="采样">
          <el-select v-model="editing.sample_mode" style="width: 100%">
            <el-option :label="modeLabel('mock_persona')" value="mock_persona" />
            <el-option :label="modeLabel('openai_compat')" value="openai_compat" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input
            v-model="editing.api_base_url"
            :disabled="editing.sample_mode !== 'openai_compat'"
            placeholder="真采样时必填"
          />
        </el-form-item>
        <el-form-item label="模型">
          <el-input
            v-model="editing.model"
            :disabled="editing.sample_mode !== 'openai_compat'"
            placeholder="真采样时必填"
          />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="editing.api_key"
            type="password"
            show-password
            :disabled="editing.sample_mode !== 'openai_compat'"
            :placeholder="editing.api_key_configured ? '已配置 · 留空保留' : '至少 8 位'"
          />
          <el-checkbox
            v-if="editing.api_key_configured && editing.sample_mode === 'openai_compat'"
            v-model="editing.clear_api_key"
          >
            清除 Key
          </el-checkbox>
        </el-form-item>
        <el-alert
          v-if="dashscopeBlocked(editing)"
          type="error"
          :closable="false"
          show-icon
          title="百炼只调用 DeepSeek。请改成该厂自己的地址，或关掉监测。"
        />
        <el-form-item v-if="isDeepseekEngine(editing.engine_key)">
          <el-button @click="applyBailian(editing)">填入百炼 DeepSeek</el-button>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeConfig">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveConfig">保存</el-button>
      </template>
    </el-dialog>

    <div class="gd-card" style="margin-bottom:16px">
      <div class="gd-hd"><h3>巡检设置</h3></div>
      <div class="gd-bd" style="max-width:560px;display:flex;flex-direction:column;gap:14px">
        <div class="geo-set-row">
          <span>巡检频率</span>
          <div class="geo-chips" style="margin:0">
            <button class="geo-chip" :class="{ active: patrol.interval_hours === 24 }" @click="savePatrol({ interval_hours: 24 })">每日 1 次</button>
            <button class="geo-chip" :class="{ active: patrol.interval_hours === 6 }" @click="savePatrol({ interval_hours: 6 })">每 6 小时</button>
            <button class="geo-chip" :class="{ active: patrol.interval_hours === 1 }" @click="savePatrol({ interval_hours: 1 })">每小时</button>
          </div>
        </div>
        <div class="geo-set-row">
          <span>巡检时间</span>
          <el-input-number
            :model-value="patrol.window_start_hour"
            :min="0"
            :max="23"
            size="small"
            @change="(v) => savePatrol({ window_start_hour: Number(v) })"
          />
          <span>至</span>
          <el-input-number
            :model-value="patrol.window_end_hour"
            :min="0"
            :max="23"
            size="small"
            @change="(v) => savePatrol({ window_end_hour: Number(v) })"
          />
        </div>
        <div class="geo-set-row">
          <span>每轮提问上限</span>
          <el-input-number
            :model-value="patrol.prompt_limit"
            :min="1"
            :max="50"
            size="small"
            @change="(v) => savePatrol({ prompt_limit: Number(v) })"
          />
        </div>
        <div class="geo-set-row">
          <span>定时巡检</span>
          <span
            class="gd-badge"
            :class="patrol.enabled ? 'green' : 'amber'"
            style="cursor:pointer"
            @click="savePatrol({ enabled: !patrol.enabled })"
          >{{ patrol.enabled ? '已开启' : '未开启' }}</span>
        </div>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />
    <NeedHintAlert v-if="showAdvancedConfig" />

    <el-card v-if="showAdvancedConfig && stance" shadow="never" class="mb stance-card">
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
      <div v-if="skipPreviewItems.length" class="skip-preview">
        <div class="skip-preview-head">
          <span class="skip-title">巡检跳过预览</span>
          <el-tag size="small" :type="skipCount > 0 ? 'warning' : 'success'">
            {{ skipPreviewSummary || '—' }}
          </el-tag>
        </div>
        <p class="skip-hint">
          按当前监测定位，预测各引擎在巡检时是否执行（不调用模型、不落库）。
          切到「仅真采样」后，无 Key / 人设模拟引擎会被跳过。
        </p>
        <el-table :data="skipPreviewItems" size="small" max-height="220" stripe>
          <el-table-column label="引擎" width="120">
            <template #default="{ row }">
              {{ row.display_name || engineDisplay(row.engine_key) || row.engine_key }}
            </template>
          </el-table-column>
          <el-table-column label="启用" width="70" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.enabled ? 'success' : 'info'">
                {{ row.enabled ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="结果" width="100" align="center">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.will_skip ? 'danger' : row.will_run ? 'success' : 'info'"
              >
                {{ row.will_skip ? '跳过' : row.will_run ? '执行' : '—' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="说明" min-width="200">
            <template #default="{ row }">{{ row.reason_label || '—' }}</template>
          </el-table-column>
          <el-table-column label="有效模式" width="120">
            <template #default="{ row }">
              {{ row.sample_mode_effective ? modeLabel(row.sample_mode_effective) : '—' }}
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <div v-if="showAdvancedConfig" class="geo-kpi-grid mb">
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

    <section v-if="showAdvancedConfig && items.length" class="geo-panel">
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
  </GeoWorkbenchPage>
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
.skip-preview {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed #fcd34d;
}
.skip-preview-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.skip-title { font-weight: 650; font-size: 13px; color: #78350f; }
.skip-hint { font-size: 12px; color: #92400e; margin: 0 0 10px; line-height: 1.45; }
.geo-eng-card {
  text-align: left;
  width: 100%;
  font: inherit;
  color: inherit;
}
.geo-eng-copy { flex: 1; min-width: 0; }
.geo-eng-flags {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  margin-left: auto;
}
</style>
