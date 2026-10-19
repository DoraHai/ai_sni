<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { session } from '../store/session'
import { fetchGeoProjects } from '../api/geoProjects'
import { reportSettings, setReportSettings, pairReportDevice, revokeReportDevice, dispatchReportTask, fetchReportTask } from '../api/geoDistributionReport'
import { reportContext, reportDigest, reportToggle, reportOutcomes, reportCodes } from '../utils/geoDistributionReport'

const props = defineProps({ tenantId: Number, projectId: Number, task: Object, accounts: Array, mode: { type: String, default: 'settings' } })
const emit = defineEmits(['changed'])
const projects = ref([]), selected = ref(null), settings = ref(null), pairing = ref(null), result = ref(null)
const busy = ref(false), error = ref(''), label = ref(''), account = ref(null), device = ref(null)
const context = reportContext()
const project = computed(() => props.projectId || selected.value)
const canManage = computed(() => settings.value?.can_manage === true)
const wechat = computed(() => props.task?.variants?.find(v => v.channel === 'wechat'))
const projected = computed(() => wechat.value?.adapt_meta?.distribution_report_v1)
const activeDevices = computed(() => (settings.value?.devices || []).filter(d => !d.revoked && d.expires_at > Date.now()))
const status = computed(() => result.value || projected.value)
const verificationLabel = computed(() => ({ verified: '页面核验通过', failed: '页面核验未通过', unavailable: '页面暂无法核验', version_changed: '稿件版本已变化', pending: '页面待核验' }[result.value?.verification?.state] || '页面待核验'))

function reset() {
  context.reset(); settings.value = null; pairing.value = null; result.value = null
  busy.value = false; error.value = ''; label.value = ''; account.value = null; device.value = null
}
async function loadSettings() {
  reset()
  if (!props.tenantId || !project.value) return
  const epoch = context.capture()
  try {
    const data = await reportSettings(props.tenantId, project.value)
    if (context.current(epoch)) settings.value = data
  } catch { if (context.current(epoch)) error.value = '回传设置暂不可用，请刷新或由管理员核对权限。' }
}
watch([() => props.tenantId, () => session.user?.id, () => session.token], async () => {
  reset(); projects.value = []; selected.value = null
  if (props.projectId) { await loadSettings(); return }
  if (!props.tenantId) return
  const epoch = context.capture()
  try {
    const data = await fetchGeoProjects(props.tenantId)
    if (!context.current(epoch)) return
    projects.value = (data.projects || []).filter(p => p.status === 'active')
    const matching = projects.value.filter(p => p.business_scope?.business_ids?.includes(props.task?.business_id))
    if (matching.length === 1) selected.value = matching[0].id
  } catch { if (context.current(epoch)) error.value = '项目加载失败，请刷新。' }
}, { immediate: true, flush: 'sync' })
watch(project, loadSettings, { immediate: true, flush: 'sync' })
watch(() => props.task, () => { reset(); loadSettings() }, { flush: 'sync' })
onBeforeUnmount(reset)

async function action(operation) {
  if (busy.value || !canManage.value || !props.tenantId || !project.value) return
  const epoch = context.capture(), tenant = props.tenantId, scope = project.value
  busy.value = true; error.value = ''
  try { await operation({ tenant, scope, current: () => context.current(epoch) }) }
  catch { if (context.current(epoch)) error.value = '操作未完成，请刷新并核对权限、设备和当前稿件。' }
  finally { if (context.current(epoch)) busy.value = false }
}
function toggle() {
  action(async ({ tenant, scope, current }) => {
    const data = await setReportSettings(tenant, scope, reportToggle(settings.value))
    if (current()) settings.value = { ...data, can_manage: true }
  })
}
function pair() {
  if (!label.value.trim()) return
  action(async ({ tenant, scope, current }) => {
    const data = await pairReportDevice(tenant, scope, { label: label.value.trim(), platform: 'wechat-article',
      account_id: account.value == null ? null : String(account.value), expected_revision: settings.value.revision })
    if (!current()) return
    pairing.value = data
    const updated = await reportSettings(tenant, scope)
    if (current()) settings.value = updated
  })
}
function revoke(id) {
  action(async ({ tenant, scope, current }) => {
    const data = await revokeReportDevice(tenant, scope, id, settings.value.revision)
    if (current()) settings.value = { ...data, can_manage: true }
  })
}
function dispatch() {
  if (!device.value || !wechat.value || !props.task?.article?.id) return
  action(async ({ tenant, scope, current }) => {
    const variant = wechat.value, articleId = props.task.article.id, taskId = props.task.id
    const hash = await reportDigest(articleId, variant)
    if (!current()) return
    const data = await dispatchReportTask(tenant, scope, { content_task_id: taskId, variant_id: variant.id,
      article_version_id: articleId, payload_hash: hash, device_id: device.value, request_id: crypto.randomUUID() })
    if (current()) { result.value = data; emit('changed') }
  })
}
async function refreshResult() {
  const id = status.value?.taskId
  if (busy.value || !id || !project.value || !props.tenantId) return
  const epoch = context.capture()
  busy.value = true
  try {
    const data = await fetchReportTask(props.tenantId, project.value, id)
    if (context.current(epoch)) result.value = data
  } catch { if (context.current(epoch)) error.value = '结果暂不可用，请核对客户和项目后重试。' }
  finally { if (context.current(epoch)) busy.value = false }
}
</script>

<template>
  <section class="report-panel">
    <strong>多号通结果回传</strong>
    <p>默认关闭。每次成功都需操作人在多号通确认公开链接；送达后继续按原规则核验页面。</p>
    <el-select v-if="!projectId" v-model="selected" placeholder="选择项目" aria-label="回传项目" :disabled="busy">
      <el-option v-for="p in projects" :key="p.id" :value="p.id" :label="p.name" />
    </el-select>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="settings">
      <p>当前项目：{{ settings.enabled && settings.scope_enabled ? '已打开' : '已关闭' }}。{{ canManage ? '' : '当前只读，请由获授权顾问或超管核对现有写入权限。' }}</p>
      <el-button v-if="mode === 'settings'" :disabled="busy || !canManage" @click="toggle">{{ settings.scope_enabled ? '关闭当前项目回传' : '打开当前项目回传' }}</el-button>
      <template v-if="mode === 'devices'">
        <el-input v-model="label" maxlength="80" placeholder="设备备注（必填，如团队电脑/用途）" aria-label="设备备注（必填）" :disabled="busy || !canManage" />
        <el-select v-model="account" clearable placeholder="不指定（由多号通发布时上报）" aria-label="设备绑定账号（可选）" :disabled="busy || !canManage">
          <el-option v-for="a in accounts || []" :key="a.id" :value="a.id" :label="a.display_name" />
        </el-select>
        <el-button :disabled="busy || !canManage || !label.trim()" @click="pair">生成配对码</el-button>
        <p>公众号可不选，没有公众号也能生成配对码；本次发布用的公众号名称由操作人在多号通回传时填写。</p>
        <el-alert v-if="pairing" :title="`一次性配对码（10分钟内有效）：${pairing.pairing_code}`" type="info" :closable="true" @close="pairing = null" />
        <p>在团队电脑的多号通选择 GEO 并输入配对码，可同时为多个客户代发。每个客户最多保留20个有效配对和20个未用配对码；发布前请核对客户、项目和公众号。</p>
        <p v-for="d in settings.devices" :key="d.id">{{ d.label }} · {{ d.revoked ? '已吊销' : '已配对，账号身份未核验' }}
          <el-button :disabled="busy || !canManage || d.revoked" @click="revoke(d.id)">吊销</el-button>
        </p>
      </template>
      <template v-if="mode === 'task'">
        <el-select v-model="device" placeholder="选择本项目设备" aria-label="派稿设备" :disabled="busy || !canManage">
          <el-option v-for="d in activeDevices" :key="d.id" :value="d.id" :label="d.label" />
        </el-select>
        <el-button :disabled="busy || !canManage || !settings.enabled || !settings.scope_enabled || !device || !wechat" @click="dispatch">派发当前已审核公众号稿</el-button>
        <p v-if="status">{{ status.delivered ? '已送达服务端' : '尚无回执' }} · {{ reportOutcomes[status.reportedOutcome] || '待回报' }} {{ reportCodes[status.code] || '' }} · {{ verificationLabel }}</p>
        <p v-if="status">回传公众号：{{ status.reportedAccount?.name || '未上报' }}</p>
        <el-button :disabled="busy || !status?.taskId" @click="refreshResult">刷新回执与核验</el-button>
      </template>
    </template>
  </section>
</template>
<style scoped>
.report-panel { padding: 16px; border: 1px solid #dbe3eb; border-radius: 12px; margin: 16px 0; background: #fff; }
.report-panel p { color: #526176; margin: 10px 0; }
.el-input, .el-select { max-width: 300px; margin-right: 8px; }
</style>
