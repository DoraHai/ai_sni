<script setup>
import { computed, reactive, ref, watch, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { evidenceTaskLink, evidenceLinkTarget } from '../utils/geoEvidenceLinks'
import GeoExecutionOverview from './GeoExecutionOverview.vue'
import * as api from '../api/geoIntegration'
import { createEvidenceController } from '../utils/geoEvidenceController'
const props = defineProps({ tenantId: [Number, String] })
const router = useRouter()
const route = useRoute()
const lookupId = ref('')
const statusFilter = ref('')
const linkTarget = computed(() => evidenceLinkTarget(route.query, props.tenantId))
const state = reactive({ items: [], selected: null, detail: null, loading: false, busy: false, error: '', message: '', more: false })
const publicationId = ref('')
const cancelPending = ref(false)
watch(() => [props.tenantId, state.selected?.id, state.selected?.status], () => { cancelPending.value = false })
async function cancelTask() {
  if (!cancelPending.value || state.loading || state.busy) return
  const tenant = props.tenantId, id = state.selected?.id
  await controller.act('cancel')
  if (tenant === props.tenantId && id === state.selected?.id) cancelPending.value = false
}
const controller = createEvidenceController(state, api, () => props.tenantId, () => statusFilter.value)
function reload() { publicationId.value = ''; return controller.load(false, linkTarget.value.id) }
watch(() => [props.tenantId, route.query.evidence_task_id, route.query.evidence_tenant_id], () => { lookupId.value = ''; reload() }, { immediate: true })
watch(statusFilter, reload)
function lookup() {
  if (!props.tenantId || state.loading || state.busy) return
  if (!/^[1-9][0-9]*$/.test(lookupId.value) || !Number.isSafeInteger(Number(lookupId.value))) { state.error = '请输入有效的验收任务编号'; return }
  if (linkTarget.value.id === Number(lookupId.value)) { reload(); return }
  router.push(evidenceTaskLink(props.tenantId, lookupId.value))
}
onBeforeUnmount(controller.invalidate)
const terminal = computed(() => ['done', 'cancelled'].includes(state.selected?.status))
const contentId = computed(() => state.selected?.params?.content_task_id)
const labels = { open: '待处理', in_progress: '进行中', done: '已完成', cancelled: '已取消' }
const metricNames = { 'geo.visibility.ai_mention_count_7d': 'AI提及次数', 'geo.visibility.ai_mention_rate_7d': 'AI提及率', 'geo.visibility.ai_visibility_score': 'AI可见度分数' }
const units = { count: '次', percent: '%', score: '分' }
const runLabels = { pending: '排队中', running: '执行中', completed: '采样结束', failed: '执行失败' }
const shown = (value) => value == null ? '尚无有效数据' : value
function select(row) {
  if (state.loading || state.busy) return
  publicationId.value = ''
  if (linkTarget.value.id === row.id) { reload(); return }
  router.push(evidenceTaskLink(props.tenantId, row.id))
}
</script>

<template>
  <section class="gd-card mb evidence-tasks">
    <div class="gd-hd"><h3>指标验收任务</h3><button class="gd-btn" :disabled="state.loading || state.busy" @click="reload()">刷新任务</button></div>
    <div class="gd-bd">
      <p class="gd-sub">查看基线、真实发布和周复测进度；完成须由服务端核验实际指标变化。</p>
      <el-alert v-if="linkTarget.error" :title="linkTarget.error" type="warning" :closable="false" />
      <label>任务状态 <select v-model="statusFilter" :disabled="state.busy">
        <option value="">全部状态</option><option value="open">待处理</option><option value="in_progress">进行中</option><option value="done">已完成</option><option value="cancelled">已取消</option>
      </select></label>
      <p v-if="statusFilter && state.selected && state.selected.status !== statusFilter">当前打开的任务不属于所选状态，保留详情供查阅。</p>
      <form class="evidence-lookup" @submit.prevent="lookup">
        <label>验收任务编号 <input v-model="lookupId" inputmode="numeric" placeholder="例如 12" /></label>
        <button class="gd-btn" :disabled="!tenantId || state.loading || state.busy" type="submit">打开任务</button>
      </form>
      <el-alert v-if="state.error" :title="state.error" type="error" :closable="false" />
      <el-alert v-if="state.message" :title="state.message" type="success" :closable="false" />
      <p v-if="state.loading">正在读取任务…</p>
      <p v-else-if="!state.items.length && !state.selected && !state.error">当前筛选下暂无指标验收任务。</p>
      <GeoExecutionOverview :tenant-id="tenantId" :tasks="state.items" :disabled="state.loading || state.busy" @open="select" />
      <div class="evidence-list">
        <button v-for="row in state.items" :key="row.id" class="gd-btn" :disabled="state.loading || state.busy" :aria-pressed="state.selected?.id === row.id" @click="select(row)">#{{ row.id }} {{ row.title }} · {{ labels[row.status] || row.status }}</button>
      </div>
      <button v-if="state.more" class="gd-btn" :disabled="state.loading || state.busy" @click="controller.load(true)">加载更多</button>
      <div v-if="state.selected" class="evidence-detail">
        <h4>{{ state.selected.title }}</h4>
        <p>负责人角色：{{ state.selected.assignee_role }} · 状态：{{ labels[state.selected.status] }}</p>
        <button v-if="state.selected.status === 'open'" class="gd-btn" :disabled="state.loading || state.busy" @click="controller.act('start')">开始处理</button>
        <button v-if="!terminal && !cancelPending" class="gd-btn" :disabled="state.loading || state.busy" @click="cancelPending = true">取消任务…</button>
        <div v-if="cancelPending && !terminal" role="group" aria-label="确认取消任务">
          <p>取消后不能重新开启此任务，需要另建任务；已启动的采样会继续执行，取消不会撤销已经发生的调用。</p>
          <button class="gd-btn" :disabled="state.loading || state.busy" @click="cancelTask">确认取消当前任务</button>
          <button class="gd-btn" :disabled="state.busy" @click="cancelPending = false">保留任务</button>
        </div>
        <button v-if="contentId" class="gd-btn" @click="router.push(`/geo/tasks/${contentId}`)">打开关联内容</button>
        <p v-if="state.busy">正在核验，请稍候…</p>
        <template v-if="state.detail">
          <h4>1. 完整周基线</h4>
          <p>{{ metricNames[state.detail.baseline?.metric_key] || "目标指标" }}：{{ shown(state.detail.baseline?.value) }} {{ state.detail.baseline?.value == null ? "" : (units[state.detail.baseline?.unit] || "") }} · 截至 {{ state.detail.baseline?.as_of || '未知' }}</p>
          <p v-if="state.detail.baseline_blocker">{{ state.detail.baseline_blocker }}</p>
          <button class="gd-btn" :disabled="terminal || state.loading || state.busy || state.detail.baseline_valid" @click="controller.act('baseline')">采集已结束周基线</button>
          <template v-if="contentId">
            <h4>2. 真实发布</h4>
            <p v-if="state.detail.publication_evidence">当前稿件已核实上线，首次核验：{{ state.detail.publication_evidence.first_verified_at }}</p>
            <p v-else>尚无发布核验证据。可自动发布渠道：{{ state.detail.publishing?.ready_count || 0 }}。稿件就绪不代表已经上线。</p>
            <button class="gd-btn" @click="router.push('/geo/publishing')">配置发布渠道</button>
            <button class="gd-btn" @click="router.push(`/geo/tasks/${contentId}/distribution`)">查看发布记录</button>
            <p v-if="!state.detail.publication_candidates?.length">暂无当前版本的已发布记录，请先完成发布并登记结果。</p>
            <label>当前稿件发布记录 <select v-model="publicationId" :disabled="terminal || state.loading || state.busy"><option value="">请选择已发布记录</option><option v-for="pub in state.detail.publication_candidates || []" :key="pub.id" :value="pub.id">{{ pub.channel }} · {{ pub.url }}</option></select></label>
            <button class="gd-btn" :disabled="terminal || state.loading || state.busy || !publicationId" @click="controller.act('publication', Number(publicationId))">重新抓取核验发布</button>
          </template>
          <h4>3. 同题同模型周复测</h4>
          <p v-if="state.detail.retest_plan">计划采样 {{ state.detail.retest_plan.total_samples }} 次，保持基线题目、模型和次数一致；启动后会调用已配置 AI 引擎。</p>
          <p v-if="state.detail.retest_blocker">{{ state.detail.retest_blocker }}</p>
          <p v-if="state.detail.latest_retest">最近复测 #{{ state.detail.latest_retest.id }}：{{ runLabels[state.detail.latest_retest.status] || state.detail.latest_retest.status }}；合格 {{ state.detail.latest_retest.result?.qualified_samples ?? '待执行' }} / {{ state.detail.latest_retest.result?.expected_samples ?? '待执行' }}。{{ state.detail.latest_retest.error }}</p>
          <button class="gd-btn" :disabled="terminal || state.loading || state.busy || !state.detail.can_retest" @click="controller.act('retest')">启动精确复测</button>
          <button class="gd-btn" :disabled="state.loading || state.busy" @click="controller.select(state.selected)">刷新执行条件</button>
          <h4>4. 实际指标验收</h4>
          <p v-if="state.detail.completion_evidence">已核验变化：{{ state.detail.completion_evidence.before?.value }} → {{ state.detail.completion_evidence.after?.value }}，变化量 {{ state.detail.completion_evidence.delta }}。</p>
          <p v-else-if="state.selected.status === 'cancelled'">任务已取消，不再进行完成验收；已有记录保留供查阅。</p>
          <p v-else>尚未完成。需等待符合条件的完整后测周，并达到任务目标；未通过会显示具体原因。</p>
          <button class="gd-btn" :disabled="terminal || state.loading || state.busy || !state.detail.baseline_valid" @click="controller.act('complete')">核验指标并完成</button>
        </template>
      </div>
    </div>
  </section>
</template>
<style scoped>
.evidence-lookup { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 12px 0; }
.evidence-lookup input { width: 120px; padding: 6px; }
.evidence-list { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.evidence-list button { white-space: normal; text-align: left; }
.evidence-detail { border-top: 1px solid #e5e7eb; margin-top: 16px; padding-top: 12px; overflow-wrap: anywhere; }
.evidence-detail h4 { margin: 18px 0 8px; }
.evidence-detail .gd-btn, .evidence-detail label { margin: 4px 8px 4px 0; }
.evidence-detail select { max-width: 100%; width: 300px; }
</style>
