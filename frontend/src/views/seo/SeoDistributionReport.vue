<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { fetchReportSettings, saveReportSettings, createReportPairing, revokeReportDevice, createReportTask, saveReportPublishAccount } from '../../api/seoDistributionReport.js'

const props = defineProps({ tenantId: Number, siteId: Number, identity: String, canEdit: Boolean, connections: Array, publications: Array, contents: Array })
const emit = defineEmits(['paired'])
const state = ref(null), busy = ref(false), error = ref(''), pairingCode = ref('')
const form = reactive({ label: '', account: '', device: '', publication: '' })
const accountEditor = ref(null)
const notice = ref('')
const scope = computed(() => `${props.tenantId}:${props.siteId}:${props.identity}`)
const canOperate = computed(() => props.canEdit && state.value?.can_operate === true && !busy.value)
const accounts = computed(() => (props.connections || []).filter(c => c.platform_code === 'wechat_browser' && c.enabled))
const publications = computed(() => (props.publications || []).filter(p => p.platform_code === 'wechat_browser' && ['manual_required','preparing','failed'].includes(p.status)))
let generation = 0

function resetScope() {
  generation += 1
  state.value = null; pairingCode.value = ''; error.value = ''; busy.value = false
  accountEditor.value = null
  notice.value = ''
  Object.assign(form, { label: '', account: '', device: '', publication: '' })
}

async function run(action, apply, failureText) {
  if (busy.value || !props.tenantId || !props.siteId) return
  const epoch = generation, selected = scope.value
  const params = { tenant_id: props.tenantId, site_id: props.siteId }
  busy.value = true; error.value = ''
  try {
    const result = await action(params, () => epoch === generation && selected === scope.value)
    if (epoch === generation && selected === scope.value) apply(result)
  } catch {
    // Keep request payloads (including a one-time code) out of error text.
    if (epoch === generation && selected === scope.value) error.value = failureText?.() || '操作未获受理，请刷新后核对客户、网站、当前权限与稿件审核状态。'
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
  if (!canOperate.value) return
  let current = state.value
  const label = form.label.trim() || defaultDeviceLabel()
  const accountId = form.account ? `seo-connection-${form.account}` : null
  let stage = 'enable'
  pairingCode.value = ''
  notice.value = ''
  await run(async (params, isCurrent) => {
    if (!current.enabled || !current.scope_enabled) {
      const enabled = await saveReportSettings(params, { enabled: true, scope_enabled: true,
        expected_revision: current.revision, expected_scope_revision: current.scope_revision })
      if (!isCurrent()) return
      current = { ...enabled, can_operate: current.can_operate }
      state.value = current
      notice.value = '已同时开启回传'
    }
    if (!isCurrent()) return
    stage = 'pair'
    const result = await createReportPairing(params, { label, platform: 'wechat-article',
      account_id: accountId, expected_revision: current.revision })
    if (!isCurrent()) return
    pairingCode.value = result.pairing_code
    emit('paired')
    // Keep the one-time code even if the subsequent status refresh fails.
    stage = 'refresh'
    return await fetchReportSettings(params)
  }, result => { state.value = result }, () => ({
    enable: '回传未能开启，尚未生成配对码。请刷新后核对权限再试。',
    pair: '配对码未能生成，请刷新状态后再试。已开启的回传会保留。',
    refresh: '配对码已生成，状态刷新失败，请保留本次配对码并稍后刷新。',
  }[stage]))
}

function defaultDeviceLabel() {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Shanghai',
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
    .formatToParts(new Date()).map(part => [part.type, part.value]))
  return `多号通电脑-${parts.month}/${parts.day} ${parts.hour}:${parts.minute}`
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

const publishAccountName = task => task.advisorAccount?.name || task.reportedAccount?.name || '未填写'

function editPublishAccount(task) {
  if (!canOperate.value) return
  accountEditor.value = { taskId: task.taskId, name: task.advisorAccount?.name || task.reportedAccount?.name || '', revision: state.value.revision }
}

async function savePublishAccount(clear = false) {
  if (!canOperate.value || !accountEditor.value) return
  const editor = accountEditor.value, current = state.value
  const name = clear ? null : editor.name
  await run(params => saveReportPublishAccount(params, editor.taskId, {
    name, expected_revision: editor.revision,
  }), result => { state.value = { ...result, can_operate: current.can_operate }; accountEditor.value = null })
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
      <el-button v-if="canEdit && state.can_operate && state.enabled && state.scope_enabled" :disabled="!canOperate" @click="toggle">关闭回传</el-button>
      <p v-if="notice" role="status">{{ notice }}</p>
      <p v-if="!state.can_operate">当前权限只允许查看，请使用已有授权的顾问或超管账号处理。</p>
      <div class="report-form">
        <el-input v-model="form.label" placeholder="设备备注（选填，留空自动填写）" aria-label="设备备注（选填）" maxlength="80" :disabled="!canOperate" />
        <el-select v-model="form.account" placeholder="不指定（由多号通发布时上报）" :disabled="!canOperate"><el-option label="不指定（由多号通发布时上报）" value="" /><el-option v-for="account in accounts" :key="account.id" :label="account.name" :value="account.id" /></el-select>
        <el-button v-if="canEdit && state.can_operate" type="primary" :disabled="!canOperate" @click="pair">生成配对码</el-button>
      </div>
      <p>直接生成配对码会同时开启当前客户与网站回传。公众号可不选，设备备注留空会按北京时间自动填写。本网站会自动准备发布连接；回传记录可由顾问补填实际发布公众号。每个客户最多保留 20 个在用配对和 20 个未用配对码；同一台电脑可分别配对多个客户。</p>
      <div v-if="pairingCode" role="status"><p>配对码仅显示本次，10 分钟内在多号通选择 SEO 模块后输入：</p><code>{{ pairingCode }}</code><el-button text @click="pairingCode = ''">隐藏</el-button></div>
      <ul><li v-for="device in state.devices" :key="device.id">{{ device.label }} · {{ device.active ? '已绑定' : '已停用' }} · 账号身份待核对 <el-button text :disabled="!canOperate || !device.active" @click="revoke(device)">吊销</el-button></li></ul>
      <div class="report-form">
        <el-select v-model="form.device" placeholder="选择执行电脑" :disabled="!canOperate"><el-option v-for="device in state.devices.filter(d => d.active)" :key="device.id" :label="device.label" :value="device.id" /></el-select>
        <el-select v-model="form.publication" placeholder="选择已审核的发布任务" :disabled="!canOperate"><el-option v-for="publication in publications" :key="publication.id" :label="publication.content_title || `发布任务 ${publication.id}`" :value="publication.id" /></el-select>
        <el-button :disabled="!canOperate || !state.enabled || !state.scope_enabled || !form.device || !form.publication" @click="dispatch">派给执行电脑</el-button>
      </div>
      <p>请先按原流程准备并审核发布任务。有图片的稿件需待素材传输接通后再派发。</p>
      <table v-if="state.tasks.length"><thead><tr><th>发布任务</th><th>回执送达</th><th>人工结果</th><th>页面核验</th></tr></thead><tbody><tr v-for="task in state.tasks" :key="task.taskId"><td>{{ task.nativePublicationId }}</td><td>{{ task.delivery === 'received' ? '已收到回报' : '待回报' }}</td><td>{{ outcomeText(task.reportedOutcome) }}<span v-if="task.last_code">（{{ codeText(task.last_code) }}）</span><div>发布公众号：{{ publishAccountName(task) }}<span v-if="task.advisorAccount?.name">（顾问标注）</span><span v-else-if="task.reportedAccount?.name">（多号通上报）</span> <el-button v-if="canOperate" text size="small" @click="editPublishAccount(task)">编辑</el-button></div></td><td>{{ verificationText(task.verification.state) }}<small v-if="task.verification.reason"> · {{ reasonText(task.verification.reason) }}</small></td></tr></tbody></table>
      <el-dialog :model-value="!!accountEditor" title="标注发布公众号" width="420px" @close="accountEditor = null">
        <template v-if="accountEditor">
          <p>填写本次实际发布的公众号名称（1–60 个字）。清除标注后显示多号通上报值。</p>
          <el-input v-model="accountEditor.name" aria-label="发布公众号名称" :disabled="!canOperate" />
          <p v-if="error" role="alert">{{ error }}</p>
        </template>
        <template #footer><el-button :disabled="busy" @click="accountEditor = null">取消</el-button><el-button :disabled="!canOperate" @click="savePublishAccount(true)">清除标注</el-button><el-button type="primary" :disabled="!canOperate" @click="savePublishAccount()">保存</el-button></template>
      </el-dialog>
    </template>
  </section>
</template>

<style scoped>
.report-card{padding:20px;border:1px solid #dce5eb;border-radius:12px;margin:20px 0;background:#fff}.report-heading{display:flex;justify-content:space-between;gap:20px}.report-card h2{margin:0;font-size:18px}.report-card p{font-size:13px;color:#566779}.report-form{display:flex;gap:12px;margin:14px 0;flex-wrap:wrap}.report-form :deep(.el-input),.report-form :deep(.el-select){max-width:270px}table{width:100%;text-align:left;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #eee}code{font-size:18px;user-select:all}
</style>
