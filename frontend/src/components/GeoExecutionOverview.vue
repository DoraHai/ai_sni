<script setup>
import { computed, reactive, ref, watch, onBeforeUnmount } from 'vue'
import * as api from '../api/geoIntegration'
import { executionNext, createOverviewLoader } from '../utils/geoExecutionOverview'
const props = defineProps({ tenantId: [String, Number], tasks: { type: Array, default: () => [] }, disabled: Boolean })
const emit = defineEmits(['open'])
const offset = ref(0)
const state = reactive({ rows: [], loading: false })
const loader = createOverviewLoader(state, api)
const page = computed(() => props.tasks.slice(offset.value, offset.value + 20))
function refresh() { return loader.load(props.tenantId, page.value) }
watch(() => [props.tenantId, props.tasks], () => { offset.value = 0; refresh() }, { immediate: true })
function move(delta) { offset.value += delta; refresh() }
onBeforeUnmount(loader.invalidate)
</script>
<template>
  <section class="execution-overview" aria-label="执行阻塞总览">
    <h4>执行阻塞总览</h4>
    <p>仅分析当前筛选已加载的任务，每批最多20项。这里只读取条件，操作需进入任务详情；未知不等于没有工作。</p>
    <button class="gd-btn" :disabled="disabled || state.loading" @click="refresh">刷新执行总览</button>
    <p v-if="state.loading">正在读取各任务的实际执行条件…</p>
    <table v-if="state.rows.length">
      <thead><tr><th>任务</th><th>当前阶段</th><th>下一步</th></tr></thead>
      <tbody><tr v-for="entry in state.rows" :key="entry.task.id">
        <td><button class="gd-btn" :disabled="disabled" @click="emit('open', entry.task)">#{{ entry.task.id }} {{ entry.task.title }}</button></td>
        <td>{{ executionNext(entry.task, entry.detail, entry.error).stage }}</td>
        <td>{{ executionNext(entry.task, entry.detail, entry.error).next }}</td>
      </tr></tbody>
    </table>
    <p v-else>当前没有已加载任务可供分析。</p>
    <p>当前批次 {{ tasks.length ? offset + 1 : 0 }}–{{ Math.min(offset + 20, tasks.length) }} / 已加载 {{ tasks.length }} 项</p>
    <button class="gd-btn" :disabled="disabled || offset === 0" @click="move(-20)">上一批</button>
    <button class="gd-btn" :disabled="disabled || offset + 20 >= tasks.length" @click="move(20)">下一批</button>
  </section>
</template>
<style scoped>
.execution-overview { margin: 16px 0; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 10px; text-align: left; border-bottom: 1px solid #e5e7eb; vertical-align: top; }
td .gd-btn { white-space: normal; text-align: left; }
th:nth-child(2) { min-width: 110px; }
</style>
