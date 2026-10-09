<script setup>
import { ref, reactive, watch, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { session } from '../store/session'
import { fetchGeoProjectExecutions, saveGeoProjectPlan } from '../api/geoProjects'
import GeoTicketExecution from './GeoTicketExecution.vue'

const props = defineProps({ projectId: { type: Number, required: true }, tenantId: [Number, String] })
const data = ref(null), loading = ref(false), saving = ref(false), error = ref('')
const form = reactive({ enabled: false, status: 'paused', prompt_ids: [], interval_days: 7 })
const labels = { baseline: '保留修改前证据', content: '准备内容任务', materials: '补齐创作要求与事实',
  article: '制作内容', review: '确认当前内容版本', publication: '发布与回填', retest: '同题复测',
  comparison: '核对前后变化', acceptance: '顾问验收' }
let generation = 0
async function load() {
  const current = ++generation
  data.value = null; error.value = ''; loading.value = true
  try {
    const result = await fetchGeoProjectExecutions(props.projectId, props.tenantId)
    if (current !== generation) return
    data.value = result
    Object.assign(form, { enabled: result.service_plan.enabled, status: result.service_plan.status,
      prompt_ids: [...result.service_plan.prompt_ids], interval_days: result.service_plan.interval_days })
  } catch (e) { if (current === generation) error.value = e.message || '执行进度读取失败' }
  finally { if (current === generation) loading.value = false }
}
async function save() {
  if (saving.value || !data.value) return
  const current = generation
  saving.value = true
  try {
    await saveGeoProjectPlan(props.projectId, props.tenantId, { ...form,
      expected_revision: data.value.service_plan.revision,
      advisor_user_id: data.value.service_plan.advisor_user_id || session.user?.id || null })
    if (current !== generation) return
    ElMessage.success('项目服务计划已保存')
    await load()
  } catch (e) { if (current === generation) error.value = e.message || '计划保存失败，请重新读取核对' }
  finally { saving.value = false }
}
watch(() => [props.tenantId, props.projectId], load, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>

<template>
  <section class="project-execution">
    <el-alert v-if="error" type="error" :title="error" :closable="false" />
    <p>只显示当前项目的业务与问题。周期任务自动更新下一步；内容确认、真实发布和验收需要明确处理。</p>
    <el-button :loading="loading" :disabled="saving" @click="load">刷新项目进度</el-button>
    <template v-if="data">
      <el-alert v-if="data.effective_pause" title="当前项目或服务计划已暂停" type="warning" :closable="false" />
      <el-alert v-if="data.blocker" title="项目计划需要顾问核对业务归属或分配权限" type="warning" :closable="false" />
      <h3>服务计划</h3>
      <el-form v-if="session.canEdit('geo.content') && session.canEdit('geo.assets')" label-width="110px">
        <el-form-item label="周期待办"><el-switch v-model="form.enabled" :disabled="saving" /></el-form-item>
        <el-form-item label="计划状态"><el-select v-model="form.status" :disabled="saving"><el-option label="运行" value="active" /><el-option label="暂停" value="paused" /></el-select></el-form-item>
        <el-form-item label="目标问题"><el-select v-model="form.prompt_ids" multiple :multiple-limit="20" :disabled="saving" style="width:100%"><el-option v-for="p in data.prompts" :key="p.id" :value="p.id" :label="p.question" /></el-select></el-form-item>
        <el-form-item label="周期天数"><el-input-number v-model="form.interval_days" :min="1" :max="90" :disabled="saving" /></el-form-item>
        <p>新计划由当前顾问负责。已开启的周期不会自动替客户确认稿件，也不会直接调用付费采样或发布渠道。</p>
        <el-button type="primary" :loading="saving" @click="save">保存服务计划</el-button>
      </el-form>
      <p v-else>{{ data.service_plan.enabled ? '已开启周期待办' : '周期待办尚未开启' }} · 每 {{ data.service_plan.interval_days }} 天</p>
      <h3>执行与人工待办</h3>
      <el-empty v-if="!data.items.length" description="当前项目暂无执行记录" />
      <article v-for="row in data.items" :key="row.id" class="project-task">
        <h4>{{ row.title }}</h4>
        <p>{{ row.status === 'done' ? '已验收' : `下一步：${labels[row.execution.next_step] || '顾问核对'}` }} <strong v-if="row.workflow?.overdue">· 已超时，需关注</strong></p>
        <p v-if="row.workflow">顾问待办 · 截止 {{ row.workflow.due_at?.slice(0, 10) }} · 站内提醒</p>
        <GeoTicketExecution :key="`${row.id}:${row.ticket.updated_at}`" :tenant-id="tenantId" :project-id="projectId" :ticket="row.ticket" :disabled="saving || data.effective_pause || !session.canEdit('geo.content')" @saved="load" />
      </article>
      <p v-if="data.truncated">显示最近 20 项；历史记录可在执行待办查看。</p>
    </template>
  </section>
</template>

<style scoped>
.project-execution{padding:0 12px}.project-task{margin-top:16px;padding:12px;border:1px solid #e2e8f0;border-radius:8px}.project-task strong{color:#b45309}.project-execution p{line-height:1.7}
</style>
