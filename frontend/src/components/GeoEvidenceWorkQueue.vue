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
  <section class="work-queue" aria-label="GEO 本期优化建议">
    <div class="queue-heading"><div><span class="eyebrow">INSIGHT → ACTION</span><h2>本期优化建议</h2><p>{{ label }} · 根据当前客户的采样证据整理</p></div><el-button text :loading="loading" :disabled="!tenantId" @click="load">刷新</el-button></div>
    <el-alert v-if="error" type="error" :title="error" :closable="false" />
    <p v-else-if="!tenantId">请先选择客户。</p>
    <p v-else-if="loading" role="status">正在检查样本与工作线索…</p>
    <p v-else-if="insights && !work.length">当前可用样本未触发引用机会规则。已有内容任务仍可继续；这不代表所有业务问题都已覆盖。</p>
    <article v-for="item in work" :key="item.id" class="work-item">
      <div class="insight-top"><el-tag size="small">{{ item.kind }}</el-tag><span class="insight-priority">{{ item.opportunity ? '高优先级' : '待确认' }}</span></div>
      <h3>{{ item.title }}</h3>
      <div class="insight-grid"><div><small>发现了什么</small><p>{{ item.reason }}</p></div><div><small>建议动作</small><p>{{ item.action }}</p></div><div><small>验收标准</small><p>{{ item.acceptance }}</p></div></div>
      <div class="queue-actions">
        <el-button type="primary" plain @click="router.push(geoSnapshotLink({ prompt_id: item.promptId }))">{{ item.kind === '补充采样' ? '去采样 →' : '查看回答证据 →' }}</el-button>
        <el-button v-if="item.opportunity" text :loading="creating === item.id" :disabled="creating !== null || !item.opportunity.sample_ids?.length || item.opportunity.sample_ids.length > 1000 || !item.opportunity.evidence_version" @click="create(item)">创建内容任务</el-button>
      </div>
    </article>
    <GeoWorkTickets :tenant-id="tenantId" :suggestions="work" :period="label" />
  </section>
</template>

<style scoped>
.work-queue{margin-bottom:24px;color:#303645}.queue-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;padding-bottom:12px;border-bottom:1px solid #e8eaf0}.eyebrow{display:block;color:#a1a7b3;font-size:10px;font-weight:800;letter-spacing:.14em;margin-bottom:4px}h2{margin:0;font-size:19px;color:#202533}h3{font-size:15px;margin:10px 0 13px;color:#202533}p{line-height:1.5;margin:4px 0}.queue-heading p{color:#8a91a0;font-size:12px}.work-item{padding:17px 0 18px;border-bottom:1px solid #e8eaf0}.work-item:last-of-type{border-bottom:0}.insight-top{display:flex;align-items:center;gap:8px}.insight-priority{font-size:11px;color:#a36f1b}.insight-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}.insight-grid small{color:#9299a7;font-size:11px}.insight-grid p{color:#586071;font-size:12px}.queue-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}@media(max-width:800px){.insight-grid{grid-template-columns:1fr}.status-note{display:none}}
</style>
