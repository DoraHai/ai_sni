<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchVisibilityPatrolSettings,
  listGeoTrackingEngines,
  putGeoTrackingEngines,
  putVisibilityPatrolSettings,
} from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { engineColor } from '../../utils/geoSnapshotSummary'
import { useGeoTenant } from '../../composables/useGeoTenant'
import {
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
const patrol = ref({
  enabled: false,
  window_start_hour: 8,
  window_end_hour: 22,
  interval_hours: 24,
  prompt_limit: 20,
})

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
    ElMessage.warning('阿里云百炼仅可用于 DeepSeek 监测')
    return
  }
  row.sample_mode = 'openai_compat'
  row.api_base_url = BAILIAN_PRESET.api_base_url
  row.model = BAILIAN_PRESET.model
}

function cardBadge(row) {
  if (row.enabled && dashscopeBlocked(row)) return { text: '百炼仅 DeepSeek', cls: 'red' }
  if (row.enabled) return { text: '监测中', cls: 'green' }
  return { text: '未开启', cls: 'amber' }
}

function modeLabel(mode) {
  return labelOf(SAMPLE_MODE_LABEL, mode || 'mock_persona', mode)
}

function hydrateItems(list) {
  return (list || []).map((it) => ({
    ...it,
    sample_mode: it.sample_mode || 'mock_persona',
    api_base_url: it.api_base_url || '',
    model: it.model || '',
    api_key: '',
    clear_api_key: false,
  }))
}

function enginePayload(it, idx) {
  return {
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
  }
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    items.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [data, patrolRes] = await Promise.all([
      listGeoTrackingEngines(tenantId.value, false),
      fetchVisibilityPatrolSettings(tenantId.value).catch(() => null),
    ])
    items.value = hydrateItems(data.items)
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

function openConfig(row) {
  editing.value = row
}

function closeConfig() {
  editing.value = null
}

async function saveConfig() {
  const row = editing.value
  if (!tenantId.value || !row) return
  if (row.enabled && dashscopeBlocked(row)) {
    ElMessage.error('百炼只调用 DeepSeek：请先关掉监测，或改成该引擎的官方兼容地址')
    return
  }
  saving.value = true
  try {
    const data = await putGeoTrackingEngines(
      tenantId.value,
      items.value.map((it, idx) => enginePayload(it, idx)),
    )
    items.value = hydrateItems(data.items)
    ElMessage.success('已保存引擎配置')
    closeConfig()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
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
    sub="点击卡片配置各引擎接口。阿里云百炼仅用于 DeepSeek 监测"
    :loading="loading"
  >
    <template #actions>
      <button class="gd-btn" @click="load">刷新</button>
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
            <span class="gd-badge" :class="cardBadge(row).cls">{{ cardBadge(row).text }}</span>
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
            title="当前接口为阿里云百炼，仅支持 DeepSeek 监测。请填写该引擎的官方兼容接口，或关闭监测。"
          />
          <el-form-item v-if="isDeepseekEngine(editing.engine_key)">
            <el-button @click="applyBailian(editing)">使用阿里云百炼</el-button>
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

      <div v-if="!items.length && !loading" class="geo-empty mb">
        <div class="empty-title">暂无引擎</div>
        <div>租户初始化后应自动生成默认引擎；刷新或检查 API / 租户选择。</div>
      </div>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
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
