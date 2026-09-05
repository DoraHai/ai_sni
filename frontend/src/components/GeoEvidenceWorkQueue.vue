<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchGeoCitationInsights, createGeoSourceOpportunityTask } from '../api/geoContent'
import { useObservationPeriod } from '../composables/useObservationPeriod'
import { evidenceWorkItems } from '../utils/geoWorkQueue'
import { geoSnapshotLink } from '../utils/geoRoutes'
import GeoWorkTickets from './GeoWorkTickets.vue'

const props = defineProps({ tenantId: { type: [Number, String], default: null } })
const router = useRouter()
const { start, end, days, label } = useObservationPeriod()
const insights = ref(null)
const loading = ref(false)
const error = ref('')
const creating = ref(null)
let generation = 0
const work = computed(() => evidenceWorkItems(insights.value))
async function load() {
  const current = ++generation
  const owner = props.tenantId
  insights.value = null
  error.value = ''
  loading.value = false
  if (!owner) return
  loading.value = true
  try {
    const result = await fetchGeoCitationInsights(owner, { date_from: start.value, date_to: end.value, days: days.value })
    if (current !== generation) return
    if (!result?.source_opportunities || !Array.isArray(result.source_opportunities.items)) throw new Error('当前接口未提供工作线索，请稍后重试。')
    insights.value = result
  } catch (e) {
    if (current === generation) error.value = e.message || '工作线索加载失败'
  } finally {
    if (current === generation) loading.value = false
  }
}
async function create(item) {
  if (creating.value !== null || !props.tenantId) return
  const current = generation
  const owner = props.tenantId
  const row = item.opportunity
  creating.value = item.id
  try {
    const result = await createGeoSourceOpportunityTask({ tenant_id: owner, prompt_id: row.prompt_id, snapshot_ids: row.sample_ids, evidence_version: row.evidence_version })
    if (current !== generation) return
    ElMessage.success(result.created ? '已创建待完善的内容草稿，请先核验事实' : '已打开该问题的已有任务')
    router.push(`/geo/tasks/${result.task_id}`)
  } catch (e) {
    if (current === generation) ElMessage.error(e.message || '创建失败，请刷新证据后重试')
  } finally { creating.value = null }
}
watch(() => [props.tenantId, start.value, end.value], load, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { generation++ })
</script>

<template>
  <section class="work-queue" aria-label="GEO 下一步工作">
    <div class="queue-heading"><div><h2>下一步做什么</h2><p>{{ label }} · 根据当前客户的采样证据整理，待你确认后执行。</p></div><el-button :loading="loading" :disabled="!tenantId" @click="load">刷新工作线索</el-button></div>
    <p>可将建议加入执行待办，记录进度与验收结果；需要制作内容时再创建内容任务。</p>
    <el-alert v-if="error" type="error" :title="error" :closable="false" />
    <p v-else-if="!tenantId">请先选择客户。</p>
    <p v-else-if="loading" role="status">正在检查样本与工作线索…</p>
    <p v-else-if="insights && !work.length">当前可用样本未触发引用机会规则。已有内容任务仍可继续；这不代表所有业务问题都已覆盖。</p>
    <article v-for="item in work" :key="item.id" class="work-item">
      <el-tag size="small">待确认 · {{ item.kind }}</el-tag><h3>{{ item.title }}</h3>
      <p><b>为什么做：</b>{{ item.reason }}</p>
      <p><b>具体动作：</b>{{ item.action }}</p>
      <p><b>怎样验收：</b>{{ item.acceptance }}</p>
      <div class="queue-actions">
        <el-button @click="router.push(geoSnapshotLink({ prompt_id: item.promptId }))">{{ item.kind === '补充采样' ? '去采样' : '查看回答证据' }}</el-button>
        <el-button v-if="item.opportunity" type="primary" :loading="creating === item.id" :disabled="creating !== null || !item.opportunity.sample_ids?.length || item.opportunity.sample_ids.length > 1000 || !item.opportunity.evidence_version" @click="create(item)">创建 / 打开内容任务</el-button>
      </div>
    </article>
    <GeoWorkTickets :tenant-id="tenantId" :suggestions="work" :period="label" />
  </section>
</template>

<style scoped>
.work-queue{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:20px;margin-bottom:20px;color:#334155}
.queue-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
h2{margin:0;font-size:20px}h3{font-size:16px;margin:10px 0}p{line-height:1.65;margin:8px 0}
.work-item{border-top:1px solid #e2e8f0;margin-top:16px;padding-top:16px}.queue-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
</style>
