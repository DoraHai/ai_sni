<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { listGeoPublicationMonitor, checkGeoPublicationMonitor } from '../api/geoContent'
const props = defineProps({ tenantId: Number, taskId: Number, revision: Number })
const rows = ref([])
const error = ref('')
const busy = ref(false)
const loading = ref(false)
let epoch = 0
const labels = { pending: '等待首次检查', healthy: '正文匹配', unreachable: '抓取失败，待重试', mismatch: '正文不匹配', version_changed: '登记后稿件已变化' }
async function load() {
  const run = ++epoch
  rows.value = []; error.value = ''; busy.value = false; loading.value = false
  if (!props.tenantId || !props.taskId) return
  loading.value = true
  try {
    const data = await listGeoPublicationMonitor(props.taskId, props.tenantId)
    if (run === epoch) rows.value = data.items || []
  } catch (e) { if (run === epoch) error.value = e.message || '监测记录读取失败' }
  finally { if (run === epoch) loading.value = false }
}
async function check(row) {
  if (busy.value || loading.value) return
  const run = epoch
  busy.value = true; error.value = ''
  try {
    const data = await checkGeoPublicationMonitor(props.taskId, props.tenantId, row.publication_id)
    if (run === epoch) Object.assign(row, data)
  } catch (e) { if (run === epoch) error.value = e.message || '检查失败' }
  finally { if (run === epoch) busy.value = false }
}
watch(() => [props.tenantId, props.taskId, props.revision], load, { immediate: true })
onBeforeUnmount(() => { epoch++ })
</script>

<template>
  <section class="geo-publication-monitor">
    <h3>发布后监测</h3>
    <p>正常页面每天复查，异常每小时重试；连续两次异常生成跟进工单。页面匹配不代表 AI 可见度提升。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="loading">正在读取发布监测记录…</p>
    <p v-if="!loading && !rows.length && !error">真实发布登记后，自动开始监测。</p>
    <article v-for="row in rows" :key="row.publication_id">
      <strong>#{{ row.publication_id }} · {{ labels[row.state] || row.state }}</strong>
      <p>{{ row.url }}</p>
      <small v-if="row.checked_at">最近检查：{{ new Date(row.checked_at).toLocaleString() }}；连续异常 {{ row.failures || 0 }} 次</small>
      <p v-if="row.state === 'version_changed'">请核对原稿版本；新稿实际发布后重新登记。系统不会把草稿变化误判为网站改动。</p>
      <button type="button" :disabled="busy" @click="check(row)">{{ busy ? '检查中…' : '重新检查' }}</button>
      <small>五分钟内重复操作返回上次检查结果。</small>
    </article>
    <router-link to="/geo/tickets">处理异常与效果复盘工单</router-link>
  </section>
</template>

<style scoped>
.geo-publication-monitor { padding: 18px; border: 1px solid #dbe3ef; border-radius: 10px; margin-top: 16px; }
article { border-top: 1px solid #e5e7eb; padding: 12px 0; overflow-wrap: anywhere; }
p, small { color: #56657a; } button { margin: 8px; padding: 6px 12px; cursor: pointer; }
[role=alert] { color: #b42318; }
</style>
