<script setup>
/**
 * AI 可见度 · 全自动巡检
 * 多机会词 × 启用引擎探测；prefer_real 优先 openai_compat；auto_persist 直接落库快照。
 */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchVisibilityPatrolSettings,
  getVisibilityPatrolRun,
  listVisibilityPatrolRuns,
  listGeoTrackingEngines,
  putVisibilityPatrolSettings,
  startVisibilityPatrolRun,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const { tenantId } = useGeoTenant()

const loading = ref(false)
const starting = ref(false)
const savingSettings = ref(false)
const error = ref('')
const settings = ref({
  enabled: false,
  daily_hour: 6,
  auto_persist: true,
  prefer_real: true,
  prompt_limit: 20,
  engine_keys: null,
})
const runs = ref([])
const engines = ref([])
const detail = ref(null)
const pollTimer = ref(null)

const form = ref({
  auto_persist: true,
  prefer_real: true,
  prompt_limit: 20,
  engine_keys: [],
})

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [s, r, eng] = await Promise.all([
      fetchVisibilityPatrolSettings(tenantId.value),
      listVisibilityPatrolRuns(tenantId.value, 30),
      listGeoTrackingEngines(tenantId.value, false),
    ])
    settings.value = s
    form.value.auto_persist = s.auto_persist !== false
    form.value.prefer_real = s.prefer_real !== false
    form.value.prompt_limit = s.prompt_limit || 20
    form.value.engine_keys = s.engine_keys || []
    runs.value = r.items || []
    engines.value = eng.items || []
    if (!form.value.engine_keys?.length) {
      form.value.engine_keys = (engines.value.filter((e) => e.enabled) || []).map(
        (e) => e.engine_key,
      )
    }
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  savingSettings.value = true
  try {
    settings.value = await putVisibilityPatrolSettings({
      tenant_id: tenantId.value,
      enabled: settings.value.enabled,
      daily_hour: settings.value.daily_hour,
      auto_persist: form.value.auto_persist,
      prefer_real: form.value.prefer_real,
      prompt_limit: form.value.prompt_limit,
      engine_keys: form.value.engine_keys?.length ? form.value.engine_keys : null,
    })
    ElMessage.success('巡检设置已保存（定时任务由主站 scheduler 每小时检查）')
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    savingSettings.value = false
  }
}

async function startRun() {
  starting.value = true
  try {
    const res = await startVisibilityPatrolRun({
      tenant_id: tenantId.value,
      auto_persist: form.value.auto_persist,
      prefer_real: form.value.prefer_real,
      prompt_limit: form.value.prompt_limit,
      engine_keys: form.value.engine_keys?.length ? form.value.engine_keys : null,
      run_async: true,
    })
    ElMessage.success(`巡检已启动 #${res.run?.id}（后台执行，自动落库=${form.value.auto_persist}）`)
    await load()
    if (res.run?.id) {
      detail.value = res.run
      startPoll(res.run.id)
    }
  } catch (e) {
    ElMessage.error(e.message || '启动失败')
  } finally {
    starting.value = false
  }
}

function startPoll(runId) {
  stopPoll()
  pollTimer.value = setInterval(async () => {
    try {
      const r = await getVisibilityPatrolRun(tenantId.value, runId)
      detail.value = r
      if (r.status === 'completed' || r.status === 'failed') {
        stopPoll()
        await load()
        if (r.status === 'completed') {
          ElMessage.success(
            `巡检 #${runId} 完成：成功 ${r.summary?.cells_ok || 0} · 失败 ${r.summary?.cells_fail || 0} · 落库 ${r.summary?.snapshots_created || 0}`,
          )
        } else {
          ElMessage.error(`巡检 #${runId} 失败：${r.error || '未知'}`)
        }
      }
    } catch {
      /* ignore poll errors */
    }
  }, 2500)
}

function stopPoll() {
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

async function openRun(row) {
  try {
    detail.value = await getVisibilityPatrolRun(tenantId.value, row.id)
    if (row.status === 'running' || row.status === 'pending') startPoll(row.id)
  } catch (e) {
    ElMessage.error(e.message || '加载失败')
  }
}

function statusType(s) {
  if (s === 'completed') return 'success'
  if (s === 'failed') return 'danger'
  if (s === 'running') return 'warning'
  return 'info'
}

watch(tenantId, load)
onMounted(load)
onUnmounted(stopPoll)
</script>

<template>
  <div v-loading="loading" class="patrol-page">
    <div class="page-header">
      <div>
        <div class="crumbs">
          <router-link to="/geo/visibility">AI 可见度</router-link>
          <span> / </span>
          <span>全自动巡检</span>
        </div>
        <div class="page-title">全自动巡检</div>
        <div class="page-desc">
          对机会词 × 启用引擎批量探测；优先
          <code>openai_compat</code> 真采样（引擎已配 Key），否则租户 LLM + 人设模拟。
          开启「自动落库」后结果直接写入回答快照。
        </div>
      </div>
      <div class="header-actions">
        <el-button @click="router.push('/geo/visibility')">登记快照</el-button>
        <el-button @click="router.push('/geo/engines')">引擎配置</el-button>
        <el-button type="primary" :loading="starting" @click="startRun">立即巡检</el-button>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <div class="layout">
      <section class="panel">
        <div class="panel-title">巡检参数</div>
        <el-form label-position="top" size="small">
          <el-form-item label="机会词数量上限">
            <el-input-number v-model="form.prompt_limit" :min="1" :max="50" />
          </el-form-item>
          <el-form-item label="引擎（多选，空=全部启用）">
            <el-select v-model="form.engine_keys" multiple clearable style="width: 100%">
              <el-option
                v-for="e in engines"
                :key="e.engine_key"
                :label="`${e.display_name || e.engine_key} · ${e.sample_mode || 'mock_persona'}${e.enabled ? '' : '（停用）'}`"
                :value="e.engine_key"
              />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="form.prefer_real">优先真采样（openai_compat / 引擎 Key）</el-checkbox>
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="form.auto_persist">自动落库为回答快照（真实落地）</el-checkbox>
          </el-form-item>
        </el-form>

        <el-divider />
        <div class="panel-title">定时全自动（主站 scheduler）</div>
        <el-form label-position="top" size="small">
          <el-form-item>
            <el-switch v-model="settings.enabled" active-text="开启每日定时" />
          </el-form-item>
          <el-form-item label="每日执行小时（Asia/Shanghai）">
            <el-input-number v-model="settings.daily_hour" :min="0" :max="23" />
          </el-form-item>
          <el-button type="primary" plain :loading="savingSettings" @click="saveSettings">
            保存定时设置
          </el-button>
          <p class="hint">
            主站进程 scheduler 每小时 :05 检查；仅当 enabled 且 daily_hour 匹配当前小时时启动巡检。
            geo_main 独立部署时请保证主站或带调度的 worker 在跑。
          </p>
        </el-form>
      </section>

      <section class="panel">
        <div class="panel-title">巡检历史</div>
        <el-table :data="runs" size="small" empty-text="暂无巡检" @row-click="openRun">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row.status)">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="trigger" label="触发" width="90" />
          <el-table-column label="摘要" min-width="200">
            <template #default="{ row }">
              <span v-if="row.summary">
                词{{ row.summary.prompts }} · 引擎{{ row.summary.engines }} ·
                成功{{ row.summary.cells_ok }} · 落库{{ row.summary.snapshots_created }} ·
                真采样{{ row.summary.real_samples }}
              </span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建" width="160" />
        </el-table>

        <div v-if="detail" class="detail">
          <div class="panel-title">
            运行 #{{ detail.id }}
            <el-tag size="small" :type="statusType(detail.status)">{{ detail.status }}</el-tag>
          </div>
          <p v-if="detail.error" class="err">{{ detail.error }}</p>
          <el-table
            v-if="detail.items?.length"
            :data="detail.items"
            size="small"
            max-height="360"
            stripe
          >
            <el-table-column prop="prompt_id" label="词ID" width="70" />
            <el-table-column prop="engine" label="引擎" width="100" />
            <el-table-column label="结果" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.ok ? 'success' : 'danger'">
                  {{ row.ok ? 'OK' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="采样" width="110">
              <template #default="{ row }">
                {{ row.sample_mode || '—' }}
                <span v-if="row.simulated === true" class="muted">模拟</span>
                <span v-else-if="row.simulated === false" class="ok">真</span>
              </template>
            </el-table-column>
            <el-table-column prop="snapshot_id" label="快照ID" width="90" />
            <el-table-column label="摘要/错误" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.error || (row.raw_text || '').slice(0, 80) }}
              </template>
            </el-table-column>
          </el-table>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.patrol-page { padding: 4px 2px 28px; }
.page-header {
  display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.crumbs { font-size: 12px; color: #9ca3af; margin-bottom: 4px; }
.crumbs a { color: #7c3aed; text-decoration: none; }
.page-title { font-size: 20px; font-weight: 700; color: #1e2330; }
.page-desc { font-size: 13px; color: #6b7280; margin-top: 4px; max-width: 640px; line-height: 1.5; }
.page-desc code { background: #f5f0ff; padding: 1px 6px; border-radius: 4px; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.mb { margin-bottom: 12px; }
.layout {
  display: grid;
  grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.panel {
  background: #fff;
  border: 1px solid #e8e4f5;
  border-radius: 12px;
  padding: 14px 16px;
  min-width: 0;
}
.panel-title {
  font-size: 14px; font-weight: 700; color: #374151; margin-bottom: 12px;
  display: flex; gap: 8px; align-items: center;
}
.hint { font-size: 12px; color: #9ca3af; margin-top: 10px; line-height: 1.45; }
.detail { margin-top: 16px; border-top: 1px solid #eee; padding-top: 12px; }
.err { color: #b91c1c; font-size: 13px; }
.muted { color: #9ca3af; font-size: 11px; margin-left: 4px; }
.ok { color: #047857; font-size: 11px; margin-left: 4px; }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
}
</style>
