import { createApp, h, ref } from 'vue'
import { createRouter, createWebHashHistory, RouterView } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '../../src/styles/geo-page.css'
import '../../src/styles/geo-dashboard.css'
import '../../src/styles/geo-v2.css'
import client from '../../src/api/client'
import { session } from '../../src/store/session'
import Citations from '../../src/views/geo/GeoCitationsView.vue'
import Visibility from '../../src/views/geo/GeoVisibilityView.vue'
import Editor from '../../src/views/geo/GeoTaskEditorView.vue'
import Tasks from '../../src/views/geo/GeoTasksView.vue'

const counts = ref(0)
const calls = ref(0)
const fault = ref('')
const pendingSave = ref(false)
let failSave = false
let delaySave = false
let releaseSave = null
window.addEventListener('error', (event) => { fault.value = event.message })
window.addEventListener('unhandledrejection', (event) => { fault.value = String(event.reason) })
session.setAuth('LOCAL-FAKE-NO-NETWORK', { id: 9, permissions: { 'geo.content': 'edit' } }, false)
session.setTenants([{ id: 7, name: '测试客户 A' }, { id: 8, name: '测试客户 B' }])
session.setTenant(7)
const question = '工业设备应该如何选型？'
const rows = [1, 2, 3].map((id) => ({
  id, tenant_id: 7, prompt_id: 2, prompt_question: question,
  engine: id === 2 ? 'doubao' : 'deepseek', raw_text: `本地模拟数据 ${id}：建议比较设备参数和维护成本。<script>不得执行</script>`,
  captured_at: '2026-09-05T12:00:00', mentions_brand: false,
  sample_mode: 'openai_compat', sample_kind: 'real', source_label: 'API 采样', simulated: false,
  sampling_method: 'unprimed_json_v2', analysis_status: 'completed',
  cited_urls: ['https://source.example/guide', 'javascript:alert(1)'], competitors: [],
  sentiment: 'unknown', brand_position: 'absent', citation_accuracy: 'unknown',
  note: 'method=unprimed_json_v2 · analysis=completed',
}))
const composition = { total: 3, real: 3, simulated: 0, manual: 0, unknown: 0, prompt_n: 1, engine_n: 2,
  suitable_for_client: false, verdict: '样本不足', verdict_reason: '测试仅有 3 条样本。', label: 'API 采样 3 · 模拟 0 · 人工 0',
  sampling_methods: { unprimed_json_v2: 3 }, needs_review: 0 }
const opportunity = { prompt_id: 2, question, priority: '优先核对', sample_count: 3, sample_ids: [1, 2, 3],
  evidence_version: 'a'.repeat(64), reason: '3 条样本引用第三方，其中 3 条未提及品牌。', next_action: '核验来源，补充品牌事实，再用同一问题复测。',
  evidence: rows.map((row) => ({ snapshot_id: row.id, engine: row.engine, captured_at: row.captured_at,
    mentions_brand: false, urls: ['https://source.example/guide'] })) }
let task = null
const tickets = []
client.defaults.adapter = async (config) => {
  calls.value++
  const path = config.url
  const method = (config.method || 'get').toLowerCase()
  const body = typeof config.data === 'string' ? JSON.parse(config.data) : config.data || {}
  const tenant = Number(config.params?.tenant_id || body.tenant_id || session.tenantId)
  const active = tenant === 7
  let data = { items: [], total: 0 }
  if (path.endsWith('/action-tickets') && method === 'get') {
    data = { items: tickets.filter((t) => t.tenant_id === tenant) }
  } else if (path.endsWith('/action-tickets') && method === 'post') {
    let ticket = tickets.find((t) => t.tenant_id === tenant && t.advice_code === body.advice_code && t.status !== 'done')
    if (!ticket) { ticket = { ...body, id: tickets.length + 1, tenant_id: tenant, status: 'todo' }; tickets.push(ticket) }
    data = ticket
  } else if (/\/action-tickets\/\d+\/execution$/.test(path) && method === 'post') {
    const ticket = tickets.find((t) => t.id === Number(path.split('/').at(-2)) && t.tenant_id === tenant)
    if (!ticket || !active || body.content_task_id !== 100 || !task) throw new Error('内容任务不存在')
    if (body.before_snapshot_ids.some((id) => ![1, 2, 3].includes(id)) || body.after_snapshot_ids.some((id) => ![4, 5, 6].includes(id))) throw new Error('样本不存在或不属于同一问题')
    ticket.content_task_id = 100
    ticket.baseline_snapshot = { prompt_id: 2, samples: body.before_snapshot_ids.map((id) => ({ id })) }
    ticket.progress = { version_no: 1, change_note: body.change_note, samples: body.after_snapshot_ids.map((id) => ({ id })), comparison: {
      engines: [{ engine: 'deepseek', before_count: body.before_snapshot_ids.length, after_count: body.after_snapshot_ids.length, before_rate: 0, after_rate: 1, delta: null }],
      delta: null, note: '本地模拟展示；样本不足，不证明内容修改造成效果。',
    } }
    data = ticket
  } else if (/\/action-tickets\/\d+$/.test(path) && method === 'patch') {
    const ticket = tickets.find((t) => t.id === Number(path.split('/').at(-1)) && t.tenant_id === tenant)
    if (!ticket) throw new Error('工单不存在')
    const record = (check, result, note) => { ticket.evidence = [...(ticket.evidence || []), { at: new Date().toISOString(), check, result, note }].slice(-6) }
    if (body.status === 'blocked' && !body.operation_note?.trim()) throw new Error('请填写受阻原因和需要的协助')
    if (body.manual_pass != null) {
      if (!body.verification_note?.trim()) throw new Error('请填写执行结果与核验依据')
      ticket.status = body.manual_pass ? 'done' : 'todo'
      ticket.last_note = body.verification_note
      ticket.closed_at = body.manual_pass ? new Date().toISOString() : null
      record(null, body.manual_pass ? 'pass' : 'fail', body.verification_note)
    } else {
      if (body.status) { record('workflow.status', body.status, `${ticket.status} → ${body.status}：${body.operation_note || ''}`); ticket.status = body.status; ticket.closed_at = null }
      if ('owner_name' in body || 'due_date' in body) record('workflow.assignment', 'updated', `负责人：${body.owner_name || ticket.owner_name || '未指定'}，截止日期：${body.due_date || '未设置'}`)
      if ('owner_name' in body) ticket.owner_name = body.owner_name
      if ('due_date' in body) ticket.due_date = body.due_date
    }
    data = ticket
  } else if (method === 'post' && path.endsWith('/from-source-opportunity')) {
    if (!active || body.evidence_version !== opportunity.evidence_version) throw new Error('证据已变化，请刷新')
    const created = !task
    if (created) {
      counts.value++
      task = { id: 100, tenant_id: 7, prompt_id: 2, prompt_question: question, title: question,
        business_id: null, status: 'draft', pipeline_step: 'opportunity', target_channels: ['website'],
        brief: { ai_question: question, notes: opportunity.next_action }, source_opportunity: opportunity,
        facts: [], variants: [], article: null, rule_result: null, review: {}, brief_ready: false }
    }
    data = { created, task_id: 100, editor_path: '/geo/tasks/100' }
  } else if (method === 'put' && path === '/api/v1/geo/content-tasks/100/article') {
    if (!active || !task) throw new Error('任务不属于当前客户')
    if (failSave) { failSave = false; throw new Error('本地模拟：正文保存失败') }
    if (delaySave) {
      delaySave = false; pendingSave.value = true
      await new Promise((resolve) => { releaseSave = resolve })
      pendingSave.value = false; releaseSave = null
    }
    task = { ...task, article: { ...task.article, ...body } }
    data = task
  } else if (method === 'patch' && path === '/api/v1/geo/content-tasks/100') {
    if (!active || !task) throw new Error('任务不属于当前客户')
    if (failSave) { failSave = false; throw new Error('本地模拟：保存失败，请重试') }
    if (delaySave) {
      delaySave = false
      pendingSave.value = true
      await new Promise((resolve) => { releaseSave = resolve })
      pendingSave.value = false
      releaseSave = null
    }
    task = { ...task, ...body, source_opportunity: opportunity }
    data = task
  } else if (method !== 'get') {
    throw new Error('本地验收禁止调用此写操作：' + path)
  } else if (path.endsWith('/citation-insights')) {
    data = { items: active ? [{ domain: 'source.example', cite_count: 3, engines: ['deepseek', 'doubao'],
      engine_counts: { deepseek: 2, doubao: 1 }, sample_urls: ['https://source.example/guide'], prompt_count: 1 }] : [],
      source_opportunities: { items: active ? [opportunity] : [], eligible_samples: active ? 3 : 0,
        excluded_samples: { non_api: 0, legacy_method: 0, needs_review: 0, brand_probe_or_missing_prompt: 0, inaccurate_citation: 0 },
        own_domains_configured: true, note: '仅用于本地页面验收，所有接口由内存数据替代。' },
      rates_comparable: true, sample_composition: active ? composition : { total: 0 },
      statistics_note: '模拟接口，不代表线上数据。', excluded_simulated: 0, own_domains: ['brand.example'],
      total_snapshots: active ? 3 : 0, snapshots_with_citations: active ? 3 : 0,
      distinct_cited_domains: active ? 1 : 0, own_domain_cite_rate: active ? 0 : null }
  } else if (path.endsWith('/answer-snapshots')) {
    data = { items: active ? rows : [], sample_composition: composition }
  } else if (path.endsWith('/prompts')) {
    data = { items: active ? [{ id: 2, question, status: 'active' }] : [] }
  } else if (path.endsWith('/tracking-engines')) {
    data = { items: [{ engine_key: 'deepseek', enabled: true }, { engine_key: 'doubao', enabled: true }] }
  } else if (path === '/api/v1/geo/content-tasks/100') {
    if (!active || !task) throw new Error('任务不属于当前客户')
    data = task
  } else if (path === '/api/v1/geo/content-tasks') {
    data = { items: active && task ? [task] : [], total: active && task ? 1 : 0, workbench_counts: { all: active && task ? 1 : 0, draft: active && task ? 1 : 0 } }
  } else if (path.endsWith('/content-brief-catalog')) {
    data = { industries: [], intents: [], content_types: [], info_gaps: [], source_bars: [], required_fields: [] }
  } else if (path.endsWith('/impact')) {
    data = { summary: {}, items: [] }
  }
  return { data: structuredClone(data), status: 200, statusText: 'OK', headers: {}, config }
}
const router = createRouter({ history: createWebHashHistory(), routes: [
  { path: '/', redirect: '/geo/citations' }, { path: '/geo/citations', component: Citations },
  { path: '/geo/visibility/snapshots', component: Visibility }, { path: '/geo/tasks/:taskId', component: Editor },
  { path: '/geo/tasks', component: Tasks },
  { path: '/:pathMatch(.*)*', redirect: '/geo/citations' },
] })
const app = createApp({ setup() { return () => h('div', [
  h('div', { style: 'background:#fff4c2;padding:12px;position:sticky;top:0;z-index:9999' }, [
    h('strong', '本地模拟验收 · 无生产连接 '),
    h('button', { onClick: () => { router.push('/geo/tasks') } }, '工作台'),
    h('button', { onClick: () => {
      if (!task) return
      task = { ...task, status: 'editing', article: { id: 1, title: '客户 A 正文', body_markdown: '客户 A 私有正文，仅供本地验收。', outline: {} } }
      session.setTenant(7); router.push('/geo/tasks/100')
    } }, '载入本地正文样稿'),
    h('button', { onClick: () => { session.setTenant(7); router.push('/geo/citations') } }, '客户 A / 信源'),
    h('button', { onClick: () => { session.setTenant(8); router.push('/geo/citations') } }, '客户 B / 信源'),
    h('button', { onClick: () => { opportunity.evidence_version = 'b'.repeat(64) } }, '使证据过期'),
    h('button', { onClick: () => { failSave = true } }, '下次保存失败'),
    h('button', { onClick: () => { delaySave = true } }, '延迟下次保存'),
    h('button', { onClick: () => { session.setTenant(8) } }, '客户 B / 当前页'),
    h('button', { onClick: () => { releaseSave?.() }, disabled: !pendingSave.value }, '释放保存响应'),
    h('span', pendingSave.value ? ' 保存响应等待中' : ''),
    h('span', ` 已建任务 ${counts.value} · 内存接口调用 ${calls.value}`),
    fault.value ? h('pre', { style: 'color:red' }, fault.value) : null,
  ]), h(RouterView),
]) } })
app.config.errorHandler = (error) => { fault.value = String(error) }
app.use(router).use(ElementPlus).mount('#app')
