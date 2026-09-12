<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { fetchTaskPushTargets, submitGeoTaskReview, decideGeoTaskReview } from '../api/geoContent'
import * as evidenceApi from '../api/geoIntegration'
import { evidenceTaskLink } from '../utils/geoEvidenceLinks'
import { executionNext } from '../utils/geoExecutionOverview'
import { describeAcceptanceSummary } from '../utils/geoAcceptanceSummary'
import { canDecideGeoReview, canSubmitGeoReview } from '../utils/geoReviewAccess'
import { session } from '../store/session'
import GeoCreateEvidenceTask from './GeoCreateEvidenceTask.vue'
const props = defineProps({ tenantId: [Number, String], task: Object, disabled: Boolean })
const emit = defineEmits(['changed'])
const router = useRouter()
const targets = ref([]), linked = ref([]), selectedId = ref(null), detail = ref(null)
const acceptance = ref(null), acceptanceError = ref('')
const expanded = ref(false)
const error = ref(''), loading = ref(false), busy = ref(false), confirmed = ref(false), createOpen = ref(false)
let epoch = 0
const selected = computed(() => linked.value.find(row => row.id === selectedId.value))
const currentVariants = computed(() => (props.task?.variants || []).filter(v => v.article_version_id === props.task?.article?.id && !v.stale))
const configured = computed(() => targets.value.filter(t => (t.accounts || []).some(a => a.has_credentials && a.push_kind)))
const next = computed(() => selected.value ? executionNext(selected.value, detail.value, error.value) : null)
const currentProof = computed(() => detail.value?.publication_evidence?.article_id === props.task?.article?.id ? detail.value.publication_evidence : null)
const canSubmit = computed(() => canSubmitGeoReview(session.user))
const canDecide = computed(() => canDecideGeoReview(session.user))
const acceptanceStages = computed(() => describeAcceptanceSummary(acceptance.value))
async function load() {
  const run = ++epoch
  targets.value = []; linked.value = []; detail.value = null; acceptance.value = null; acceptanceError.value = ''; confirmed.value = false; error.value = ''; busy.value = false
  if (!props.tenantId || !props.task?.id) { loading.value = false; return }
  loading.value = true
  try {
    const acceptanceRead = evidenceApi.acceptanceSummary(props.tenantId, props.task.id)
      .then((value) => ({ value, error: '' }))
      .catch((e) => ({ value: null, error: e.message || 'H3/H4 验收摘要读取失败' }))
    const [push, tasks, acceptanceResult] = await Promise.all([
      fetchTaskPushTargets(props.tenantId, props.task.id),
      evidenceApi.listForContent(props.tenantId, props.task.id),
      acceptanceRead,
    ])
    if (run !== epoch) return
    targets.value = push.targets || []; linked.value = tasks
    acceptance.value = acceptanceResult.value; acceptanceError.value = acceptanceResult.error
    if (!tasks.some(row => row.id === selectedId.value)) selectedId.value = [...tasks].reverse().find(row => !['done','cancelled'].includes(row.status))?.id || tasks.at(-1)?.id || null
    if (selectedId.value) {
      const data = await evidenceApi.readiness(props.tenantId, selectedId.value)
      if (run !== epoch) return
      detail.value = data
    }
  } catch (e) { if (run === epoch) error.value = e.message || '检查失败，请刷新' }
  finally { if (run === epoch) loading.value = false }
}
async function review(decision) {
  if (busy.value || loading.value || props.disabled || (decision === 'approved' && !confirmed.value)) return
  if ((decision === 'submit' && !canSubmit.value) || (decision !== 'submit' && !canDecide.value)) return
  const run = epoch, tenant = props.tenantId, id = props.task.id
  busy.value = true; error.value = ''
  try {
    if (decision === 'submit') await submitGeoTaskReview(tenant, id)
    else await decideGeoTaskReview(tenant, id, decision, decision === 'approved' ? '客户确认已保存稿件可发布' : '客户要求修改', { expected_article_id: props.task.article?.id, expected_updated_at: props.task.updated_at })
    if (run !== epoch) return
    confirmed.value = false; emit('changed')
  } catch (e) { if (run === epoch) error.value = e.message || '审核操作失败' }
  finally { if (run === epoch) busy.value = false }
}
function openEvidence() { if (selected.value) router.push(evidenceTaskLink(props.tenantId, selected.value.id)) }
function distribution() { router.push(`/geo/tasks/${props.task.id}/distribution`) }
function requestReview() { expanded.value = true; document.getElementById('geo-launch-checklist')?.scrollIntoView({ behavior: 'smooth' }) }
defineExpose({ requestReview })
watch(() => [props.tenantId, props.task], () => { selectedId.value = null; createOpen.value = false; load() }, { immediate: true })
onBeforeUnmount(() => { epoch++ })
</script>
<template>
  <section id="geo-launch-checklist" class="launch-checklist" aria-label="发布前检查清单">
    <header><h3>发布前检查清单 · 客户审核一次</h3><el-button @click="expanded = !expanded">{{ expanded ? '收起' : '展开' }}</el-button><el-button :disabled="loading || busy || disabled" @click="load">刷新发布检查</el-button></header>
    <div v-show="expanded">
    <p>发布只需客户这一道人审，技术检查仍需通过。AI 检查提供修改建议，不代替客户确认。审核前请先保存母稿和渠道稿。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <p v-if="loading">正在读取渠道和验收状态…</p>
    <div v-else-if="task">
      <p><b>1. 自动发布账号：</b>{{ error ? '状态读取失败，请刷新' : configured.length ? `已有 ${configured.length} 个渠道配置账号` : '尚未配置；也可手工发布后回填链接' }} <el-button link @click="router.push('/geo/publishing')">配置渠道</el-button></p>
      <p><b>2. 渠道稿版本：</b>{{ currentVariants.length }} 个与当前母稿一致，共 {{ (task.variants || []).length }} 个。<el-button link @click="distribution">查看渠道稿与发布</el-button></p>
      <p><b>3. 客户审核：</b>{{ {none:'待提交客户审核',pending:'等待客户确认',approved:'客户已确认',rejected:'客户要求修改'}[task.review_status || 'none'] }}</p>
      <p v-if="disabled">请先保存当前修改或等待当前操作结束，再进行客户审核。</p>
      <el-button v-if="canSubmit && ['none','rejected'].includes(task.review_status || 'none')" :disabled="disabled || busy || !task.article" @click="review('submit')">提交客户审核</el-button>
      <div v-if="task.review_status === 'pending' && canDecide">
        <el-checkbox v-model="confirmed" :disabled="disabled || busy">我已审核当前已保存的母稿及渠道稿，确认可以发布</el-checkbox>
        <el-button :disabled="disabled || busy || !confirmed" @click="review('approved')">客户确认通过</el-button>
        <el-button :disabled="disabled || busy" @click="review('rejected')">需要修改</el-button>
      </div>
      <p v-else-if="task.review_status === 'pending'">当前账号只能查看审核状态。</p>
      <p><b>4. 指标基线：</b>{{ error ? '状态未知，请刷新' : !selected ? '尚未关联指标验收任务' : detail?.baseline_valid ? '已有有效基线' : detail?.baseline_blocker || '尚无有效基线' }}</p>
      <el-button v-if="!linked.length" :disabled="busy || disabled" @click="createOpen = true">建立指标验收任务</el-button>
      <el-select v-if="linked.length" v-model="selectedId" aria-label="关联验收任务" @change="load">
        <el-option v-for="row in linked" :key="row.id" :value="row.id" :label="`#${row.id} ${row.title}`" />
      </el-select>
      <p v-if="linked.length === 200">当前显示前 200 个关联任务，其余请到指标验收列表查看。</p>
      <p><b>5. 上线核验：</b>{{ currentProof ? '当前母稿已有抓取核验记录，验收时仍会重新检查' : '尚未核实当前版本上线；回填链接不等于核验通过' }} <el-button link @click="distribution">发布 / 回填 / 恢复</el-button></p>
      <section class="h3h4-summary" aria-label="H3 H4 只读验收摘要">
        <p><b>H3/H4 只读验收：</b>以下结论只读取已保存记录，不会自动发布、抓取或重试。</p>
        <p v-if="acceptanceError" role="alert">{{ acceptanceError }}；不影响上方已有发布检查，请刷新后重试。</p>
        <article v-for="stage in acceptanceStages" :key="stage.key">
          <strong>{{ stage.title }}：{{ stage.statusLabel }}</strong>
          <ul v-if="stage.blockers.length">
            <li v-for="item in stage.blockers" :key="`${stage.key}-${item.stage}-${item.key}`">
              {{ item.label }}
              <small v-if="item.requirement">对应{{ item.stage.toUpperCase() }}要求：{{ item.requirement }}</small>
              <small v-if="item.evidenceNote">检查依据：{{ item.evidenceNote }}</small>
            </li>
          </ul>
          <ul v-else-if="stage.humanRequirements.length">
            <li v-for="item in stage.humanRequirements" :key="`${stage.key}-${item.key}`">
              待人工确认：{{ item.description }}
            </li>
          </ul>
          <p v-else-if="stage.systemReady">系统前置检查已满足。</p>
          <div v-if="stage.observations.length" class="monitor-evidence">
            <p><b>已保存的发布后检查依据</b></p>
            <div v-for="(item, index) in stage.observations" :key="`${stage.key}-${item.publicationLabel}-${index}`">
              <strong>{{ item.publicationLabel }} · {{ item.channelLabel }}：{{ item.stateLabel }}</strong>
              <small :class="item.evidenceValid ? 'evidence-valid' : 'evidence-invalid'">{{ item.evidenceStatusLabel }}</small>
              <small>
                最近检查：{{ item.checkedAt || '时间未记录' }}；下次计划：{{ item.nextCheckAt || '尚未安排' }}；连续异常：{{ item.failures }} 次
              </small>
              <small v-if="item.evidenceReasons.length">依据不足：{{ item.evidenceReasons.join('；') }}</small>
              <small v-if="item.checkIncomplete">最近一次后台检查未完成；当前结论仍来自此前已保存记录。</small>
              <small>{{ item.recoveryGuide }}</small>
            </div>
          </div>
        </article>
      </section>
      <p><b>6. 复测与验收：</b>{{ next ? `${next.stage}：${next.next}` : '建立验收任务后查看同题同模型复测条件' }} <el-button v-if="selected" link @click="openEvidence">处理指标验收</el-button></p>
      <p v-if="detail?.outcome_review_error" role="alert">{{ detail.outcome_review_error }}；下方显示的是此前评估。</p>
      <p v-if="detail?.outcome_review"><b>7. 效果复盘：</b>{{ {waiting:'待观察',needs_review:'完整周指标未达目标，已生成复盘工单',target_met:'观察指标已达到目标，仍需完成原任务验收'}[detail.outcome_review.state] }} {{ detail.outcome_review.reason || '' }} <el-button link @click="router.push('/geo/tickets')">查看复盘工单</el-button></p>
    </div>
    </div>
    <GeoCreateEvidenceTask v-if="createOpen" :tenant-id="tenantId" :content="task" @close="createOpen = false; load()" />
  </section>
</template>
<style scoped>
.launch-checklist { flex: none; max-height: 45vh; overflow: auto; margin: 12px 20px; padding: 16px; border: 1px solid #dbe4ee; border-radius: 10px; background: #fff; }
header { display:flex; align-items:center; justify-content:space-between; }
h3 { margin:0; font-size:16px; }
p { font-size:13px; line-height:1.7; color:#475569; }
:deep(.el-checkbox) { white-space:normal; height:auto; margin:8px 12px 8px 0; }
:deep(.el-checkbox__label) { white-space:normal; }
.h3h4-summary { margin: 12px 0; padding: 12px; border: 1px solid #dbe4ee; border-radius: 8px; background: #f8fafc; }
.h3h4-summary article + article { margin-top: 10px; padding-top: 10px; border-top: 1px solid #e2e8f0; }
.h3h4-summary ul { margin: 6px 0 0; padding-left: 20px; color: #475569; font-size: 13px; line-height: 1.65; }
.h3h4-summary small { display: block; color: #64748b; }
.monitor-evidence { margin-top: 8px; padding: 8px 10px; border-left: 3px solid #94a3b8; background: #fff; }
.monitor-evidence > div + div { margin-top: 8px; }
.evidence-valid { color: #16794b !important; }
.evidence-invalid { color: #b45309 !important; }
</style>
