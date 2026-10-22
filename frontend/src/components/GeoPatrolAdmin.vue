<script setup>
import { onBeforeUnmount, reactive, ref } from 'vue'
import { listPatrolAdminSettings, patrolAdminAction, putPatrolManualLimit } from '../api/geoContent'
import { beijingTime, patrolError, patrolStatus, scheduleMode } from '../utils/geoAutopatrol'
import GeoPatrolHistory from './GeoPatrolHistory.vue'
const emit = defineEmits(['changed'])
const rows = ref([]), total = ref(0), page = ref(1), loading = ref(false), busy = ref(false), error = ref('')
const filters = reactive({ search: '', enabled: '', admin_locked: '', blocked: '' })
const dialog = ref(null), reason = ref(''), limit = ref(10), dialogError = ref('')
const historyTenant = ref(null), historyOpen = ref(false), manualHistory = ref(false)
let generation = 0, abort, disposed = false
async function load(reset = false) {
  if (reset) page.value = 1
  const version = ++generation
  abort?.abort(); abort = new AbortController()
  loading.value = true; error.value = ''; rows.value = []; total.value = 0
  const params = { page: page.value, page_size: 20, search: filters.search.trim() || undefined }
  for (const key of ['enabled', 'admin_locked', 'blocked']) if (filters[key] !== '') params[key] = filters[key] === 'true'
  try {
    const data = await listPatrolAdminSettings(params, abort.signal)
    if (version === generation) { rows.value = data.items; total.value = data.total }
  } catch (e) { if (version === generation) error.value = patrolError(e) }
  finally { if (version === generation) loading.value = false }
}
function open(row, action) {
  if (busy.value || loading.value) return
  dialog.value = { ...row, action }
  reason.value = ''; dialogError.value = ''; limit.value = row.manual_quota.limit
}
function history(row, manual) {
  historyTenant.value = row.tenant_id; manualHistory.value = manual; historyOpen.value = true
}
async function submit() {
  if (busy.value || !dialog.value) return
  const target = dialog.value, why = reason.value.trim()
  if (!why || why.length > 500) { dialogError.value = '请填写 1–500 字原因'; return }
  if (target.action === 'manual_limit' && (!Number.isInteger(limit.value) || limit.value < 0 || limit.value > 100)) {
    dialogError.value = '手动次数须为 0–100 的整数'; return
  }
  busy.value = true; dialogError.value = ''
  try {
    if (target.action === 'manual_limit') {
      await putPatrolManualLimit({ tenant_id: target.tenant_id, manual_daily_limit: limit.value, expected_revision: target.manual_limit_revision, reason: why })
    } else {
      await patrolAdminAction({ tenant_id: target.tenant_id, action: target.action, expected_revision: target.revision, reason: why })
    }
    if (disposed) return
    dialog.value = null; emit('changed'); await load()
  } catch (e) {
    if (disposed) return
    if ([409, 423].includes(e?.status)) {
      dialog.value = null; await load(); error.value = patrolError(e)
      emit('changed')
    } else dialogError.value = patrolError(e)
  } finally { if (!disposed) busy.value = false }
}
load()
onBeforeUnmount(() => { disposed = true; generation++; abort?.abort() })
</script>
<template>
  <section class="gd-card admin-patrol" data-testid="admin-patrol">
    <div class="gd-hd"><h3>全部客户自动检测</h3><button class="gd-btn" :disabled="busy" @click="load()">刷新客户状态</button></div>
    <div class="gd-bd">
      <p class="note">自动检测由负责顾问开启。平台管理员可强制关闭并加锁、解锁；解锁后仍由顾问自行开启。时间均为北京时间。</p>
      <form class="filters" @submit.prevent="load(true)">
        <el-input v-model="filters.search" placeholder="搜索客户名称" clearable style="width:190px" aria-label="搜索客户名称" />
        <el-select v-model="filters.enabled" placeholder="自动状态" style="width:125px" aria-label="自动状态"><el-option label="全部开关" value="" /><el-option label="已开启" value="true" /><el-option label="已关闭" value="false" /></el-select>
        <el-select v-model="filters.admin_locked" placeholder="管理锁" style="width:125px" aria-label="管理锁"><el-option label="全部管理锁" value="" /><el-option label="已锁定" value="true" /><el-option label="未锁定" value="false" /></el-select>
        <el-select v-model="filters.blocked" placeholder="阻塞状态" style="width:125px" aria-label="阻塞状态"><el-option label="全部阻塞" value="" /><el-option label="受阻" value="true" /><el-option label="未受阻" value="false" /></el-select>
        <button class="gd-btn" type="submit" :disabled="busy">筛选</button>
      </form>
      <el-alert v-if="error" :title="error" type="warning" :closable="false" />
      <el-table v-loading="loading" :data="rows" empty-text="暂无客户状态" :row-key="row => row.tenant_id">
        <el-table-column label="客户 / 模式" min-width="180"><template #default="{ row }"><b>{{ row.tenant_name }}</b><div class="note">{{ scheduleMode(row.schedule_mode) }}</div></template></el-table-column>
        <el-table-column label="状态" min-width="180"><template #default="{ row }">{{ patrolStatus(row) }}<div v-if="row.admin_locked" class="note">{{ row.lock_reason }}</div></template></el-table-column>
        <el-table-column label="负责人" width="110"><template #default="{ row }">{{ row.owner?.display_name || '—' }}</template></el-table-column>
        <el-table-column label="下次预计（北京时间）" width="175"><template #default="{ row }">{{ row.enabled ? beijingTime(row.next_run_estimate) : '—' }}</template></el-table-column>
        <el-table-column label="今日手动 已用/上限" width="155"><template #default="{ row }">{{ row.manual_quota.used }}/{{ row.manual_quota.limit }}</template></el-table-column>
        <el-table-column label="操作" min-width="285"><template #default="{ row }">
          <el-button v-if="!row.admin_locked" link type="danger" :disabled="busy || loading" @click="open(row, 'force_disable')">强制关闭</el-button>
          <el-button v-else link type="primary" :disabled="busy || loading" @click="open(row, 'unlock')">解锁</el-button>
          <el-button link type="primary" :disabled="busy || loading" @click="open(row, 'manual_limit')">每天手动检测次数</el-button>
          <el-button link @click="history(row, false)">开关历史</el-button><el-button link @click="history(row, true)">次数修改记录</el-button>
        </template></el-table-column>
      </el-table>
      <el-pagination :current-page="page" :page-size="20" :total="total" layout="prev, pager, next, total" @current-change="page = $event; load()" />
    </div>
    <el-dialog :model-value="!!dialog" :title="dialog?.action === 'manual_limit' ? '每天手动检测次数' : dialog?.action === 'unlock' ? '解除管理锁' : '强制关闭自动检测'" width="540px" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" @update:model-value="value => { if (!value && !busy) dialog = null }">
      <template v-if="dialog">
        <p>客户：{{ dialog.tenant_name }}</p>
        <p class="note">{{ dialog.action === 'manual_limit' ? '同一客户所有顾问共享，按北京时间自然日计算；0 表示禁用手动检测。' : dialog.action === 'unlock' ? '仅解除管理锁，保持关闭；顾问需要自行开启。' : '立即关闭并加管理锁；已发出的平台请求无法撤回，后续检测停止。' }}</p>
        <el-form label-position="top">
          <el-form-item v-if="dialog.action === 'manual_limit'" label="每天手动检测次数（当前上限）"><el-input-number v-model="limit" :min="0" :max="100" :precision="0" :disabled="busy" aria-label="每天手动检测次数" /></el-form-item>
          <el-form-item label="原因（必填）"><el-input v-model="reason" type="textarea" :rows="3" maxlength="500" show-word-limit :disabled="busy" aria-label="操作原因" /></el-form-item>
        </el-form>
        <el-alert v-if="dialogError" :title="dialogError" type="warning" :closable="false" />
      </template>
      <template #footer><el-button :disabled="busy" @click="dialog = null">取消</el-button><el-button type="primary" :loading="busy" @click="submit">确认</el-button></template>
    </el-dialog>
    <GeoPatrolHistory v-model:open="historyOpen" :tenant-id="historyTenant" :manual="manualHistory" />
  </section>
</template>
<style scoped>
.admin-patrol { margin-bottom:16px; }
.filters { display:flex; gap:10px; flex-wrap:wrap; margin:14px 0; }
.note { color:#67758a; font-size:12px; line-height:1.7; overflow-wrap:anywhere; }
.el-pagination { margin-top:14px; }
</style>
