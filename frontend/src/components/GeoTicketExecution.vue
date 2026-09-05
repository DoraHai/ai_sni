<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { saveGeoTicketExecution } from '../api/geo'
import { executionDraft, snapshotIds } from '../utils/geoTicketExecution'
import { geoSnapshotLink } from '../utils/geoRoutes'

const props = defineProps({ tenantId: [Number, String], ticket: { type: Object, required: true }, disabled: Boolean })
const emit = defineEmits(['saved'])
const draft = ref({}), saving = ref(false), error = ref('')
let generation = 0
watch(() => [props.tenantId, props.ticket.id], () => {
  generation++; draft.value = executionDraft(props.ticket); error.value = ''; saving.value = false
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { generation++ })
const rate = (n) => n == null ? '—' : `${(n * 100).toFixed(1)}%`
const delta = (n) => n == null ? '样本不足，暂不判断' : `${n > 0 ? '+' : ''}${(n * 100).toFixed(1)} 个百分点`
async function save() {
  if (saving.value || props.disabled) return
  const current = generation, owner = props.tenantId, id = props.ticket.id
  saving.value = true; error.value = ''
  try {
    const taskId = Number(draft.value.taskId)
    if (!Number.isSafeInteger(taskId) || taskId <= 0) throw new Error('请填写有效的内容任务编号')
    if (!draft.value.note.trim()) throw new Error('请填写具体修改内容')
    const saved = await saveGeoTicketExecution(owner, id, {
      content_task_id: taskId, before_snapshot_ids: snapshotIds(draft.value.before),
      after_snapshot_ids: snapshotIds(draft.value.after), change_note: draft.value.note.trim(),
    })
    if (current !== generation) return
    draft.value = executionDraft(saved)
    emit('saved', saved)
  } catch (e) { if (current === generation) error.value = e.message || '关联失败，请重试' }
  finally { if (current === generation) saving.value = false }
}
</script>

<template>
  <details class="execution">
    <summary>内容修改与同题复测{{ ticket.content_task_id ? ` · 已关联任务 #${ticket.content_task_id}` : '' }}</summary>
    <p>记录具体修改，关联同一问题的前后快照。可以先保存任务和修改前样本，完成内容修改、采样后再补复测编号。</p>
    <fieldset :disabled="saving || disabled">
      <label>内容任务编号 <input v-model="draft.taskId" inputmode="numeric" aria-label="关联内容任务编号" /></label>
      <label>修改前快照编号 <input v-model="draft.before" placeholder="例如 101, 102, 103" aria-label="修改前快照编号" /></label>
      <label>复测快照编号 <input v-model="draft.after" placeholder="内容保存后，同一问题的新快照" aria-label="复测快照编号" /></label>
      <label>具体修改 <textarea v-model="draft.note" maxlength="4000" rows="3" aria-label="具体内容修改" placeholder="补充了哪些事实、出处或适用条件" /></label>
      <el-button :loading="saving" :disabled="saving || disabled" @click="save">保存内容与复测关联</el-button>
    </fieldset>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="ticket.content_task_id">
      <router-link :to="`/geo/tasks/${ticket.content_task_id}`">打开关联内容任务 #{{ ticket.content_task_id }}</router-link>
      <p v-if="ticket.progress?.change_note">已记录修改：{{ ticket.progress.change_note }} · 内容版本 {{ ticket.progress.version_no || '尚未保存' }}</p>
      <router-link :to="geoSnapshotLink({ prompt_id: ticket.baseline_snapshot?.prompt_id })">用同一问题采样 / 查看记录</router-link>
      <div v-for="group in [{ label: '修改前', samples: ticket.baseline_snapshot?.samples }, { label: '复测', samples: ticket.progress?.samples }]" :key="group.label">
        <p>{{ group.label }}证据：<router-link v-for="sample in group.samples || []" :key="sample.id" :to="geoSnapshotLink({ prompt_id: ticket.baseline_snapshot?.prompt_id, snapshot_id: sample.id })"> #{{ sample.id }} </router-link></p>
      </div>
      <table v-if="ticket.progress?.comparison?.engines?.length">
        <caption>所选样本的品牌提及率</caption>
        <thead><tr><th>引擎</th><th>修改前</th><th>复测</th><th>变化</th></tr></thead>
        <tbody><tr v-for="row in ticket.progress.comparison.engines" :key="row.engine"><td>{{ row.engine }}</td><td>{{ row.before_count }} 条 · {{ rate(row.before_rate) }}</td><td>{{ row.after_count }} 条 · {{ rate(row.after_rate) }}</td><td>{{ delta(row.delta) }}</td></tr></tbody>
      </table>
      <p v-if="ticket.progress?.comparison">等权提及率变化：{{ delta(ticket.progress.comparison.delta) }}。{{ ticket.progress.comparison.note }}</p>
      <p>关联结果不会自动将待办标记完成；请核验后记录验收结论。</p>
    </template>
  </details>
</template>
<style scoped>
.execution{margin:16px 0;padding:12px;background:#f8fafc}.execution p{line-height:1.6}fieldset{border:0;padding:0;display:grid;gap:10px}label{display:grid;gap:4px}input,textarea{padding:8px;border:1px solid #cbd5e1;border-radius:4px;font:inherit}table{width:100%;border-collapse:collapse}th,td{padding:8px;text-align:left;border-bottom:1px solid #ddd}
</style>
