<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { listPatrolSettingHistory, listPatrolManualLimitHistory } from '../api/geoContent'
import { beijingTime, EVENT_ACTION, patrolError } from '../utils/geoAutopatrol'
const props = defineProps({ open: Boolean, tenantId: Number, manual: Boolean })
const emit = defineEmits(['update:open'])
const items = ref([]), total = ref(0), page = ref(1), loading = ref(false), error = ref('')
let generation = 0, abort
async function load() {
  const version = ++generation
  abort?.abort()
  items.value = []; total.value = 0; error.value = ''; loading.value = false
  if (!props.open || !props.tenantId) return
  abort = new AbortController()
  loading.value = true
  try {
    const data = await (props.manual ? listPatrolManualLimitHistory : listPatrolSettingHistory)(props.tenantId, page.value, abort.signal)
    if (version !== generation) return
    items.value = data.items; total.value = data.total
  } catch (e) {
    if (version === generation) error.value = patrolError(e)
  } finally { if (version === generation) loading.value = false }
}
watch(() => [props.open, props.tenantId, props.manual], () => { page.value = 1; load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { generation++; abort?.abort() })
</script>
<template>
  <el-dialog :model-value="open" :title="manual ? '手动次数修改记录' : '开关历史'" width="850px" @update:model-value="emit('update:open', $event)">
    <p>时间均为北京时间</p>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <el-table v-loading="loading" :data="items" empty-text="暂无记录">
      <el-table-column label="时间" width="165"><template #default="{ row }">{{ beijingTime(row.created_at) }}</template></el-table-column>
      <el-table-column label="操作人" width="110"><template #default="{ row }">{{ row.actor?.display_name || '—' }}</template></el-table-column>
      <el-table-column label="操作" min-width="140"><template #default="{ row }">{{ EVENT_ACTION[row.action] || '状态变更' }}</template></el-table-column>
      <el-table-column v-if="manual" label="旧值 → 新值" width="125"><template #default="{ row }">{{ row.before?.manual_daily_limit ?? '—' }} → {{ row.after?.manual_daily_limit ?? '—' }}</template></el-table-column>
      <el-table-column v-else label="自动检测" width="100"><template #default="{ row }">{{ row.before?.enabled ? '开' : '关' }} → {{ row.after?.enabled ? '开' : '关' }}</template></el-table-column>
      <el-table-column label="原因" min-width="180"><template #default="{ row }">{{ row.reason || '—' }}</template></el-table-column>
    </el-table>
    <el-pagination :current-page="page" :page-size="20" :total="total" layout="prev, pager, next, total" @current-change="page = $event; load()" />
  </el-dialog>
</template>
