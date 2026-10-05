<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { currentTenantId, session } from '../../store/session'
import { currentSeoSiteId as siteId } from './seoSiteContext'
import { fetchSeoSites } from '../../api/moduleAssets'
import { fetchSeoAnalyticsSources, saveSeoAnalyticsSource, deleteSeoAnalyticsSource, testSeoAnalyticsSource, exchangeSeoBaiduCode, pullSeoAnalytics, fetchSeoAnalyticsMonthly, fetchSeoExportTemplate, saveSeoExportTemplate, resetSeoExportTemplate, fetchSeoMonthlyReportTemplate, saveSeoMonthlyReportTemplate, resetSeoMonthlyReportTemplate, fetchSeoTdkReviewTemplate, saveSeoTdkReviewTemplate, resetSeoTdkReviewTemplate } from '../../api/seo'
import { moveReportSection, validReportSections } from '../../api/seoMonthlyReport.js'
import { moveTdkReviewSection, validTdkReviewTemplate } from '../../api/seoTdkReview.js'
import { previousBeijingMonth, monthRange, metricText, beijingTime, baiduAuthorizeUrl, sanitizedSecrets } from './seoSiteAnalytics.js'

const sites = ref([]), sources = ref([]), monthly = ref([]), columns = ref([]), available = ref([])
const reportSections = ref([])
const tdkSections = ref([]), tdkColumns = ref({ char_counts: true, rationale: true })
const busy = ref(false), month = ref(previousBeijingMonth()), code = ref(''), ga4Json = ref(''), ga4UploadJson = ref(''), ga4File = ref('')
const baiduEnabled = ref(true), ga4Enabled = ref(true)
const baidu = reactive({ mode: 'account', tongji_site_id: '', api_key: '', username: '', secret_key: '', refresh_token: '', access_token: '', token_entered_at: '' })
const ga4 = reactive({ property_id: '' })
const canEdit = computed(() => !session.isLoggedIn || session.canEdit('seo.site'))
const scoped = () => ({ tenant_id: currentTenantId.value, site_id: siteId.value })
const source = name => sources.value.find(item => item.source === name)
const savedBaidu = computed(() => source('baidu_tongji'))
const modeWillSwitch = computed(() => savedBaidu.value?.config?.mode && savedBaidu.value.config.mode !== baidu.mode)
const canExchange = computed(() => canEdit.value && savedBaidu.value?.config?.mode === 'account' && savedBaidu.value?.has_secret_key)
const currentMonth = () => { const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit' }).formatToParts(new Date()); return `${parts.find(p => p.type === 'year').value}-${parts.find(p => p.type === 'month').value}` }
const statusText = row => row.status === 'ok' ? '成功' : row.status === 'no_data' ? '无数据' : `失败：${row.error_message || '请重试'}`
const explainError = error => error.response?.data?.detail?.message || error.message || '操作失败'
async function load() {
  if (!currentTenantId.value || !siteId.value) return
  try {
    const [a, b, c, d, tdk] = await Promise.all([
      fetchSeoAnalyticsSources(scoped()),
      fetchSeoAnalyticsMonthly({ ...scoped(), ...monthRange(month.value) }),
      fetchSeoExportTemplate(scoped()),
      fetchSeoMonthlyReportTemplate(scoped()),
      fetchSeoTdkReviewTemplate(scoped()),
    ])
    sources.value = a.items || []; monthly.value = b.items || []; columns.value = structuredClone(c.columns || [])
    reportSections.value = structuredClone(d.sections || [])
    tdkSections.value = structuredClone(tdk.sections || [])
    tdkColumns.value = structuredClone(tdk.columns || { char_counts: true, rationale: true })
    baiduEnabled.value = source('baidu_tongji')?.enabled ?? true; ga4Enabled.value = source('ga4')?.enabled ?? true
    if (!available.value.length) available.value = structuredClone(c.available || c.columns || [])
    const bsource = source('baidu_tongji')?.config || {}, gsource = source('ga4')?.config || {}
    Object.assign(baidu, { mode: bsource.mode || 'account', tongji_site_id: bsource.tongji_site_id || '', api_key: bsource.api_key || '', username: bsource.username || '', token_entered_at: bsource.token_entered_at || '' })
    ga4.property_id = gsource.property_id || ''
  } catch (error) { ElMessage.error(explainError(error)) }
}
async function init() {
  if (!currentTenantId.value) return
  try { sites.value = (await fetchSeoSites(currentTenantId.value)).sites || []; if (!siteId.value) siteId.value = sites.value[0]?.id || null; await load() }
  catch (error) { ElMessage.error(explainError(error)) }
}
async function run(action, success) { busy.value = true; try { await action(); ElMessage.success(success); await load(); return true } catch (error) { ElMessage.error(explainError(error)); return false } finally { busy.value = false } }
async function saveBaidu() {
  const saved = await run(() => saveSeoAnalyticsSource({ ...scoped(), source: 'baidu_tongji', enabled: baiduEnabled.value,
    config: { mode: baidu.mode, tongji_site_id: baidu.tongji_site_id, api_key: baidu.api_key, username: baidu.username, token_entered_at: baidu.mode === 'business' && baidu.access_token ? new Date().toISOString() : baidu.token_entered_at },
    secrets: sanitizedSecrets({ secret_key: baidu.secret_key, refresh_token: baidu.refresh_token, access_token: baidu.access_token }) }), '百度统计配置已保存')
  if (saved) baidu.secret_key = baidu.refresh_token = baidu.access_token = ''
}
async function saveGa4() { if (await run(() => saveSeoAnalyticsSource({ ...scoped(), source: 'ga4', enabled: ga4Enabled.value, config: { property_id: ga4.property_id }, secrets: sanitizedSecrets({ service_account_json: ga4UploadJson.value || ga4Json.value }) }), 'GA4 配置已保存')) ga4Json.value = ga4UploadJson.value = ga4File.value = '' }
async function upload(event) { const file = event.target.files?.[0]; if (file) { ga4UploadJson.value = await file.text(); ga4File.value = file.name } event.target.value = '' }
async function clearSaved(name, fields) {
  const config = name === 'ga4' ? { property_id: ga4.property_id } : { mode: baidu.mode, tongji_site_id: baidu.tongji_site_id, api_key: baidu.api_key, username: baidu.username, token_entered_at: baidu.token_entered_at }
  await run(() => saveSeoAnalyticsSource({ ...scoped(), source: name, enabled: name === 'ga4' ? ga4Enabled.value : baiduEnabled.value, config, clear_secrets: fields }), '已清除保存的凭证')
}
async function testConnection(name) { busy.value = true; try { const result = await testSeoAnalyticsSource(name, scoped()); ElMessage.success(result.last_test_message || '连接成功') } catch (error) { ElMessage.error(explainError(error)) } finally { busy.value = false; await load() } }
async function remove(name) { try { await ElMessageBox.confirm('确定删除此数据源配置？', '删除配置', { type: 'warning' }); await run(() => deleteSeoAnalyticsSource(name, scoped()), '配置已删除') } catch (error) { if (error !== 'cancel') ElMessage.error(explainError(error)) } }
async function authorize() { if (!baidu.api_key) return ElMessage.warning('请先填写 API Key'); window.open(baiduAuthorizeUrl(baidu.api_key), '_blank', 'noopener,noreferrer') }
async function exchange() { if (!code.value.trim()) return ElMessage.warning('请粘贴授权码'); if (await run(() => exchangeSeoBaiduCode({ ...scoped(), code: code.value.trim() }), '授权成功')) code.value = '' }
async function pull() { await run(() => pullSeoAnalytics({ ...scoped(), month: month.value }), '拉取已完成') }
function enabled(key) { return columns.value.some(col => col.key === key) }
function toggle(spec) { columns.value = enabled(spec.key) ? columns.value.filter(col => col.key !== spec.key) : [...columns.value, structuredClone(spec)] }
function move(index, direction) { const other = index + direction; if (other < 0 || other >= columns.value.length) return; [columns.value[index], columns.value[other]] = [columns.value[other], columns.value[index]] }
async function saveTemplate() { await run(() => saveSeoExportTemplate({ ...scoped(), columns: columns.value }), '导出列模板已保存') }
async function resetTemplate() { await run(() => resetSeoExportTemplate(scoped()), '已恢复默认模板') }
function moveReport(index, direction) { reportSections.value = moveReportSection(reportSections.value, index, direction) }
async function saveReportTemplate() {
  if (!validReportSections(reportSections.value)) return ElMessage.error('请至少显示一个章节，并填写有效标题')
  await run(() => saveSeoMonthlyReportTemplate({ ...scoped(), sections: reportSections.value }), '月报章节已保存')
}
async function resetReportTemplate() { await run(() => resetSeoMonthlyReportTemplate(scoped()), '月报章节已恢复默认') }
function moveTdk(index, direction) { tdkSections.value = moveTdkReviewSection(tdkSections.value, index, direction) }
async function saveTdkTemplate() {
  if (!validTdkReviewTemplate(tdkSections.value, tdkColumns.value)) return ElMessage.error('请检查审核稿章节和列设置')
  await run(() => saveSeoTdkReviewTemplate({ ...scoped(), sections: tdkSections.value, columns: tdkColumns.value }), 'TDK 审核稿模板已保存')
}
async function resetTdkTemplate() { await run(() => resetSeoTdkReviewTemplate(scoped()), 'TDK 审核稿模板已恢复默认') }
watch([currentTenantId, siteId], init); watch(month, load); onMounted(init)
</script>

<template>
  <div class="settings">
    <header><div><h2>数据源与导出设置</h2><p>按网站配置客户分析数据，月度 UV/PV 由手动拉取。缺失数据始终显示“无数据”。</p></div><el-select v-model="siteId" placeholder="选择网站" style="width:240px"><el-option v-for="item in sites" :key="item.id" :label="item.name" :value="item.id" /></el-select></header>
    <template v-if="siteId">
      <el-alert title="客户需提供：百度账号模式的统计站点 ID、API Key、Secret Key，并由客户完成授权；也可提供 Refresh Token。商业账号模式需用户名、站点 ID、数据 API Access Token。GA4 需媒体资源 ID 和服务账号 JSON，并在媒体资源访问管理中将服务账号邮箱添加为查看者。GA4 媒体资源时区建议设为 Asia/Shanghai，以对齐自然月。" type="info" :closable="false" show-icon />
      <div class="cards">
        <el-card><template #header><b>百度统计</b></template><el-switch v-model="baiduEnabled" active-text="启用拉取" inactive-text="暂停拉取" :disabled="!canEdit" />
          <el-radio-group v-model="baidu.mode"><el-radio value="account">百度账号授权（推荐）</el-radio><el-radio value="business">百度商业账号 Token</el-radio></el-radio-group>
          <p v-if="modeWillSwitch" class="warning">保存将切换模式并清除另一模式的 Token。</p>
          <ol v-if="baidu.mode === 'account'" class="guide"><li>填写站点 ID、API Key、Secret Key 并保存</li><li>点击 打开百度授权页，用能查看该站点报告的百度账号登录并同意</li><li>复制页面上的授权码，粘贴后点 完成授权</li><li>点 测试连接</li></ol>
          <el-form label-width="115px"><el-form-item label="统计站点 ID"><el-input v-model="baidu.tongji_site_id" /></el-form-item>
            <template v-if="baidu.mode === 'account'"><el-form-item label="API Key"><el-input v-model="baidu.api_key" /></el-form-item><el-form-item label="Secret Key"><el-input v-model="baidu.secret_key" type="password" show-password :placeholder="source('baidu_tongji')?.has_secret_key ? '已保存，留空不修改' : '请输入 Secret Key'" /></el-form-item><el-form-item label="Refresh Token"><el-input v-model="baidu.refresh_token" type="password" show-password :placeholder="source('baidu_tongji')?.refresh_token_set ? '已保存，留空不修改' : '可直接粘贴已有 Token'" /></el-form-item><el-form-item label="授权码"><el-input v-model="code" placeholder="打开授权页后粘贴授权码" /></el-form-item></template>
            <template v-else><el-form-item label="用户名"><el-input v-model="baidu.username" /></el-form-item><el-form-item label="Access Token"><el-input v-model="baidu.access_token" type="password" show-password :placeholder="source('baidu_tongji')?.access_token_set ? '已保存，留空不修改' : '在数据 API 页面获取'" /></el-form-item><p v-if="baidu.token_entered_at && Date.now()-Date.parse(baidu.token_entered_at)>25*86400000" class="warning">Token 已保存超过 25 天，请准备更新（通常 30 天有效）。</p></template></el-form>
          <div class="actions"><el-button v-if="baidu.mode==='account'" @click="authorize">打开百度授权页</el-button><el-button v-if="baidu.mode==='account'" :disabled="!canExchange" @click="exchange">完成授权</el-button><span v-if="baidu.mode==='account' && !canExchange" class="warning">请先保存 Secret Key</span><el-button type="primary" :disabled="!canEdit" :loading="busy" @click="saveBaidu">保存</el-button><el-button :disabled="!canEdit || !source('baidu_tongji')" @click="testConnection('baidu_tongji')">测试连接</el-button><el-button :disabled="!canEdit || !source('baidu_tongji')" @click="clearSaved('baidu_tongji', baidu.mode === 'account' ? ['secret_key','refresh_token','access_token'] : ['access_token'])">清除凭证</el-button><el-button type="danger" plain :disabled="!canEdit || !source('baidu_tongji')" @click="remove('baidu_tongji')">删除配置</el-button></div>
          <p v-if="source('baidu_tongji')?.last_test_at">上次测试：{{ beijingTime(source('baidu_tongji').last_test_at) }}（北京时间） · {{ source('baidu_tongji').last_test_message }}</p>
        </el-card>
        <el-card><template #header><b>GA4</b></template><ol class="guide"><li>填写媒体资源 ID</li><li>上传服务账号 JSON 并保存</li><li>在 GA4 管理-媒体资源访问管理 中将显示的服务账号邮箱添加为查看者</li><li>测试连接</li></ol><el-switch v-model="ga4Enabled" active-text="启用拉取" inactive-text="暂停拉取" :disabled="!canEdit" /><el-form label-width="125px"><el-form-item label="媒体资源 ID"><el-input v-model="ga4.property_id" placeholder="123 或 properties/123" /></el-form-item><el-form-item label="服务账号 JSON"><input type="file" accept=".json,application/json" @change="upload"><span v-if="ga4File">已选文件：{{ ga4File }}（内容不会回显）</span><el-input v-model="ga4Json" type="textarea" :rows="4" :placeholder="source('ga4')?.service_account_email ? '已保存，留空不修改' : '可粘贴 JSON'" /></el-form-item></el-form>
          <p v-if="source('ga4')?.service_account_email">服务账号邮箱：{{ source('ga4').service_account_email }}</p><div class="actions"><el-button type="primary" :disabled="!canEdit" :loading="busy" @click="saveGa4">保存</el-button><el-button :disabled="!canEdit || !source('ga4')" @click="testConnection('ga4')">测试连接</el-button><el-button :disabled="!canEdit || !source('ga4')" @click="clearSaved('ga4', ['service_account_json'])">清除凭证</el-button><el-button type="danger" plain :disabled="!canEdit || !source('ga4')" @click="remove('ga4')">删除配置</el-button></div><p v-if="source('ga4')?.last_test_at">上次测试：{{ beijingTime(source('ga4').last_test_at) }}（北京时间） · {{ source('ga4').last_test_message }}</p>
        </el-card>
      </div>
      <el-card><template #header><b>月度流量</b></template><div class="actions"><el-date-picker v-model="month" type="month" value-format="YYYY-MM" placeholder="选择月份" /><el-button type="primary" :disabled="!canEdit" :loading="busy" @click="pull">拉取</el-button></div><p v-if="month===currentMonth()">本月未结束，数据为截至拉取时。</p><el-table :data="monthly" empty-text="暂无数据"><el-table-column prop="month" label="月份" /><el-table-column label="数据源"><template #default="{row}">{{ row.source==='ga4'?'GA4':'百度统计' }}</template></el-table-column><el-table-column label="UV"><template #default="{row}">{{ metricText(row.uv) }}</template></el-table-column><el-table-column label="PV"><template #default="{row}">{{ metricText(row.pv) }}</template></el-table-column><el-table-column label="状态"><template #default="{row}">{{ statusText(row) }}<span v-if="row.last_error_message && row.status==='ok'">（上次拉取失败：{{ row.last_error_message }}）</span></template></el-table-column><el-table-column label="拉取时间（北京时间）"><template #default="{row}">{{ beijingTime(row.fetched_at) }}</template></el-table-column></el-table></el-card>
      <el-card><template #header><b>导出列模板</b></template><p>选择发布清单列，调整顺序并修改标题。</p><div class="columns"><label v-for="spec in available" :key="spec.key"><el-checkbox :model-value="enabled(spec.key)" @change="toggle(spec)">{{ spec.title }}</el-checkbox></label></div><div v-for="(col,index) in columns" :key="col.key" class="column"><span>{{ col.key }}</span><el-input v-model="col.title" maxlength="30" /><el-button :disabled="index===0" @click="move(index,-1)">上移</el-button><el-button :disabled="index===columns.length-1" @click="move(index,1)">下移</el-button></div><div class="actions"><el-button type="primary" :disabled="!canEdit || !columns.length" @click="saveTemplate">保存</el-button><el-button :disabled="!canEdit" @click="resetTemplate">恢复默认</el-button></div></el-card>
      <el-card><template #header><b>月报章节</b></template><p>选择显示的章节、调整顺序并修改标题。</p><div v-for="(section,index) in reportSections" :key="section.key" class="column"><el-checkbox v-model="section.enabled" :disabled="!canEdit">显示</el-checkbox><span>{{ section.key }}</span><el-input v-model="section.title" maxlength="40" :disabled="!canEdit" /><el-button :disabled="!canEdit || index===0" @click="moveReport(index,-1)">上移</el-button><el-button :disabled="!canEdit || index===reportSections.length-1" @click="moveReport(index,1)">下移</el-button></div><div class="actions"><el-button type="primary" :disabled="!canEdit || busy || !validReportSections(reportSections)" @click="saveReportTemplate">保存</el-button><el-button :disabled="!canEdit || busy" @click="resetReportTemplate">恢复默认</el-button></div></el-card>
      <el-card><template #header><b>TDK 审核稿模板</b></template><p>选择显示的章节、调整顺序并修改标题。</p><div v-for="(section,index) in tdkSections" :key="section.key" class="column"><el-checkbox v-model="section.enabled" :disabled="!canEdit">显示</el-checkbox><span>{{ section.key }}</span><el-input v-model="section.title" maxlength="40" :disabled="!canEdit" /><el-button :disabled="!canEdit || index===0" @click="moveTdk(index,-1)">上移</el-button><el-button :disabled="!canEdit || index===tdkSections.length-1" @click="moveTdk(index,1)">下移</el-button></div><div class="actions"><el-checkbox v-model="tdkColumns.char_counts" :disabled="!canEdit">显示字数</el-checkbox><el-checkbox v-model="tdkColumns.rationale" :disabled="!canEdit">显示说明 / 批注</el-checkbox></div><div class="actions"><el-button type="primary" :disabled="!canEdit || busy || !validTdkReviewTemplate(tdkSections, tdkColumns)" @click="saveTdkTemplate">保存</el-button><el-button :disabled="!canEdit || busy" @click="resetTdkTemplate">恢复默认</el-button></div></el-card>
    </template>
  </div>
</template>
<style scoped>.guide{padding-left:22px;color:#667085;line-height:1.8}.settings{padding:24px;display:grid;gap:18px}header{display:flex;justify-content:space-between;align-items:center}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:16px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.columns{display:flex;gap:12px;flex-wrap:wrap}.column{display:flex;align-items:center;gap:8px;margin:8px 0}.column span{min-width:120px}.column .el-input{max-width:300px}.warning{color:#b45309}p{color:#667085}</style>
