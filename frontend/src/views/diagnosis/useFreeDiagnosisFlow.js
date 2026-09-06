import { computed, onScopeDispose, reactive, ref, watch } from 'vue'
import * as diagnosticApi from '../../api/diagnostic'
import { brandDraft, mergeBrandProfile, missingBrandFields } from './brandProfileFields'
import { initialWebsite, validWebsite } from './diagnosisWebsite'

export function useFreeDiagnosisFlow({ tenantId, audit, pageSpeed, brandProfile, brandReady, url, samplingLoading, pageSpeedLoading, sampleQuestions, ensureTenant, api = diagnosticApi, search = window.location.search }) {
  const initial = initialWebsite(search)
  const stage = ref('entry')
  const website = ref(initial.website)
  const error = ref(initial.error)
  const draft = reactive(brandDraft())
  const edited = new Set()
  const editAll = ref(false)
  const missing = computed(() => missingBrandFields(draft))
  const statuses = reactive({ brand:'idle', audit:'idle', sample:'idle', performance:'idle' })
  const errors = reactive({ sample:'', performance:'' })
  let generation = 0
  let sampleRun = 0
  let performanceRun = 0
  let sampleKey = ''
  let performanceKey = ''
  const keyFor = () => `${tenantId.value}:${audit.value?.id}`
  const current = (g, tenant) => g === generation && tenant === tenantId.value
  function reset(value = '') {
    generation++; sampleRun++; performanceRun++
    stage.value = 'entry'; website.value = value; error.value = ''; editAll.value = false
    edited.clear(); Object.assign(draft, brandDraft())
    Object.assign(statuses, {brand:'idle',audit:'idle',sample:'idle',performance:'idle'})
    errors.sample = ''; errors.performance = ''
    samplingLoading.value = false; pageSpeedLoading.value = false
    sampleKey = ''; performanceKey = ''
  }
  function setField(key, value) { draft[key] = value; edited.add(key) }
  async function discover() {
    if (stage.value === 'recognizing') return
    error.value = ''
    try { website.value = validWebsite(website.value) } catch { error.value = '请输入有效的公司官网地址，例如 https://example.com'; return }
    const g = ++generation
    stage.value = 'recognizing'
    if (!tenantId.value && !await ensureTenant()) {
      if (g === generation) { stage.value = 'entry'; error.value = '请先登录并选择有诊断权限的客户。' }
      return
    }
    const tenant = tenantId.value
    if (g !== generation) return
    try {
      const result = await api.discoverGeoBrand({ tenantId:tenant, website:website.value })
      if (!current(g, tenant)) return
      Object.assign(draft, brandDraft({ ...result.brand, website:result.brand?.website || website.value }))
      edited.clear(); editAll.value = false; stage.value = 'confirm'
    } catch (e) {
      if (current(g, tenant)) { error.value = e.message || '企业识别失败，请重试'; stage.value = 'recognition-error' }
    }
  }
  function manual() { Object.assign(draft, brandDraft({website:website.value})); edited.clear(); stage.value = 'confirm' }
  async function confirm() {
    if (stage.value !== 'confirm') return
    if (missing.value.length) { error.value = '请补充必填信息后开始诊断'; return }
    try { draft.website = validWebsite(draft.website) } catch { error.value = '官网地址无效，请修改'; editAll.value = true; return }
    if (!tenantId.value && !await ensureTenant()) { error.value = '当前没有可用的客户身份'; return }
    const g = generation, tenant = tenantId.value
    stage.value = 'saving'; error.value = ''; statuses.brand = 'running'
    try {
      // A failed read must never be treated as an empty profile.
      const existing = await api.fetchGeoAssetProfile(tenant, draft.website)
      if (!current(g, tenant)) return
      if (!existing?.brand || typeof existing.brand !== 'object') throw new Error('旧资料读取结果不完整，已停止保存')
      const payload = mergeBrandProfile(existing.brand || {}, draft, edited)
      const saved = await api.saveGeoBrand({ ...payload, tenant_id:tenant })
      if (!current(g, tenant)) return
      brandProfile.value = saved.brand; brandReady.value = true; url.value = saved.brand.website
      statuses.brand = 'success'
    } catch (e) {
      if (current(g, tenant)) { stage.value = 'confirm'; statuses.brand = 'error'; error.value = `品牌资料未完成保存：${e.message}。草稿已保留，请重试。` }
      return
    }
    await runAudit()
  }
  async function runAudit() {
    if (statuses.audit === 'running') return
    const g = generation, tenant = tenantId.value
    stage.value = 'progress'; statuses.audit = 'running'; error.value = ''
    audit.value = null; pageSpeed.value = null; sampleQuestions.value = ['', '', '']
    statuses.sample = 'idle'; statuses.performance = 'idle'
    try {
      const result = await api.runGeoAudit({ tenantId:tenant, url:url.value, scope:'single' })
      if (!current(g, tenant)) return
      audit.value = result; statuses.audit = 'success'; stage.value = 'report'
    } catch (e) {
      if (current(g, tenant)) { statuses.audit = 'error'; error.value = e.message || '网站诊断失败，请重试' }
    }
  }
  async function sample({ automatic = false } = {}) {
    const record = audit.value
    if (!record?.id || samplingLoading.value) return
    const g = generation, tenant = tenantId.value
    const key = keyFor()
    if (automatic && sampleKey === key) return
    const run = ++sampleRun
    sampleKey = key; samplingLoading.value = true; statuses.sample = 'running'; errors.sample = ''
    try {
      const result = await api.runDeepSeekSample({ tenantId:tenant, auditId:record.id, questions:automatic ? [] : sampleQuestions.value.map(s => s.trim()).filter(Boolean) })
      if (!current(g, tenant) || keyFor() !== key || run !== sampleRun) return
      const value = result.snapshot?.ai_sampling
      if (!value) throw new Error('接口未返回品牌测试结果')
      audit.value = { ...audit.value, snapshot:{...audit.value.snapshot, ai_sampling:value} }
      sampleQuestions.value = (value.results || []).map(r => r.question)
      while (sampleQuestions.value.length < 3) sampleQuestions.value.push('')
      statuses.sample = 'success'
    } catch (e) {
      if (current(g, tenant) && keyFor() === key && run === sampleRun) { statuses.sample = /未启用|未配置|不可用/.test(e.message) ? 'unavailable' : 'error'; errors.sample = e.message }
    } finally {
      if (current(g, tenant) && keyFor() === key && run === sampleRun) samplingLoading.value = false
    }
  }
  async function performance() {
    const record = audit.value
    if (!record || pageSpeedLoading.value) return
    const target = record.final_url || record.url
    if (!target) { statuses.performance = 'unavailable'; return }
    const g = generation, tenant = tenantId.value, key = keyFor(), run = ++performanceRun
    performanceKey = key; pageSpeedLoading.value = true; statuses.performance = 'running'; errors.performance = ''
    try {
      const result = await api.fetchPageSpeedInsights({ tenantId:tenant, url:target, strategy:'mobile' })
      if (!current(g, tenant) || keyFor() !== key || run !== performanceRun) return
      pageSpeed.value = result
      statuses.performance = result.status === 'available' ? 'success' : result.status === 'error' ? 'error' : 'unavailable'
      errors.performance = result.reason || ''
    } catch (e) {
      if (current(g, tenant) && keyFor() === key && run === performanceRun) { statuses.performance = 'error'; errors.performance = e.message; pageSpeed.value = {status:'error',reason:e.message,metrics:{}} }
    } finally {
      if (current(g, tenant) && keyFor() === key && run === performanceRun) pageSpeedLoading.value = false
    }
  }
  watch(() => [tenantId.value, audit.value?.id], ([tenant, id], old = []) => {
    if (!tenant || !id) return
    if (old[1] !== id) { sampleRun++; performanceRun++; samplingLoading.value = false; pageSpeedLoading.value = false }
    statuses.audit = 'success'
    if (audit.value.snapshot?.ai_sampling) statuses.sample = 'success'
    else if (audit.value.ai_enabled && audit.value.snapshot?.audit_mode !== 'competitor') void sample({automatic:true})
    else statuses.sample = 'unavailable'
    if (performanceKey !== keyFor()) void performance()
  })
  watch(tenantId, (next, previous) => { if (previous && next !== previous) reset() })
  onScopeDispose(() => { generation++; sampleRun++; performanceRun++ })
  return { stage, website, error, draft, missing, editAll, statuses, errors, discover, manual, confirm, runAudit, sample, performance, reset, setField,
    showReport:() => { if (audit.value) stage.value = 'report' },
  }
}
