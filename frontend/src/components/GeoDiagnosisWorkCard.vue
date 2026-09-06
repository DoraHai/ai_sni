<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { fetchGeoDiagnosisWork, patchGeoActionTicket } from '../api/geo'
const props = defineProps({ tenantId: [Number,String], ticket: Object, disabled: Boolean })
const emit = defineEmits(['saved'])
const plan = ref(null), error = ref(''), loading = ref(false), busy = ref(false)
const owner = ref(''), due = ref('')
let epoch = 0
async function load() {
  const run = ++epoch
  plan.value = null; error.value = ''; busy.value = false
  owner.value = props.ticket?.owner_name || ''; due.value = props.ticket?.due_date || ''
  if (!props.tenantId || !props.ticket?.id) { loading.value = false; return }
  loading.value = true
  try {
    const result = await fetchGeoDiagnosisWork(props.tenantId, props.ticket.id)
    if (run !== epoch) return
    plan.value = result
  } catch (e) { if (run === epoch) error.value = e.message || '执行卡加载失败' }
  finally { if (run === epoch) loading.value = false }
}
async function save(start = false) {
  if (busy.value || loading.value || props.disabled || !plan.value) return
  const run = epoch
  busy.value = true; error.value = ''
  try {
    const payload = start ? {status:'doing'} : {owner_name:owner.value.trim() || null,due_date:due.value || null}
    const saved = await patchGeoActionTicket(props.tenantId, props.ticket.id, payload)
    if (run !== epoch) return
    emit('saved',saved)
  } catch (e) { if (run === epoch) error.value = e.message || '保存失败' }
  finally { if (run === epoch) busy.value = false }
}
watch(() => [props.tenantId,props.ticket?.id], load, {immediate:true})
onBeforeUnmount(() => { epoch++ })
</script>
<template>
  <section class="diagnosis-work" aria-label="整改执行卡">
    <header><h4>整改执行卡</h4><el-button :disabled="busy || disabled" @click="load">刷新执行卡</el-button></header>
    <el-alert v-if="error" type="error" :title="error" :closable="false" />
    <p v-if="loading">正在读取原始诊断…</p>
    <template v-if="plan">
      <p><b>目标页面：</b><a v-if="plan.page_url" :href="plan.page_url" target="_blank" rel="noopener noreferrer">{{ plan.page_url }}</a><span v-else>缺少有效页面地址，请核对原始诊断。</span></p>
      <p><b>诊断时间：</b>{{ plan.diagnosed_at || '未记录' }} · {{ plan.page_title }}</p>
      <p><b>原始问题依据：</b>{{ plan.source_evidence || '该诊断未保存详细依据，请先核对页面。' }}</p>
      <el-alert v-if="plan.source_passed === true" title="原始诊断中该项已经通过，请先确认是否仍需整改。" type="warning" :closable="false" />
      <p><b>建议处理角色：</b>{{ plan.suggested_role }}</p>
      <ol><li v-for="(step,index) in plan.steps" :key="index">{{ step }}</li></ol>
      <p><b>验收要求：</b>{{ plan.acceptance }}</p>
      <p>{{ plan.outcome_note }}</p>
      <div class="assignment">
        <label>负责人 <input v-model="owner" :disabled="busy || disabled" maxlength="100" placeholder="填写实际负责人" /></label>
        <label>计划完成日期 <input v-model="due" :disabled="busy || disabled" type="date" /></label>
        <el-button :disabled="busy || disabled" @click="save(false)">保存执行安排</el-button>
        <el-button v-if="['todo','reopened','blocked'].includes(ticket.status)" :disabled="busy || disabled || !plan.page_url" @click="save(true)">开始处理</el-button>
      </div>
      <p>{{ plan.acceptance_type === 'auto' ? '实际改动生效后，请使用工单行的重抓验收。' : '实际改动生效后，请按人工验收要求记录依据。' }}保存执行安排不会将任务标记为完成。</p>
    </template>
  </section>
</template>
<style scoped>
.diagnosis-work { padding:16px 24px; background:#f8fafc; }
header,.assignment { display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
h4 { margin:0; }
p,li { font-size:13px; line-height:1.7; overflow-wrap:anywhere; }
input { border:1px solid #cbd5e1; border-radius:5px; padding:6px; }
a { color:#2563eb; }
</style>
