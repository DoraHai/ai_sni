<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import client from '../../api/client'
import { session } from '../../store/session'
import { createShadowApi, SHADOW_NOTICE, LAST_GRANT_NOTICE, validateScreenshots, shadowError, submissionPayload, changeAndReloadGrants } from './shadowPlanning'

const api = createShadowApi(client)
const route = useRoute(), router = useRouter()
const base = '/onboarding/sem-shadow'
const page = computed(() => route.meta.shadowPage || 'entry')
const tenant = computed(() => Number(session.tenantId) || null)
const customer = computed(() => session.tenants.find(t => t.id === tenant.value))
const accounts = computed(() => (customer.value?.sem_accounts || []).filter(a => a.status === 'active'))
const account = ref(null)
const canWrite = computed(() => session.user?.is_advisor === true)
const canManage = computed(() => session.canManage && !session.user?.is_advisor && !session.user?.tenant_id)
const busy = ref(false), message = ref(''), error = ref(''), plans = ref([]), plan = ref(null), grants = ref([])
const files = ref([]), saved = ref(null), offset = ref(0), grantForm = reactive({ user_id: null, advisor_grant_id: null })
const grantsStale = ref(false)
const reason = ref('')
const activeCount = computed(() => grants.value.filter(g => !g.revoked_at).length)
const defaults = () => ({ product_line_id: '', landing_page_id: '', expected_revision: 0, case_type: 'new_account',
  account_ready: false, landing_url: '', page_content: '', goal: '', budget_cents: null, budget_period: 'daily', bid_cap_cents: null,
  regions: '', days: [], start_hour: 0, end_hour: 24, brand_rules: '', negative_keywords: '', starts_at: '', ends_at: '',
  no_deadline_explicit: false, link_source: 'email', authorized_scope: '' })
const form = reactive(defaults())
let generation = 0, mounted = false
const context = () => [session.token, tenant.value, account.value].join('|')
function resetScope() {
  generation++
  plans.value = []; plan.value = null; grants.value = []; grantsStale.value = false; files.value = []; saved.value = null
  offset.value = 0; error.value = ''; message.value = ''; reason.value = ''; busy.value = false
  Object.assign(form, defaults()); grantForm.user_id = null; grantForm.advisor_grant_id = null
}
async function perform(action) {
  const scope = context(), ticket = ++generation
  busy.value = true; error.value = ''; message.value = ''
  const current = () => scope === context() && ticket === generation
  try { await action(current) } catch (e) { if (current()) error.value = shadowError(e) }
  finally { if (current()) busy.value = false }
}
async function load() {
  plan.value = null; plans.value = []
  if (page.value !== 'grants') grants.value = []
  if (!tenant.value || !account.value) return
  await perform(async current => {
    if (page.value === 'grants') {
      if (!canManage.value) throw Object.assign(new Error(), { status: 403 })
      grantsStale.value = true
      const rows = await api.grants(tenant.value, account.value)
      if (current()) { grants.value = rows; grantsStale.value = false }
    } else if (route.params.planId) {
      const result = await api.read(route.params.planId)
      if (current()) {
        // Route IDs are untrusted; never display another selected account's plan.
        if (result.submission.tenant_id !== tenant.value || result.submission.account_id !== account.value) throw Object.assign(new Error(), { status: 403 })
        plan.value = result
      }
    } else if (['entry', 'plans'].includes(page.value)) {
      const rows = await api.list(tenant.value, account.value, offset.value)
      if (current()) plans.value = rows
    }
  })
}
function choose(event) {
  try { files.value = validateScreenshots(Array.from(event.target.files)); error.value = '' }
  catch (e) { files.value = []; error.value = e.message }
  event.target.value = ''
}
async function submit() {
  saved.value = null
  if (!canWrite.value) return
  await perform(async current => {
    const payload = submissionPayload(form, tenant.value, account.value)
    const result = await api.submit(payload, files.value)
    if (current()) {
      saved.value = { tenant_id: payload.tenant_id, account_id: payload.account_id, page_id: payload.landing_page_id, submission_revision: result.revision }
      form.expected_revision = result.revision; files.value = []
      message.value = `来源 v${result.revision} 已保存。可生成影子规划；尚未改动投放。`
    }
  })
}
async function createPlan() {
  if (!saved.value || !canWrite.value) return
  await perform(async current => {
    const result = await api.create({ ...saved.value })
    if (current()) await router.push(`${base}/plans/${result.plan_id}`)
  })
}
async function rule() {
  if (!plan.value || !reason.value.trim() || !canWrite.value) return
  await perform(async current => {
    const result = await api.rule(plan.value.plan_id, plan.value.version, reason.value)
    if (current()) { plan.value = result; message.value = '来源裁定已记录，建议仅供内部复核。' }
  })
}
async function download() {
  if (!plan.value || !canWrite.value) return
  await perform(async current => {
    const id = plan.value.plan_id
    const blob = await api.excel(id)
    if (!current()) return
    if (!(blob instanceof Blob) || !blob.size) throw new Error('导出未返回有效文件')
    const url = URL.createObjectURL(blob), link = document.createElement('a')
    link.href = url; link.download = `shadow-${id}-internal.xlsx`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    message.value = '内部演练表已下载；导出已由服务端记录审计。'
  })
}
async function changeGrant(revoke, row) {
  if (!canManage.value || grantsStale.value) return
  await perform(async current => {
    const body = { tenant_id: tenant.value, user_id: Number(row?.user_id || grantForm.user_id),
      advisor_grant_id: row?.advisor_grant_id ?? (grantForm.advisor_grant_id ? Number(grantForm.advisor_grant_id) : null) }
    if (!Number.isSafeInteger(body.user_id) || body.user_id <= 0) throw new Error('请填写批准名单中的人员 ID')
    const aid = account.value, tid = tenant.value
    const outcome = await changeAndReloadGrants(
      () => revoke ? api.revoke(aid, body) : api.grant(aid, body), () => api.grants(tid, aid), current)
    if (!current()) return
    if (outcome.refreshFailed) {
      grantsStale.value = true
      error.value = '变更请求已成功，但授权列表刷新失败。下方为旧记录，操作已暂停；请点刷新核对当前状态。'
    } else { grants.value = outcome.rows; grantsStale.value = false }
    message.value = outcome.result.changed ? '授权变更已保存并记录审计。' : '授权状态未变化。'
  })
}
function navigate(path) { router.push(path) }
watch(() => [session.token, tenant.value], () => {
  resetScope(); account.value = accounts.value[0]?.id || null
  if (mounted) load()
})
watch(accounts, rows => { if (!rows.some(a => a.id === account.value)) account.value = rows[0]?.id || null })
watch(account, () => { resetScope(); if (mounted) load() })
watch(() => route.fullPath, () => { generation++; error.value = ''; message.value = ''; if (mounted) load() })
onMounted(() => { mounted = true; account.value = accounts.value[0]?.id || null; if (account.value) load() })
onBeforeUnmount(() => { mounted = false; generation++ })
</script>

<template>
  <div class="shadow-page">
    <header><div><small>SEM SHADOW PLANNING</small><h1>{{ route.meta.title }}</h1><p>基于落地页资料整理建议，保留来源版本与人工复核。</p></div></header>
    <el-alert :title="SHADOW_NOTICE" type="warning" :closable="false" show-icon />
    <div class="context-bar">
      <span>客户：{{ customer?.name || (tenant ? `#${tenant}` : '请先在顶栏选择客户') }}</span>
      <label>推广账户 <select v-model="account" :disabled="busy"><option :value="null">请选择</option><option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.username || a.account_name }} · #{{ a.id }}</option></select></label>
      <el-button :disabled="busy || !account" @click="load">刷新</el-button>
    </div>
    <el-alert v-if="!account" title="请选择当前客户的有效推广账户；无精确账户授权时服务端仍会拒绝访问。" type="info" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" role="alert" />
    <el-alert v-if="message" :title="message" type="success" :closable="false" role="status" />
    <nav v-if="page !== 'grants'" class="page-nav">
      <el-button @click="navigate(base)">工作台</el-button><el-button @click="navigate(base + '/submit')">提交落地页</el-button><el-button @click="navigate(base + '/plans')">影子规划</el-button>
    </nav>
    <el-card v-if="page === 'entry'" class="hero" shadow="never">
      <h2>从页面资料，开始一份可复核的规划</h2><p>提交链接、长文本与可选截图，再核对来源、检查建议并导出内部演练表。</p>
      <el-button type="primary" @click="navigate(base + '/submit')">提交落地页</el-button><el-button @click="navigate(base + '/plans')">查看影子规划</el-button>
      <p>当前不会抓网页、不会 OCR、不会调用模型。附件默认未装配，带图提交可能返回 503。</p>
    </el-card>
    <div v-if="page === 'submit'" class="columns">
      <el-card shadow="never"><h2>页面资料</h2><p v-if="!canWrite">当前为只读身份，只有获当前账户授权的顾问可以提交。</p>
        <form @submit.prevent="submit">
          <fieldset :disabled="busy || !canWrite || !account" class="form-grid">
            <label>产品线标识<input v-model="form.product_line_id" required maxlength="80" pattern="[\w\-]+"></label>
            <label>页面标识<input v-model="form.landing_page_id" required maxlength="80" pattern="[\w\-]+"></label>
            <label>当前来源版本（首次填 0）<input v-model.number="form.expected_revision" type="number" min="0" required></label>
            <label>提交情况<select v-model="form.case_type"><option value="new_account">①新开户</option><option value="new_product">③新品</option><option value="event">③活动</option></select></label>
            <label class="wide">落地页链接<input v-model="form.landing_url" type="url" required maxlength="2000"></label>
            <label class="wide">页面内容（长文本）<textarea v-model="form.page_content" required maxlength="50000" rows="9" placeholder="product: 产品事实&#10;benefit: 卖点事实&#10;keywords: 关键词&#10;补充完整页面正文" /></label>
            <p class="wide hint">必须包含 product:/benefit:/keywords:。链接只作来源标识；不会自动抓取或识别截图。</p>
            <label class="wide">页面截图（可选）<input type="file" accept="image/png,image/jpeg,image/webp" multiple @change="choose"><span class="hint">PNG/JPEG/WebP · 单张 10MiB · 最多 10 张 · 合计 30MiB</span></label>
            <div class="wide hint" aria-live="polite">已选 {{ files.length }} 张 <el-button v-if="files.length" size="small" @click="files = []">清空截图</el-button></div>
            <label class="wide">投放目标<input v-model="form.goal" required maxlength="2000"></label>
            <label>预算（整数分）<input v-model.number="form.budget_cents" type="number" min="1" required></label>
            <label>预算周期<select v-model="form.budget_period"><option value="daily">每日</option><option value="total">总计</option></select></label>
            <label>出价上限（整数分）<input v-model.number="form.bid_cap_cents" type="number" min="1" required></label>
            <label>地域（每行一个）<textarea v-model="form.regions" required rows="2" /></label>
            <label>开始时间（北京时间）<input v-model="form.starts_at" type="datetime-local" required></label>
            <label>截止时间（北京时间）<input v-model="form.ends_at" type="datetime-local" :required="!form.no_deadline_explicit"></label>
            <label class="wide check"><input v-model="form.no_deadline_explicit" type="checkbox">明确无截止（活动不适用）</label>
            <div class="wide">投放星期 <label v-for="d in 7" :key="d" class="day"><input v-model="form.days" :value="d" type="checkbox">{{ ['一','二','三','四','五','六','日'][d-1] }}</label></div>
            <label>开始小时<input v-model.number="form.start_hour" type="number" min="0" max="23" required></label><label>结束小时<input v-model.number="form.end_hour" type="number" min="1" max="24" required></label>
            <label class="wide">品牌与投放边界<textarea v-model="form.brand_rules" required maxlength="2000" rows="2" /></label>
            <label class="wide">否定关键词（每行一个，可空）<textarea v-model="form.negative_keywords" rows="2" /></label>
            <label>链接来源<select v-model="form.link_source"><option value="email">邮件</option><option value="group">日常沟通群</option></select></label>
            <label>已授权范围<input v-model="form.authorized_scope" required maxlength="2000"></label>
            <label class="wide check"><input v-model="form.account_ready" type="checkbox" required>已明确账户开好，以上资料属于当前客户和账户</label>
            <div class="wide actions"><el-button native-type="submit" type="primary" :loading="busy">保存来源</el-button></div>
          </fieldset>
        </form>
        <el-button v-if="saved" type="primary" :disabled="busy" @click="createPlan">以已保存的 v{{ saved.submission_revision }} 生成影子规划</el-button>
      </el-card>
      <aside><el-card shadow="never"><h2>提交前检查</h2><p>页面、产品线和链接身份绑定后不能更换。修改内容追加版本，旧规划会失效。</p><p>截图可能含个人信息，请提交前裁剪或打码。服务端只验证图片签名，不代表图片内容安全。</p><p>附件后端未显式注入时保持 503；界面不会假装上传成功。</p><p>账户首次授权仍须另行批准，管理员不能通过此界面初始化。</p></el-card></aside>
    </div>
    <el-card v-if="['entry','plans'].includes(page) && !route.params.planId" shadow="never">
      <h2>当前账户影子规划</h2><p class="hint">以下为服务端真实索引；有效性须进入详情重新核验来源。</p>
      <el-table :data="plans" v-loading="busy" border><el-table-column prop="product_line_id" label="产品线" /><el-table-column prop="plan_id" label="规划 ID" /><el-table-column prop="version" label="版本" width="80" /><el-table-column label="来源"><template #default="{ row }">{{ row.pages.map(p => `${p.page_id} / v${p.revision}`).join('；') }}</template></el-table-column><el-table-column label="操作" width="120"><template #default="{ row }"><el-button link type="primary" @click="navigate(base + '/plans/' + row.plan_id)">查看详情</el-button></template></el-table-column><template #empty>{{ busy ? '正在读取…' : '当前页无规划' }}</template></el-table>
      <div class="actions"><el-button :disabled="busy || offset === 0" @click="offset -= 50; load()">上一页</el-button><span>第 {{ offset / 50 + 1 }} 页</span><el-button :disabled="busy || plans.length < 50" @click="offset += 50; load()">下一页</el-button></div>
    </el-card>
    <div v-if="plan && ['plans','export'].includes(page)" class="columns">
      <el-card shadow="never"><div class="actions"><h2>{{ plan.submission.product_line_id }} · {{ page === 'export' ? '导出内部演练表' : '规划详情' }}</h2><el-button v-if="page !== 'export'" @click="navigate(base + '/plans/' + plan.plan_id + '/export')">导出 Excel</el-button></div>
        <p class="hint">{{ plan.plan_id }} · v{{ plan.version }} · {{ plan.state === 'awaiting_ruling' ? '待来源裁定' : '待顾问复核' }}</p>
        <el-table :data="plan.rows" border><el-table-column prop="kind" label="类型" /><el-table-column prop="text" label="结构与关键词" /><el-table-column prop="verification" label="来源核验" /><el-table-column prop="budget_cents" label="预算（分）" /></el-table>
        <details><summary>来源与版本</summary><p v-for="s in plan.submissions" :key="s.payload.landing_page_id">{{ s.payload.landing_page_id }} · v{{ s.revision }} · {{ s.sha256 }}</p><p v-for="s in plan.sources" :key="s.source_id">{{ s.field }}：{{ s.value }}（{{ s.origin }} · {{ s.locator }}）</p></details>
        <template v-if="plan.state === 'awaiting_ruling' && canWrite && page !== 'export'"><p>请核对上方全部提交来源，确认默认来源选择后生成建议；有误请追加来源版本。</p><label>来源核对理由<el-input v-model="reason" maxlength="2000" /></label><el-button type="primary" :disabled="busy || !reason.trim()" @click="rule">确认提交来源并生成建议</el-button></template>
        <template v-if="page === 'export'"><p>仅当前规划与当前来源版本；不是百度上传模板。导出会写审计，仅顾问可用。</p><el-button type="primary" :disabled="busy || !canWrite || !plan.rows.length" @click="download">下载内部 Excel</el-button><p v-if="!plan.rows.length" class="hint">请先返回详情完成来源裁定。</p></template>
        <details><summary>复核记录</summary><p v-for="a in plan.audit" :key="a.ordinal">{{ a.at }} · {{ a.action }} · {{ a.actor }}</p></details>
      </el-card>
      <el-card shadow="never"><h2>当前复核边界</h2><p>客户正式确认：待完成</p><p>真实账户预算帽：未核验</p><p>既有资产：未核验</p><el-alert title="P5 / P6 仍阻断；来源更新后旧规划失效。" type="warning" :closable="false" /><p v-for="i in [...(plan.p5?.issues || []), ...(plan.p6?.issues || [])]" :key="i.rule" class="hint">{{ i.rule }}</p></el-card>
    </div>
    <div v-if="page === 'grants'" class="columns">
      <el-card shadow="never"><h2>精确账户授权</h2><el-alert :title="LAST_GRANT_NOTICE" type="warning" :closable="false" />
        <p v-if="!canManage">仅可归属真实登录用户的平台管理员可管理；当前身份没有管理权限。</p>
        <el-table :data="grants" v-loading="busy" border><el-table-column prop="user_id" label="人员 ID" /><el-table-column prop="advisor_grant_id" label="顾问授权 ID" /><el-table-column prop="generation" label="绑定代次" /><el-table-column label="状态"><template #default="{ row }">{{ row.revoked_at ? '已撤销' : '有效' }}</template></el-table-column><el-table-column label="操作"><template #default="{ row }"><el-button v-if="!row.revoked_at" :disabled="!canManage || busy || grantsStale || activeCount <= 1" title="服务端同时保护最后一名可写顾问" @click="changeGrant(true, row)">撤销</el-button><el-button v-else :disabled="!canManage || busy || grantsStale" @click="changeGrant(false, row)">重新授予</el-button></template></el-table-column></el-table>
        <form @submit.prevent="changeGrant(false)"><fieldset :disabled="!canManage || busy || grantsStale || !account" class="form-grid"><label>批准名单中的人员 ID<input v-model.number="grantForm.user_id" type="number" min="1" required></label><label>顾问授权 ID（客户只读留空）<input v-model.number="grantForm.advisor_grant_id" type="number" min="1"></label><div class="wide"><el-button type="primary" native-type="submit">授予账户访问</el-button></div></fieldset></form>
      </el-card><el-card shadow="never"><h2>首次授权须另走流程</h2><p>账户没有有效绑定时，列出、授予、撤销均返回 403。此页不能初始化账户。</p><p>按书面名单逐条核对客户、账户、人员和顾问授权 ID。撤销保留历史与审计。</p><p>界面末条禁用仅作提示；最后可写顾问由后端按当前身份与授权状态再次判断。</p></el-card>
    </div>
  </div>
</template>

<style scoped>
.shadow-page{padding:24px;max-width:1440px;margin:auto;color:var(--text,#22262d)}header{margin-bottom:18px}header small{color:#e86f1c;letter-spacing:2px}h1{font-size:26px;margin:8px 0}h2{font-size:18px;margin:0 0 16px}p{line-height:1.8;color:#647084;font-size:13px}.shadow-page>.el-alert{margin-bottom:14px}.context-bar,.page-nav,.actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:16px 0}.context-bar{padding:12px 16px;background:#fff;border:1px solid #e6e8ec;border-radius:10px;font-size:13px}.columns{display:grid;grid-template-columns:minmax(0,2fr) minmax(240px,1fr);gap:16px}.el-card{margin-bottom:16px;border-radius:12px}.hero{background:linear-gradient(120deg,#fff8ef,#fafdff)}.form-grid{border:0;padding:0;display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:20px 0}.form-grid label{display:flex;flex-direction:column;gap:7px;font-size:13px}.form-grid input:not([type=checkbox]),.form-grid textarea,.form-grid select,.context-bar select{box-sizing:border-box;width:100%;padding:10px;border:1px solid #dcdfe6;border-radius:7px;font:inherit;color:inherit;background:#fff}.form-grid input:focus,.form-grid textarea:focus{outline:1px solid #e86f1c}.wide{grid-column:1/-1}.hint{font-size:12px;color:#7a828e}.form-grid .check{flex-direction:row;align-items:center}.day{display:inline-flex!important;margin:8px 8px 0 0;flex-direction:row!important}details{margin:20px 0;overflow-wrap:anywhere}summary{cursor:pointer;color:#c86115}button:disabled,input:disabled,select:disabled{cursor:not-allowed}.actions h2{margin:0;flex:1}@media(max-width:1050px){.columns{grid-template-columns:1fr}}@media(max-width:650px){.shadow-page{padding:12px}.form-grid{grid-template-columns:1fr}.wide{grid-column:auto}}
</style>
