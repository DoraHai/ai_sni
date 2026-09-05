<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { saveGeoTicketExecution, fetchGeoExecutionPlan, prepareGeoTicketContent } from '../api/geo'
import { executionDraft, snapshotIds, recommendedSamples } from '../utils/geoTicketExecution'
import { geoSnapshotLink } from '../utils/geoRoutes'

const props = defineProps({ tenantId: [Number, String], ticket: { type: Object, required: true }, disabled: Boolean })
const emit = defineEmits(['saved', 'busy'])
const draft = ref({}), saving = ref(false), error = ref('')
const plan = ref(null), planLoading = ref(false), planError = ref(''), promptChoice = ref('')
let generation = 0, planRequest = 0
watch([() => props.tenantId, () => props.ticket.id], () => {
  generation++; planRequest++; draft.value = executionDraft(props.ticket); error.value = ''; saving.value = false
  plan.value = null; planError.value = ''; planLoading.value = false; promptChoice.value = ''
}, { immediate: true, flush: 'sync' })
watch(saving, (value) => emit('busy', value), { flush: 'sync' })
onBeforeUnmount(() => { generation++; planRequest++; if (saving.value) emit('busy', false) })
const rate = (n) => n == null ? '—' : `${(n * 100).toFixed(1)}%`
const delta = (n) => n == null ? '样本不足，暂不判断' : `${n > 0 ? '+' : ''}${(n * 100).toFixed(1)} 个百分点`
async function loadPlan() {
  const current = generation, request = ++planRequest
  planLoading.value = true; planError.value = ''
  try {
    const result = await fetchGeoExecutionPlan(props.tenantId, props.ticket.id, draft.value.taskId)
    if (current !== generation || request !== planRequest) return
    plan.value = result
    if (!draft.value.taskId && result.selected_task_id) draft.value.taskId = result.selected_task_id
  } catch (e) { if (current === generation && request === planRequest) { plan.value = null; planError.value = e.message || '执行计划加载失败' } }
  finally { if (current === generation && request === planRequest) planLoading.value = false }
}
function changeTask() {
  draft.value.before = ''; draft.value.after = ''; draft.value.note = ''
  plan.value = null
  loadPlan()
}
function selected(group, id) { return snapshotIds(draft.value[group]).includes(id) }
function toggleSample(group, id, checked) {
  const ids = new Set(snapshotIds(draft.value[group]))
  if (checked) ids.add(id); else ids.delete(id)
  draft.value[group] = [...ids].join(', ')
}
function recommend() {
  draft.value.before = recommendedSamples(plan.value?.before || []).join(', ')
  draft.value.after = recommendedSamples(plan.value?.after || []).join(', ')
}
async function prepare() {
  if (saving.value || props.disabled || planLoading.value || props.ticket.status === 'done' || !plan.value) return
  const current = generation
  saving.value = true; error.value = ''
  try {
    const result = await prepareGeoTicketContent(props.tenantId, props.ticket.id, plan.value.prompt_id || Number(promptChoice.value))
    if (current !== generation) return
    draft.value = executionDraft(result.ticket)
    emit('saved', result.ticket)
    await loadPlan()
  } catch (e) { if (current === generation) error.value = e.message || '准备失败，请重试' }
  finally { if (current === generation) saving.value = false }
}
async function save() {
  if (saving.value || props.disabled || planLoading.value || props.ticket.status === 'done' || !plan.value) return
  const current = generation, owner = props.tenantId, id = props.ticket.id
  saving.value = true; error.value = ''
  try {
    const taskId = Number(draft.value.taskId)
    if (!Number.isSafeInteger(taskId) || taskId <= 0) throw new Error('请填写有效的内容任务编号')
    if (!draft.value.note.trim()) throw new Error('请填写具体修改内容')
    const saved = await saveGeoTicketExecution(owner, id, {
      content_task_id: taskId, before_snapshot_ids: snapshotIds(draft.value.before),
      expected_article_id: plan.value.article_id ?? null,
      after_snapshot_ids: snapshotIds(draft.value.after), change_note: draft.value.note.trim(),
    })
    if (current !== generation) return
    draft.value = executionDraft(saved)
    emit('saved', saved)
    await loadPlan()
  } catch (e) { if (current === generation) error.value = e.message || '关联失败，请重试' }
  finally { if (current === generation) saving.value = false }
}
</script>

<template>
  <details class="execution" @toggle="(event) => { if (event.target.open && !plan && !planLoading) loadPlan() }">
    <summary>内容修改与同题复测{{ ticket.content_task_id ? ` · 已关联任务 #${ticket.content_task_id}` : '' }}</summary>
    <p>按步骤推进工作，系统会根据内容与证据显示尚未完成的环节。</p>
    <el-button :loading="planLoading" :disabled="saving" @click="loadPlan">刷新执行进度</el-button>
    <p v-if="planError" role="alert">{{ planError }}</p>
    <template v-if="plan">
      <ol class="steps"><li v-for="step in plan.steps" :key="step.id" :class="{ current: step.id === plan.next_step }"><b>{{ step.done ? '已具备' : '待处理' }} · {{ step.title }}</b><p>{{ step.instruction }}</p></li></ol>
      <p v-if="ticket.content_task_id">{{ plan.next_step === 'acceptance' ? '执行条件已具备，请在下方填写核验结论并验收。' : '验收前请补齐标记为待处理的步骤；保存关联后刷新进度。' }}</p>
      <p v-if="plan.question"><b>目标问题：</b>{{ plan.question }}</p>
      <label v-if="!plan.prompt_id">选择目标问题 <select v-model="promptChoice" aria-label="待办目标问题"><option value="">请选择</option><option v-for="prompt in plan.prompts" :key="prompt.id" :value="prompt.id">{{ prompt.question }}</option></select></label>
      <el-button v-if="!ticket.content_task_id" :loading="saving" :disabled="disabled || saving || planLoading || ticket.status === 'done' || (!plan.prompt_id && !promptChoice)" @click="prepare">准备内容任务并保留基线</el-button>
      <p v-if="!ticket.content_task_id">优先关联同题已有任务；没有时创建草稿并带入待办要求，不覆盖已有正文。</p>
      <p v-if="draft.taskId"><router-link :to="`/geo/tasks/${draft.taskId}`">继续完善事实、制作内容与发布</router-link></p>
      <p v-if="plan.prompt_id"><router-link :to="geoSnapshotLink({ prompt_id: plan.prompt_id })">打开同题采样，补齐下方缺口</router-link></p>
      <p v-for="gap in plan.gaps" :key="gap.engine">{{ gap.engine }} 候选样本：修改前 {{ gap.before_count }} 条，复测 {{ gap.after_count }} 条；还需修改前 {{ gap.before_needed }} 条、复测 {{ gap.after_needed }} 条。</p>
      <p v-if="plan.truncated">每侧最多显示最近 100 条记录，请结合观察期选择证据。</p>
      <p v-if="plan.excluded">已排除 {{ plan.excluded }} 条不符合真实采样或判读要求的记录。</p>
    </template>
    <fieldset :disabled="saving || disabled || planLoading || !plan || ticket.status === 'done'">
      <label>关联内容任务 <select v-model="draft.taskId" aria-label="关联内容任务" @change="changeTask"><option value="">请选择或准备任务</option><option v-if="ticket.content_task_id && !plan?.tasks?.some((t) => t.id === ticket.content_task_id)" :value="ticket.content_task_id">已关联任务 #{{ ticket.content_task_id }}</option><option v-for="task in plan?.tasks || []" :key="task.id" :value="task.id">{{ task.title }} · #{{ task.id }} · {{ task.status }}</option></select></label>
      <el-button :disabled="!plan || planLoading" @click="recommend">选择每个引擎最近 3 条候选</el-button>
      <div v-for="group in [{ key: 'before', label: '修改前证据' }, { key: 'after', label: '复测证据' }]" :key="group.key">
        <h4>{{ group.label }} · 已选 {{ snapshotIds(draft[group.key]).length }} 条</h4>
        <p v-if="!plan?.[group.key]?.length">暂无可用候选，请先完成对应采样与判读。</p>
        <label v-for="sample in plan?.[group.key] || []" :key="sample.id" class="sample"><input type="checkbox" :checked="selected(group.key, sample.id)" @change="toggleSample(group.key, sample.id, $event.target.checked)" /><span>{{ sample.engine }} · {{ sample.captured_at }} · {{ sample.mentions_brand ? '提及品牌' : '未提及品牌' }} · #{{ sample.id }}<small>{{ sample.raw_text }}</small><router-link :to="geoSnapshotLink({ prompt_id: plan.prompt_id, snapshot_id: sample.id })">查看原始回答与引用</router-link></span></label>
      </div>
      <label>具体修改 <textarea v-model="draft.note" maxlength="4000" rows="3" aria-label="具体内容修改" placeholder="补充了哪些事实、出处或适用条件" /></label>
      <el-button :loading="saving" :disabled="saving || disabled" @click="save">保存内容与复测关联</el-button>
    </fieldset>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="ticket.content_task_id">
      <router-link :to="`/geo/tasks/${ticket.content_task_id}`">打开关联内容任务 #{{ ticket.content_task_id }}</router-link>
      <p v-if="ticket.progress?.change_note">已记录修改：{{ ticket.progress.change_note }} · 内容版本 {{ ticket.progress.version_no || '尚未保存' }}</p>
      <p v-if="ticket.progress?.acceptance"><b>执行验收回执：</b>{{ ticket.progress.acceptance.checked_at }} · 内容版本记录 #{{ ticket.progress.acceptance.article_id }} · {{ ticket.progress.acceptance.note }}。回执保留验收当时的检查结果，后续内容变化需重新核验。</p>
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
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;padding:0;list-style:none}.steps li{padding:12px;border:1px solid #cbd5e1;border-radius:8px}.steps .current{border-color:#2563eb;background:#eff6ff}.sample{grid-template-columns:18px 1fr;padding:10px;border-bottom:1px solid #e2e8f0;align-items:start}.sample small{display:block;max-height:4.5em;overflow:hidden;white-space:pre-wrap;margin:4px 0;color:#64748b}select{padding:8px;max-width:100%;font:inherit}
</style>
