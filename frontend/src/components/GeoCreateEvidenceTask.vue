<script setup>
import { reactive, watch, onBeforeUnmount } from 'vue'
import { evidenceTaskLink } from '../utils/geoEvidenceLinks'
import * as api from '../api/geoIntegration'
import { evidenceRequest, createEvidenceSubmitter } from '../utils/geoEvidenceCreate'
const props = defineProps({ tenantId: [Number, String], content: Object })
const emit = defineEmits(['close'])
const state = reactive({ busy: false, error: '', result: null })
const form = reactive({ title: '', metric: 'geo.visibility.ai_mention_rate_7d', delta: 1, role: 'geo_operator' })
const submitter = createEvidenceSubmitter(state, api, () => props.tenantId, () => props.content?.id)
watch(() => [props.tenantId, props.content], () => {
  submitter.invalidate()
  Object.assign(state, { busy: false, error: '', result: null })
  Object.assign(form, { title: `提升AI可见度：${props.content?.title || ''}`.slice(0, 300), metric: 'geo.visibility.ai_mention_rate_7d', delta: 1, role: 'geo_operator' })
}, { immediate: true })
onBeforeUnmount(submitter.invalidate)
function submit() {
  try { submitter.submit(evidenceRequest(props.content?.id, form)) }
  catch (e) { state.error = e.message }
}
</script>
<template>
  <el-dialog :model-value="!!content" title="建立指标验收任务" width="min(560px, 94vw)" @close="emit('close')">
    <p>关联文章 #{{ content?.id }}：{{ content?.title }}</p>
    <p>目标按客户完整自然周统计，不代表该篇文章的独立贡献。创建后需核实真实发布，并通过同题同模型周复测验收。</p>
    <el-alert v-if="state.error" type="error" :title="state.error" :closable="false" />
    <template v-if="state.result">
      <p>指标验收任务 #{{ state.result.id }} 已就绪。重复提交会返回已有任务。</p>
      <router-link :to="evidenceTaskLink(tenantId, state.result.id)" @click="emit('close')">前往指标验收任务，查看基线和执行条件</router-link>
    </template>
    <form v-else @submit.prevent="submit" class="evidence-create">
      <label>任务标题<input v-model="form.title" maxlength="300" required :disabled="state.busy" /></label>
      <label>目标指标<select v-model="form.metric" :disabled="state.busy">
        <option value="geo.visibility.ai_mention_rate_7d">AI提及率（百分点）</option>
        <option value="geo.visibility.ai_mention_count_7d">AI提及次数（次）</option>
        <option value="geo.visibility.ai_visibility_score">AI可见度分数（分）</option>
      </select></label>
      <label>至少提升量<input v-model="form.delta" type="number" :max="form.metric === 'geo.visibility.ai_mention_count_7d' ? undefined : 100" min="0.0001" step="any" required :disabled="state.busy" /></label>
      <label>负责人角色<input v-model="form.role" maxlength="100" required :disabled="state.busy" /></label>
      <p>尚无合格周数据时可以先建任务，基线显示未知，不会自动记为零或完成。</p>
      <button class="gd-btn primary" :disabled="state.busy || !tenantId" type="submit">{{ state.busy ? '正在创建…' : '建立验收任务' }}</button>
    </form>
  </el-dialog>
</template>
<style scoped>
.evidence-create label { display: grid; gap: 6px; margin: 14px 0; }
.evidence-create input, .evidence-create select { padding: 8px; border: 1px solid #d1d5db; border-radius: 6px; width: 100%; box-sizing: border-box; }
p { line-height: 1.7; }
</style>
