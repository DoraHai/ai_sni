<script setup>
/**
 * AI 可见度 · 全自动巡检
 * 多机会词 × 启用引擎探测；prefer_real 优先 openai_compat；auto_persist 直接落库快照。
 */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchVisibilityPatrolOpsStatus,
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
  window_start_hour: 6,
  window_end_hour: 22,
  interval_hours: 24,
  last_scheduled_at: null,
  auto_persist: true,
  prefer_real: true,
  prompt_limit: 20,
  engine_keys: null,
  interval_choices: [1, 2, 3, 4, 6, 8, 12, 24],
})
const runs = ref([])
const engines = ref([])
const detail = ref(null)
const pollTimer = ref(null)
const ops = ref(null)

const form = ref({
  auto_persist: true,
  prefer_real: true,
  prompt_limit: 20,
  engine_keys: [],
})

const intervalOptions = [
  { value: 1, label: '每 1 小时' },
  { value: 2, label: '每 2 小时' },
  { value: 3, label: '每 3 小时' },
  { value: 4, label: '每 4 小时' },
  { value: 6, label: '每 6 小时' },
  { value: 8, label: '每 8 小时' },
  { value: 12, label: '每 12 小时' },
  { value: 24, label: '每 24 小时（每天）' },
]

function hourLabel(h) {
  const n = Number(h)
  if (Number.isNaN(n)) return '—'
  return `${String(n).padStart(2, '0')}:00`
}

function windowHint() {
  const s = settings.value.window_start_hour
  const e = settings.value.window_end_hour
  if (s == null || e == null) return ''
  if (Number(s) <= Number(e)) {
    return `允许时段 ${hourLabel(s)} – ${hourLabel(e)}（含整点，Asia/Shanghai）`
  }
  return `允许时段 ${hourLabel(s)} – 次日 ${hourLabel(e)}（跨夜，含整点）`
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [s, r, eng, opsRes] = await Promise.all([
      fetchVisibilityPatrolSettings(tenantId.value),
      listVisibilityPatrolRuns(tenantId.value, 30),
      listGeoTrackingEngines(tenantId.value, false),
      fetchVisibilityPatrolOpsStatus(tenantId.value).catch(() => null),
    ])
    settings.value = {
      ...settings.value,
      ...s,
      window_start_hour: s.window_start_hour ?? s.daily_hour ?? 6,
      window_end_hour: s.window_end_hour ?? s.daily_hour ?? 22,
      interval_hours: s.interval_hours ?? 24,
      interval_choices: s.interval_choices || [1, 2, 3, 4, 6, 8, 12, 24],
    }
    form.value.auto_persist = s.auto_persist !== false
    form.value.prefer_real = s.prefer_real !== false
    form.value.prompt_limit = s.prompt_limit || 20
    form.value.engine_keys = s.engine_keys || []
    runs.value = r.items || []
    engines.value = eng.items || []
    ops.value = opsRes
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
    const saved = await putVisibilityPatrolSettings({
      tenant_id: tenantId.value,
      enabled: settings.value.enabled,
      window_start_hour: settings.value.window_start_hour,
      window_end_hour: settings.value.window_end_hour,
      interval_hours: settings.value.interval_hours,
      auto_persist: form.value.auto_persist,
      prefer_real: form.value.prefer_real,
      prompt_limit: form.value.prompt_limit,
      engine_keys: form.value.engine_keys?.length ? form.value.engine_keys : null,
    })
    settings.value = {
      ...settings.value,
      ...saved,
      window_start_hour: saved.window_start_hour ?? 6,
      window_end_hour: saved.window_end_hour ?? 22,
      interval_hours: saved.interval_hours ?? 24,
    }
    ElMessage.success('定时设置已保存（主站 scheduler 每小时 :05 检查时间段与间隔）')
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
  let ticks = 0
  pollTimer.value = setInterval(async () => {
    ticks += 1
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
        return
      }
      // ~2 min still pending → surface (server also reconciles after 90s)
      if (r.status === 'pending' && ticks >= 48) {
        stopPoll()
        await load()
        ElMessage.warning(
          `巡检 #${runId} 长时间仍为 pending。请刷新历史；若已自动标失败请重新「立即巡检」。`,
        )
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
    <el-alert
      v-for="(a, i) in ops?.alerts || []"
      :key="'a' + i"
      type="warning"
      :title="a"
      show-icon
      class="mb"
      :closable="false"
    />
    <div v-if="ops" class="ops-bar mb">
      <span>
        今日配额 {{ ops.quota?.used_today ?? 0 }} / {{ ops.quota?.max_per_day ?? '—' }}
        （剩 {{ ops.quota?.remaining ?? '—' }}）
      </span>
      <span>
        真采样就绪
        {{ (ops.engines || []).filter((e) => e.ready_for_real).length }}
        / {{ (ops.engines || []).length }}
      </span>
      <span v-if="ops.last_run">最近 #{{ ops.last_run.id }} · {{ ops.last_run.status }}</span>
    </div>

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
            <el-switch v-model="settings.enabled" active-text="开启定时巡检" />
          </el-form-item>
          <el-form-item label="执行时间段（Asia/Shanghai 整点）">
            <div class="window-row">
              <el-input-number
                v-model="settings.window_start_hour"
                :min="0"
                :max="23"
                controls-position="right"
              />
              <span class="window-sep">至</span>
              <el-input-number
                v-model="settings.window_end_hour"
                :min="0"
                :max="23"
                controls-position="right"
              />
            </div>
            <p class="field-hint">{{ windowHint() }}；开始晚于结束表示跨夜（如 22→6）。</p>
          </el-form-item>
          <el-form-item label="执行时间间隔">
            <el-select v-model="settings.interval_hours" style="width: 100%">
              <el-option
                v-for="opt in intervalOptions"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
            <p class="field-hint">
              在允许时段内，距上次定时触发至少间隔这么久才再跑；主站每小时 :05 检查一次。
            </p>
          </el-form-item>
          <p v-if="settings.last_scheduled_at" class="last-run">
            上次定时触发：{{ settings.last_scheduled_at }}
          </p>
          <el-button type="primary" plain :loading="savingSettings" @click="saveSettings">
            保存定时设置
          </el-button>
          <p class="hint">
            例：时段 8–20、间隔 4 小时 → 约在 8/12/16/20 点（:05）可触发。
            日配额默认最多 24 次/租户（环境变量 GEO_PATROL_MAX_RUNS_PER_DAY）；超限返回明确错误。
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
.ops-bar {
  display: flex; flex-wrap: wrap; gap: 16px;
  font-size: 12px; color: #4b5563;
  background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 8px; padding: 8px 12px;
}
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
.field-hint { font-size: 12px; color: #9ca3af; margin: 6px 0 0; line-height: 1.4; }
.window-row {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap; width: 100%;
}
.window-sep { color: #6b7280; font-size: 13px; }
.last-run { font-size: 12px; color: #6b7280; margin: 0 0 10px; }
.detail { margin-top: 16px; border-top: 1px solid #eee; padding-top: 12px; }
.err { color: #b91c1c; font-size: 13px; }
.muted { color: #9ca3af; font-size: 11px; margin-left: 4px; }
.ok { color: #047857; font-size: 11px; margin-left: 4px; }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
}
</style>
