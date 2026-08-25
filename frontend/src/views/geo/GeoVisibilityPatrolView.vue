<script setup>
/**
 * AI 可见度 · 全自动巡检
 * 多优化意图词 × 启用引擎探测；prefer_real 优先 openai_compat；auto_persist 直接落库快照。
 */
import { geoSnapshotLink } from '../../utils/geoRoutes'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  cleanupVisibilityPatrolRuns,
  deleteVisibilityPatrolRun,
  fetchVisibilityPatrolOpsStatus,
  fetchVisibilityPatrolSettings,
  getVisibilityPatrolRun,
  listVisibilityPatrolRuns,
  listGeoTrackingEngines,
  putVisibilityPatrolSettings,
  startVisibilityPatrolRun,
} from '../../api/geoContent'
import GeoVisibilityNav from '../../components/GeoVisibilityNav.vue'
import NeedHintAlert from '../../components/NeedHintAlert.vue'
import { useClientPager } from '../../composables/useClientPager'
import { useGeoTenant } from '../../composables/useGeoTenant'
import {
  PATROL_STATUS_LABEL,
  PATROL_TRIGGER_LABEL,
  REPORT_GLOSSARY,
  SAMPLE_MODE_LABEL,
  downloadCsv,
  engineDisplay,
  fmtCaptured,
  labelOf,
} from '../../utils/geoReportLabels'

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
const runPager = useClientPager(runs, { pageSize: 10 })
const detailItems = computed(() => detail.value?.items || [])
const detailPager = useClientPager(detailItems, { pageSize: 20 })

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

const enabledEngines = computed(() => engines.value.filter((e) => e.enabled))
const realReadyCount = computed(
  () => (ops.value?.engines || []).filter((e) => e.ready_for_real).length,
)
const engineTotal = computed(() => (ops.value?.engines || []).length)

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

function statusLabel(s) {
  return labelOf(PATROL_STATUS_LABEL, s, s || '—')
}

function triggerLabel(t) {
  return labelOf(PATROL_TRIGGER_LABEL, t, t || '—')
}

function sampleModeLabel(mode) {
  if (!mode) return '—'
  return labelOf(SAMPLE_MODE_LABEL, mode, mode)
}

function engineOptionLabel(e) {
  const name = e.display_name || engineDisplay(e.engine_key)
  const mode = sampleModeLabel(e.sample_mode || 'mock_persona')
  const off = e.enabled ? '' : ' · 已停用'
  return `${name} · ${mode}${off}`
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
    ElMessage.success(
      `巡检已启动 #${res.run?.id}（后台执行 · ${form.value.auto_persist ? '自动落库' : '仅明细不落库'}）`,
    )
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
      if (r.status === 'pending' && ticks >= 48) {
        stopPoll()
        await load()
        ElMessage.warning(
          `巡检 #${runId} 长时间仍为排队中。请刷新历史；若已自动标失败请重新「立即巡检」。`,
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
    detailPager.resetPage()
    if (row.status === 'running' || row.status === 'pending') startPoll(row.id)
  } catch (e) {
    ElMessage.error(e.message || '加载失败')
  }
}

async function removeRun(row) {
  try {
    const force = row.status === 'pending' || row.status === 'running'
    await ElMessageBox.confirm(
      force
        ? `强制删除进行中的巡检 #${row.id}？`
        : `删除巡检历史 #${row.id}？`,
      '删除巡检',
      { type: 'warning', confirmButtonText: '删除' },
    )
    await deleteVisibilityPatrolRun(tenantId.value, row.id, force)
    if (detail.value?.id === row.id) detail.value = null
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '删除失败')
  }
}

async function cleanupRuns() {
  try {
    await ElMessageBox.confirm('仅保留最近 20 条已结束巡检，删除更旧历史？', '清理历史', {
      type: 'warning',
    })
    const res = await cleanupVisibilityPatrolRuns(tenantId.value, 20)
    ElMessage.success(`已删除 ${res.deleted ?? 0} 条，保留 ${res.kept ?? 0} 条`)
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '清理失败')
  }
}

function statusType(s) {
  if (s === 'completed') return 'success'
  if (s === 'failed') return 'danger'
  if (s === 'running') return 'warning'
  return 'info'
}

function summaryText(row) {
  const s = row?.summary
  if (s && Object.keys(s).length) {
    return `意图词 ${s.prompts ?? '—'} · 引擎 ${s.engines ?? '—'} · 成功 ${s.cells_ok ?? 0} · 落库 ${s.snapshots_created ?? 0} · 真采样 ${s.real_samples ?? 0}`
  }
  if (row?.error) return row.error
  return '—'
}

function exportDetailCsv() {
  if (!detail.value?.items?.length) return
  const rows = detail.value.items.map((r) => [
    r.prompt_id,
    engineDisplay(r.engine),
    r.ok ? '成功' : '失败',
    sampleModeLabel(r.sample_mode),
    r.simulated === true ? '模拟' : r.simulated === false ? '真采样' : '',
    r.snapshot_id ?? '',
    r.error || (r.raw_text || '').slice(0, 200),
  ])
  downloadCsv(
    `geo-patrol-run-${detail.value.id}.csv`,
    ['意图词ID', '引擎', '结果', '采样模式', '真/模拟', '快照ID', '摘要或错误'],
    rows,
  )
  ElMessage.success(`已导出运行 #${detail.value.id} 明细`)
}

function fmtRate(v) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}
function fmtDelta(v) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  const pct = (n * 100).toFixed(1)
  return n > 0 ? `+${pct}pp` : `${pct}pp`
}
function deltaClass(v) {
  if (v == null) return ''
  const n = Number(v)
  if (Number.isNaN(n) || n === 0) return ''
  return n > 0 ? 'up' : 'down'
}

watch(tenantId, load)
onMounted(load)
onUnmounted(stopPoll)
</script>

<template>
  <div v-loading="loading" class="patrol-page geo-page">
    <div class="page-header">
      <div>
        <div class="crumbs">
          <router-link to="/geo/visibility">AI 可见度</router-link>
          <span> / </span>
          <span>全自动巡检</span>
        </div>
        <div class="page-title">全自动巡检</div>
        <div class="page-desc">
          按「意图词 × 引擎」批量探测并可选自动落库；真采样优先用引擎 Key，否则人设模拟。
          手工单条登记请回
          <router-link :to="geoSnapshotLink()">登记快照</router-link>。
        </div>
        <GeoVisibilityNav />
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button @click="router.push('/geo/engines')">引擎配置</el-button>
        <el-button @click="router.push('/geo/prompts')">优化意图词</el-button>
        <el-button type="primary" :loading="starting" @click="startRun">立即巡检</el-button>
      </div>
    </div>

    <details class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li v-for="(line, i) in REPORT_GLOSSARY.patrol" :key="i">{{ line }}</li>
      </ul>
    </details>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />
    <NeedHintAlert />
    <el-alert
      v-for="(a, i) in ops?.alerts || []"
      :key="'a' + i"
      type="warning"
      :title="a"
      show-icon
      class="mb"
      :closable="false"
    />

    <div v-if="ops" class="geo-kpi-grid mb">
      <div class="geo-kpi">
        <div class="kpi-label">今日配额</div>
        <div class="kpi-value">
          {{ ops.quota?.used_today ?? 0 }}
          <span class="kpi-den">/ {{ ops.quota?.max_per_day ?? '—' }}</span>
        </div>
        <div class="kpi-hint">剩余 {{ ops.quota?.remaining ?? '—' }} 次</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">真采样就绪</div>
        <div class="kpi-value">
          {{ realReadyCount }}
          <span class="kpi-den">/ {{ engineTotal || '—' }}</span>
        </div>
        <div class="kpi-hint">引擎已配 Key 且模式可用</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">启用引擎</div>
        <div class="kpi-value">{{ enabledEngines.length }}</div>
        <div class="kpi-hint">空选引擎时默认跑这些</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">最近一次</div>
        <div class="kpi-value kpi-sm">
          <template v-if="ops.last_run">
            #{{ ops.last_run.id }}
            <el-tag size="small" :type="statusType(ops.last_run.status)" class="kpi-tag">
              {{ statusLabel(ops.last_run.status) }}
            </el-tag>
          </template>
          <template v-else>—</template>
        </div>
        <div class="kpi-hint">{{ settings.enabled ? '定时已开' : '定时关闭' }} · {{ windowHint() || '未设时段' }}</div>
      </div>
    </div>

    <div class="layout">
      <section class="panel">
        <div class="panel-title">本次巡检参数</div>
        <p class="geo-panel-desc">立即巡检与「保存定时设置」都会沿用这些参数。</p>
        <el-form label-position="top" size="small">
          <el-form-item label="意图词数量上限">
            <el-input-number v-model="form.prompt_limit" :min="1" :max="50" />
            <p class="field-hint">按活跃意图词优先级取前 N 条（最多 50）。</p>
          </el-form-item>
          <el-form-item label="引擎（可多选）">
            <el-select
              v-model="form.engine_keys"
              multiple
              clearable
              collapse-tags
              collapse-tags-tooltip
              placeholder="空=全部已启用引擎"
              style="width: 100%"
            >
              <el-option
                v-for="e in engines"
                :key="e.engine_key"
                :label="engineOptionLabel(e)"
                :value="e.engine_key"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="采样与落库">
            <el-checkbox v-model="form.prefer_real">
              优先真采样（引擎已配兼容接口 Key）
            </el-checkbox>
            <el-checkbox v-model="form.auto_persist">
              自动落库为回答快照
            </el-checkbox>
            <p class="field-hint">
              关闭落库时只保留运行明细，不会进入引用/评价等报表。
            </p>
          </el-form-item>
        </el-form>

        <el-divider />
        <div class="panel-title">定时全自动</div>
        <p class="geo-panel-desc">由主站 scheduler 触发；需进程在跑且未超日配额。</p>
        <el-form label-position="top" size="small">
          <el-form-item>
            <el-switch v-model="settings.enabled" active-text="开启定时巡检" />
          </el-form-item>
          <el-form-item label="允许执行时段（Asia/Shanghai 整点）">
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
          <el-form-item label="最短触发间隔">
            <el-select v-model="settings.interval_hours" style="width: 100%">
              <el-option
                v-for="opt in intervalOptions"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
            <p class="field-hint">
              时段内距上次定时触发至少间隔这么久才再跑；主站每小时 :05 检查一次。
            </p>
          </el-form-item>
          <p v-if="settings.last_scheduled_at" class="last-run">
            上次定时触发：{{ fmtCaptured(settings.last_scheduled_at) }}
          </p>
          <el-button type="primary" plain :loading="savingSettings" @click="saveSettings">
            保存定时设置
          </el-button>
          <p class="hint">
            例：时段 8–20、间隔 4 小时 → 约在 8/12/16/20 点（:05）可触发。
            日配额默认最多 24 次/租户（GEO_PATROL_MAX_RUNS_PER_DAY）。
          </p>
        </el-form>
      </section>

      <section class="panel">
        <div class="panel-title">
          巡检历史
          <el-button size="small" plain style="margin-left: auto" @click="cleanupRuns">
            清理旧记录
          </el-button>
        </div>
        <div v-if="!runs.length && !loading" class="geo-empty" style="margin-bottom: 12px">
          <div class="empty-title">暂无巡检记录</div>
          <div>先确认意图词与引擎，再点「立即巡检」；落库后可在可见度与报表页查看。</div>
          <div class="empty-actions">
            <el-button type="primary" size="small" :loading="starting" @click="startRun">
              立即巡检
            </el-button>
            <router-link class="el-button el-button--small is-plain" to="/geo/engines">
              检查引擎
            </router-link>
          </div>
        </div>
        <el-table
          :data="runPager.pagedItems"
          size="small"
          empty-text=" "
          highlight-current-row
          @row-click="openRun"
        >
          <el-table-column prop="id" label="运行ID" width="80" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row.status)">
                {{ statusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="触发方式" width="88">
            <template #default="{ row }">{{ triggerLabel(row.trigger) }}</template>
          </el-table-column>
          <el-table-column label="结果摘要" min-width="220">
            <template #default="{ row }">
              <span :class="{ err: !!row.error && !(row.summary && Object.keys(row.summary).length) }">
                {{ summaryText(row) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="150">
            <template #default="{ row }">{{ fmtCaptured(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button
                size="small"
                text
                type="danger"
                @click.stop="removeRun(row)"
              >删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="geo-pager">
          <el-pagination
            background
            layout="total, prev, pager, next"
            :total="runPager.total"
            :page-size="runPager.pageSize"
            :current-page="runPager.page"
            @current-change="runPager.onPageChange"
          />
        </div>

        <div v-if="detail" class="detail">
          <div class="panel-title">
            运行明细 #{{ detail.id }}
            <el-tag size="small" :type="statusType(detail.status)">
              {{ statusLabel(detail.status) }}
            </el-tag>
            <el-button
              size="small"
              plain
              style="margin-left: auto"
              :disabled="!detail.items?.length"
              @click="exportDetailCsv"
            >
              导出明细 CSV
            </el-button>
          </div>
          <p class="geo-panel-desc">
            {{ summaryText(detail) }}
            <template v-if="detail.trigger"> · {{ triggerLabel(detail.trigger) }}</template>
            <template v-if="detail.sample_composition?.label">
              · {{ detail.sample_composition.label }}
            </template>
          </p>
          <p v-if="detail.error" class="err">{{ detail.error }}</p>

          <!-- 本次 vs 上次 -->
          <div v-if="detail.vs_previous" class="vs-box">
            <div class="vs-title">本次 vs 上次巡检</div>
            <div class="vs-grid">
              <div class="vs-cell">
                <div class="vs-k">本次提及率</div>
                <div class="vs-v">{{ fmtRate(detail.vs_previous.this_brand_mention_rate) }}</div>
                <div class="vs-h">
                  可见样本 {{ detail.vs_previous.this_snapshots ?? '—' }} · 提及
                  {{ detail.vs_previous.this_mentions ?? '—' }}
                </div>
              </div>
              <div class="vs-cell">
                <div class="vs-k">上次提及率</div>
                <div class="vs-v">
                  {{
                    detail.vs_previous.previous_run_id
                      ? fmtRate(detail.vs_previous.previous_brand_mention_rate)
                      : '—'
                  }}
                </div>
                <div class="vs-h">
                  <template v-if="detail.vs_previous.previous_run_id">
                    运行 #{{ detail.vs_previous.previous_run_id }} · 样本
                    {{ detail.vs_previous.previous_snapshots ?? '—' }}
                  </template>
                  <template v-else>无更早完成的巡检</template>
                </div>
              </div>
              <div class="vs-cell">
                <div class="vs-k">Δ 提及率</div>
                <div
                  class="vs-v"
                  :class="deltaClass(detail.vs_previous.brand_mention_rate_delta)"
                >
                  {{ fmtDelta(detail.vs_previous.brand_mention_rate_delta) }}
                </div>
                <div class="vs-h">
                  首选位
                  {{ fmtRate(detail.vs_previous.this_top1_rate) }}
                </div>
              </div>
            </div>
            <div
              v-if="detail.sample_composition?.has_simulated"
              class="vs-warn"
            >
              本运行含模拟样本，交付汇报须标注，不可当作真实引擎效果。
            </div>
          </div>

          <div v-if="!detail.items?.length" class="geo-empty" style="margin-top: 8px">
            {{
              detail.status === 'pending' || detail.status === 'running'
                ? '执行中，明细稍后刷新…'
                : '本运行无单元格明细'
            }}
          </div>
          <el-table
            v-if="detail.items?.length"
            :data="detailPager.pagedItems"
            size="small"
            max-height="360"
            stripe
          >
            <el-table-column prop="prompt_id" label="意图词ID" width="88">
              <template #default="{ row }">
                <router-link
                  class="link"
                  :to="{ path: '/geo/prompts', query: { q: row.prompt_id } }"
                >
                  #{{ row.prompt_id }}
                </router-link>
              </template>
            </el-table-column>
            <el-table-column label="引擎" width="110">
              <template #default="{ row }">{{ engineDisplay(row.engine) }}</template>
            </el-table-column>
            <el-table-column label="结果" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.ok ? 'success' : 'danger'">
                  {{ row.ok ? '成功' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="采样方式" width="140">
              <template #default="{ row }">
                {{ sampleModeLabel(row.sample_mode) }}
                <span v-if="row.simulated === true" class="muted">· 模拟</span>
                <span v-else-if="row.simulated === false" class="ok">· 真采样</span>
              </template>
            </el-table-column>
            <el-table-column label="快照" width="100">
              <template #default="{ row }">
                <router-link
                  v-if="row.snapshot_id"
                  class="link"
                  :to="geoSnapshotLink({ snapshot_id: row.snapshot_id, patrol_run_id: detail.id })"
                >
                  #{{ row.snapshot_id }}
                </router-link>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="摘要 / 错误" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.error || (row.raw_text || '').slice(0, 80) || '—' }}
              </template>
            </el-table-column>
          </el-table>
          <div v-if="detail.items?.length" class="geo-pager">
            <el-pagination
              background
              layout="total, sizes, prev, pager, next"
              :total="detailPager.total"
              :page-size="detailPager.pageSize"
              :current-page="detailPager.page"
              :page-sizes="[10, 20, 50, 100]"
              @current-change="detailPager.onPageChange"
              @size-change="detailPager.onSizeChange"
            />
          </div>
          <div v-if="detail.status === 'completed'" class="detail-links">
            <router-link
              class="el-button el-button--small el-button--primary is-plain"
              :to="geoSnapshotLink({ patrol_run_id: detail.id })"
            >
              查看本运行快照（{{ detail.snapshot_count ?? detail.snapshot_ids?.length ?? 0 }}）
            </router-link>
            <router-link class="el-button el-button--small is-plain" to="/geo/overview">
              GEO 概览
            </router-link>
            <router-link class="el-button el-button--small is-plain" to="/geo/period-diff">
              期次对比
            </router-link>
            <router-link class="el-button el-button--small is-plain" to="/geo/citations">
              引用分析
            </router-link>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.patrol-page { padding: 4px 2px 28px; }
.vs-box {
  margin: 10px 0 14px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #e8edf5;
}
.vs-title { font-weight: 700; font-size: 13px; color: #0f172a; margin-bottom: 10px; }
.vs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 10px;
}
.vs-cell {
  background: #fff;
  border: 1px solid #eef2f7;
  border-radius: 10px;
  padding: 10px 12px;
}
.vs-k { font-size: 11px; color: #64748b; font-weight: 600; }
.vs-v { font-size: 20px; font-weight: 750; color: #0f172a; margin-top: 4px; }
.vs-v.up { color: #059669; }
.vs-v.down { color: #dc2626; }
.vs-h { font-size: 11px; color: #94a3b8; margin-top: 4px; line-height: 1.4; }
.vs-warn {
  margin-top: 10px;
  font-size: 12px;
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 8px;
  padding: 8px 10px;
}
.link { color: #185fa5; text-decoration: none; font-weight: 600; }
.link:hover { text-decoration: underline; }
.ok { color: #059669; font-size: 12px; }
.muted { color: #9ca3af; font-size: 12px; }
.page-header {
  display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.crumbs { font-size: 12px; color: #9ca3af; margin-bottom: 4px; }
.crumbs a { color: #7c3aed; text-decoration: none; }
.page-title { font-size: 20px; font-weight: 700; color: #1e2330; }
.page-desc { font-size: 13px; color: #6b7280; margin-top: 4px; max-width: 640px; line-height: 1.5; }
.page-desc a { color: #7c3aed; text-decoration: none; }
.page-desc a:hover { text-decoration: underline; }
.sub-tabs {
  display: flex;
  gap: 4px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.sub-tab {
  display: inline-flex;
  align-items: center;
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #6b7280;
  text-decoration: none;
  border: 1px solid transparent;
  background: #f3f4f6;
}
.sub-tab:hover { color: #5b21b6; background: #f5f0ff; }
.sub-tab.is-active {
  color: #5b21b6;
  background: #f5f0ff;
  border-color: #ddd6fe;
}
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.mb { margin-bottom: 12px; }
.kpi-den { font-size: 14px; font-weight: 500; color: #94a3b8; margin-left: 2px; }
.kpi-sm { font-size: 18px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.kpi-tag { vertical-align: middle; }
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
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
}
.hint { font-size: 12px; color: #9ca3af; margin-top: 10px; line-height: 1.45; }
.field-hint { font-size: 12px; color: #9ca3af; margin: 6px 0 0; line-height: 1.4; }
.window-row {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap; width: 100%;
}
.window-sep { color: #6b7280; font-size: 13px; }
.last-run { font-size: 12px; color: #6b7280; margin: 0 0 10px; }
.detail { margin-top: 16px; border-top: 1px solid #eee; padding-top: 12px; }
.detail-links {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.err { color: #b91c1c; font-size: 13px; }
.muted { color: #9ca3af; font-size: 11px; margin-left: 4px; }
.ok { color: #047857; font-size: 11px; margin-left: 4px; }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
}
</style>
