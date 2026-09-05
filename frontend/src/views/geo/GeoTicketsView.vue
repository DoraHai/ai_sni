<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoActionTicket,
  fetchLatestGeoAudit,
  listGeoActionTickets,
  materializeGeoAuditTickets,
  patchGeoActionTicket,
  verifyGeoActionTicket,
  verifyGeoAuditTickets,
} from '../../api/geo'
import { listGeoMediaPlacements } from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'

const route = useRoute()
const { tenantId } = useGeoTenant()

const loading = ref(false)
const error = ref('')
const items = ref([])
const statusFilter = ref('')
const auditId = ref(route.query.audit_id ? String(route.query.audit_id) : '')
const mediaItems = ref([])
const mediaPick = ref(null)
const busy = ref('')

const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'todo', label: 'todo' },
  { value: 'doing', label: 'doing' },
  { value: 'done', label: 'done' },
  { value: 'reopened', label: 'reopened' },
  { value: 'blocked', label: 'blocked' },
]

const summary = computed(() => {
  const counts = { pass: 0, fail: 0, manual: 0, open: 0 }
  for (const t of items.value || []) {
    if (t.last_verdict === 'pass') counts.pass++
    else if (t.last_verdict === 'fail') counts.fail++
    else if (t.last_verdict === 'manual') counts.manual++
    if (t.status !== 'done') counts.open++
  }
  return counts
})

const auditIdNum = computed(() => {
  const n = Number(auditId.value || 0)
  return Number.isFinite(n) && n > 0 ? n : null
})

const unsupportedReason = '当前后端未提供该操作'

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户'
    items.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const params = {}
    if (statusFilter.value) params.status = statusFilter.value
    if (auditIdNum.value) params.audit_id = auditIdNum.value
    const [tickets, media] = await Promise.all([
      listGeoActionTickets(tenantId.value, params),
      listGeoMediaPlacements(tenantId.value).catch(() => ({ items: [] })),
    ])
    items.value = tickets.items || []
    mediaItems.value = media.items || []
    if (!mediaPick.value && mediaItems.value.length) {
      mediaPick.value = mediaItems.value[0].id
    }
  } catch (e) {
    error.value = e.message || '加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

async function ensureAuditId() {
  if (auditIdNum.value) return auditIdNum.value
  const latest = await fetchLatestGeoAudit(tenantId.value)
  const id = latest?.id || latest?.audit_id
  if (!id) throw new Error('没有可用诊断，请先跑诊断中心')
  auditId.value = String(id)
  return Number(id)
}

async function materialize() {
  busy.value = 'materialize'
  try {
    const id = await ensureAuditId()
    await materializeGeoAuditTickets(tenantId.value, id, false)
    ElMessage.success('已从诊断生成工单')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '生成失败')
  } finally {
    busy.value = ''
  }
}

async function batchVerify(recrawl) {
  if (!auditIdNum.value) {
    ElMessage.warning('请先填写诊断 ID')
    return
  }
  busy.value = recrawl ? 'batch-recrawl' : 'batch-dry'
  try {
    await verifyGeoAuditTickets(tenantId.value, auditIdNum.value, recrawl)
    ElMessage.success(recrawl ? '批量重抓验收完成' : '批量验收完成')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '批量验收失败')
  } finally {
    busy.value = ''
  }
}

async function verifyOne(row, recrawl = true) {
  busy.value = `verify-${row.id}`
  try {
    await verifyGeoActionTicket(tenantId.value, row.id, recrawl)
    ElMessage.success(`工单 #${row.id} 已验收`)
    await load()
  } catch (e) {
    ElMessage.error(e.message || '验收失败')
  } finally {
    busy.value = ''
  }
}

async function manualPass(row, pass) {
  const owner = tenantId.value
  let verification_note
  if (row.advice_code?.startsWith('workqueue:v1:')) {
    try {
      const result = await ElMessageBox.prompt('请填写执行结果与核验依据', pass ? '人工验收通过' : '记录未达标', {
        inputType: 'textarea', inputValidator: (value) => !!value?.trim() && value.trim().length <= 4000 || '请填写 1–4000 字的核验记录',
      })
      verification_note = result.value.trim()
    } catch { return }
    if (owner !== tenantId.value) return
  }
  busy.value = `manual-${row.id}`
  try {
    await patchGeoActionTicket(owner, row.id, { manual_pass: pass, verification_note })
    if (owner !== tenantId.value) return
    ElMessage.success(pass ? '已人工通过' : '已标记未达标')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '更新失败')
  } finally {
    busy.value = ''
  }
}

async function createMediaTicket() {
  if (!mediaPick.value) {
    ElMessage.warning('请选择媒体布局')
    return
  }
  busy.value = 'media'
  try {
    const mp = mediaItems.value.find((m) => m.id === mediaPick.value)
    await createGeoActionTicket(tenantId.value, {
      title: `媒体铺设验收 · ${mp?.name || mediaPick.value}`,
      action: '确认目标 URL 已铺设并可被引用',
      priority: 'P2',
      media_placement_id: mediaPick.value,
      audit_id: auditIdNum.value,
    })
    ElMessage.success('已创建媒体工单')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    busy.value = ''
  }
}

watch([tenantId, statusFilter], load)
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="验收工单"
    sub="诊断整改 → 自动/人工验收 · site/media checker"
    :loading="loading"
  >
    <template #actions>
      <span class="sum">
        通过 {{ summary.pass }} · 失败 {{ summary.fail }} · 人工 {{ summary.manual }} · 未关闭 {{ summary.open }}
      </span>
    </template>

    <div class="geo-dash">
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <section class="gd-card mb">
        <div class="toolbar">
          <label class="lbl">
            诊断 ID
            <input v-model="auditId" class="gd-search" style="width:110px" placeholder="可选" />
          </label>
          <el-select v-model="statusFilter" style="width: 140px">
            <el-option
              v-for="o in statusOptions"
              :key="o.value || 'all'"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
          <button class="gd-btn" type="button" @click="load">刷新列表</button>
          <button
            class="gd-btn primary"
            type="button"
            :loading="busy === 'materialize'"
            @click="materialize"
          >
            从诊断生成工单
          </button>
          <button
            class="gd-btn"
            type="button"
            :disabled="!auditIdNum"
            :title="auditIdNum ? '' : '需要诊断 ID'"
            :loading="busy === 'batch-recrawl'"
            @click="batchVerify(true)"
          >
            批量重抓验收
          </button>
          <button
            class="gd-btn"
            type="button"
            :disabled="!auditIdNum"
            :loading="busy === 'batch-dry'"
            @click="batchVerify(false)"
          >
            批量验收
          </button>
        </div>
        <div class="gd-sub pad">
          先跑诊断中心拿到 audit_id，再生成工单并验收。媒体工单可在下方单独创建。
        </div>
      </section>

      <section class="gd-card mb">
        <div class="gd-hd"><h3>工单列表</h3></div>
        <div class="gd-bd" style="padding:0">
          <el-table :data="items" empty-text="暂无验收工单" size="small">
            <el-table-column prop="id" label="ID" width="72" />
            <el-table-column prop="priority" label="优先级" width="90" />
            <el-table-column label="标题" min-width="240">
              <template #default="{ row }">
                <div class="name">{{ row.title || '—' }}</div>
                <div v-if="row.action" class="note">{{ row.action }}</div>
                <div v-if="row.last_note" class="hint">{{ row.last_note }}</div>
              </template>
            </el-table-column>
            <el-table-column label="验收" min-width="140">
              <template #default="{ row }">
                {{ row.acceptance_type || '—' }}
                <span v-if="row.acceptance_check"> · {{ row.acceptance_check }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="row.status === 'done' ? 'success' : row.status === 'blocked' || row.status === 'reopened' ? 'danger' : 'warning'"
                >
                  {{ row.status || '—' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="最近判定" width="110">
              <template #default="{ row }">{{ row.last_verdict || '—' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-button
                  link
                  type="primary"
                  :loading="busy === `verify-${row.id}`"
                  v-if="!row.advice_code?.startsWith('workqueue:v1:')"
                  @click="verifyOne(row, true)"
                >验收</el-button>
                <el-button link :loading="busy === `manual-${row.id}`" @click="manualPass(row, true)">通过</el-button>
                <el-button link :loading="busy === `manual-${row.id}`" @click="manualPass(row, false)">驳回</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </section>

      <section class="gd-card">
        <div class="gd-hd"><h3>新建媒体铺设验收</h3></div>
        <div class="toolbar pad">
          <el-select v-model="mediaPick" filterable style="min-width: 240px" placeholder="选择媒体布局">
            <el-option
              v-for="m in mediaItems"
              :key="m.id"
              :label="`#${m.id} ${m.name}`"
              :value="m.id"
            />
          </el-select>
          <button
            class="gd-btn"
            type="button"
            :disabled="!mediaItems.length"
            :title="mediaItems.length ? '' : unsupportedReason"
            :loading="busy === 'media'"
            @click="createMediaTicket"
          >
            创建媒体工单
          </button>
        </div>
      </section>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.mb { margin-bottom: 14px; }
.pad { padding: 0 14px 12px; }
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding: 12px 14px;
}
.lbl {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #6b7280;
}
.name { font-weight: 650; }
.note { margin-top: 3px; font-size: 12px; color: #6b7280; }
.hint { margin-top: 3px; font-size: 12px; color: #9ca3af; }
.sum { font-size: 12px; color: #6b7280; }
.gd-sub { font-size: 12px; color: #6b7280; line-height: 1.5; }
</style>
