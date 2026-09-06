<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { baselineReadiness } from '../api/geoIntegration'
const props = defineProps({ tenantId: [String, Number], taskId: Number, disabled: Boolean })
const data = ref(null), error = ref(''), loading = ref(false)
let epoch = 0
watch(() => [props.tenantId, props.taskId], () => { epoch++; data.value = null; error.value = ''; loading.value = false })
onBeforeUnmount(() => { epoch++ })
async function check() {
  if (loading.value || props.disabled || !props.tenantId) return
  const token = ++epoch, tenant = props.tenantId, id = props.taskId
  const current = () => token === epoch && tenant === props.tenantId && id === props.taskId
  loading.value = true; error.value = ''; data.value = null
  try { const result = await baselineReadiness(tenant, id); if (current()) data.value = result }
  catch (e) { if (current()) error.value = e.message || '读取失败，请重试' }
  finally { if (current()) loading.value = false }
}
</script>
<template>
  <section aria-label="基线窗口诊断">
    <button class="gd-btn" :disabled="disabled || loading" @click="check">{{ loading ? '正在检查样本…' : '检查样本与周窗口' }}</button>
    <p v-if="error">{{ error }}</p>
    <template v-if="data">
      <p>{{ data.message }}</p>
      <p>本周合格覆盖：{{ data.current_week_counts?.samples }} 条回答、{{ data.current_week_counts?.questions }} 个问题、{{ data.current_week_counts?.engines }} 个引擎。</p>
      <p>本周结束时间：{{ data.current_week_end }}；最近完整周截至：{{ data.closed_week_as_of }}。</p>
      <p>{{ data.note }}</p>
    </template>
  </section>
</template>
