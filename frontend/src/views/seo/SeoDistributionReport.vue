<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { fetchReportSettings, saveReportSettings, createReportPairing, revokeReportDevice, createReportTask } from '../../api/seoDistributionReport.js'

const props = defineProps({ tenantId: Number, siteId: Number, identity: String, canEdit: Boolean, connections: Array, publications: Array, contents: Array })
const state = ref(null), busy = ref(false), error = ref(''), pairingCode = ref('')
const form = reactive({ label: '', account: '', device: '', publication: '' })
const scope = computed(() => `${props.tenantId}:${props.siteId}:${props.identity}`)
const canOperate = computed(() => props.canEdit && state.value?.can_operate === true && !busy.value)
const accounts = computed(() => (props.connections || []).filter(c => c.platform_code === 'wechat_browser' && c.enabled))
const publications = computed(() => (props.publications || []).filter(p => p.platform_code === 'wechat_browser' && ['manual_required','preparing','failed'].includes(p.status)))
let generation = 0

function resetScope() {
  generation += 1
  state.value = null; pairingCode.value = ''; error.value = ''; busy.value = false
  Object.assign(form, { label: '', account: '', device: '', publication: '' })
}

async function run(action, apply) {
  if (busy.value || !props.tenantId || !props.siteId) return
  const epoch = generation, selected = scope.value
  const params = { tenant_id: props.tenantId, site_id: props.siteId }
  busy.value = true; error.value = ''
  try {
    const result = await action(params)
    if (epoch === generation && selected === scope.value) apply(result)
  } catch {
    // Keep request payloads (including a one-time code) out of error text.
    if (epoch === generation && selected === scope.value) error.value = '操作未获受理，请刷新后核对客户、网站、当前权限与稿件审核状态。'
  } finally {
    if (epoch === generation && selected === scope.value) busy.value = false
  }
}

async function refresh() {
  await run(params => fetchReportSettings(params), result => { state.value = result })
}

async function toggle() {
  if (!canOperate.value) return
  const current = state.value
  await run(params => saveReportSettings(params, {
    enabled: !(current.enabled && current.scope_enabled), scope_enabled: !(current.enabled && current.scope_enabled),
    expected_revision: current.revision, expected_scope_revision: current.scope_revision,
  }), result => { state.value = { ...result, can_operate: current.can_operate } })
}

async function pair() {
  if (!canOperate.value || !form.account || !form.label.trim()) return
  const body = { label: form.label.trim(), platform: 'wechat-article', account_id: `seo-connection-${form.account}`, expected_revision: state.value.revision }
  pairingCode.value = ''
  await run(params => createReportPairing(params, body), result => { pairingCode.value = result.pairing_code })
  await refresh()
}

async function revoke(device) {
  if (!canOperate.value) return
  const current = state.value
  await run(params => revokeReportDevice(params, device.id, { expected_revision: current.revision }), result => {
    state.value = { ...result, can_operate: current.can_operate }
  })
}

async function dispatch() {
  if (!canOperate.value || !state.value.enabled || !state.value.scope_enabled || !form.device || !form.publication) return
  const publication = publications.value.find(p => p.id === form.publication)
  const content = (props.contents || []).find(c => c.id === publication?.content_id)
  if (!publication || !content?.payload_hash || content.version_count !== publication.source_version) {
    error.value = '稿件版本已变化，请刷新并重新核对。'; return
  }
  const body = { publication_id: publication.id, source_version: publication.source_version,
    payload_hash: content.payload_hash, device_id: form.device, request_id: crypto.randomUUID() }
  await run(params => createReportTask(params, body), () => { form.publication = '' })
  await refresh()
}

const outcomeText = value => ({queued:'待执行', 'awaiting-human':'待人工处理', unknown:'结果未知', failed:'失败', 'human-reported-published':'人工报告已发布'}[value] || value)
const verificationText = value => ({pending:'待核验', verified:'已通过', failed:'未通过', unavailable:'暂无法核验', version_changed:'稿件已变化'}[value] || '待核验')
const codeText = value => ({HUMAN_PUBLISHED:'已人工确认发布', HUMAN_REQUIRED:'等待人工确认', HUMAN_FAILED:'人工确认失败', HUMAN_UNKNOWN:'人工确认结果未知', LOGIN_REQUIRED:'需登录', CAPTCHA:'需验证码', RISK_CONTROL:'平台风控', PAGE_UNVERIFIED:'页面待核对', OFFLINE:'执行电脑离线', PLATFORM_REVIEW_PENDING:'平台审核中', PLATFORM_PUBLISH_FAILED:'平台发布失败', UPLOAD_RESULT_UNKNOWN:'上传结果未知', SUBMISSION_RESULT_UNKNOWN:'提交结果未知', ACCEPTED:'执行电脑已接单', DISPATCHED:'已交接执行', PREFLIGHT_OK:'预检完成'}[value] || '请核对执行结果')
const reasonText = value => ({not_reported:'尚无成功链接', not_checked:'等待检查', text_not_found:'未匹配审核正文', capture_unavailable:'截图证据暂不可用', source_or_review_changed:'稿件版本或审核已变化', publication_url_changed:'登记链接已变化', full_body_and_capture_observed:'正文与截图证据均满足'}[value] || '请查看页面证据')
watch(scope, () => { resetScope(); refresh() }, { immediate: true, flush: 'sync' })
</script>

<template>
  <section class="report-card" aria-label="多号通结果回传">
    <div class="report-heading"><div><h2>多号通结果回传</h2><p>首期支持公众号。每次成功都需在多号通核对稿件并人工确认公开链接。</p></div><el-button :disabled="busy" @click="refresh">刷新回传状态</el-button></div>
    <p v-if="!tenantId || !siteId">请先选择客户和网站。</p>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <template v-if="state">
      <p>当前客户：{{ state.enabled ? '已开启' : '关闭' }}；当前网站：{{ state.scope_enabled ? '已开启' : '关闭' }}。只有两项均开启才接收结果。</p>
      <el-button :disabled="!canOperate" @click="toggle">{{ state.enabled && state.scope_enabled ? '关闭当前客户与网站回传' : '开启当前客户与网站回传' }}</el-button>
      <p v-if="!state.can_operate">当前权限只允许查看，请使用已有授权的顾问或超管账号处理。</p>
      <div class="report-form">
        <el-input v-model="form.label" placeholder="设备备注（必填，如团队电脑与用途）" aria-label="设备备注（必填）" maxlength="80" :disabled="!canOperate" />
        <el-select v-model="form.account" placeholder="选择已绑定本站的公众号" :disabled="!canOperate"><el-option v-for="account in accounts" :key="account.id" :label="account.name" :value="account.id" /></el-select>
        <el-button :disabled="!canOperate || !form.account || !form.label.trim()" @click="pair">生成配对码</el-button>
      </div>
      <p>请填写团队代发电脑的备注，方便区分配对。每个客户最多保留 20 个在用配对和 20 个未用配对码；同一台电脑可分别配对多个客户。</p>
      <div v-if="pairingCode" role="status"><p>配对码仅显示本次，10 分钟内在多号通选择 SEO 模块后输入：</p><code>{{ pairingCode }}</code><el-button text @click="pairingCode = ''">隐藏</el-button></div>
      <ul><li v-for="device in state.devices" :key="device.id">{{ device.label }} · {{ device.active ? '已绑定' : '已停用' }} · 账号身份待核对 <el-button text :disabled="!canOperate || !device.active" @click="revoke(device)">吊销</el-button></li></ul>
      <div class="report-form">
        <el-select v-model="form.device" placeholder="选择执行电脑" :disabled="!canOperate"><el-option v-for="device in state.devices.filter(d => d.active)" :key="device.id" :label="device.label" :value="device.id" /></el-select>
        <el-select v-model="form.publication" placeholder="选择已审核的发布任务" :disabled="!canOperate"><el-option v-for="publication in publications" :key="publication.id" :label="publication.content_title || `发布任务 ${publication.id}`" :value="publication.id" /></el-select>
        <el-button :disabled="!canOperate || !state.enabled || !state.scope_enabled || !form.device || !form.publication" @click="dispatch">派给执行电脑</el-button>
      </div>
      <p>请先按原流程准备并审核发布任务。有图片的稿件需待素材传输接通后再派发。</p>
      <table v-if="state.tasks.length"><thead><tr><th>发布任务</th><th>回执送达</th><th>人工结果</th><th>页面核验</th></tr></thead><tbody><tr v-for="task in state.tasks" :key="task.taskId"><td>{{ task.nativePublicationId }}</td><td>{{ task.delivery === 'received' ? '已收到回报' : '待回报' }}</td><td>{{ outcomeText(task.reportedOutcome) }}<span v-if="task.last_code">（{{ codeText(task.last_code) }}）</span></td><td>{{ verificationText(task.verification.state) }}<small v-if="task.verification.reason"> · {{ reasonText(task.verification.reason) }}</small></td></tr></tbody></table>
    </template>
  </section>
</template>

<style scoped>
.report-card{padding:20px;border:1px solid #dce5eb;border-radius:12px;margin:20px 0;background:#fff}.report-heading{display:flex;justify-content:space-between;gap:20px}.report-card h2{margin:0;font-size:18px}.report-card p{font-size:13px;color:#566779}.report-form{display:flex;gap:12px;margin:14px 0;flex-wrap:wrap}.report-form :deep(.el-input),.report-form :deep(.el-select){max-width:270px}table{width:100%;text-align:left;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #eee}code{font-size:18px;user-select:all}
</style>
