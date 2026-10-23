<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { session } from '../../store/session'
import { fetchUsers } from '../../api/auth'
import { fetchRoles } from '../../api/roles'
import { fetchManualQuota, saveManualQuota, fetchAssignmentSites, fetchSiteAssignments, saveSiteAssignment } from '../../api/platformCustomerServices'

const props = defineProps({ customer: { type: Object, required: true }, kind: { type: String, required: true } })
const emit = defineEmits(['close'])
const manual = computed(() => props.kind === 'manual')
const allowed = computed(() => session.user?.tenant_id == null && !session.isAdvisorSession
  && session.canEdit('settings.accounts') && session.canEdit(manual.value ? 'geo.content' : 'seo.content'))
const loading = ref(false), busy = ref(false), error = ref(''), success = ref('')
const quota = ref(null), limit = ref(''), reason = ref('')
const sites = ref([]), users = ref([]), roles = ref([]), assignments = ref([])
const siteId = ref(''), advisorId = ref(''), active = ref(true), pending = ref(null)
let generation = 0
onBeforeUnmount(() => { generation++ })
const selectedSite = computed(() => sites.value.find(s => s.id === Number(siteId.value)))
const candidates = computed(() => users.value.filter(u => u.is_active
  && (u.tenant_id === props.customer.id || u.tenant_ids?.includes(props.customer.id))
  && roles.value.find(r => r.id === u.role_id)?.permissions?.['seo.content'] === 'edit'))
const selectedAdvisor = computed(() => candidates.value.find(u => u.id === Number(advisorId.value)))
const quotaReady = computed(() => Number.isInteger(quota.value?.manual_limit_revision)
  && quota.value.manual_limit_revision >= 0 && Number.isInteger(quota.value?.manual_quota?.limit))

async function load() {
  if (!allowed.value || busy.value) return
  const request = ++generation
  loading.value = true; error.value = ''; success.value = ''; quota.value = null; assignments.value = []
  try {
    if (manual.value) {
      const data = await fetchManualQuota(props.customer.id)
      if (request !== generation) return
      quota.value = data; limit.value = String(data.manual_quota?.limit ?? '')
      if (!quotaReady.value) error.value = '次数或版本信息不完整，请重新读取后再保存'
    } else {
      sites.value = []; users.value = []; roles.value = []; siteId.value = ''; advisorId.value = ''
      const [s, u, r] = await Promise.all([fetchAssignmentSites(props.customer.id), fetchUsers(), fetchRoles()])
      if (request !== generation) return
      sites.value = s.sites || []; users.value = u.users || []; roles.value = r.roles || []
    }
  } catch (e) { if (request === generation) error.value = e.message }
  finally { if (request === generation) loading.value = false }
}
async function selectSite() {
  const request = ++generation
  assignments.value = []; advisorId.value = ''; active.value = true; success.value = ''; error.value = ''
  if (!selectedSite.value) return
  loading.value = true
  try {
    const data = await fetchSiteAssignments(props.customer.id, Number(siteId.value))
    if (request === generation) assignments.value = data.items || []
  } catch (e) {
    if (request === generation) { error.value = e.message; siteId.value = '' }
  } finally { if (request === generation) loading.value = false }
}
function selectAdvisor() {
  active.value = assignments.value.find(a => a.advisor_user_id === Number(advisorId.value))?.active ?? true
}
function prepare() {
  if (!allowed.value || busy.value || loading.value) return
  error.value = ''; success.value = ''
  if (manual.value) {
    if (!/^[1-9]\d*$/.test(limit.value) || Number(limit.value) > 100) {
      error.value = '次数须为 1–100 的整数，不能为 0、负数、小数或空值'; return
    }
    if (!reason.value.trim() || reason.value.trim().length > 500) { error.value = '请填写 1–500 字的修改原因'; return }
    if (!quotaReady.value) { error.value = '请重新读取次数与版本后再保存'; return }
    pending.value = { tenant_id: props.customer.id, manual_daily_limit: Number(limit.value), expected_revision: quota.value.manual_limit_revision, reason: reason.value.trim() }
  } else {
    if (!selectedSite.value || selectedSite.value.status !== 'active' || !selectedAdvisor.value) { error.value = '请选择启用的网站和已获该客户授权的有效顾问'; return }
    pending.value = { tenant_id: props.customer.id, site_id: Number(siteId.value), advisor_user_id: Number(advisorId.value), active: active.value }
  }
  busy.value = true
}
async function confirm() {
  if (!pending.value || loading.value || !allowed.value) return
  const body = { ...pending.value }
  loading.value = true; pending.value = null
  try {
    if (manual.value) quota.value = await saveManualQuota(body)
    else {
      const row = await saveSiteAssignment(body)
      assignments.value = [...assignments.value.filter(a => a.advisor_user_id !== body.advisor_user_id), row]
    }
    success.value = manual.value ? '手动检测次数已保存' : 'SEO 网站分配已保存'
  } catch (e) {
    error.value = `${e.message}；请重新读取并核对后再保存`
    if (manual.value) quota.value = null
    else { siteId.value = ''; advisorId.value = ''; assignments.value = [] }
  } finally { loading.value = false; busy.value = false }
}
onMounted(load)
</script>

<template>
  <el-dialog :model-value="true" class="platform-responsive-dialog service-dialog" :title="manual ? '手动检测次数设置' : 'SEO 网站分配'" width="620px"
    :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" @close="!busy && emit('close')">
    <section class="service-panel">
      <h3>{{ customer.name }}</h3>
      <p v-if="!allowed" role="alert">需要平台账号管理及对应内容管理权限。</p>
      <template v-else>
        <p v-if="manual">同一客户的所有顾问共享每日次数，按北京时间自然日计算。</p>
        <p v-else>按网站分配顾问；停用分配将保留记录。顾问须先获得该客户授权及 SEO 内容编辑权限。</p>
        <button type="button" :disabled="busy || loading" @click="load">重新读取</button>
        <p v-if="loading" role="status">正在处理…</p>
        <form @submit.prevent="prepare">
          <template v-if="manual">
            <p>今日已用 / 上限：<b>{{ quota?.manual_quota?.used ?? '—' }} / {{ quota?.manual_quota?.limit ?? '—' }}</b></p>
            <label>每日手动检测次数<input v-model="limit" aria-label="每日手动检测次数" inputmode="numeric" :disabled="busy || loading" placeholder="1–100 的整数" /></label>
            <label>修改原因<textarea v-model="reason" aria-label="修改原因" maxlength="500" :disabled="busy || loading" rows="2" /></label>
          </template>
          <template v-else>
            <label>SEO 网站<select v-model="siteId" aria-label="SEO 网站" :disabled="busy || loading" @change="selectSite">
              <option value="">请选择网站</option><option v-for="s in sites" :key="s.id" :value="s.id" :disabled="s.status !== 'active'">{{ s.name || s.domain }} · {{ s.status === 'active' ? '启用' : '不可分配' }}</option>
            </select></label>
            <p v-if="!loading && !sites.length">暂无可读取的网站。</p>
            <label>顾问<select v-model="advisorId" aria-label="顾问" :disabled="busy || loading || !siteId" @change="selectAdvisor">
              <option value="">请选择顾问</option><option v-for="u in candidates" :key="u.id" :value="u.id">{{ u.display_name || u.username }}</option>
            </select></label>
            <p v-if="!loading && !candidates.length">暂无符合条件的顾问，请先在账号管理中配置授权。</p>
            <label>分配状态<select v-model="active" aria-label="分配状态" :disabled="busy || loading"><option :value="true">启用</option><option :value="false">停用（保留记录）</option></select></label>
            <ul v-if="assignments.length"><li v-for="a in assignments" :key="a.id">{{ a.advisor_name || `账号 #${a.advisor_user_id}` }}：{{ a.active ? '已启用' : '已停用' }}</li></ul>
          </template>
          <p v-if="error" role="alert" class="service-error">{{ error }}</p>
          <p v-if="success" role="status" class="service-success">{{ success }}</p>
          <button type="submit" class="primary" :disabled="busy || loading || (manual && !quotaReady)">保存变更</button>
        </form>
        <div v-if="pending" role="alertdialog" aria-modal="true" aria-label="确认保存变更" class="service-confirm">
          <h4>确认保存变更</h4>
          <p>{{ customer.name }}</p>
          <p v-if="manual">每日手动检测次数：{{ quota?.manual_quota?.limit }} → {{ pending.manual_daily_limit }}。所有顾问共享此额度。</p>
          <p v-else>{{ selectedSite?.name || selectedSite?.domain }} · {{ selectedAdvisor?.display_name || selectedAdvisor?.username }}：{{ pending.active ? '启用' : '停用' }}分配。停用保留历史记录。</p>
          <button type="button" autofocus @click="pending = null; busy = false">返回修改</button>
          <button type="button" class="primary" @click="confirm">确认保存</button>
        </div>
      </template>
    </section>
  </el-dialog>
</template>

<style scoped>
.service-panel{color:#253047;overflow-wrap:anywhere}.service-panel h3{margin-top:0}.service-panel p{line-height:1.6}.service-panel label{display:block;margin:18px 0 8px;font-weight:600}.service-panel input,.service-panel textarea,.service-panel select{display:block;box-sizing:border-box;width:100%;margin-top:8px;border:1px solid #b8c3d5;border-radius:6px;padding:10px;font:inherit;background:#fff;color:#253047}.service-panel button{padding:10px 16px;border:1px solid #b8c3d5;border-radius:6px;background:#fff;color:#253047;cursor:pointer}.service-panel button:disabled{opacity:.5;cursor:default}.service-panel .primary{background:#4338ca;color:#fff;border-color:#4338ca}.service-error{color:#b42318}.service-success{color:#16734b}.service-confirm{position:absolute;inset:0;background:#fff;z-index:2;padding:28px;box-sizing:border-box;border-radius:8px;box-shadow:0 4px 30px #17203333}.service-confirm button{margin:8px 8px 0 0}.service-confirm h4{font-size:18px}
</style>
