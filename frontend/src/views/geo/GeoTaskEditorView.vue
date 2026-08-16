<script setup>
/**
 * Vue 母稿编辑器 · 第一刀 + 第二刀
 * 一：Brief / 事实 / 生成 / 检查(Score) / AI 审稿
 * 二：渠道稿 / 审校 / 回填 URL / Webhook 推送
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  nextEditorStep,
  pipelineLabel,
  reviewStatusLabel as reviewStatusText,
  taskStatusLabel,
} from '../../utils/geoReportLabels'
import {
  aiReviewGeoContentTask,
  applyGeoContentPatch,
  applyGeoRetrievedFacts,
  bindGeoTaskFacts,
  checkGeoContentTask,
  createGeoVariants,
  decideGeoTaskReview,
  exportGeoVariant,
  fetchGeoBriefCatalog,
  generateGeoContentTask,
  getGeoContentTask,
  fetchGeoContentTaskImpact,
  listGeoChannelAccounts,
  listGeoFacts,
  listGeoPublishingChannels,
  patchGeoContentTask,
  patchGeoVariant,
  publishGeoVariant,
  fetchTaskPushTargets,
  pushGeoVariantBatch,
  pushGeoVariantWebhook,
  retrieveGeoTaskFacts,
  saveGeoArticle,
  formatGeoError,
  submitGeoTaskReview,
  suggestGeoTaskBrief,
  fetchChannelBlueprint,
  waitGeoAsyncJob,
  getGeoAsyncJob,
  listGeoAsyncJobs,
  cancelGeoAsyncJob,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

function toastError(e, fallback) {
  const msg = formatGeoError(e, fallback)
  ElMessage({ type: 'error', message: msg, duration: 6000, showClose: true })
  return msg
}

const route = useRoute()
const router = useRouter()
const { tenantId } = useGeoTenant()
const taskId = computed(() => Number(route.params.taskId))

const loading = ref(false)
const busy = ref('')
const error = ref('')
const task = ref(null)
const allFacts = ref([])
const catalog = ref(null)
const checkResult = ref(null)
const retrievePreview = ref([])
const selectedFactIds = ref([])
const docTab = ref('master')
const channelPick = ref(['website', 'wechat', 'zhihu'])
const reviewNote = ref('')
const publishUrl = ref('')
const publishNote = ref('')
const webhookAccountId = ref(null)
const channelAccounts = ref([])
const publishingChannels = ref([])
const channelBlueprint = ref(null)
const pushTargets = ref([])
const pushSelected = ref([])
const pushBatchBusy = ref(false)
const impact = ref(null)
const impactLoading = ref(false)
const impactWindowDays = ref(14)

const brief = reactive({
  industry: '',
  audience: '',
  intent: '',
  content_type: '',
  cta: '',
  banned_claims: '',
  notes: '',
  ai_question: '',
  not_recommended_reasons: '',
  /** 枚举 key 数组，如 industry_positioning；UI 用中文多选 */
  info_gaps: [],
  recommend_when: '',
  competitors: '',
  must_cover: '',
})

const article = reactive({
  title: '',
  body_markdown: '',
})

const variantEdit = reactive({
  title: '',
  body_markdown: '',
  body_html: '',
})
/** 渠道稿：默认预览 HTML 正稿；源码仅供改写 */
const variantViewMode = ref('preview') // preview | source

const REVIEW_LABELS = {
  none: '未提交',
  pending: '待审',
  approved: '已通过',
  rejected: '已驳回',
}

/** 规则 code → 运营可读名（母稿就绪检查，非正式成稿） */
const CHECK_LABELS = {
  direct_answer: '开篇直接答',
  definition: '定义段',
  faq_min: 'FAQ 问答',
  conclusion_extractable: '可抽取结论',
  numbers_extractable: '可抽取数据',
  comparison_extractable: '可抽取对比',
  howto_extractable: '可抽取步骤',
  updated_at_visible: '更新日期可见',
  author_visible: '作者信息可见',
  sources_footer: '信源页脚',
  facts_bound_min: '事实绑定数量',
  evidence_publishable: '可引用证据',
  channel_variant_ready: '渠道稿已生成',
  fabrication_lint: '编造风险扫描',
}
const SUBSCORE_LABELS = {
  authority: '权威度',
  structure: '结构',
  comparison: '对比覆盖',
  evidence_use: '证据引用',
  gap_coverage: '缺口覆盖',
  extractability: '可抽取性',
  brand_mention: '品牌提及',
}

/** 信息缺口：AI 回答里缺什么、母稿必须用事实补什么（禁止编造） */
const INFO_GAP_FALLBACK = [
  { key: 'industry_positioning', label: '行业定位' },
  { key: 'comparison', label: '竞品对比' },
  { key: 'customer_case', label: '客户案例' },
  { key: 'authority_source', label: '权威来源' },
  { key: 'pricing_transparency', label: '价格透明度' },
  { key: 'risk_compliance', label: '风险合规' },
  { key: 'scenario_fit', label: '场景适配' },
  { key: 'entity_clarity', label: '实体清晰度' },
]
const CHANNEL_CN = {
  website: '官网',
  wechat: '微信',
  zhihu: '知乎',
  bilibili: 'B站',
  toutiao: '头条',
  baijiahao: '百家号',
  douyin: '抖音',
  xiaohongshu: '小红书',
}
const showPassedChecks = ref(false)

function checkLabel(code) {
  return CHECK_LABELS[code] || String(code || '').replace(/_/g, ' ')
}
function channelLabel(key) {
  const k = String(key || '').toLowerCase()
  return CHANNEL_CN[k] || key || '—'
}
function channelListLabel(list) {
  if (!list?.length) return '无'
  return list.map(channelLabel).join('、')
}

function splitCsv(s) {
  return String(s || '')
    .split(/[,，;；]/)
    .map((x) => x.trim())
    .filter(Boolean)
}

function joinCsv(arr) {
  return Array.isArray(arr) ? arr.join(', ') : ''
}

function normalizeKeyList(v) {
  if (Array.isArray(v)) {
    return v.map((x) => String(x || '').trim()).filter(Boolean)
  }
  return splitCsv(v)
}

function applyBriefToForm(b) {
  const x = b || {}
  brief.industry = x.industry || ''
  brief.audience = x.audience || ''
  brief.intent = x.intent || ''
  brief.content_type = x.content_type || ''
  brief.cta = x.cta || ''
  brief.banned_claims = joinCsv(x.banned_claims)
  brief.notes = x.notes || ''
  brief.ai_question = x.ai_question || ''
  brief.not_recommended_reasons = joinCsv(x.not_recommended_reasons)
  brief.info_gaps = normalizeKeyList(x.info_gaps)
  brief.recommend_when = x.recommend_when || ''
  brief.competitors = joinCsv(x.competitors)
  brief.must_cover = joinCsv(x.must_cover)
}

function briefPayload() {
  return {
    industry: brief.industry.trim(),
    audience: brief.audience.trim(),
    intent: brief.intent,
    content_type: brief.content_type,
    cta: brief.cta.trim(),
    banned_claims: splitCsv(brief.banned_claims),
    notes: brief.notes.trim() || null,
    ai_question: brief.ai_question.trim() || null,
    not_recommended_reasons: splitCsv(brief.not_recommended_reasons),
    info_gaps: Array.isArray(brief.info_gaps)
      ? brief.info_gaps.filter(Boolean)
      : splitCsv(brief.info_gaps),
    recommend_when: brief.recommend_when.trim() || null,
    competitors: splitCsv(brief.competitors),
    must_cover: splitCsv(brief.must_cover),
    schema_version: 2,
  }
}

/** Rewrite leaked English outline keys (## definition) into Chinese draft headings. */
function sanitizeDraftHeadings(md) {
  const map = {
    definition: '定义与背景',
    comparison: '关键对比与考量',
    faq: '常见问题',
    conclusion: '结论与建议',
    body: '正文',
    howto: '操作步骤',
  }
  return String(md || '').replace(/^##\s*([A-Za-z_]+)\s*$/gm, (full, key) => {
    const zh = map[String(key).toLowerCase()]
    return zh ? `## ${zh}` : full
  })
}

function applyArticleFromTask(t) {
  const a = t?.article
  article.title = a?.title || t?.title || ''
  article.body_markdown = sanitizeDraftHeadings(a?.body_markdown || '')
}

/** Lightweight MD→HTML for older variants missing body_html (tables + headings). */
function mdToPublishHtmlClient(md) {
  if (!md) return ''
  const esc = (s) =>
    String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
  const inline = (s) => {
    let t = esc(s)
    t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    t = t.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>')
    t = t.replace(/`([^`]+)`/g, '<code>$1</code>')
    return t
  }
  const lines = String(md).replace(/\r\n/g, '\n').split('\n')
  const out = []
  let i = 0
  const isSep = (ln) => {
    const s = ln.trim()
    if (!s.includes('|')) return false
    return s
      .replace(/^\|/, '')
      .replace(/\|$/, '')
      .split('|')
      .every((c) => /^:?-{3,}:?$/.test(c.trim()))
  }
  const splitRow = (ln) =>
    ln
      .trim()
      .replace(/^\|/, '')
      .replace(/\|$/, '')
      .split('|')
      .map((c) => c.trim())
  while (i < lines.length) {
    const raw = lines[i]
    const s = raw.trim()
    if (!s) {
      i += 1
      continue
    }
    if (s.includes('|') && i + 1 < lines.length && isSep(lines[i + 1])) {
      const header = splitRow(s)
      i += 2
      const rows = []
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
        if (!isSep(lines[i])) rows.push(splitRow(lines[i]))
        i += 1
      }
      const th = header.map((h) => `<th>${inline(h)}</th>`).join('')
      const trs = rows
        .map((r) => {
          const cells = [...r, ...Array(header.length).fill('')].slice(0, header.length)
          return `<tr>${cells.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`
        })
        .join('')
      out.push(
        `<table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;margin:12px 0;"><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table>`,
      )
      continue
    }
    const hm = s.match(/^(#{1,3})\s+(.+)$/)
    if (hm) {
      const lv = hm[1].length
      out.push(`<h${lv}>${inline(hm[2])}</h${lv}>`)
      i += 1
      continue
    }
    const um = s.match(/^[-*+]\s+(.+)$/)
    if (um) {
      const items = [um[1]]
      i += 1
      while (i < lines.length && /^[-*+]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*+]\s+/, ''))
        i += 1
      }
      out.push(`<ul>${items.map((x) => `<li>${inline(x)}</li>`).join('')}</ul>`)
      continue
    }
    // paragraph: gather until blank
    const para = [s]
    i += 1
    while (i < lines.length && lines[i].trim() && !lines[i].trim().startsWith('#') && !lines[i].includes('|') && !/^[-*+]\s+/.test(lines[i].trim())) {
      para.push(lines[i].trim())
      i += 1
    }
    out.push(`<p>${inline(para.join(' '))}</p>`)
  }
  return `<div class="geo-channel-article" style="font-size:16px;line-height:1.75;color:#1f2937;">${out.join('\n')}</div>`
}

function resolveVariantHtml(v) {
  if (!v) return ''
  const fromApi = v.body_html || v.adapt_meta?.body_html
  if (fromApi && String(fromApi).includes('<')) return fromApi
  return mdToPublishHtmlClient(sanitizeDraftHeadings(v.body_markdown || ''))
}

function applyVariantFromTask() {
  if (docTab.value === 'master') return
  const v = (task.value?.variants || []).find((x) => x.channel === docTab.value)
  variantEdit.title = v?.title || ''
  variantEdit.body_markdown = sanitizeDraftHeadings(v?.body_markdown || '')
  variantEdit.body_html = resolveVariantHtml(v)
  // 正式稿默认看预览；母稿保持源码
  if (v && (v.body_html || v.adapt_meta?.body_html || v.adapt_meta?.delivery === 'html_publish_ready')) {
    variantViewMode.value = 'preview'
  }
}

function onDocTabChange(name) {
  docTab.value = name
  applyVariantFromTask()
  if (name !== 'master') variantViewMode.value = 'preview'
}

/** Bump to ignore stale load() completions (prevents wiping AI-suggested brief). */
let loadGeneration = 0
/** When true, load/refresh must not overwrite local Brief form until user saves/discards. */
const briefLocalDraft = ref(false)
const briefSuggestHint = ref('')

async function load() {
  if (!tenantId.value || !taskId.value) {
    error.value = '缺少租户或任务 ID'
    return
  }
  const gen = ++loadGeneration
  loading.value = true
  error.value = ''
  try {
    if (!catalog.value) {
      catalog.value = await fetchGeoBriefCatalog()
    }
    const [t, factsRes, chRes, accRes] = await Promise.all([
      getGeoContentTask(tenantId.value, taskId.value),
      listGeoFacts(tenantId.value, { status: 'active' }),
      listGeoPublishingChannels(tenantId.value, false),
      listGeoChannelAccounts(tenantId.value),
    ])
    // Stale load: a newer load or AI suggest already owns the form
    if (gen !== loadGeneration) return
    const bid = t.business_id
    allFacts.value = (factsRes.items || [])
      .filter((f) => !bid || !f.business_id || f.business_id === bid)
      .map((f) => ({ ...f, id: Number(f.id) }))
    publishingChannels.value = chRes.items || []
    channelAccounts.value = accRes.items || []
    if (!webhookAccountId.value && channelAccounts.value.length) {
      webhookAccountId.value = channelAccounts.value[0].id
    }
    loadImpact()
    if (t.target_channels?.length) {
      channelPick.value = [...t.target_channels]
    }
    // Never clobber an in-progress AI Brief draft with empty server brief
    applyTaskPayload(t, { skipBrief: briefLocalDraft.value || busy.value === 'suggest' })
    await loadPushTargets()
    if (
      (t.status === 'facts_bound' || (t.pipeline_step && t.pipeline_step !== 'opportunity')) &&
      !(t.facts || []).length
    ) {
      if (gen === loadGeneration) await refreshTaskDetail({ skipBrief: true })
    }
    if (docTab.value !== 'master') {
      const still = (task.value?.variants || []).some((v) => v.channel === docTab.value)
      if (!still) docTab.value = 'master'
    }
    applyVariantFromTask()
    await resumeActiveJob()
    if (task.value?.rule_result) {
      const rr = task.value.rule_result
      checkResult.value = {
        ready: rr.ready,
        checks: rr.checks || [],
        geo_score: rr.geo_score,
        geo_subscores: rr.geo_subscores,
        geo_actions: rr.geo_actions || [],
        ai_review: rr.ai_review,
        // Keep stored fix patches so rail buttons survive reload
        patches: rr.patches || [],
      }
    }
  } catch (e) {
    if (gen !== loadGeneration) return
    error.value = e.message || '加载失败'
    task.value = null
  } finally {
    if (gen === loadGeneration) loading.value = false
  }
}

async function saveBrief() {
  busy.value = 'brief'
  try {
    task.value = await patchGeoContentTask(tenantId.value, taskId.value, {
      brief: briefPayload(),
    })
    applyBriefToForm(task.value.brief)
    briefLocalDraft.value = false
    briefSuggestHint.value = ''
    ElMessage.success('Brief 已保存')
  } catch (e) {
    toastError(e, '保存 Brief 失败')
  } finally {
    busy.value = ''
  }
}

function briefRequiredEmpty() {
  return !(
    brief.industry?.trim() ||
    brief.audience?.trim() ||
    brief.intent ||
    brief.content_type ||
    brief.cta?.trim()
  )
}

async function suggestBrief() {
  busy.value = 'suggest'
  error.value = ''
  briefSuggestHint.value = '正在请求 AI 建议…'
  // Invalidate in-flight loads so they cannot wipe the form after we fill it
  loadGeneration += 1
  try {
    if (!tenantId.value || !taskId.value) {
      const msg = '缺少租户或任务 ID，无法建议 Brief'
      error.value = msg
      briefSuggestHint.value = msg
      ElMessage.error(msg)
      return
    }
    // Empty form → overwrite so merge does not keep schema-normalized blanks
    const overwrite = briefRequiredEmpty()
    const res = await suggestGeoTaskBrief(tenantId.value, taskId.value, {
      overwrite,
      use_llm: true,
    })
    const sb =
      res?.suggested_brief && typeof res.suggested_brief === 'object'
        ? res.suggested_brief
        : res?.brief && typeof res.brief === 'object'
          ? res.brief
          : null
    if (!sb) {
      const msg =
        'AI 建议接口未返回 suggested_brief。请检查网络/鉴权，或到 AI 设置确认 Key 后重试。'
      error.value = msg
      briefSuggestHint.value = msg
      ElMessage({ type: 'error', message: msg, duration: 8000, showClose: true })
      return
    }
    applyBriefToForm(sb)
    briefLocalDraft.value = true
    const filled = [
      brief.industry,
      brief.audience,
      brief.intent,
      brief.content_type,
      brief.cta,
    ].filter((x) => String(x || '').trim()).length
    if (filled === 0) {
      const msg =
        '建议已返回但必填字段仍为空（可能被空 Brief 合并吞掉）。请再点一次「AI 建议」，或手动填写。'
      error.value = msg
      briefSuggestHint.value = msg
      ElMessage.error(msg)
      // one automatic retry with overwrite=true
      try {
        const res2 = await suggestGeoTaskBrief(tenantId.value, taskId.value, {
          overwrite: true,
          use_llm: true,
        })
        if (res2?.suggested_brief) {
          applyBriefToForm(res2.suggested_brief)
          briefLocalDraft.value = true
        }
      } catch {
        /* keep first error */
      }
      const filled2 = [
        brief.industry,
        brief.audience,
        brief.intent,
        brief.content_type,
        brief.cta,
      ].filter((x) => String(x || '').trim()).length
      if (filled2 === 0) return
    }
    const mode = res.used_llm ? 'LLM' : '启发式'
    const rich = Math.round(Number(res.strategy_richness || 0) * 100)
    const msg = `已填入建议（未保存）· ${mode} · 策略 ${rich}% · 必填 ${Math.max(filled, 1)}/5 · 请点「保存 Brief」落库`
    briefSuggestHint.value = msg
    error.value = ''
    ElMessage({ type: 'success', message: msg, duration: 6000, showClose: true })
  } catch (e) {
    const msg = toastError(e, '建议 Brief 失败')
    error.value = msg
    briefSuggestHint.value = msg
  } finally {
    busy.value = ''
  }
}

function coerceFactIds(list) {
  return Array.from(
    new Set(
      (list || [])
        .map((x) => {
          if (x && typeof x === 'object') return Number(x.id ?? x.fact_id)
          return Number(x)
        })
        .filter((n) => Number.isFinite(n) && n > 0),
    ),
  )
}

function applyTaskPayload(t, opts = {}) {
  if (!t) return t
  const skipBrief = Boolean(opts.skipBrief)
  // normalize fact id types so el-select / bound list stay consistent
  if (Array.isArray(t.facts)) {
    t.facts = t.facts.map((f) => ({ ...f, id: Number(f.id) }))
  } else {
    t.facts = []
  }
  task.value = t
  selectedFactIds.value = t.facts.map((f) => Number(f.id))
  if (!skipBrief) {
    applyBriefToForm(t.brief)
  }
  applyArticleFromTask(t)
  return t
}

async function refreshTaskDetail(opts = {}) {
  const t = await getGeoContentTask(tenantId.value, taskId.value)
  return applyTaskPayload(t, opts)
}

/** Always PUT then GET so UI bound count never depends on a partial response. */
async function bindAndRefresh(ids, successPrefix = '已绑定') {
  const clean = coerceFactIds(ids)
  if (!clean.length) {
    const msg = '请先在下拉框中勾选至少 1 条事实，再点「保存绑定」'
    error.value = msg
    ElMessage.warning(msg)
    return 0
  }
  await bindGeoTaskFacts(tenantId.value, taskId.value, clean)
  // Always re-fetch detail — never trust only the PUT body for facts[]
  let t = await refreshTaskDetail()
  let bound = (t?.facts || []).length
  if (bound === 0) {
    // rare race: one more pull
    await new Promise((r) => setTimeout(r, 200))
    t = await refreshTaskDetail()
    bound = (t?.facts || []).length
  }
  if (bound === 0) {
    const msg =
      `绑定请求已发送（提交 ${clean.length} 个 id）但任务仍显示 0 条。请硬刷新页面；若仍失败请确认 Vite 代理到 :8000 且 API 已重启。`
    error.value = msg
    ElMessage.error(msg)
    return 0
  }
  ElMessage.success(`${successPrefix} ${bound} 条事实`)
  error.value = ''
  return bound
}

async function saveFacts() {
  busy.value = 'facts'
  error.value = ''
  try {
    await bindAndRefresh(selectedFactIds.value, '已绑定')
  } catch (e) {
    const msg = toastError(e, '绑定失败')
    error.value = msg
  } finally {
    busy.value = ''
  }
}

/** Unblock B3: bind first N verified active facts without relying on retrieve. */
async function bindTopVerified(n = 3) {
  const verified = (allFacts.value || [])
    .filter((f) => f.trust_level === 'verified' && (f.status === 'active' || !f.status))
    .map((f) => Number(f.id))
    .filter((id) => Number.isFinite(id) && id > 0)
  if (verified.length < n) {
    const msg = `库中 verified 事实不足 ${n} 条（当前 ${verified.length}），请先在事实库核验`
    error.value = msg
    ElMessage.warning(msg)
    return
  }
  const pick = verified.slice(0, Math.max(n, 3))
  selectedFactIds.value = pick
  busy.value = 'facts'
  error.value = ''
  try {
    await bindAndRefresh(pick, '已绑定 verified')
  } catch (e) {
    const msg = toastError(e, '绑定失败')
    error.value = msg
  } finally {
    busy.value = ''
  }
}

async function retrieveFacts() {
  busy.value = 'retrieve'
  error.value = ''
  retrievePreview.value = []
  try {
    // Brief patch is best-effort; do not block retrieve if it fails
    try {
      await patchGeoContentTask(tenantId.value, taskId.value, { brief: briefPayload() })
    } catch (pe) {
      console.warn('retrieve: brief patch skipped', pe)
    }
    const res = await retrieveGeoTaskFacts(tenantId.value, taskId.value, {
      limit: 8,
      verified_only: false,
      auto_bind: false,
    })
    // Support both {items:[{fact_id}]} and accidental nested shapes
    let items = Array.isArray(res?.items) ? res.items : []
    if (!items.length && Array.isArray(res?.results)) items = res.results
    items = items
      .map((x) => ({
        ...x,
        fact_id: Number(x.fact_id ?? x.id),
        title: x.title || x.fact_title || '',
        score: x.score,
        trust_level: x.trust_level,
      }))
      .filter((x) => Number.isFinite(x.fact_id) && x.fact_id > 0)
    retrievePreview.value = items
    const meta = res?.query_meta || {}
    if (!items.length) {
      // Client-side soft fallback: rank local allFacts by simple keyword overlap
      const q = [
        task.value?.prompt_question || '',
        brief.ai_question || '',
        brief.must_cover || '',
        brief.industry || '',
      ]
        .join(' ')
        .toLowerCase()
      const local = (allFacts.value || [])
        .map((f) => {
          const hay = `${f.title || ''} ${f.statement || ''} ${f.source_name || ''}`.toLowerCase()
          let score = f.trust_level === 'verified' ? 1 : 0
          if (q) {
            for (const tok of q.split(/\s+/).filter((t) => t.length >= 2).slice(0, 20)) {
              if (hay.includes(tok)) score += tok.length >= 2 ? 2 : 1
            }
          }
          return {
            fact_id: Number(f.id),
            title: f.title,
            score,
            trust_level: f.trust_level,
            reasons: ['local_fallback'],
          }
        })
        .filter((x) => x.fact_id > 0)
        .sort((a, b) => b.score - a.score || a.fact_id - b.fact_id)
        .slice(0, 8)
      if (local.length) {
        retrievePreview.value = local
        const ids = local.map((x) => x.fact_id)
        selectedFactIds.value = Array.from(
          new Set([...(selectedFactIds.value || []).map(Number), ...ids]),
        )
        const msg =
          `API 召回 0 条，已用本地库兜底 ${local.length} 条候选（已勾选）。请点「绑定召回 Top」或「保存绑定」。` +
          (meta.algorithm ? `（API 算法 ${meta.algorithm}）` : '')
        ElMessage.warning(msg)
        error.value = msg
      } else {
        const msg =
          '召回无候选：库中也无可用事实。请先在事实库创建/核验至少 3 条。' +
          (meta.tokens ? `（分词：${(meta.tokens || []).slice(0, 8).join('、')}）` : '')
        ElMessage.warning(msg)
        error.value = msg
      }
    } else {
      const ids = coerceFactIds(items.map((x) => x.fact_id))
      selectedFactIds.value = Array.from(
        new Set([...(selectedFactIds.value || []).map(Number), ...ids]),
      )
      ElMessage.success(
        `召回 ${items.length} 条候选（已勾选）。点「绑定召回 Top」写入任务，或「保存绑定」。`,
      )
      error.value = ''
    }
  } catch (e) {
    const raw = formatGeoError(e, '召回失败')
    const msg =
      /not found|404/i.test(raw)
        ? '召回接口 404：请重启 uvicorn（:8000 / :8011）加载最新 retrieve-facts 路由后再试'
        : raw
    error.value = msg
    ElMessage({ type: 'error', message: msg, duration: 8000, showClose: true })
  } finally {
    busy.value = ''
  }
}

async function applyRetrieveTop() {
  let ids = coerceFactIds(retrievePreview.value.map((x) => x.fact_id))
  if (!ids.length) {
    await retrieveFacts()
    ids = coerceFactIds(retrievePreview.value.map((x) => x.fact_id))
  }
  if (!ids.length) {
    // last resort: verified from library
    ids = (allFacts.value || [])
      .filter((f) => f.trust_level === 'verified')
      .slice(0, 8)
      .map((f) => Number(f.id))
      .filter(Boolean)
  }
  if (!ids.length) {
    ElMessage.warning(
      '仍无召回候选。请先点「召回」，或「一键绑 3 条 verified」，或手动勾选后「保存绑定」',
    )
    return
  }
  busy.value = 'apply'
  error.value = ''
  try {
    await applyGeoRetrievedFacts(tenantId.value, taskId.value, ids)
    const t = await refreshTaskDetail()
    const bound = (t?.facts || []).length
    if (bound === 0) {
      // fallback to PUT path
      await bindAndRefresh(ids, '已绑定召回')
    } else {
      ElMessage.success(`已绑定召回事实 ${bound} 条`)
      error.value = ''
    }
  } catch (e) {
    // apply path failed — try PUT
    try {
      await bindAndRefresh(ids, '已绑定')
    } catch (e2) {
      const msg = toastError(e2, '绑定失败')
      error.value = msg
    }
  } finally {
    busy.value = ''
  }
}

function validateBeforeGenerate() {
  const b = briefPayload()
  const missing = []
  if (!b.industry) missing.push('行业')
  if (!b.audience) missing.push('受众')
  if (!b.intent) missing.push('意图')
  if (!b.content_type) missing.push('内容类型')
  if (!b.cta) missing.push('CTA')
  if (missing.length) {
    return `Brief 缺少：${missing.join('、')}。请填齐并保存 Brief 后再生成`
  }
  const nBound = (task.value?.facts || []).length
  const nSelected = selectedFactIds.value.length
  if (nBound < 3 && nSelected < 3) {
    return '生成前至少绑定 3 条事实卡（建议已核验）。请在左侧选择事实并点「保存绑定」'
  }
  if (nBound < 3 && nSelected >= 3) {
    return '已选事实尚未保存绑定，请先点「保存绑定」再生成'
  }
  const verified = (task.value?.facts || []).filter((f) => f.trust_level === 'verified')
  if (verified.length < 3) {
    // soft warning path: still allow API to enforce exact rule (eligible may differ)
    // but surface if clearly short on verified
    const anyUnverified = (task.value?.facts || []).some((f) => f.trust_level !== 'verified')
    if (anyUnverified || verified.length === 0) {
      return null // let API return precise evidence error
    }
  }
  return null
}

const generateHint = ref('')
const activeJob = ref(null)

function jobStorageKey() {
  return `geo_async_job_${tenantId.value || 0}_${taskId.value || 0}`
}

function persistJobId(id) {
  if (id) sessionStorage.setItem(jobStorageKey(), String(id))
  else sessionStorage.removeItem(jobStorageKey())
}

const sentenceCites = computed(
  () =>
    task.value?.article?.outline?.sentence_citations ||
    task.value?.article?.generation_meta?.sentence_citations ||
    [],
)

const jobLive = computed(() =>
  ['pending', 'running'].includes(activeJob.value?.status),
)

async function resumeActiveJob() {
  if (!tenantId.value || !taskId.value) return
  try {
    const stored = Number(sessionStorage.getItem(jobStorageKey()) || 0)
    const listed = await listGeoAsyncJobs(tenantId.value, {
      ref_type: 'content_task',
      ref_id: taskId.value,
      limit: 5,
    }).catch(() => ({ items: [] }))
    const open = (listed.items || []).find((j) =>
      ['pending', 'running'].includes(j.status),
    )
    const jobId = open?.id || stored
    if (!jobId) return
    const job = await getGeoAsyncJob(tenantId.value, jobId)
    activeJob.value = job
    if (['pending', 'running'].includes(job.status)) {
      persistJobId(job.id)
      generateHint.value = job.progress_label || `后台任务 #${job.id} ${job.status}`
      busy.value = job.kind === 'create_variants' ? 'variants' : 'generate'
      followJob(job.id)
    } else {
      persistJobId(null)
    }
  } catch {
    /* ignore */
  }
}

async function followJob(jobId) {
  persistJobId(jobId)
  try {
    const job = await waitGeoAsyncJob(tenantId.value, jobId, {
      intervalMs: 2000,
      maxMs: 180000,
      onTick: (j) => {
        activeJob.value = j
        if (j.cancel_requested) {
          generateHint.value = '已请求取消，等待当前步骤结束…'
        } else {
          generateHint.value =
            j.progress_label || `后台任务 #${j.id} ${j.status}`
        }
      },
    })
    activeJob.value = job
    if (job.status === 'failed') throw new Error(job.error || '后台任务失败')
    if (job.status === 'cancelled') {
      generateHint.value = '已取消'
      persistJobId(null)
      return job
    }
    persistJobId(null)
    return job
  } finally {
    if (busy.value === 'generate' || busy.value === 'variants') busy.value = ''
  }
}

async function cancelActiveJob() {
  if (!activeJob.value?.id) return
  try {
    activeJob.value = await cancelGeoAsyncJob(tenantId.value, activeJob.value.id)
    generateHint.value = '已请求取消'
    ElMessage.info('已请求取消，正在跑的模型调用结束后会停')
  } catch (e) {
    toastError(e, '取消失败')
  }
}

async function generate() {
  error.value = ''
  generateHint.value = '正在生成母稿…'
  const pre = validateBeforeGenerate()
  if (pre) {
    error.value = pre
    generateHint.value = pre
    ElMessage({ type: 'error', message: pre, duration: 6000, showClose: true })
    return
  }
  busy.value = 'generate'
  try {
    await patchGeoContentTask(tenantId.value, taskId.value, { brief: briefPayload() })
    generateHint.value = '已提交后台生成，请稍候…'
    const gen = await generateGeoContentTask(tenantId.value, taskId.value, {
      runAsync: true,
    })
    let payload = gen
    if (gen?.async && gen?.job?.id) {
      activeJob.value = gen.job
      persistJobId(gen.job.id)
      ElMessage.info(`生成任务 #${gen.job.id} 排队中，可刷新页面稍后再看`)
      const job = await followJob(gen.job.id)
      if (job?.status === 'failed') {
        throw new Error(job.error || '后台生成失败')
      }
      if (job?.status === 'cancelled') return
      payload = await getGeoContentTask(tenantId.value, taskId.value)
    }
    applyTaskPayload(payload)
    docTab.value = 'master'
    const bodyLen = (article.body_markdown || '').length
    const st = payload?.status || task.value?.status || '—'
    error.value = ''
    const msg =
      bodyLen > 0
        ? `母稿已生成（${bodyLen} 字）· 状态 ${st}` +
          (st === 'needs_fix' ? ' · 请点「检查就绪」并用补丁修齐规则' : '')
        : `生成返回成功但正文为空 · 状态 ${st}`
    generateHint.value = msg
    if (bodyLen > 0) {
      ElMessage({
        type: st === 'needs_fix' ? 'warning' : 'success',
        message: msg,
        duration: 8000,
        showClose: true,
      })
    } else {
      ElMessage({ type: 'error', message: msg, duration: 8000, showClose: true })
    }
  } catch (e) {
    const msg = toastError(e, '生成失败')
    error.value = msg
    generateHint.value = msg
  } finally {
    busy.value = ''
  }
}

async function saveArticleBody() {
  if (!article.title.trim() || !article.body_markdown.trim()) {
    ElMessage.warning('标题与正文不能为空')
    return
  }
  busy.value = 'save'
  try {
    const outline = task.value?.article?.outline || {}
    task.value = await saveGeoArticle(tenantId.value, taskId.value, {
      title: article.title.trim(),
      body_markdown: article.body_markdown,
      outline,
    })
    applyArticleFromTask(task.value)
    ElMessage.success('母稿已保存')
  } catch (e) {
    toastError(e, '保存失败')
  } finally {
    busy.value = ''
  }
}

async function runCheck() {
  busy.value = 'check'
  try {
    const res = await checkGeoContentTask(tenantId.value, taskId.value, false)
    checkResult.value = res
    if (res.task) {
      task.value = res.task
      applyArticleFromTask(res.task)
    }
    ElMessage.success(
      res.ready
        ? `规则就绪 · Score ${res.geo_score ?? '—'}`
        : `尚未就绪 · Score ${res.geo_score ?? '—'}`,
    )
  } catch (e) {
    toastError(e, '检查失败')
  } finally {
    busy.value = ''
  }
}

async function runAiReview() {
  busy.value = 'review'
  try {
    const res = await aiReviewGeoContentTask(tenantId.value, taskId.value, {
      persist: true,
    })
    if (res.task) task.value = res.task
    const rr = task.value?.rule_result || {}
    checkResult.value = {
      ...(checkResult.value || {}),
      ai_review: res.ai_review,
      checks: rr.checks || checkResult.value?.checks || [],
      ready: rr.ready,
      geo_score: rr.geo_score ?? checkResult.value?.geo_score,
      geo_subscores: rr.geo_subscores || checkResult.value?.geo_subscores,
      geo_actions: rr.geo_actions || checkResult.value?.geo_actions || [],
      patches: rr.patches || checkResult.value?.patches || [],
    }
    ElMessage.success(res.ai_review?.summary || '审稿完成')
  } catch (e) {
    toastError(e, '审稿失败')
  } finally {
    busy.value = ''
  }
}

async function applyPatch(code) {
  busy.value = 'patch'
  error.value = ''
  const beforeLen = (article.body_markdown || '').length
  try {
    // Always edit master draft when applying structural patches
    docTab.value = 'master'
    const res = await applyGeoContentPatch(tenantId.value, taskId.value, code)
    // Prefer explicit article on response; fall back to task.article then re-GET
    let art = res.article || res.task?.article || null
    if (res.task) {
      applyTaskPayload(res.task)
    }
    if (art?.body_markdown != null) {
      article.title = art.title || article.title
      article.body_markdown = sanitizeDraftHeadings(art.body_markdown)
    } else {
      const t = await refreshTaskDetail()
      art = t?.article || null
    }
    const afterLen = (article.body_markdown || '').length
    const bodyChanged =
      res.body_changed === true ||
      afterLen !== beforeLen ||
      (res.body_len_after != null && res.body_len_before != null && res.body_len_after !== res.body_len_before)

    checkResult.value = {
      ready: res.ready,
      checks: res.checks || [],
      patches: res.patches || [],
      lint: res.lint,
      blocks: res.blocks,
      geo_score: res.geo_score,
      geo_subscores: res.geo_subscores,
      geo_actions: res.geo_actions || [],
      ai_review: checkResult.value?.ai_review,
    }

    if (!bodyChanged) {
      const msg = `补丁 ${code} 返回成功但正文长度未变化（${beforeLen}→${afterLen}）。请硬刷新后重试。`
      error.value = msg
      ElMessage.error(msg)
      return
    }

    const target = (res.checks || []).find((c) => c.code === code)
    const effective = res.effective !== false && (target ? target.passed : true)
    const scorePart =
      res.geo_score != null ? ` · Score ${res.geo_score}/100` : ''
    if (effective) {
      ElMessage.success(
        `已应用补丁 ${code}（正文 ${beforeLen}→${afterLen} 字${scorePart}，规则已通过）`,
      )
    } else {
      ElMessage.warning(
        `已写入补丁 ${code}（正文 ${beforeLen}→${afterLen} 字${scorePart}），但该规则仍未通过，请检查插入内容或再点检查`,
      )
    }
    error.value = ''
  } catch (e) {
    toastError(e, '补丁失败')
  } finally {
    busy.value = ''
  }
}

async function retryFailedVariants() {
  const keys = failedVariantItems.value.map((f) => f.channel).filter(Boolean)
  if (!keys.length) {
    ElMessage.warning('没有失败渠道可重试')
    return
  }
  channelPick.value = [...new Set([...channelPick.value, ...keys])]
  const keep = channelPick.value
  channelPick.value = keys
  try {
    await genVariants()
  } finally {
    channelPick.value = [...new Set([...keep, ...channelPick.value])]
  }
}

async function genVariants() {
  if (!channelPick.value.length) {
    ElMessage.warning('请至少勾选一个渠道')
    return
  }
  busy.value = 'variants'
  try {
    let t = await createGeoVariants(tenantId.value, taskId.value, channelPick.value, {
      useLlm: true,
      runAsync: true,
    })
    if (t?.async && t?.job?.id) {
      activeJob.value = t.job
      persistJobId(t.job.id)
      ElMessage.info(`渠道稿任务 #${t.job.id} 排队中…`)
      const job = await followJob(t.job.id)
      if (job?.status === 'cancelled') return
      if (job.status === 'failed') {
        throw new Error(job.error || '渠道稿后台生成失败')
      }
      t = await getGeoContentTask(tenantId.value, taskId.value)
      if (job.result_meta?.variant_polish) {
        t = { ...t, variant_polish: job.result_meta.variant_polish }
      }
    }
    applyTaskPayload(t)
    if (channelPick.value[0]) {
      docTab.value = channelPick.value[0]
      applyVariantFromTask()
    }
    // Backend re-scores after create; pull into checkResult so channel_variant_ready updates
    const rr = t?.rule_result
    if (rr?.checks) {
      checkResult.value = {
        ...(checkResult.value || {}),
        ready: rr.ready,
        checks: rr.checks,
        geo_score: rr.geo_score ?? checkResult.value?.geo_score,
        geo_subscores: rr.geo_subscores || checkResult.value?.geo_subscores,
        geo_actions: rr.geo_actions || checkResult.value?.geo_actions || [],
        patches: checkResult.value?.patches || [],
      }
    }
    // Always re-check so patches/score stay in sync with latest master + variants
    try {
      const res = await checkGeoContentTask(tenantId.value, taskId.value, false)
      checkResult.value = res
      if (res.task) applyTaskPayload(res.task)
    } catch {
      /* keep variant success even if re-check fails */
    }
    applyVariantFromTask()
    variantViewMode.value = 'preview'
    const polish = t?.variant_polish || {}
    const llmN = polish.llm ?? 0
    const fbN = polish.fallback ?? 0
    const rejN = polish.rejected ?? (polish.failed || []).length
    const failMsg = (polish.failed || [])
      .slice(0, 2)
      .map((f) => `${channelLabel(f.channel)}：${(f.issues || [f.message])[0] || '未过门控'}`)
      .join('；')
    if (llmN && !fbN && !rejN) {
      ElMessage.success(
        `已过完整文章硬门控（${llmN} 路）。可预览/复制 HTML 正稿。`,
      )
    } else if (llmN && (fbN || rejN)) {
      ElMessage.warning(
        `过门控 ${llmN} 路；规则裁剪 ${fbN}；硬拦 ${rejN}。${failMsg ? ' ' + failMsg : ''} 请对失败渠道重试。`,
      )
    } else if (rejN && !llmN) {
      ElMessage.error(
        `全部未过完整文章硬门控，未保存伪正稿。${failMsg || '请加长母稿后重生成。'}`,
      )
    } else {
      ElMessage.warning(
        `仅规则裁剪稿，未过发布门控。请配置 AI 后重生成；提纲体/过短会被拦截。`,
      )
    }
  } catch (e) {
    toastError(e, '生成渠道稿失败（未过完整文章门控则不会保存伪正稿）')
  } finally {
    busy.value = ''
  }
}

const currentVariantMeta = computed(() => {
  if (docTab.value === 'master') return null
  const v = (task.value?.variants || []).find((x) => x.channel === docTab.value)
  return v?.adapt_meta || null
})
/** 仅 quality===publish_ready 且无编造风险才标「可发布」 */
const isPublishReadyVariant = computed(() => {
  const m = currentVariantMeta.value
  if (!m) return false
  if (m.publishable === false) return false
  const q = m.quality || ''
  if (q !== 'publish_ready' || m.delivery !== 'html_publish_ready') return false
  if ((failedChecks.value || []).some((c) => c.code === 'fabrication_lint')) return false
  const lint = checkResult.value?.lint || task.value?.rule_result?.lint
  if (lint && Number(lint.high || 0) > 0) return false
  return true
})
const currentVariantQualityLabel = computed(() => {
  const m = currentVariantMeta.value
  if (!m) return null
  if (m.quality === 'publish_ready_with_warnings') {
    const n = (m.quality_issues || []).length
    return `未过硬门控（遗留 ${n} 项问题）· 请重新「AI 生成正式渠道稿」`
  }
  if (isPublishReadyVariant.value) {
    const table = m?.has_table ? ' · 含表格' : ''
    const chars = m?.body_chars ? ` · ${m.body_chars}字` : ''
    const std = m?.article_standard === 'full_article_v2' ? ' · 硬门控v2' : ''
    return `已过完整文章门控 · HTML 可发布${table}${chars}${std}`
  }
  if (
    m?.fallback ||
    m?.quality === 'adapted_draft' ||
    m?.quality === 'adapted_draft_not_publishable' ||
    m?.quality === 'adapted_publish_html'
  ) {
    return '规则裁剪稿 · 未过发布门控 · 请点「AI 生成正式渠道稿」'
  }
  if (Array.isArray(m.quality_issues) && m.quality_issues.length) {
    return `未过门控：${m.quality_issues[0]}`
  }
  return null
})
const currentVariantHasTable = computed(() => {
  if (currentVariantMeta.value?.has_table) return true
  return /<table/i.test(variantEdit.body_html || '')
})

/** Apply every available structural patch so publish gate can pass faster. */
async function applyAllPatches() {
  const codes = (patches.value || []).map((p) => p.code).filter(Boolean)
  if (!codes.length) {
    ElMessage.info('当前没有可一键插入的补丁，请先点「检查就绪」')
    return
  }
  busy.value = 'patch'
  error.value = ''
  docTab.value = 'master'
  let applied = 0
  try {
    for (const code of codes) {
      try {
        const res = await applyGeoContentPatch(tenantId.value, taskId.value, code)
        if (res.task) applyTaskPayload(res.task)
        if (res.article?.body_markdown != null) {
          article.body_markdown = sanitizeDraftHeadings(res.article.body_markdown)
          article.title = res.article.title || article.title
        }
        checkResult.value = {
          ready: res.ready,
          checks: res.checks || [],
          patches: res.patches || [],
          lint: res.lint,
          blocks: res.blocks,
          geo_score: res.geo_score,
          geo_subscores: res.geo_subscores,
          geo_actions: res.geo_actions || [],
          ai_review: checkResult.value?.ai_review,
        }
        applied += 1
      } catch (e) {
        console.warn('patch skip', code, e)
      }
    }
    // Final check after batch
    const res = await checkGeoContentTask(tenantId.value, taskId.value, false)
    checkResult.value = res
    if (res.task) applyTaskPayload(res.task)
    ElMessage.success(
      `已批量应用 ${applied}/${codes.length} 个补丁 · Score ${res.geo_score ?? '—'} · ${
        res.ready ? '规则就绪' : '仍有规则未过'
      }`,
    )
  } catch (e) {
    toastError(e, '批量补丁失败')
  } finally {
    busy.value = ''
  }
}

async function saveVariantBody() {
  if (docTab.value === 'master') return
  if (!variantEdit.title.trim() || !variantEdit.body_markdown.trim()) {
    ElMessage.warning('渠道稿标题与正文不能为空')
    return
  }
  busy.value = 'saveVar'
  try {
    task.value = await patchGeoVariant(tenantId.value, taskId.value, docTab.value, {
      title: variantEdit.title.trim(),
      body_markdown: variantEdit.body_markdown,
    })
    applyVariantFromTask()
    variantViewMode.value = 'preview'
    ElMessage.success('渠道稿已保存并刷新 HTML 正稿')
  } catch (e) {
    toastError(e, '保存渠道稿失败')
  } finally {
    busy.value = ''
  }
}

async function exportCurrentVariant() {
  if (docTab.value === 'master') {
    ElMessage.warning('请先切换到渠道页签')
    return
  }
  busy.value = 'export'
  try {
    const res = await exportGeoVariant(tenantId.value, taskId.value, docTab.value)
    await load()
    applyVariantFromTask()
    if (res.body_html) {
      variantEdit.body_html = res.body_html
      variantViewMode.value = 'preview'
    }
    ElMessage.success(
      res.export_format === 'html'
        ? `已导出 HTML 正稿 ${res.channel}${res.has_table ? '（含表格）' : ''}`
        : `已导出 ${res.channel}（status=${res.status}）`,
    )
  } catch (e) {
    toastError(e, '导出失败')
  } finally {
    busy.value = ''
  }
}

async function copyCurrentDoc() {
  try {
    if (docTab.value === 'master') {
      await navigator.clipboard.writeText(`# ${article.title}\n\n${article.body_markdown}`)
      ElMessage.success('已复制母稿 Markdown（草案，勿直接外发）')
      return
    }
    // 渠道：默认复制 HTML 正稿（无 ## / ** 标记）
    let html = variantEdit.body_html
    if (!html || !html.includes('<')) {
      html = resolveVariantHtml({
        body_markdown: variantEdit.body_markdown,
        body_html: variantEdit.body_html,
        adapt_meta: currentVariantMeta.value,
      })
      variantEdit.body_html = html
    }
    const title = variantEdit.title || ''
    // Prefer rich HTML; also put plain title line for CMS
    const payload = title
      ? `<h1>${title.replace(/</g, '&lt;')}</h1>\n${html}`
      : html
    try {
      await navigator.clipboard.write([
        new ClipboardItem({
          'text/html': new Blob([payload], { type: 'text/html' }),
          'text/plain': new Blob(
            [
              `${title}\n\n${(variantEdit.body_plain || currentVariantMeta.value?.body_plain || '').trim() || html.replace(/<[^>]+>/g, '')}`,
            ],
            { type: 'text/plain' },
          ),
        }),
      ])
    } catch {
      // Fallback: plain HTML string
      await navigator.clipboard.writeText(payload)
    }
    ElMessage.success(
      currentVariantHasTable.value
        ? '已复制 HTML 正稿（含表格，可粘贴到公众号/知乎后台）'
        : '已复制 HTML 正稿（可粘贴到平台后台，非 Markdown）',
    )
  } catch {
    ElMessage.error('复制失败')
  }
}

async function submitReview() {
  busy.value = 'submitRev'
  try {
    task.value = await submitGeoTaskReview(
      tenantId.value,
      taskId.value,
      reviewNote.value || null,
    )
    ElMessage.success('已提交审校')
  } catch (e) {
    toastError(e, '提交审校失败')
  } finally {
    busy.value = ''
  }
}

async function decideReview(decision) {
  busy.value = 'decideRev'
  try {
    task.value = await decideGeoTaskReview(
      tenantId.value,
      taskId.value,
      decision,
      reviewNote.value || null,
    )
    ElMessage.success(decision === 'approved' ? '已通过审校' : '已驳回')
  } catch (e) {
    toastError(e, '审校决策失败')
  } finally {
    busy.value = ''
  }
}

/** Why publish/push may fail — shown in UI; click still hits API when possible (N2 expects 审校提示). */
const publishGateHint = computed(() => {
  if (docTab.value === 'master') {
    return '请先切换到 website/wechat/zhihu 等渠道页签再回填'
  }
  const rs = task.value?.review_status || 'none'
  if (rs !== 'approved') {
    return `未通过审校（当前：${rs}），请先提交审校并审批通过后再回填/推送`
  }
  if (!liveChannelCoverage.value.present.includes(normChannelKey(docTab.value))) {
    return `当前渠道 ${docTab.value} 尚无渠道稿，请先生成渠道稿`
  }
  return ''
})

async function recordPublication() {
  if (docTab.value === 'master') {
    const msg = '请切换到渠道页签再回填 URL'
    ElMessage.warning(msg)
    error.value = msg
    return
  }
  if (!publishUrl.value.trim().startsWith('http')) {
    ElMessage.warning('请填写 http(s) 发布 URL')
    return
  }
  // Soft pre-check: still call API so gate returns 400 + 审校文案（清单 N2）
  if ((task.value?.review_status || 'none') !== 'approved') {
    ElMessage({
      type: 'warning',
      message: publishGateHint.value || '未通过审校，将请求接口确认门禁',
      duration: 5000,
      showClose: true,
    })
  }
  busy.value = 'publish'
  try {
    task.value = await publishGeoVariant(taskId.value, {
      tenant_id: tenantId.value,
      channel: docTab.value,
      published_url: publishUrl.value.trim(),
      note: publishNote.value || null,
    })
    ElMessage.success('已回填发布 URL')
    error.value = ''
    await loadImpact()
  } catch (e) {
    const msg = toastError(e, '回填失败')
    error.value = msg
  } finally {
    busy.value = ''
  }
}

async function loadPushTargets() {
  if (!tenantId.value || !taskId.value) return
  try {
    const data = await fetchTaskPushTargets(tenantId.value, taskId.value)
    pushTargets.value = data.targets || []
    const ready = (data.ready_targets || []).map(
      (t) => `${t.adapt_key || t.channel_type}:${t.account_id}`,
    )
    if (!pushSelected.value.length) pushSelected.value = ready
  } catch {
    pushTargets.value = []
  }
}

async function loadImpact() {
  if (!tenantId.value || !taskId.value) return
  impactLoading.value = true
  try {
    impact.value = await fetchGeoContentTaskImpact(
      tenantId.value,
      taskId.value,
      impactWindowDays.value,
    )
  } catch {
    impact.value = null
  } finally {
    impactLoading.value = false
  }
}

function fmtRate(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return `${(Number(v) * 100).toFixed(1)}%`
}

function fmtDelta(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v) * 100
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}pp`
}

const impactInsufficient = computed(
  () =>
    !!(
      impact.value?.summary?.insufficient_data ||
      impact.value?.prompt_mention?.insufficient_data
    ),
)
const impactActionHint = computed(
  () =>
    impact.value?.summary?.action_hint ||
    impact.value?.prompt_mention?.confidence_reason ||
    '',
)

async function pushWebhook() {
  if (docTab.value === 'master') {
    ElMessage.warning('请切换到渠道页签')
    return
  }
  if (!webhookAccountId.value) {
    ElMessage.warning('请选择推送账号（Webhook 或社交 social_api）')
    return
  }
  if ((task.value?.review_status || 'none') !== 'approved') {
    ElMessage({
      type: 'warning',
      message: publishGateHint.value || '未通过审校',
      duration: 5000,
      showClose: true,
    })
  }
  busy.value = 'push'
  try {
    const res = await pushGeoVariantWebhook(taskId.value, {
      tenant_id: tenantId.value,
      channel: docTab.value,
      account_id: webhookAccountId.value,
      mode: 'publish',
      create_publication: true,
      published_url: publishUrl.value.trim() || null,
      note: publishNote.value || null,
    })
    if (res.task) task.value = res.task
    else await load()
    await loadPushTargets()
    ElMessage.success(
      res?.connector === 'social' ? '社交直发完成' : 'Webhook 推送完成',
    )
  } catch (e) {
    toastError(e, '推送失败')
  } finally {
    busy.value = ''
  }
}

async function pushBatchSelected() {
  if (!pushSelected.value.length) {
    ElMessage.warning('请勾选至少一个就绪渠道')
    return
  }
  if ((task.value?.review_status || 'none') !== 'approved') {
    ElMessage({
      type: 'warning',
      message: publishGateHint.value || '未通过审校',
      duration: 5000,
      showClose: true,
    })
  }
  pushBatchBusy.value = true
  try {
    const targets = pushSelected.value.map((key) => {
      const [channel, accountId] = String(key).split(':')
      return { channel, account_id: Number(accountId) }
    })
    let res = await pushGeoVariantBatch(
      taskId.value,
      {
        tenant_id: tenantId.value,
        mode: 'publish',
        create_publication: true,
        targets,
        note: publishNote.value || null,
      },
      { runAsync: true },
    )
    if (res?.async && res?.job?.id) {
      ElMessage.info(`推送任务 #${res.job.id} 排队中…`)
      const job = await waitGeoAsyncJob(tenantId.value, res.job.id, {
        intervalMs: 2000,
        maxMs: 180000,
      })
      if (job.status === 'failed') {
        throw new Error(job.error || '后台推送失败')
      }
      res = {
        ok_count: job.result_meta?.ok_count ?? 0,
        fail_count: job.result_meta?.fail_count ?? 0,
        results: job.result_meta?.results || [],
      }
      await load()
    } else if (res.task) {
      task.value = res.task
    } else {
      await load()
    }
    await loadPushTargets()
    ElMessage.success(
      `多媒推送完成：成功 ${res.ok_count || 0} · 失败 ${res.fail_count || 0}`,
    )
    if (res.fail_count) {
      const errs = (res.results || [])
        .filter((r) => !r.ok)
        .map((r) => `${r.channel}: ${r.error}`)
        .slice(0, 3)
      if (errs.length) ElMessage.warning(errs.join('；'))
    }
  } catch (e) {
    toastError(e, '批量推送失败')
  } finally {
    pushBatchBusy.value = false
  }
}

async function pushBatchAllReady() {
  const ready = (pushTargets.value || []).filter((t) => t.ready)
  pushSelected.value = ready.map(
    (t) => `${t.adapt_key || t.channel_type}:${t.account_id}`,
  )
  await pushBatchSelected()
}

function normChannelKey(raw) {
  const key = String(raw || '').trim().toLowerCase()
  const aliases = {
    web: 'website',
    官网: 'website',
    网站: 'website',
    docs: 'website',
    微信: 'wechat',
    公众号: 'wechat',
    weixin: 'wechat',
    知乎: 'zhihu',
    百家号: 'baijiahao',
    头条: 'toutiao',
    今日头条: 'toutiao',
  }
  return aliases[key] || key
}

/** Live channel coverage from task.variants (not stale rule_result). */
const liveChannelCoverage = computed(() => {
  const targets = (task.value?.target_channels || channelPick.value || []).map(normChannelKey)
  const have = new Set((task.value?.variants || []).map((v) => normChannelKey(v.channel)))
  const uniqTargets = [...new Set(targets.filter(Boolean))]
  const missing = uniqTargets.filter((c) => !have.has(c))
  const present = [...have]
  return {
    targets: uniqTargets,
    present,
    missing,
    ok: missing.length === 0 && (uniqTargets.length > 0 || present.length > 0),
  }
})

async function loadChannelBlueprint() {
  if (!tenantId.value) return
  const group =
    task.value?.prompt?.question_group ||
    task.value?.prompt_question_group ||
    brief.intent ||
    '推荐'
  try {
    channelBlueprint.value = await fetchChannelBlueprint(tenantId.value, group)
  } catch {
    channelBlueprint.value = null
  }
}

watch(
  () => [task.value?.id, task.value?.prompt?.question_group, brief.intent],
  () => {
    loadChannelBlueprint()
  },
)

const scoreMeta = computed(() => {
  const s = checkResult.value?.geo_score ?? task.value?.rule_result?.geo_score
  const subs = checkResult.value?.geo_subscores || task.value?.rule_result?.geo_subscores || {}
  const chips = Object.keys(subs).map((k) => ({
    key: k,
    label: SUBSCORE_LABELS[k] || k,
    value: Math.round((subs[k] || 0) * 100),
  }))
  const lintHigh = Number(
    (checkResult.value?.lint || task.value?.rule_result?.lint || {}).high || 0,
  )
  let tone = 'muted'
  if (s != null) {
    if (lintHigh > 0) tone = 'bad'
    else if (s >= 80) tone = 'good'
    else if (s >= 60) tone = 'warn'
    else tone = 'bad'
  }
  return {
    score: s,
    chips,
    tone,
    headline: s == null ? '尚未检查' : `${s}`,
    subline:
      s == null
        ? '点「检查」查看母稿就绪度（非正式成稿评分）'
        : '母稿结构就绪度 · 仍需人工润色后再发布',
  }
})

/** @deprecated kept for any leftover refs */
const scoreLine = computed(() => {
  const m = scoreMeta.value
  if (m.score == null) return m.subline
  return `GEO Score ${m.score}/100`
})

/**
 * Prefer latest checkResult, but always overlay channel_variant_ready from live
 * variants so generated tabs never leave a stale「缺少 website, wechat, zhihu」.
 */
const checks = computed(() => {
  const base = [
    ...(checkResult.value?.checks || task.value?.rule_result?.checks || []),
  ]
  const cov = liveChannelCoverage.value
  const liveMsg = cov.ok
    ? `目标渠道稿已齐：${channelListLabel(cov.present)}`
    : `还缺渠道稿：${channelListLabel(cov.missing)}（已有 ${channelListLabel(cov.present)}）`
  const liveChannel = {
    code: 'channel_variant_ready',
    passed: cov.ok,
    message: liveMsg,
    action: cov.ok
      ? ''
      : '在中间栏勾选渠道 →「生成所选渠道稿」→ 再点检查',
  }
  let replaced = false
  const out = base.map((c) => {
    if (c.code === 'channel_variant_ready') {
      replaced = true
      return { ...c, ...liveChannel }
    }
    return c
  })
  if (!replaced && (cov.targets.length || cov.present.length)) {
    out.push(liveChannel)
  }
  return out.map((c) => ({
    ...c,
    label: checkLabel(c.code),
  }))
})
const failedChecks = computed(() => checks.value.filter((c) => !c.passed))
const passedChecks = computed(() => checks.value.filter((c) => c.passed))
const geoActions = computed(
  () => checkResult.value?.geo_actions || task.value?.rule_result?.geo_actions || [],
)
const aiReview = computed(
  () => checkResult.value?.ai_review || task.value?.rule_result?.ai_review || null,
)
const patches = computed(
  () => checkResult.value?.patches || task.value?.rule_result?.patches || [],
)
const boundFacts = computed(() => task.value?.facts || [])
const boundVerifiedCount = computed(
  () => boundFacts.value.filter((f) => f.trust_level === 'verified').length,
)
const factsBindReady = computed(
  () => boundFacts.value.length >= 3 && boundVerifiedCount.value >= 3,
)
const libraryVerifiedCount = computed(
  () =>
    (allFacts.value || []).filter(
      (f) => f.trust_level === 'verified' && (f.status === 'active' || !f.status),
    ).length,
)
const infoGapOptions = computed(() => {
  const fromCat = catalog.value?.info_gaps
  if (Array.isArray(fromCat) && fromCat.length) return fromCat
  return INFO_GAP_FALLBACK
})
const variants = computed(() => task.value?.variants || [])
const failedVariantItems = computed(() => {
  const failed = task.value?.variant_polish?.failed
  return Array.isArray(failed) ? failed : []
})
const nextStep = computed(() =>
  nextEditorStep(task.value, {
    boundFacts: boundFacts.value,
    hasArticle: !!(task.value?.article || article.body_markdown),
    variants: variants.value,
    publications: task.value?.publications || impact.value?.publications || [],
    checkFailed: failedChecks.value.length > 0 && !!checkResult.value,
    blocked: failedChecks.value
      .slice(0, 2)
      .map((c) => c.label || c.code)
      .join('、'),
  }),
)

const foldBrief = ref(false)
const foldFacts = ref(false)

function goNextStep() {
  const key = nextStep.value?.key
  if (key === 'generate') return generate()
  if (key === 'check') return runCheck()
  if (key === 'variants') return genVariants()
  if (key === 'submit-review') return submitReview()
  if (key === 'brief') foldBrief.value = false
  if (key === 'facts') foldFacts.value = false
  const map = {
    brief: 'step-brief',
    facts: 'step-facts',
    'wait-review': 'step-publish',
    'fix-review': 'step-publish',
    publish: 'step-publish',
    impact: 'step-impact',
  }
  const id = map[key]
  if (id) document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function trustTagType(level) {
  if (level === 'verified') return 'success'
  if (level === 'needs_review') return 'warning'
  return 'info'
}
function trustLabel(level) {
  if (level === 'verified') return '已核验'
  if (level === 'needs_review') return '待核验'
  return level || '未知'
}
function factSnippet(f, max = 72) {
  const stmt = String(f?.statement || '').replace(/\s+/g, ' ').trim()
  if (!stmt) return ''
  return stmt.length > max ? `${stmt.slice(0, max)}…` : stmt
}
function factOptionLabel(f) {
  const t = trustLabel(f.trust_level)
  const title = f.title || '未命名事实'
  const snippet = factSnippet(f, 40)
  return snippet ? `#${f.id} · ${t} · ${title} — ${snippet}` : `#${f.id} · ${t} · ${title}`
}
async function removeBoundFact(id) {
  const nid = Number(id)
  selectedFactIds.value = (selectedFactIds.value || []).filter((x) => Number(x) !== nid)
  busy.value = 'facts'
  try {
    if (!selectedFactIds.value.length) {
      await bindGeoTaskFacts(tenantId.value, taskId.value, [])
      await refreshTaskDetail()
      ElMessage.success('已清空事实绑定')
    } else {
      await bindAndRefresh(selectedFactIds.value, '已更新绑定')
    }
  } catch (e) {
    toastError(e, '移除失败')
  } finally {
    busy.value = ''
  }
}
const channelOptions = computed(() => {
  const opts = task.value?.channel_options || []
  if (opts.length) {
    const seen = new Set()
    return opts
      .map((o) => ({
        key: o.adapt_key || o.channel_type || o.key,
        label: o.name || o.display_name || o.adapt_key || o.channel_type,
      }))
      .filter((o) => o.key && !seen.has(o.key) && (seen.add(o.key) || true))
  }
  const profiles = task.value?.channel_profiles || []
  if (profiles.length) {
    return profiles.map((p) => ({ key: p.key, label: p.display_name || p.key }))
  }
  return [
    { key: 'website', label: '官网' },
    { key: 'wechat', label: '微信' },
    { key: 'zhihu', label: '知乎' },
  ]
})
const reviewStatusLabel = computed(() => {
  const s = task.value?.review_status || 'none'
  return REVIEW_LABELS[s] || s
})
const canSubmitReview = computed(() => !!task.value?.can_submit_review && !!task.value?.article)
const canDecideReview = computed(() => !!task.value?.can_decide_review)
const webhookAccountsForChannel = computed(() => {
  // Webhook + social_api for auto push; backend validates channel match
  return (channelAccounts.value || []).filter(
    (a) =>
      a.auth_type === 'webhook' ||
      a.auth_type === 'social_api' ||
      a.auth_type === 'api_key' ||
      a.auth_type === 'oauth2' ||
      !a.auth_type,
  )
})

watch([tenantId, taskId], load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="editor">
    <div class="toolbar">
      <div class="left">
        <el-button text type="primary" @click="router.push('/geo/tasks')">← 任务列表</el-button>
        <div class="meta">
          <span class="title">任务 #{{ taskId }}</span>
          <span v-if="task" class="sub">
            {{ task.title }}
            · {{ taskStatusLabel(task.status) }}
            · {{ pipelineLabel(task.pipeline_step) }}
            · {{ reviewStatusText(task.review_status) }}
          </span>
        </div>
      </div>
      <div class="right">
        <el-button @click="load">刷新</el-button>
      </div>
    </div>

    <div v-if="task && nextStep" class="next-step" :class="{ done: nextStep.key === 'impact' }">
      <div class="next-copy">
        <div class="next-kicker">当前下一步</div>
        <div class="next-title">{{ nextStep.title }}</div>
        <div class="next-detail">{{ nextStep.detail }}</div>
      </div>
      <el-button type="primary" :loading="!!busy" @click="goNextStep">
        {{ nextStep.action }}
      </el-button>
    </div>

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      closable
      class="mb"
      @close="error = ''"
    />
    <div v-if="task" class="grid">
      <!-- Left: brief + facts -->
      <aside class="col col-left">
        <el-card id="step-brief" shadow="never" class="card">
          <template #header>
            <div class="card-head">
              <button type="button" class="fold-toggle" @click="foldBrief = !foldBrief">
                {{ foldBrief ? '▸' : '▾' }} 内容策略
                <el-tag v-if="foldBrief && task?.brief_ready" size="small" type="success" effect="plain">已齐</el-tag>
              </button>
              <div v-show="!foldBrief" class="row-actions">
                <el-button size="small" :loading="busy === 'suggest'" @click="suggestBrief">
                  AI 建议
                </el-button>
                <el-button size="small" type="primary" :loading="busy === 'brief'" @click="saveBrief">
                  保存策略
                </el-button>
              </div>
            </div>
          </template>
          <div v-show="!foldBrief">
          <div v-if="briefSuggestHint" class="hint mb" style="color: #2563eb">
            {{ briefSuggestHint }}
            <span v-if="briefLocalDraft"> · 本地草稿未保存</span>
          </div>
          <el-form label-width="88px" size="small">
            <el-form-item label="行业" required>
              <el-input v-model="brief.industry" />
            </el-form-item>
            <el-form-item label="受众" required>
              <el-input v-model="brief.audience" />
            </el-form-item>
            <el-form-item label="意图" required>
              <el-select v-model="brief.intent" clearable style="width: 100%">
                <el-option
                  v-for="it in catalog?.intents || []"
                  :key="it.key"
                  :label="it.label"
                  :value="it.key"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="内容类型" required>
              <el-select v-model="brief.content_type" clearable style="width: 100%">
                <el-option
                  v-for="it in catalog?.content_types || []"
                  :key="it.key"
                  :label="it.label"
                  :value="it.key"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="CTA" required>
              <el-input v-model="brief.cta" />
            </el-form-item>
            <el-form-item label="禁用表述">
              <el-input v-model="brief.banned_claims" placeholder="逗号分隔" />
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="brief.notes" />
            </el-form-item>
            <el-divider content-position="left">策略（可选）</el-divider>
            <el-form-item label="AI 问题">
              <el-input v-model="brief.ai_question" />
            </el-form-item>
            <el-form-item label="不推荐原因">
              <el-input
                v-model="brief.not_recommended_reasons"
                type="textarea"
                :rows="2"
                placeholder="AI 目前不推荐你的原因，逗号分隔；母稿须用事实回应"
              />
            </el-form-item>
            <el-form-item>
              <template #label>
                <span
                  title="AI 回答里缺哪些信息维度。勾选后，母稿必须用已绑定事实回应这些缺口，禁止编造补全。"
                >
                  信息缺口
                </span>
              </template>
              <el-select
                v-model="brief.info_gaps"
                multiple
                collapse-tags
                collapse-tags-tooltip
                filterable
                clearable
                placeholder="选择需用事实补齐的缺口（可多选）"
                style="width: 100%"
              >
                <el-option
                  v-for="g in infoGapOptions"
                  :key="g.key"
                  :label="g.label"
                  :value="g.key"
                />
              </el-select>
              <div class="field-help">
                指<strong>AI 回答里缺什么</strong>（定位/对比/案例/权威源等）。勾选后生成母稿须用事实回应，不要写英文 key。
              </div>
            </el-form-item>
            <el-form-item label="推荐场景">
              <el-input v-model="brief.recommend_when" placeholder="在什么场景下可被考虑/推荐" />
            </el-form-item>
            <el-form-item label="竞品">
              <el-input v-model="brief.competitors" placeholder="逗号分隔，对比段会点名" />
            </el-form-item>
            <el-form-item label="必须覆盖">
              <el-input v-model="brief.must_cover" placeholder="逗号分隔，如品牌名、产品线" />
            </el-form-item>
          </el-form>
          </div>
        </el-card>

        <el-card id="step-facts" shadow="never" class="card fact-bind-card">
          <template #header>
            <div class="card-head">
              <button type="button" class="fold-toggle" @click="foldFacts = !foldFacts">
                {{ foldFacts ? '▸' : '▾' }} 事实绑定
                <el-tag
                  size="small"
                  :type="factsBindReady ? 'success' : 'warning'"
                  effect="plain"
                >
                  {{ factsBindReady ? '可生成' : '未就绪' }}
                </el-tag>
              </button>
            </div>
          </template>
          <div v-show="!foldFacts">

          <div class="fact-status" :class="{ ready: factsBindReady }">
            <div class="fact-status-row">
              <span>
                已绑
                <strong>{{ boundFacts.length }}</strong>
                条
              </span>
              <span class="dot">·</span>
              <span>
                已核验
                <strong>{{ boundVerifiedCount }}</strong>
                / 需 ≥3
              </span>
            </div>
            <el-progress
              :percentage="Math.min(100, Math.round((boundVerifiedCount / 3) * 100))"
              :stroke-width="8"
              :status="factsBindReady ? 'success' : undefined"
              :show-text="false"
            />
            <div class="hint fact-status-sub">
              生成母稿至少绑定 <strong>3 条已核验</strong>事实。库中可选
              {{ allFacts.length }} 条（已核验 {{ libraryVerifiedCount }}）
              <span v-if="task?.status"> · {{ taskStatusLabel(task.status) }}</span>
            </div>
          </div>

          <!-- 已绑定列表 -->
          <div class="fact-section">
            <div class="fact-section-label">当前绑定</div>
            <div v-if="!boundFacts.length" class="fact-empty">
              尚未绑定事实。可用下方「快速绑定」或从库中多选后保存。
            </div>
            <div v-else class="bound-chips">
              <div v-for="f in boundFacts" :key="f.id" class="bound-chip">
                <div class="bound-chip-main">
                  <div class="bound-chip-top">
                    <el-tag size="small" :type="trustTagType(f.trust_level)" effect="light">
                      {{ trustLabel(f.trust_level) }}
                    </el-tag>
                    <span class="bound-chip-id">#{{ f.id }}</span>
                    <span class="bound-chip-title" :title="f.title">{{ f.title || '未命名' }}</span>
                    <button
                      type="button"
                      class="bound-chip-x"
                      title="移除此条"
                      @click="removeBoundFact(f.id)"
                    >
                      ×
                    </button>
                  </div>
                  <div v-if="f.statement" class="bound-chip-stmt" :title="f.statement">
                    {{ f.statement }}
                  </div>
                  <div v-else class="bound-chip-stmt is-empty">这条事实没有正文</div>
                  <div v-if="f.source_name || f.source_url" class="bound-chip-src">
                    来源 {{ f.source_name || f.source_url }}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 快速操作 -->
          <div class="fact-section">
            <div class="fact-section-label">快速绑定</div>
            <div class="fact-actions">
              <el-button
                size="small"
                type="success"
                :loading="busy === 'facts'"
                :disabled="libraryVerifiedCount < 3"
                @click="bindTopVerified(3)"
              >
                一键绑 3 条已核验
              </el-button>
              <el-button size="small" :loading="busy === 'retrieve'" @click="retrieveFacts">
                按 Brief 召回
              </el-button>
              <el-button
                size="small"
                :loading="busy === 'apply'"
                :disabled="!retrievePreview.length"
                @click="applyRetrieveTop"
              >
                绑定召回结果
              </el-button>
            </div>
            <div class="field-help">
              推荐：有核验事实时点「一键绑 3 条」；或先「按 Brief 召回」再「绑定召回结果」。
            </div>
          </div>

          <!-- 手动多选 -->
          <div class="fact-section">
            <div class="fact-section-label">从事实库勾选</div>
            <el-select
              v-model="selectedFactIds"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="搜索标题 / 勾选多条事实卡"
              style="width: 100%"
            >
              <el-option
                v-for="f in allFacts"
                :key="f.id"
                :label="factOptionLabel(f)"
                :value="Number(f.id)"
              >
                <div class="fact-option">
                  <el-tag size="small" :type="trustTagType(f.trust_level)" effect="plain">
                    {{ trustLabel(f.trust_level) }}
                  </el-tag>
                  <span class="fact-option-id">#{{ f.id }}</span>
                  <div class="fact-option-text">
                    <div class="fact-option-title">{{ f.title || '未命名' }}</div>
                    <div v-if="factSnippet(f, 48)" class="fact-option-stmt">{{ factSnippet(f, 48) }}</div>
                  </div>
                </div>
              </el-option>
            </el-select>
            <div class="fact-actions fact-actions-end">
              <el-button
                size="small"
                type="primary"
                :loading="busy === 'facts'"
                :disabled="!selectedFactIds.length"
                @click="saveFacts"
              >
                保存绑定（{{ selectedFactIds.length }}）
              </el-button>
            </div>
          </div>

          <!-- 召回预览 -->
          <div v-if="retrievePreview.length" class="fact-section retrieve-box">
            <div class="fact-section-label">
              召回候选
              <span class="hint">{{ retrievePreview.length }} 条 · 已勾入选择框</span>
            </div>
            <div
              v-for="r in retrievePreview"
              :key="r.fact_id"
              class="retrieve-row"
            >
              <el-tag
                size="small"
                :type="trustTagType(r.trust_level)"
                effect="plain"
              >
                {{ trustLabel(r.trust_level) }}
              </el-tag>
              <span class="bound-chip-id">#{{ r.fact_id }}</span>
              <div class="retrieve-text">
                <span class="retrieve-title">{{ r.title || '—' }}</span>
                <span v-if="r.statement" class="retrieve-stmt">{{ factSnippet(r, 48) }}</span>
              </div>
              <span v-if="r.score != null" class="retrieve-score">{{ Number(r.score).toFixed(1) }}</span>
            </div>
          </div>
          </div>
        </el-card>
      </aside>

      <!-- Center: article + publish -->
      <div class="col col-main">
        <el-card id="step-doc" shadow="never" class="card">
          <template #header>
            <div class="card-head">
              <span>文档</span>
              <div class="row-actions">
                <el-button
                  v-if="docTab === 'master'"
                  size="small"
                  type="primary"
                  :loading="busy === 'generate'"
                  @click="generate"
                >
                  生成母稿
                </el-button>
                <el-button
                  v-if="docTab === 'master'"
                  size="small"
                  :loading="busy === 'save'"
                  @click="saveArticleBody"
                >
                  保存正文
                </el-button>
                <el-button
                  v-if="docTab !== 'master'"
                  size="small"
                  type="primary"
                  :loading="busy === 'saveVar'"
                  @click="saveVariantBody"
                >
                  保存渠道稿
                </el-button>
                <el-button
                  v-if="docTab !== 'master'"
                  size="small"
                  :loading="busy === 'export'"
                  @click="exportCurrentVariant"
                >
                  导出
                </el-button>
                <el-button size="small" @click="copyCurrentDoc">复制</el-button>
                <el-button size="small" :loading="busy === 'check'" @click="runCheck">
                  检查就绪
                </el-button>
                <el-button size="small" :loading="busy === 'review'" @click="runAiReview">
                  AI 审稿
                </el-button>
              </div>
            </div>
          </template>

          <div v-if="generateHint" class="hint mb" style="color: #2563eb">{{ generateHint }}</div>
          <el-alert
            v-if="activeJob && ['pending', 'running'].includes(activeJob.status)"
            type="info"
            show-icon
            class="mb"
            :closable="false"
            :title="`后台任务 #${activeJob.id} · ${activeJob.status}`"
            :description="`${activeJob.cancel_requested ? '已请求取消 · ' : ''}${activeJob.progress_label || '处理中'}${activeJob.progress_pct != null ? ' · ' + activeJob.progress_pct + '%' : ''}。刷新页面不会中断，稍后可继续看结果。`"
          >
            <el-button
              size="small"
              :disabled="!!activeJob.cancel_requested"
              @click="cancelActiveJob"
            >取消</el-button>
          </el-alert>
          <el-alert
            v-if="activeJob?.status === 'failed'"
            type="error"
            show-icon
            class="mb"
            :title="`后台任务 #${activeJob.id} 失败`"
            :description="activeJob.error || '无错误详情'"
          >
            <el-button size="small" type="primary" @click="generate">重试生成</el-button>
          </el-alert>
          <el-alert
            v-if="activeJob?.status === 'cancelled'"
            type="warning"
            show-icon
            class="mb"
            :closable="false"
            :title="`后台任务 #${activeJob.id} 已取消`"
            description="生成已停下，正文未覆盖。可再点「生成母稿」。"
          />

          <div v-if="docTab === 'master'" class="doc-draft-banner mb">
            <b>自动生成母稿草案</b>
            — 供内部改稿与结构检查，<b>不能直接当正式发布文</b>。
            请润色语气、删模板痕迹、核对事实后再审校推送。
          </div>
          <div
            v-else-if="isPublishReadyVariant"
            class="channel-quality mb is-good"
          >
            <b>正式渠道稿（HTML 正稿）</b>
            — 下方默认「正稿预览」无 ## / ** 标记；点顶部「复制」粘贴到平台后台。
            推送前建议快速核对关键数字与来源。
            <span v-if="currentVariantMeta?.display_name" class="muted">
              · {{ currentVariantMeta.display_name }}
            </span>
          </div>
          <div v-else class="channel-quality mb is-warn">
            <b>规则裁剪稿（非正式成稿）</b>
            — 未走 AI 时接近母稿结构，不能当正式发布文。
            请点下方「AI 生成正式渠道稿」。
          </div>

          <el-tabs :model-value="docTab" class="mb" @tab-change="onDocTabChange">
            <el-tab-pane label="母稿草案" name="master" />
            <el-tab-pane
              v-for="v in variants"
              :key="v.channel"
              :name="v.channel"
              :label="`${channelLabel(v.channel)}${v.stale ? ' *' : ''}`"
            />
          </el-tabs>

          <template v-if="docTab === 'master'">
            <el-form label-width="56px" size="small">
              <el-form-item label="标题">
                <el-input v-model="article.title" />
              </el-form-item>
              <el-form-item label="正文">
                <el-input
                  :key="`master-body-${task?.article?.version_no || 0}-${(article.body_markdown || '').length}`"
                  v-model="article.body_markdown"
                  type="textarea"
                  :rows="16"
                  placeholder="Markdown 母稿草案（需人工润色）"
                />
              </el-form-item>
            </el-form>
            <div v-if="task.article" class="hint">
              草案 v{{ task.article.version_no }} · {{ task.article.created_at || '' }}
              · 正文字数 {{ (article.body_markdown || '').length }}
            </div>
            <div v-if="sentenceCites.length" class="cite-box mb">
              <div class="section-title">逐句证据</div>
              <div v-for="(c, i) in sentenceCites" :key="i" class="cite-row">
                <span class="cite-sent">{{ c.sentence }}</span>
                <el-tag v-if="c.cited" size="small" type="success">
                  #{{ c.fact_id }} {{ c.fact_title }}
                </el-tag>
                <el-tag v-else size="small" type="warning">未挂事实</el-tag>
              </div>
            </div>
            <div class="hint">重新「生成母稿」会覆盖当前正文</div>
          </template>
          <template v-else>
            <div class="hint mb">
              渠道 {{ channelLabel(docTab) }} · 状态 {{ variants.find((v) => v.channel === docTab)?.status || '—' }}
              <span v-if="variants.find((v) => v.channel === docTab)?.stale"> · 母稿已变需重生</span>
              <span v-if="currentVariantQualityLabel"> · {{ currentVariantQualityLabel }}</span>
              <span v-if="currentVariantHasTable"> · 含对比表</span>
            </div>
            <el-form label-width="56px" size="small">
              <el-form-item label="标题">
                <el-input v-model="variantEdit.title" />
              </el-form-item>
              <el-form-item label="正文">
                <div class="variant-body-wrap">
                  <div class="variant-view-toggle mb">
                    <el-radio-group v-model="variantViewMode" size="small">
                      <el-radio-button label="preview">正稿预览（发布样式）</el-radio-button>
                      <el-radio-button label="source">源码改写（高级）</el-radio-button>
                    </el-radio-group>
                    <span class="muted small">复制按钮默认复制 HTML 正稿，不是 ## 标记</span>
                  </div>
                  <div
                    v-if="variantViewMode === 'preview'"
                    class="variant-html-preview"
                    v-html="variantEdit.body_html || '<p class=muted>暂无 HTML，请重新「AI 生成正式渠道稿」或点导出</p>'"
                  />
                  <el-input
                    v-else
                    v-model="variantEdit.body_markdown"
                    type="textarea"
                    :rows="16"
                    placeholder="内部改写用结构化文本；保存后会重新生成 HTML 正稿"
                  />
                  <div v-if="variantViewMode === 'source'" class="hint">
                    改完请点「保存渠道稿」，系统会重算 HTML 表格正稿。
                  </div>
                </div>
              </el-form-item>
            </el-form>
          </template>
        </el-card>

        <el-card id="step-publish" shadow="never" class="card">
          <template #header>
            <div class="card-head">
              <span>渠道成稿 · 审校 · 发布</span>
              <el-button size="small" type="primary" :loading="busy === 'variants'" @click="genVariants">
                AI 生成正式渠道稿
              </el-button>
            </div>
          </template>
          <div class="hint mb">
            AI 按渠道写成可直接发布的正式稿（官网/微信/知乎等）；失败才回退规则裁剪。
            正式稿可复制发布；关键数字建议发布前扫一眼。
          </div>
          <el-checkbox-group v-model="channelPick" class="mb">
            <el-checkbox
              v-for="c in channelOptions"
              :key="c.key"
              :label="c.key"
            >
              {{ c.label }} ({{ c.key }})
            </el-checkbox>
          </el-checkbox-group>
          <el-alert
            v-if="failedVariantItems.length"
            type="warning"
            show-icon
            :closable="false"
            class="mb"
          >
            <template #title>
              勾选 {{ channelPick.length }} 个渠道，已成稿 {{ variants.length }} 个；
              {{ failedVariantItems.length }} 个未过门控
            </template>
            <ul class="variant-fail-list">
              <li v-for="f in failedVariantItems" :key="f.channel">
                <b>{{ channelLabel(f.channel) }}</b>
                ：{{ (f.issues && f.issues[0]) || f.message || '未达完整文章标准' }}
              </li>
            </ul>
            <el-button size="small" :loading="busy === 'variants'" @click="retryFailedVariants">
              重试失败渠道
            </el-button>
          </el-alert>

          <div v-if="channelBlueprint?.channels?.length" class="blueprint-box mb">
            <div class="blueprint-title">
              分发推荐（问题组：{{ channelBlueprint.group || '推荐' }}）
            </div>
            <ul class="blueprint-list">
              <li v-for="ch in channelBlueprint.channels.slice(0, 6)" :key="ch.channel_key || ch.id">
                <b>{{ ch.channel_name || ch.name || ch.channel_key }}</b>
                <span class="muted"> · {{ ch.priority_band || ch.band || '—' }}</span>
                <span v-if="ch.placement_status" class="muted"> · 阵地 {{ ch.placement_status }}</span>
                <div v-if="ch.why || ch.reason" class="muted small">{{ ch.why || ch.reason }}</div>
              </li>
            </ul>
          </div>

          <el-divider content-position="left">审校</el-divider>
          <div class="hint mb">
            状态：{{ reviewStatusLabel }}
            <template v-if="task.review_note"> · {{ task.review_note }}</template>
            <template v-if="task.reviewed_at"> · {{ task.reviewed_at }}</template>
          </div>
          <el-input
            v-model="reviewNote"
            size="small"
            placeholder="审校备注（可选）"
            class="mb"
          />
          <div class="row-actions">
            <el-button
              size="small"
              :disabled="!canSubmitReview"
              :loading="busy === 'submitRev'"
              @click="submitReview"
            >
              提交审校
            </el-button>
            <el-button
              size="small"
              type="success"
              :disabled="!canDecideReview"
              :loading="busy === 'decideRev'"
              @click="decideReview('approved')"
            >
              通过
            </el-button>
            <el-button
              size="small"
              type="danger"
              :disabled="!canDecideReview"
              :loading="busy === 'decideRev'"
              @click="decideReview('rejected')"
            >
              驳回
            </el-button>
          </div>

          <el-divider content-position="left">回填 / 一键推送</el-divider>
          <div v-if="publishGateHint" class="hint mb" style="color: #b45309">
            门禁：{{ publishGateHint }}
          </div>
          <el-form label-width="100px" size="small">
            <el-form-item label="发布 URL">
              <el-input v-model="publishUrl" placeholder="https://..." />
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="publishNote" />
            </el-form-item>
            <el-form-item label="推送账号">
              <el-select
                v-model="webhookAccountId"
                clearable
                style="width: 100%"
                placeholder="Webhook 或社交 social_api"
              >
                <el-option
                  v-for="a in webhookAccountsForChannel"
                  :key="a.id"
                  :label="`${a.display_name} · ${a.auth_type || 'webhook'} (#${a.id})`"
                  :value="a.id"
                />
              </el-select>
            </el-form-item>
          </el-form>
          <div class="row-actions">
            <el-button
              size="small"
              type="primary"
              :loading="busy === 'publish'"
              :title="publishGateHint || '回填发布 URL'"
              @click="recordPublication"
            >
              回填 URL
            </el-button>
            <el-button
              size="small"
              :loading="busy === 'push'"
              :title="publishGateHint || 'Webhook / 社交直发'"
              @click="pushWebhook"
            >
              推送当前渠道
            </el-button>
          </div>

          <el-divider content-position="left">多媒自动推送</el-divider>
          <p class="hint mb">
            就绪 = auto_publish + 凭证 + 渠道稿已导出。只差配置的项见「发布渠道」矩阵。
            <el-button link type="primary" size="small" @click="loadPushTargets">刷新目标</el-button>
          </p>
          <el-checkbox-group v-if="pushTargets.length" v-model="pushSelected" class="mb">
            <div v-for="t in pushTargets" :key="`${t.adapt_key}-${t.account_id || t.channel_id}`" class="push-row">
              <el-checkbox
                v-if="t.ready"
                :label="`${t.adapt_key || t.channel_type}:${t.account_id}`"
              >
                <b>{{ t.channel_name }}</b>
                <span class="muted"> · {{ t.channel_type }} · {{ t.push_kind || t.auth_type }}</span>
              </el-checkbox>
              <div v-else class="push-blocked">
                <span class="muted">{{ t.channel_name }}（{{ t.channel_type }}）</span>
                <span class="blocked"> — {{ (t.block_reasons || []).join('；') }}</span>
              </div>
            </div>
          </el-checkbox-group>
          <p v-else class="hint mb">暂无自动推送目标，请先在「发布渠道」一键开启多媒包并配置凭证。</p>
          <div class="row-actions">
            <el-button
              size="small"
              type="primary"
              :loading="pushBatchBusy"
              @click="pushBatchSelected"
            >
              推送勾选渠道
            </el-button>
            <el-button size="small" :loading="pushBatchBusy" @click="pushBatchAllReady">
              一键推送全部就绪
            </el-button>
            <router-link class="el-button el-button--small" to="/geo/publishing">管理渠道账号</router-link>
          </div>
          <div class="hint mt">
            推送前通常需「导出」渠道稿。未审校时按钮可点：接口返回 400 并提示审校要求（也可用上方橙色门禁文案）。
          </div>

          <el-divider id="step-impact" content-position="left">发布后效果</el-divider>
          <div v-loading="impactLoading" class="impact-panel">
            <div class="row-actions mb">
              <el-select v-model="impactWindowDays" size="small" style="width: 110px" @change="loadImpact">
                <el-option :value="7" label="±7 天" />
                <el-option :value="14" label="±14 天" />
                <el-option :value="30" label="±30 天" />
              </el-select>
              <el-button size="small" :loading="impactLoading" @click="loadImpact">刷新</el-button>
            </div>
            <template v-if="impact">
              <div class="hint mb" v-if="!impact.summary?.published_count">
                尚未回填发布 URL。发布后系统会把引用 URL 反查到本篇，并对比发布前后提及率。
              </div>
              <template v-else>
                <el-alert
                  v-if="impactInsufficient"
                  type="warning"
                  show-icon
                  :closable="false"
                  class="mb"
                  :title="impactActionHint || '数据不足以判断'"
                  description="任一侧快照不足阈值时不展示变化率。建议提高巡检频率或延长观察期。"
                />
                <div class="impact-kpis">
                  <div class="impact-kpi">
                    <div class="ik-label">引用命中</div>
                    <div class="ik-value">{{ impact.cite_hits?.total ?? 0 }}</div>
                    <div class="ik-hint">快照中匹配本篇 URL</div>
                  </div>
                  <div class="impact-kpi">
                    <div class="ik-label">发布前提及率</div>
                    <div class="ik-value">
                      {{
                        impactInsufficient
                          ? '—'
                          : fmtRate(impact.prompt_mention?.before?.mention_rate)
                      }}
                    </div>
                    <div class="ik-hint">
                      样本 {{ impact.prompt_mention?.before?.snapshot_count ?? 0 }}
                    </div>
                  </div>
                  <div class="impact-kpi">
                    <div class="ik-label">发布后提及率</div>
                    <div class="ik-value">
                      {{
                        impactInsufficient
                          ? '—'
                          : fmtRate(impact.prompt_mention?.after?.mention_rate)
                      }}
                    </div>
                    <div class="ik-hint">
                      样本 {{ impact.prompt_mention?.after?.snapshot_count ?? 0 }}
                      <template v-if="!impactInsufficient">
                        · Δ {{ fmtDelta(impact.prompt_mention?.delta_mention_rate) }}
                      </template>
                    </div>
                  </div>
                </div>
                <p v-if="impact.net_effect_vs_control != null && !impactInsufficient" class="hint">
                  净效应（处理 − 对照）
                  <b>{{ fmtDelta(impact.net_effect_vs_control) }}</b>
                  · 置信度 {{ impact.confidence || impact.summary?.confidence || '—' }}
                </p>
                <p v-else-if="impact.prompt_mention?.methodology_note" class="hint">
                  {{ impact.prompt_mention.methodology_note }}
                </p>
                <ul v-if="impact.publications?.length" class="impact-pubs">
                  <li v-for="p in impact.publications" :key="p.id">
                    <a :href="p.published_url" target="_blank" rel="noopener">{{ p.channel }}</a>
                    <span class="muted"> · 命中 {{ p.cite_hit_count || 0 }}</span>
                  </li>
                </ul>
                <p class="hint mt">
                  首次发布 {{ impact.first_published_at || '—' }} ·
                  对比窗 ±{{ impact.window_days }} 天 · 相关意图词 #{{ impact.prompt_id }}
                </p>
              </template>
            </template>
            <p v-else class="hint">加载效果数据…</p>
          </div>
        </el-card>
      </div>

      <!-- Right: draft readiness (not publish-ready copy) -->
      <aside class="col col-rail">
        <el-card id="step-check" shadow="never" class="card rail-card">
          <template #header>
            <div class="card-head">
              <div>
                <div class="rail-title">母稿就绪检查</div>
                <div class="rail-sub">生成稿体检 · 非正式成稿</div>
              </div>
              <div class="row-actions">
                <el-button size="small" :loading="busy === 'check'" @click="runCheck">检查</el-button>
                <el-button size="small" :loading="busy === 'review'" @click="runAiReview">审稿</el-button>
              </div>
            </div>
          </template>

          <div class="draft-banner mb">
            当前是 AI 母稿草案，通过检查只代表「结构/证据够用」，
            <b>还不能直接当正式发布文</b>。请人工润色后再审校推送。
          </div>

          <div class="score-block" :class="'tone-' + scoreMeta.tone">
            <div class="score-row">
              <div class="score-num">
                <template v-if="scoreMeta.score != null">
                  <span class="score-big">{{ scoreMeta.headline }}</span>
                  <span class="score-den">/100</span>
                </template>
                <template v-else>
                  <span class="score-big muted-num">—</span>
                </template>
              </div>
              <div class="score-copy">
                <div class="score-label">GEO 就绪分</div>
                <div class="score-hint">{{ scoreMeta.subline }}</div>
              </div>
            </div>
            <div v-if="scoreMeta.score != null" class="score-bar">
              <div class="score-bar-fill" :style="{ width: `${Math.min(100, scoreMeta.score)}%` }" />
            </div>
            <div v-if="scoreMeta.chips.length" class="score-chips">
              <span
                v-for="chip in scoreMeta.chips"
                :key="chip.key"
                class="score-chip"
                :class="{ low: chip.value < 60 }"
              >
                {{ chip.label }} {{ chip.value }}
              </span>
            </div>
          </div>

          <div class="channel-pill mb" :class="liveChannelCoverage.ok ? 'is-ok' : 'is-warn'">
            <span class="pill-mark">{{ liveChannelCoverage.ok ? '✓' : '!' }}</span>
            <div>
              <div class="pill-title">
                {{ liveChannelCoverage.ok ? '渠道稿已齐' : '渠道稿未齐' }}
              </div>
              <div class="pill-desc">
                目标 {{ channelListLabel(liveChannelCoverage.targets) }}
                · 已有 {{ channelListLabel(liveChannelCoverage.present) }}
                <template v-if="liveChannelCoverage.missing.length">
                  · 还缺 {{ channelListLabel(liveChannelCoverage.missing) }}
                </template>
              </div>
            </div>
          </div>

          <div v-if="failedChecks.length" class="sec-row">
            <span class="sec">待补齐 {{ failedChecks.length }}</span>
          </div>
          <ul v-if="failedChecks.length" class="check-list fail-list">
            <li v-for="c in failedChecks" :key="c.code">
              <span class="bad">✗</span>
              <div>
                <div class="check-title">{{ c.label }}</div>
                <div class="check-msg">{{ c.message }}</div>
                <div v-if="c.action" class="check-action">{{ c.action }}</div>
              </div>
            </li>
          </ul>
          <div v-else-if="checks.length" class="all-pass mb">结构项已全部通过 · 仍建议人工过目</div>

          <button
            v-if="passedChecks.length"
            type="button"
            class="toggle-passed"
            @click="showPassedChecks = !showPassedChecks"
          >
            {{ showPassedChecks ? '收起' : '展开' }}已通过 {{ passedChecks.length }} 项
          </button>
          <ul v-if="showPassedChecks && passedChecks.length" class="check-list pass-list">
            <li v-for="c in passedChecks" :key="c.code">
              <span class="ok">✓</span>
              <div>
                <div class="check-title">{{ c.label }}</div>
                <div class="check-msg">{{ c.message }}</div>
              </div>
            </li>
          </ul>

          <div v-if="geoActions.length" class="mt">
            <div class="sec">建议补强</div>
            <ul class="check-list fail-list">
              <li v-for="a in geoActions" :key="a.code">
                <span class="warn">!</span>
                <div>
                  <div class="check-title">{{ a.message }}</div>
                  <div v-if="a.action" class="check-action">{{ a.action }}</div>
                </div>
              </li>
            </ul>
          </div>

          <div v-if="patches.length" class="mt patch-box">
            <div class="sec">一键补结构（写入母稿，仍需人工改）</div>
            <div class="row-actions">
              <el-button
                size="small"
                type="warning"
                plain
                :loading="busy === 'patch'"
                @click="applyAllPatches"
              >
                全部应用 ({{ patches.length }})
              </el-button>
              <el-button
                v-for="p in patches"
                :key="p.code"
                size="small"
                :loading="busy === 'patch'"
                @click="applyPatch(p.code)"
              >
                {{ p.label || checkLabel(p.code) }}
              </el-button>
            </div>
          </div>
          <div v-else-if="failedChecks.length" class="mt patch-box">
            <div class="sec">一键补结构</div>
            <div class="hint mb">当前无补丁缓存，请先点上方「检查就绪」生成可插入补丁。</div>
            <el-button size="small" type="warning" plain :loading="busy === 'check'" @click="runCheck">
              检查就绪并生成补丁
            </el-button>
          </div>

          <div v-if="aiReview" class="mt ai-box">
            <div class="sec">
              AI 审阅意见
              <span class="sec-meta">
                阻断 {{ aiReview.block_count || 0 }} · 提醒 {{ aiReview.warn_count || 0 }}
              </span>
            </div>
            <div class="ai-summary">{{ aiReview.summary }}</div>
            <ul class="check-list">
              <li v-for="(iss, i) in aiReview.issues || []" :key="i">
                <span class="warn">{{ iss.severity === 'block' ? '阻断' : '提醒' }}</span>
                <div>
                  <div class="check-title">{{ iss.category || '意见' }}</div>
                  <div class="check-msg">{{ iss.message }}</div>
                  <div v-if="iss.fix_hint" class="check-action">{{ iss.fix_hint }}</div>
                </div>
              </li>
            </ul>
          </div>
        </el-card>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.editor { padding: 4px 2px 28px; max-width: none; width: 100%; }
.toolbar {
  display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap;
  margin-bottom: 12px; align-items: center;
}
.left, .right, .row-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.meta { display: flex; flex-direction: column; }
.title { font-weight: 700; color: #1e2330; }
.sub { font-size: 13px; color: #64748b; }
.next-step {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin: 0 0 14px;
  padding: 12px 16px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 12px;
}
.next-step.done {
  background: #ecfdf5;
  border-color: #a7f3d0;
}
.next-kicker {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #1d4ed8;
  margin-bottom: 2px;
}
.next-step.done .next-kicker { color: #047857; }
.next-title { font-size: 15px; font-weight: 700; color: #0f172a; }
.next-detail { font-size: 13px; color: #475569; margin-top: 2px; line-height: 1.45; }
.fold-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 0;
  background: transparent;
  padding: 0;
  font: inherit;
  font-weight: 650;
  color: #0f172a;
  cursor: pointer;
}
.mb { margin-bottom: 10px; }
.mt { margin-top: 12px; }
.grid {
  display: grid;
  /* 大屏：左 Brief · 中文档 · 右 Score，中间优先吃宽 */
  grid-template-columns: minmax(280px, 0.85fr) minmax(0, 2.4fr) minmax(300px, 1fr);
  gap: 14px;
  align-items: start;
  width: 100%;
}
@media (min-width: 1800px) {
  .grid {
    grid-template-columns: minmax(320px, 0.9fr) minmax(0, 2.6fr) minmax(340px, 1.05fr);
    gap: 16px;
  }
}
@media (max-width: 1280px) {
  .grid {
    grid-template-columns: minmax(240px, 280px) minmax(0, 1fr) minmax(260px, 300px);
  }
}
@media (max-width: 1100px) {
  .grid { grid-template-columns: 1fr; }
  .col-rail { order: -1; }
  .rail-card {
    position: static;
    max-height: none;
  }
}
.col { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.col-rail {
  position: sticky;
  top: 12px;
  align-self: start;
  max-height: calc(100vh - 88px);
}
.rail-card {
  max-height: calc(100vh - 88px);
  overflow: auto;
  border: 1px solid #e8e4f5;
  background: #fcfbff;
}
.rail-card :deep(.el-card__header) {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #fcfbff;
}
.card {
  border-radius: 14px;
  overflow: hidden;
}
.card :deep(.el-card__header) {
  padding: 12px 14px;
}
.card :deep(.el-card__body) {
  padding: 14px 14px 16px;
}
.card :deep(.el-form-item) {
  margin-bottom: 12px;
}
.card :deep(.el-form-item__label) {
  font-size: 12px !important;
}
.card-head {
  display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;
  font-weight: 650;
  color: #0f172a;
}
.hint { font-size: 12px; color: #8b93a7; }
.impact-panel { min-height: 48px; }
.impact-kpis {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 10px;
}
.impact-kpi {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px 10px;
}
.ik-label { font-size: 11px; color: #64748b; }
.ik-value { font-size: 18px; font-weight: 700; color: #0f172a; line-height: 1.3; }
.ik-hint { font-size: 11px; color: #94a3b8; margin-top: 2px; }
.impact-pubs {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  color: #334155;
}
.impact-pubs li { margin-bottom: 4px; }
.blueprint-box {
  background: #f8f7fc; border: 1px solid #e8e4f5; border-radius: 8px; padding: 10px 12px;
}
.blueprint-title { font-size: 12px; font-weight: 700; color: #5b21b6; margin-bottom: 6px; }
.blueprint-list { margin: 0; padding-left: 18px; font-size: 12px; color: #374151; }
.blueprint-list li { margin-bottom: 4px; }
.variant-fail-list { margin: 6px 0 8px; padding-left: 18px; font-size: 12px; line-height: 1.5; }
.muted { color: #9ca3af; }
.small { font-size: 11px; margin-top: 2px; }
.push-row { margin-bottom: 6px; }
.push-blocked { font-size: 12px; line-height: 1.4; }
.blocked { color: #b45309; }
.doc-draft-banner {
  font-size: 12px;
  line-height: 1.55;
  color: #9a3412;
  background: #fff7ed;
  border: 1px solid #fdba74;
  border-radius: 8px;
  padding: 8px 12px;
}
.channel-quality {
  font-size: 12px;
  font-weight: 650;
  line-height: 1.45;
  border-radius: 8px;
  padding: 8px 12px;
  border: 1px solid #e5e7eb;
}
.channel-quality.is-good {
  color: #065f46;
  background: #ecfdf5;
  border-color: #a7f3d0;
}
.channel-quality.is-warn {
  color: #92400e;
  background: #fffbeb;
  border-color: #fde68a;
}
.variant-body-wrap {
  width: 100%;
}
.variant-view-toggle {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.variant-html-preview {
  min-height: 320px;
  max-height: 560px;
  overflow: auto;
  padding: 16px 18px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  font-size: 15px;
  line-height: 1.75;
  color: #1f2937;
}
.variant-html-preview :deep(h1),
.variant-html-preview :deep(h2),
.variant-html-preview :deep(h3) {
  margin: 1em 0 0.5em;
  font-weight: 700;
  line-height: 1.35;
  color: #111827;
}
.variant-html-preview :deep(h2) { font-size: 1.15em; }
.variant-html-preview :deep(h3) { font-size: 1.05em; }
.variant-html-preview :deep(p) {
  margin: 0 0 0.85em;
}
.variant-html-preview :deep(strong) {
  font-weight: 700;
}
.variant-html-preview :deep(ul),
.variant-html-preview :deep(ol) {
  margin: 0 0 0.85em 1.25em;
  padding: 0;
}
.variant-html-preview :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0 16px;
  font-size: 14px;
}
.variant-html-preview :deep(th),
.variant-html-preview :deep(td) {
  border: 1px solid #d1d5db;
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
}
.variant-html-preview :deep(th) {
  background: #f3f4f6;
  font-weight: 650;
}
.variant-html-preview :deep(blockquote) {
  margin: 0 0 0.85em;
  padding: 8px 12px;
  border-left: 3px solid #93c5fd;
  background: #f8fafc;
  color: #475569;
}
.rail-title { font-weight: 700; font-size: 14px; color: #1e2330; line-height: 1.3; }
.rail-sub { font-size: 11px; color: #8b93a7; margin-top: 2px; }
.draft-banner {
  font-size: 12px;
  line-height: 1.55;
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 8px;
  padding: 8px 10px;
}
.score-block {
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 12px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
}
.score-block.tone-good { background: #ecfdf5; border-color: #a7f3d0; }
.score-block.tone-warn { background: #fffbeb; border-color: #fde68a; }
.score-block.tone-bad { background: #fef2f2; border-color: #fecaca; }
.score-row { display: flex; gap: 12px; align-items: center; }
.score-num { min-width: 72px; }
.score-big { font-size: 32px; font-weight: 750; color: #1e2330; line-height: 1; font-variant-numeric: tabular-nums; }
.score-den { font-size: 13px; color: #9ca3af; margin-left: 2px; }
.muted-num { color: #cbd5e1; }
.score-label { font-size: 13px; font-weight: 650; color: #374151; }
.score-hint { font-size: 11px; color: #6b7280; margin-top: 2px; line-height: 1.4; }
.score-bar {
  height: 6px; border-radius: 999px; background: #e5e7eb; margin-top: 10px; overflow: hidden;
}
.score-bar-fill { height: 100%; background: #7c3aed; border-radius: 999px; }
.tone-good .score-bar-fill { background: #059669; }
.tone-warn .score-bar-fill { background: #d97706; }
.tone-bad .score-bar-fill { background: #dc2626; }
.score-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.score-chip {
  font-size: 11px; color: #4b5563; background: #fff; border: 1px solid #e5e7eb;
  border-radius: 999px; padding: 2px 8px; font-variant-numeric: tabular-nums;
}
.score-chip.low { color: #b45309; border-color: #fcd34d; background: #fffbeb; }
.channel-pill {
  display: flex; gap: 8px; align-items: flex-start;
  border-radius: 8px; padding: 8px 10px; border: 1px solid #e5e7eb; background: #fff;
}
.channel-pill.is-ok { border-color: #a7f3d0; background: #ecfdf5; }
.channel-pill.is-warn { border-color: #fde68a; background: #fffbeb; }
.pill-mark { font-weight: 700; font-size: 14px; line-height: 1.2; }
.channel-pill.is-ok .pill-mark { color: #059669; }
.channel-pill.is-warn .pill-mark { color: #d97706; }
.pill-title { font-size: 12px; font-weight: 650; color: #374151; }
.pill-desc { font-size: 11px; color: #6b7280; margin-top: 2px; line-height: 1.45; }
.sec-row { display: flex; align-items: center; margin: 4px 0 6px; }
.sec { font-weight: 650; font-size: 12px; color: #374151; margin-bottom: 6px; }
.sec-meta { font-weight: 500; color: #9ca3af; margin-left: 6px; }
.all-pass {
  font-size: 12px; color: #047857; background: #ecfdf5; border-radius: 8px;
  padding: 8px 10px; border: 1px solid #a7f3d0;
}
.toggle-passed {
  display: block; width: 100%; margin: 8px 0 4px; padding: 6px 8px;
  border: 1px dashed #ddd6fe; border-radius: 8px; background: #faf5ff;
  color: #6d28d9; font-size: 12px; cursor: pointer; text-align: left;
}
.toggle-passed:hover { background: #f3e8ff; }
.check-list { list-style: none; padding: 0; margin: 0; }
.check-list li {
  display: flex; gap: 8px; padding: 8px 0; border-bottom: 1px solid #f3f0fa; font-size: 12px;
}
.check-title { font-weight: 650; color: #1f2937; line-height: 1.35; }
.check-msg { color: #6b7280; margin-top: 2px; line-height: 1.45; }
.check-action { color: #7c3aed; margin-top: 3px; line-height: 1.4; font-size: 11px; }
.pass-list .check-title { color: #6b7280; font-weight: 500; }
.pass-list .check-msg { color: #9ca3af; }
.patch-box, .ai-box {
  border-top: 1px solid #f0ecf9; padding-top: 10px;
}
.ai-summary {
  font-size: 12px; color: #4b5563; line-height: 1.5; margin-bottom: 8px;
  background: #f8fafc; border-radius: 8px; padding: 8px 10px;
}
.ok { color: #059669; font-weight: 700; }
.bad { color: #dc2626; font-weight: 700; }
.warn {
  color: #d97706; font-size: 11px; font-weight: 650; flex-shrink: 0;
  min-width: 28px;
}
.retrieve { font-size: 12px; color: #4b5563; }
.field-help {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.45;
  color: #9ca3af;
}
.fact-bind-card :deep(.el-card__body) {
  padding-top: 12px;
}
.fact-head-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.fact-status {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
}
.fact-status.ready {
  background: #ecfdf5;
  border-color: #a7f3d0;
}
.fact-status-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 8px;
  font-size: 13px;
  color: #374151;
  margin-bottom: 8px;
}
.fact-status-row .dot { color: #d1d5db; }
.fact-status-sub { margin-top: 8px; line-height: 1.45; }
.fact-section { margin-top: 12px; }
.fact-section-label {
  font-size: 12px;
  font-weight: 650;
  color: #4b5563;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.fact-empty {
  font-size: 12px;
  color: #9ca3af;
  padding: 8px 10px;
  border: 1px dashed #e5e7eb;
  border-radius: 8px;
  background: #fafafa;
}
.fact-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.fact-actions-end {
  margin-top: 8px;
  justify-content: flex-end;
}
.bound-chips {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.bound-chip {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  font-size: 12px;
  min-width: 0;
}
.bound-chip-main {
  flex: 1;
  min-width: 0;
}
.bound-chip-top {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.bound-chip-id {
  color: #6b7280;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.bound-chip-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #1f2937;
  font-weight: 600;
}
.bound-chip-stmt {
  margin-top: 4px;
  color: #374151;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: normal;
}
.bound-chip-stmt.is-empty { color: #9ca3af; }
.bound-chip-src {
  margin-top: 3px;
  color: #6b7280;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bound-chip-x {
  border: none;
  background: transparent;
  color: #9ca3af;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  padding: 0 2px;
  flex-shrink: 0;
}
.bound-chip-x:hover { color: #dc2626; }
.fact-option {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  max-width: 100%;
}
.fact-option-id { color: #9ca3af; flex-shrink: 0; }
.fact-option-text { min-width: 0; flex: 1; }
.fact-option-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}
.fact-option-stmt {
  color: #6b7280;
  font-size: 12px;
  line-height: 1.35;
  white-space: normal;
}
.retrieve-text {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.retrieve-stmt {
  color: #6b7280;
  font-size: 12px;
  line-height: 1.35;
}
.retrieve-box {
  padding: 8px 10px;
  border-radius: 8px;
  background: #f8f7fc;
  border: 1px solid #e8e4f5;
}
.retrieve-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  font-size: 12px;
  border-bottom: 1px solid #f3f0fa;
}
.retrieve-row:last-child { border-bottom: none; }
.retrieve-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #374151;
}
.retrieve-score {
  flex-shrink: 0;
  color: #7c3aed;
  font-variant-numeric: tabular-nums;
  font-size: 11px;
}
.bound-list {
  list-style: none; padding: 0; margin: 0 0 8px;
  font-size: 12px; color: #374151;
  max-height: 120px; overflow: auto;
  border: 1px solid #f0ecf9; border-radius: 8px; padding: 8px;
}
.bound-list li { padding: 2px 0; }
.cite-box {
  border: 1px solid #dbeafe;
  background: #eff6ff;
  border-radius: 8px;
  padding: 10px 12px;
}
.cite-box .section-title {
  font-size: 12px;
  font-weight: 650;
  color: #1e40af;
  margin-bottom: 8px;
}
.cite-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 6px 8px;
  padding: 6px 0;
  border-top: 1px solid #dbeafe;
  font-size: 12px;
  line-height: 1.45;
}
.cite-row:first-of-type { border-top: 0; padding-top: 0; }
.cite-sent { flex: 1 1 220px; color: #334155; min-width: 0; }
</style>
