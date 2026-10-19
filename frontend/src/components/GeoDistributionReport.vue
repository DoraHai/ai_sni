<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { session } from '../store/session'
import { fetchGeoProjects } from '../api/geoProjects'
import { reportSettings, setReportSettings, pairReportDevice, revokeReportDevice, dispatchReportTask, fetchReportTask, setReportPublishAccount } from '../api/geoDistributionReport'
import { reportContext, reportDigest, reportToggle, reportOutcomes, reportCodes, reportPublishAccount, reportAccountName, reportDeviceLabel } from '../utils/geoDistributionReport'

const props = defineProps({ tenantId: Number, projectId: Number, task: Object, accounts: Array, mode: { type: String, default: 'settings' } })
const emit = defineEmits(['changed'])
const projects = ref([]), selected = ref(null), settings = ref(null), pairing = ref(null), result = ref(null)
const busy = ref(false), error = ref(''), label = ref(''), account = ref(null), device = ref(null)
const notice = ref(''), editing = ref(false), editName = ref(''), editTask = ref(null), editRevision = ref(null)
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
  notice.value = ''; editing.value = false; editName.value = ''; editTask.value = null; editRevision.value = null
}
async function loadSettings() {
  reset()
  if (!props.tenantId || !project.value) return
  const epoch = context.capture()
  busy.value = true
  try {
    const data = await reportSettings(props.tenantId, project.value)
    if (!context.current(epoch)) return
    settings.value = data
    // The annotation lives in the report ledger, never in article metadata.
    const id = projected.value?.taskId
    if (props.mode === 'task' && id) {
      const latest = await fetchReportTask(props.tenantId, project.value, id)
      if (context.current(epoch)) result.value = latest
    }
  } catch { if (context.current(epoch)) error.value = '回传设置暂不可用，请刷新或由管理员核对权限。' }
  finally { if (context.current(epoch)) busy.value = false }
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
  return action(async ({ tenant, scope, current }) => {
    const remark = reportDeviceLabel(label.value), selectedAccount = account.value == null ? null : String(account.value)
    notice.value = ''; pairing.value = null
    if (!settings.value.enabled || !settings.value.scope_enabled) {
      let opened
      try {
        opened = await setReportSettings(tenant, scope, { enabled: true, scope_enabled: true,
          expected_revision: settings.value.revision, expected_scope_revision: settings.value.scope_revision })
      } catch { if (current()) error.value = '回传未能开启，未生成配对码。请刷新并核对当前客户和项目权限。'; return }
      if (!current()) return
      settings.value = { ...opened, can_manage: true }
      notice.value = '已同时开启回传'
    }
    let data
    try {
      data = await pairReportDevice(tenant, scope, { label: remark, platform: 'wechat-article',
        account_id: selectedAccount, expected_revision: settings.value.revision })
    } catch { if (current()) error.value = '配对码未生成，请刷新后重试。当前回传状态请查看上方提示。'; return }
    if (!current()) return
    pairing.value = data
    try {
      const updated = await reportSettings(tenant, scope)
      if (current()) settings.value = updated
    } catch { if (current()) error.value = '配对码已生成，设置刷新暂未完成。请先使用上方配对码。' }
  })
}
function startEdit() {
  const id = status.value?.taskId
  if (!id) return
  return action(async ({ tenant, scope, current }) => {
    const latest = await fetchReportTask(tenant, scope, id)
    if (!current()) return
    result.value = latest; editTask.value = id; editRevision.value = latest.revision
    editName.value = latest.advisorAccount?.name || latest.reportedAccount?.name || ''
    editing.value = true
  })
}
function saveAccount(clear = false) {
  if (!editing.value || !editTask.value) return
  const name = clear ? null : reportAccountName(editName.value)
  if (name !== null && (Array.from(name).length < 1 || Array.from(name).length > 60)) {
    error.value = '请填写1至60个字的公众号名称；需要移除顾问标注时请点清除标注。'; return
  }
  return action(async ({ tenant, scope, current }) => {
    try {
      const data = await setReportPublishAccount(tenant, scope, editTask.value,
        { name, expected_revision: editRevision.value })
      if (!current()) return
      result.value = data; settings.value = { ...settings.value, revision: data.revision }
      editing.value = false; emit('changed')
    } catch (failure) {
      if (!current()) return
      if (failure.code === 'SOURCE_CHANGED') {
        editing.value = false; error.value = '记录已更新，请重新点编辑后再保存。'
      } else error.value = '公众号标注未保存，请核对权限并重试。'
    }
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
  <p><a href="#/distribution-inbox">多号通回传：任意平台、无需稿件，生成通用配对码</a></p>
  <section class="report-panel">
    <h3>旧版稿件派发（0.3.5 / 0.3.6）</h3>
    <strong>多号通结果回传</strong>
    <p>默认关闭。生成配对码会同时开启当前客户和项目回传；每次成功仍需操作人在多号通确认公开链接，送达后继续核验页面。</p>
    <el-select v-if="!projectId" v-model="selected" placeholder="选择项目" aria-label="回传项目" :disabled="busy">
      <el-option v-for="p in projects" :key="p.id" :value="p.id" :label="p.name" />
    </el-select>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="notice" :title="notice" type="success" :closable="false" />
    <template v-if="settings">
      <p>当前项目：{{ settings.enabled && settings.scope_enabled ? '已打开' : '已关闭' }}。{{ canManage ? '' : '当前只读，请由获授权顾问或超管核对现有写入权限。' }}</p>
      <template v-if="mode === 'devices' || mode === 'settings'">
        <el-input v-model="label" maxlength="80" placeholder="设备备注（选填，如团队电脑/用途）" aria-label="设备备注（选填）" :disabled="busy || !canManage" />
        <el-select v-model="account" clearable placeholder="不指定（由多号通发布时上报）" aria-label="设备绑定账号（可选）" :disabled="busy || !canManage">
          <el-option v-for="a in accounts || []" :key="a.id" :value="a.id" :label="a.display_name" />
        </el-select>
        <el-button v-if="canManage" type="primary" :disabled="busy" @click="pair">生成配对码</el-button>
        <el-button v-if="canManage && settings.enabled && settings.scope_enabled" :disabled="busy" @click="toggle">关闭回传</el-button>
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
        <p v-if="status">发布公众号：{{ reportPublishAccount(status) }}
          <el-button v-if="canManage" size="small" :disabled="busy" @click="startEdit">编辑</el-button>
        </p>
        <el-button :disabled="busy || !status?.taskId" @click="refreshResult">刷新回执与核验</el-button>
      </template>
    </template>
    <el-dialog v-model="editing" title="标注发布公众号" width="420px" :close-on-click-modal="false" :show-close="!busy" :close-on-press-escape="!busy">
      <p>顾问标注只用于显示，不改变多号通原上报名称和页面核验结果。</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-input v-model="editName" maxlength="120" placeholder="发布公众号名称（最多60个字）" aria-label="发布公众号名称" :disabled="busy || !canManage" />
      <template #footer>
        <el-button :disabled="busy" @click="editing = false">取消</el-button>
        <el-button v-if="canManage" :disabled="busy" @click="saveAccount(true)">清除标注</el-button>
        <el-button v-if="canManage" type="primary" :disabled="busy" @click="saveAccount(false)">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>
<style scoped>
.report-panel { padding: 16px; border: 1px solid #dbe3eb; border-radius: 12px; margin: 16px 0; background: #fff; }
.report-panel p { color: #526176; margin: 10px 0; }
.el-input, .el-select { max-width: 300px; margin-right: 8px; }
</style>
