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
const supportServices = ref([])
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

function cardBadge(row) {
  if (!row.enabled) return { text: '未开启', cls: 'amber' }
  if (row.api_key_configured) return { text: '平台已配置', cls: 'green' }
  if (row.platform_managed) return { text: '平台待配置', cls: 'amber' }
  return { text: '仅模拟', cls: 'amber' }
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
  }))
}

function enginePayload(it, idx) {
  return {
    engine_key: it.engine_key,
    display_name: it.display_name,
    enabled: !!it.enabled,
    note: it.note || null,
    sort_order: it.sort_order ?? idx * 10,
  }
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择已开通 GEO 的客户'
    items.value = []
    supportServices.value = []
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
    supportServices.value = data.support_services || []
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
    supportServices.value = []
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

async function saveTable() {
  if (!tenantId.value) return
  saving.value = true
  try {
    const data = await putGeoTrackingEngines(
      tenantId.value,
      items.value.map((it, idx) => enginePayload(it, idx)),
    )
    items.value = hydrateItems(data.items)
    ElMessage.success('已保存租户监测引擎')
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
    title="AI 引擎管理"
    :show-period="false"
    sub="平台统一管理引擎接口与密钥；客户只需选择参与监测的引擎"
    :loading="loading"
  >
    <template #actions>
      <span class="more">AI 能力由平台统一提供</span>
      <button class="gd-btn" type="button" @click="load">刷新</button>
      <button class="gd-btn primary" type="button" :disabled="saving" @click="saveTable">保存</button>
    </template>
    <div class="geo-dash">
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <section class="gd-card mb">
        <div class="gd-hd">
          <h3>租户监测引擎</h3>
          <span class="more">启用后可用于可见度快照与巡检</span>
        </div>
        <div class="gd-bd" style="padding:0">
          <el-table :data="items" empty-text="暂无引擎" size="small">
            <el-table-column label="启用" width="80">
              <template #default="{ row }">
                <el-switch v-model="row.enabled" size="small" />
              </template>
            </el-table-column>
            <el-table-column label="引擎 key" min-width="120">
              <template #default="{ row }">
                <span class="muted">{{ row.engine_key }}</span>
              </template>
            </el-table-column>
            <el-table-column label="展示名" min-width="160">
              <template #default="{ row }">
                <el-input v-model="row.display_name" size="small" />
              </template>
            </el-table-column>
            <el-table-column label="排序" width="110">
              <template #default="{ row }">
                <el-input-number v-model="row.sort_order" size="small" :min="0" :max="9999" controls-position="right" />
              </template>
            </el-table-column>
            <el-table-column label="备注" min-width="180">
              <template #default="{ row }">
                <el-input v-model="row.note" size="small" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openConfig(row)">状态</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </section>

      <details class="adv mb">
        <summary>平台状态与巡检设置</summary>
        <div class="adv-body">
          <p class="hint">接口、模型与密钥由平台统一维护；客户可查看状态并设置巡检调度。</p>
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
                <div class="gd-sub" style="margin:0">{{ row.engine_key }} · 查看平台状态</div>
              </div>
              <div class="geo-eng-flags">
                <span class="gd-badge" :class="cardBadge(row).cls">{{ cardBadge(row).text }}</span>
              </div>
            </button>
          </div>

          <div class="gd-card" style="margin-top:16px">
            <div class="gd-hd"><h3>巡检设置</h3></div>
            <div class="gd-bd" style="max-width:560px;display:flex;flex-direction:column;gap:14px">
              <div class="geo-set-row">
                <span>巡检频率</span>
                <div class="geo-chips" style="margin:0">
                  <button class="geo-chip" :class="{ active: patrol.interval_hours === 24 }" type="button" @click="savePatrol({ interval_hours: 24 })">每日 1 次</button>
                  <button class="geo-chip" :class="{ active: patrol.interval_hours === 6 }" type="button" @click="savePatrol({ interval_hours: 6 })">每 6 小时</button>
                  <button class="geo-chip" :class="{ active: patrol.interval_hours === 1 }" type="button" @click="savePatrol({ interval_hours: 1 })">每小时</button>
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
        </div>
      </details>

      <div v-if="supportServices.length" class="gd-card geo-support-card">
        <div class="gd-hd"><h3>联网搜索辅助服务</h3></div>
        <div class="gd-bd">
          <div v-for="service in supportServices" :key="service.service_key" class="geo-set-row">
            <div>
              <b>{{ service.display_name }}</b>
              <div class="gd-sub">用于搜索与信源补充，不作为 AI 引擎回答样本</div>
            </div>
            <span class="gd-badge" :class="service.configured ? 'green' : 'amber'">
              {{ service.configured ? '平台已配置' : '平台待配置' }}
            </span>
          </div>
        </div>
      </div>

      <el-dialog
        v-model="configOpen"
        :title="editing ? `${editing.display_name || engineDisplay(editing.engine_key)} 平台状态` : '引擎平台状态'"
        width="520px"
        class="geo-form-dialog"
        @closed="closeConfig"
      >
        <el-form v-if="editing" label-width="96px" label-position="right">
          <el-form-item label="监测">
            <el-switch v-model="editing.enabled" />
          </el-form-item>
          <el-alert
            :type="editing.api_key_configured ? 'success' : 'warning'"
            :closable="false"
            show-icon
            :title="editing.api_key_configured ? '平台接口已配置；巡检将调用真实 API，调用失败会单独记录' : '平台尚未配置该接口，当前使用人设模拟样本'"
          />
          <div class="geo-platform-meta">
            <div><span>提供商</span><b>{{ editing.provider_label || '平台未配置' }}</b></div>
            <div><span>模型</span><b>{{ editing.model || '—' }}</b></div>
            <div><span>采样方式</span><b>{{ modeLabel(editing.sample_mode) }}</b></div>
          </div>
          <div class="gd-sub geo-managed-note">API Key、接口地址和模型由平台管理员统一维护，客户侧不可查看或修改。</div>
        </el-form>
        <template #footer>
          <el-button @click="closeConfig">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveConfig">保存</el-button>
        </template>
      </el-dialog>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.muted { color: #6b7280; }
.adv {
  background: #fff;
  border: 1px solid #eef0f4;
  border-radius: 10px;
  padding: 10px 14px;
}
.adv summary {
  cursor: pointer;
  font-weight: 650;
  color: #374151;
}
.adv-body { margin-top: 12px; }
.hint { font-size: 12px; color: #6b7280; margin: 0 0 12px; }
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
.geo-support-card { margin-bottom: 16px; }
.geo-platform-meta {
  display: grid;
  gap: 10px;
  margin-top: 14px;
  padding: 14px;
  border-radius: 10px;
  background: #f7f9fc;
}
.geo-platform-meta > div { display: flex; justify-content: space-between; gap: 16px; }
.geo-platform-meta span { color: #77849a; }
.geo-platform-meta b { text-align: right; overflow-wrap: anywhere; }
.geo-managed-note { margin-top: 12px; }
</style>
