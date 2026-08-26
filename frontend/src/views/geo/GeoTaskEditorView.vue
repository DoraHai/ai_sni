<script setup>
/**
 * Vue 母稿编辑器
 * Brief / 母稿 / 渠道稿（勾选生成、预览、复制）/ 检查
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  nextEditorStep,
  pipelineLabel,
  taskStatusLabel,
} from '../../utils/geoReportLabels'
import {
  applyGeoContentPatch,
  applyGeoRetrievedFacts,
  bindGeoTaskFacts,
  checkGeoContentTask,
  createGeoVariants,
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
  suggestGeoTaskBrief,
  fetchChannelBlueprint,
  waitGeoAsyncJob,
  getGeoAsyncJob,
  listGeoAsyncJobs,
  cancelGeoAsyncJob,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { getGeoPrototypeEditorSurface } from '../../utils/geoEditorSurface'
import RichTextMarkdownEditor from '../../components/RichTextMarkdownEditor.vue'

function toastError(e, fallback) {
  const msg = formatGeoError(e, fallback)
  ElMessage({ type: 'error', message: msg, duration: 6000, showClose: true })
  return msg
}

const route = useRoute()
const router = useRouter()
const { tenantId } = useGeoTenant()
const editorSurface = getGeoPrototypeEditorSurface()
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
  sentence_evidence: '逐句证据',
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

function stripCiteAppendix(md) {
  return String(md || '').replace(/\n+## 逐句证据[\s\S]*$/, '').trimEnd()
}

function applyArticleFromTask(t) {
  const a = t?.article
  article.title = a?.title || t?.title || ''
  article.body_markdown = sanitizeDraftHeadings(stripCiteAppendix(a?.body_markdown || ''))
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
    } else {
      const enabled = (publishingChannels.value || [])
        .filter((c) => c.enabled)
        .map((c) => c.channel_type || c.adapt_key)
        .filter(Boolean)
      if (enabled.length) channelPick.value = [...new Set(enabled)]
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
  if (nBound < 3 && nSelected < 3 && libraryVerifiedCount.value < 3) {
    return '生成母稿前需要至少 3 条已核验的可信材料，请先到知识库补充并核验资料'
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

async function ensurePrototypeMaterials() {
  if ((task.value?.facts || []).length >= 3) return true
  if (libraryVerifiedCount.value < 3) return false
  await bindTopVerified(3)
  return (task.value?.facts || []).length >= 3
}

const generateHint = ref('')
const activeJob = ref(null)
const variantFails = ref([])

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
const citeBlocking = computed(() => sentenceCites.value.filter((c) => c.needs_fact))
const citeOkCount = computed(() => sentenceCites.value.filter((c) => c.cited).length)

function removeCiteSentence(sent) {
  const body = article.body_markdown || ''
  const next = body
    .split('\n')
    .map((line) => (line.includes(sent.slice(0, 24)) ? '' : line))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
  article.body_markdown = next
  ElMessage.info('已从正文去掉该句，请保存后重新挂证据')
}

async function reciteEvidence() {
  await saveArticleBody()
}

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

async function followJob(jobId, { maxMs = 12 * 60 * 1000 } = {}) {
  persistJobId(jobId)
  try {
    const job = await waitGeoAsyncJob(tenantId.value, jobId, {
      intervalMs: 2000,
      maxMs,
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
    if (['pending', 'running'].includes(job.status)) {
      generateHint.value = `后台任务 #${job.id} 仍在跑，完成后刷新即可看到全部渠道稿`
      return job
    }
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
  if (!(await ensurePrototypeMaterials())) {
    const msg = '未能关联足够的已核验可信材料，请先到知识库检查资料状态'
    error.value = msg
    generateHint.value = msg
    ElMessage.warning(msg)
    return
  }
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
          (st === 'needs_fix' ? ' · 请点「检查就绪」并用补丁修齐规则' : '') +
          (editorSurface.showChannelVariants ? ' · 可到下方生成渠道稿' : '')
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

async function saveArticleBody({ silent = false } = {}) {
  if (!article.title.trim() || !article.body_markdown.trim()) {
    if (!silent) ElMessage.warning('标题与正文不能为空')
    return
  }
  if (!silent) busy.value = 'save'
  try {
    const outline = task.value?.article?.outline || {}
    task.value = await saveGeoArticle(tenantId.value, taskId.value, {
      title: article.title.trim(),
      body_markdown: stripCiteAppendix(article.body_markdown),
      outline,
    })
    applyArticleFromTask(task.value)
    lastSavedAt.value = new Date()
    if (!silent) ElMessage.success('母稿已保存')
  } catch (e) {
    if (!silent) toastError(e, '保存失败')
  } finally {
    if (!silent) busy.value = ''
  }
}

async function runCheck({ silent = false } = {}) {
  busy.value = 'check'
  try {
    const res = await checkGeoContentTask(tenantId.value, taskId.value, false)
    checkResult.value = res
    if (res.task) {
      task.value = res.task
      applyArticleFromTask(res.task)
    }
    if (!silent) {
      ElMessage.closeAll()
      if (res.ready) {
        ElMessage.success(`结构检查已通过，就绪分 ${res.geo_score ?? '—'}`)
      } else {
        ElMessage.warning(`尚未就绪，就绪分 ${res.geo_score ?? '—'}。请看右侧待补齐。`)
      }
    }
    return res
  } catch (e) {
    toastError(e, '检查失败')
    return null
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
      const msg = `「${checkLabel(code)}」写入后正文没有变化（${beforeLen}→${afterLen} 字）。请刷新后再试。`
      error.value = msg
      ElMessage.error(msg)
      return
    }

    const target = (res.checks || []).find((c) => c.code === code)
    const effective = res.effective !== false && (target ? target.passed : true)
    const scorePart = res.geo_score != null ? `就绪分 ${res.geo_score}` : ''
    const sizePart = `${beforeLen}→${afterLen} 字`
    if (effective) {
      ElMessage.success(
        `已按「${checkLabel(code)}」改完母稿（${sizePart}）${scorePart ? '，' + scorePart : ''}。`,
      )
    } else {
      const why = target?.message ? `：${target.message}` : ''
      const next = target?.action ? target.action : '请按右侧说明改完后再点检查'
      ElMessage.warning(
        `已尝试写入「${checkLabel(code)}」（${sizePart}），但这项仍未通过${why}。${next}${
          scorePart ? ` 目前${scorePart}。` : ''
        }`,
      )
    }
    error.value = ''
  } catch (e) {
    toastError(e, '写入失败')
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
      if (['pending', 'running'].includes(job.status)) {
        ElMessage.info('三路渠道稿还在后台写，完成后请刷新，不要重复点生成')
        return
      }
      t = await getGeoContentTask(tenantId.value, taskId.value)
      if (job.result_meta?.variant_polish) {
        t = { ...t, variant_polish: job.result_meta.variant_polish }
      }
    }
    applyTaskPayload(t)
    const created = (t.variants || []).map((v) => v.channel)
    const firstOk = created.find((ch) => channelPick.value.includes(ch)) || created[0]
    if (firstOk) {
      docTab.value = firstOk
      applyVariantFromTask()
    } else {
      docTab.value = 'master'
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
    variantFails.value = polish.failed || []
    const rejN = polish.rejected ?? variantFails.value.length
    const failMsg = variantFails.value
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
    ElMessage.info('当前没有可自动写入的修改，请先点「检查就绪」')
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
      `已写入 ${applied}/${codes.length} 项建议修改，${
        res.ready ? '结构检查已通过' : '仍有项未通过'
      }${res.geo_score != null ? `，就绪分 ${res.geo_score}` : ''}`,
    )
  } catch (e) {
    toastError(e, '批量写入失败')
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

/** Explain missing channel drafts only; review is not a workflow gate for this deployment. */
const publishGateHint = computed(() => {
  if (docTab.value === 'master') {
    return '请先切换到 website/wechat/zhihu 等渠道页签再回填'
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
  const hiddenCodes = new Set([
    'facts_bound_min',
    'sentence_evidence',
    'channel_variant_ready',
    'evidence_publishable',
  ])
  return out
    .filter((c) => !hiddenCodes.has(c.code))
    .map((c) => ({
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
function patchForCheck(code) {
  return (patches.value || []).find((p) => p.code === code) || null
}

function formatLintPoint(issue) {
  const excerpt = String(issue?.excerpt || '').replace(/\s+/g, ' ').trim()
  const why = String(issue?.detail || issue?.type || '').replace(/`/g, '').trim()
  if (excerpt && why) return `「${excerpt.slice(0, 56)}」 ${why}`
  if (excerpt) return `「${excerpt}」`
  return why
}

function checkDetails(c) {
  if (Array.isArray(c?.details) && c.details.length) return c.details
  if (c?.code !== 'fabrication_lint') return []
  const issues = checkResult.value?.lint?.issues || task.value?.rule_result?.lint?.issues || []
  return (issues || [])
    .filter((i) => i?.level === '高')
    .map(formatLintPoint)
    .filter(Boolean)
}
async function fixCheck(code) {
  const patch = patchForCheck(code)
  if (patch) {
    await applyPatch(code)
    return
  }
  await runCheck({ silent: true })
  if (patchForCheck(code)) {
    await applyPatch(code)
    return
  }
  ElMessage.closeAll()
  ElMessage.warning('这项需要对照右侧原文手工改，没有可自动写入的修改。')
}
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
const hasMasterDraft = computed(
  () => !!(task.value?.article || String(article.body_markdown || '').trim()),
)
const recordedPublications = computed(
  () => task.value?.publications || impact.value?.publications || [],
)
const failedVariantItems = computed(() => {
  const fromTask = task.value?.variant_polish?.failed
  if (Array.isArray(fromTask) && fromTask.length) return fromTask
  return Array.isArray(variantFails.value) ? variantFails.value : []
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
const factQuery = ref('')
const factTrustFilter = ref('all')

const filteredTrustedFacts = computed(() => {
  const q = String(factQuery.value || '').trim().toLowerCase()
  return (allFacts.value || []).filter((f) => {
    if (factTrustFilter.value === 'verified' && f.trust_level !== 'verified') return false
    if (factTrustFilter.value === 'needs_review' && f.trust_level !== 'needs_review') return false
    if (!q) return true
    const blob = `${f.id} ${f.title || ''} ${f.statement || ''}`.toLowerCase()
    return blob.includes(q)
  })
})

function isFactSelected(id) {
  const nid = Number(id)
  return (selectedFactIds.value || []).some((x) => Number(x) === nid)
}

function toggleFact(id) {
  const nid = Number(id)
  if (!Number.isFinite(nid) || nid <= 0) return
  const cur = (selectedFactIds.value || []).map(Number)
  if (cur.includes(nid)) selectedFactIds.value = cur.filter((x) => x !== nid)
  else selectedFactIds.value = [...cur, nid]
}

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
        key: o.channel_type || o.adapt_key || o.key,
        label: o.name || o.display_name || o.channel_type || o.adapt_key,
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

const currentPushTargets = computed(() => {
  const ch = String(docTab.value || '')
  if (!ch || ch === 'master') return []
  return (pushTargets.value || []).filter(
    (t) => t.channel_type === ch || t.adapt_key === ch,
  )
})
const currentPushReady = computed(() =>
  currentPushTargets.value.filter((t) => t.ready && t.account_id),
)
const currentPushBlock = computed(
  () => currentPushTargets.value.find((t) => !t.ready && !t.copy_only)?.block_reasons || [],
)
const COMPOSE_URLS = {
  encyclopedia: 'https://baike.baidu.com/',
  zhihu: 'https://zhuanlan.zhihu.com/write',
  wechat: 'https://mp.weixin.qq.com/',
  baijiahao: 'https://baijiahao.baidu.com/',
  toutiao: 'https://mp.toutiao.com/',
  community_qa: 'https://zhuanlan.zhihu.com/write',
}
const composeUrl = computed(() => {
  const t = currentPushTargets.value.find((x) => x.compose_url)
  if (t?.compose_url) return t.compose_url
  return COMPOSE_URLS[docTab.value] || ''
})
const canCopyPublish = computed(() => docTab.value && docTab.value !== 'master')
function openCompose() {
  if (composeUrl.value) window.open(composeUrl.value, '_blank', 'noopener')
}

watch(
  currentPushReady,
  (rows) => {
    if (!rows.length) return
    if (!rows.some((t) => t.account_id === webhookAccountId.value)) {
      webhookAccountId.value = rows[0].account_id
    }
  },
  { immediate: true },
)

const leftTab = ref('brief')
const showAdvancedBrief = ref(false)
const showCheckDrawer = ref(false)
const focusMode = ref(false)
const lastSavedAt = ref(null)
const handledIssueCodes = ref([])
let autosaveTimer = null

const unifiedStatus = computed(() => {
  if (busy.value === 'generate') return { key: 'generating', label: '草稿生成中' }
  if (!hasMasterDraft.value) return { key: 'empty', label: '待生成母稿' }
  if (failedChecks.value.length) return { key: 'review', label: '待人工审核' }
  if (checkResult.value && !failedChecks.value.length) {
    if (['published', 'approved'].includes(String(task.value?.status || ''))) {
      return { key: 'publishable', label: '可发布' }
    }
    return { key: 'passed', label: '检查通过' }
  }
  return { key: 'review', label: '待人工审核' }
})

const saveHint = computed(() => {
  if (busy.value === 'save') return '保存中…'
  if (!lastSavedAt.value) return '未自动保存'
  const d = lastSavedAt.value
  const pad = (n) => String(n).padStart(2, '0')
  return `已保存 ${pad(d.getHours())}:${pad(d.getMinutes())}`
})

const mustIssues = computed(() =>
  failedChecks.value.filter((c) => !handledIssueCodes.value.includes(c.code)),
)
const suggestIssues = computed(() =>
  (geoActions.value || []).filter((a) => !handledIssueCodes.value.includes(a.code || a.message)),
)

function isFactCited(id) {
  return (sentenceCites.value || []).some((c) => Number(c.fact_id) === Number(id))
}

function locateIssue(item) {
  const details = checkDetails(item)
  const needle = String(details[0] || item?.message || item?.excerpt || '').replace(/[「」]/g, '')
  const excerpt = needle.match(/「([^」]+)」/)?.[1] || needle.slice(0, 32)
  locateInEditor(excerpt)
}

function locateInEditor(text) {
  const root = document.querySelector('.rich-content')
  const needle = String(text || '').trim().slice(0, 28)
  if (!root || needle.length < 4) {
    ElMessage.info('没有可定位的正文片段')
    return
  }
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  while (walker.nextNode()) {
    const node = walker.currentNode
    const i = node.textContent.indexOf(needle)
    if (i < 0) continue
    const range = document.createRange()
    range.setStart(node, i)
    range.setEnd(node, Math.min(i + needle.length, node.textContent.length))
    const sel = window.getSelection()
    sel.removeAllRanges()
    sel.addRange(range)
    node.parentElement?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    return
  }
  ElMessage.info('正文中未找到对应片段，请按建议手工修改')
}

function markHandled(code) {
  const key = String(code || '')
  if (!key || handledIssueCodes.value.includes(key)) return
  handledIssueCodes.value = [...handledIssueCodes.value, key]
}

function toggleFocus() {
  focusMode.value = !focusMode.value
  if (focusMode.value) showCheckDrawer.value = false
  window.dispatchEvent(new CustomEvent('geo-editor-focus', { detail: focusMode.value }))
}

function onMoreCommand(cmd) {
  if (cmd === 'save') return saveArticleBody()
  if (cmd === 'copy') return copyCurrentDoc()
  if (cmd === 'check') {
    showCheckDrawer.value = true
    return runCheck()
  }
  if (cmd === 'variants') return genVariants()
  if (cmd === 'refresh') return load()
  if (cmd === 'focus') return toggleFocus()
}

watch(
  () => article.body_markdown,
  () => {
    if (!hasMasterDraft.value) return
    clearTimeout(autosaveTimer)
    autosaveTimer = setTimeout(() => {
      saveArticleBody({ silent: true })
    }, 8000)
  },
)

watch([tenantId, taskId], load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="ed-shell" :class="{ focus: focusMode, 'check-open': showCheckDrawer && !focusMode }">
    <header class="ed-top">
      <button type="button" class="ed-back" @click="router.push('/geo/tasks')">← 任务列表</button>
      <div class="ed-ident">
        <div class="ed-kicker">#{{ taskId }} · {{ unifiedStatus.label }}</div>
        <div class="ed-name">{{ article.title || task?.title || '未命名文章' }}</div>
      </div>
      <div class="ed-top-actions">
        <span class="ed-save">{{ saveHint }}</span>
        <el-button
          type="primary"
          :loading="busy === 'generate'"
          :disabled="!task"
          @click="generate"
        >
          {{ hasMasterDraft ? '更新母稿' : '生成母稿' }}
        </el-button>
        <el-button :class="{ 'is-active': showCheckDrawer }" @click="showCheckDrawer = !showCheckDrawer">
          检查
        </el-button>
        <el-dropdown trigger="click" @command="onMoreCommand">
          <el-button>更多</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="save">保存正文</el-dropdown-item>
              <el-dropdown-item command="copy">复制</el-dropdown-item>
              <el-dropdown-item command="check">检查就绪</el-dropdown-item>
              <el-dropdown-item command="variants" :disabled="!hasMasterDraft">生成渠道稿</el-dropdown-item>
              <el-dropdown-item command="refresh" divided>刷新</el-dropdown-item>
              <el-dropdown-item command="focus">{{ focusMode ? '退出专注' : '专注模式' }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      closable
      class="ed-alert"
      @close="error = ''"
    />

    <div v-if="task" class="ed-body">
      <aside v-show="!focusMode" class="ed-left">
        <div class="ed-tabs">
          <button type="button" :class="{ on: leftTab === 'brief' }" @click="leftTab = 'brief'">内容设定</button>
          <button type="button" :class="{ on: leftTab === 'facts' }" @click="leftTab = 'facts'">
            可信材料 {{ selectedFactIds.length ? selectedFactIds.length : '' }}
          </button>
        </div>

        <div v-show="leftTab === 'brief'" class="ed-pane">
          <div v-if="briefSuggestHint" class="ed-hint">
            {{ briefSuggestHint }}
            <span v-if="briefLocalDraft"> · 本地草稿未保存</span>
          </div>
          <el-form label-position="top" size="small">
            <el-form-item label="行业" required>
              <el-input v-model="brief.industry" />
            </el-form-item>
            <el-form-item label="受众" required>
              <el-input v-model="brief.audience" />
            </el-form-item>
            <el-form-item label="意图" required>
              <el-select v-model="brief.intent" clearable style="width: 100%">
                <el-option v-for="it in catalog?.intents || []" :key="it.key" :label="it.label" :value="it.key" />
              </el-select>
            </el-form-item>
            <el-form-item label="内容类型" required>
              <el-select v-model="brief.content_type" clearable style="width: 100%">
                <el-option v-for="it in catalog?.content_types || []" :key="it.key" :label="it.label" :value="it.key" />
              </el-select>
            </el-form-item>
            <el-form-item label="CTA" required>
              <el-input v-model="brief.cta" />
            </el-form-item>
            <button type="button" class="ed-adv" @click="showAdvancedBrief = !showAdvancedBrief">
              {{ showAdvancedBrief ? '收起高级设置' : '高级设置' }}
            </button>
            <template v-if="showAdvancedBrief">
              <el-form-item label="禁用表述">
                <el-input v-model="brief.banned_claims" placeholder="逗号分隔" />
              </el-form-item>
              <el-form-item v-if="editorSurface.briefFields.includes('notes')" label="备注">
                <el-input v-model="brief.notes" />
              </el-form-item>
              <template v-if="editorSurface.briefFields.includes('ai_question')">
                <el-form-item label="AI 问题">
                  <el-input v-model="brief.ai_question" />
                </el-form-item>
                <el-form-item label="不推荐原因">
                  <el-input v-model="brief.not_recommended_reasons" type="textarea" :rows="2" />
                </el-form-item>
                <el-form-item label="信息缺口">
                  <el-select v-model="brief.info_gaps" multiple collapse-tags collapse-tags-tooltip filterable clearable style="width: 100%">
                    <el-option v-for="g in infoGapOptions" :key="g.key" :label="g.label" :value="g.key" />
                  </el-select>
                </el-form-item>
                <el-form-item label="推荐场景">
                  <el-input v-model="brief.recommend_when" />
                </el-form-item>
                <el-form-item label="竞品">
                  <el-input v-model="brief.competitors" />
                </el-form-item>
                <el-form-item label="必须覆盖">
                  <el-input v-model="brief.must_cover" />
                </el-form-item>
              </template>
            </template>
          </el-form>
          <div class="ed-left-foot">
            <el-button size="small" :loading="busy === 'suggest'" @click="suggestBrief">AI 建议</el-button>
            <el-button size="small" type="primary" :loading="busy === 'brief'" @click="saveBrief">保存设定</el-button>
          </div>
        </div>

        <div v-show="leftTab === 'facts'" class="ed-pane">
          <div class="ed-fact-status" :class="{ ready: factsBindReady }">
            已绑 {{ boundFacts.length }} · 已核验 {{ boundVerifiedCount }}/需≥3
            <router-link class="ed-link" to="/geo/knowledge">管理知识库</router-link>
          </div>
          <el-input v-model="factQuery" clearable size="small" placeholder="搜索材料" class="mb" />
          <el-radio-group v-model="factTrustFilter" size="small" class="mb">
            <el-radio-button label="all">全部</el-radio-button>
            <el-radio-button label="verified">已核验</el-radio-button>
            <el-radio-button label="needs_review">待核验</el-radio-button>
          </el-radio-group>
          <div class="ed-fact-list">
            <label
              v-for="f in filteredTrustedFacts"
              :key="f.id"
              class="ed-fact"
              :class="{ selected: isFactSelected(f.id) }"
            >
              <input type="checkbox" :checked="isFactSelected(f.id)" @change="toggleFact(f.id)">
              <div class="ed-fact-main">
                <div class="ed-fact-top">
                  <span class="ed-fact-title">{{ f.title || '未命名' }}</span>
                  <span class="ed-pill" :class="f.trust_level === 'verified' ? 'ok' : 'warn'">
                    {{ trustLabel(f.trust_level) }}
                  </span>
                </div>
                <div class="ed-fact-sum">{{ factSnippet(f, 72) || '无摘要' }}</div>
                <div class="ed-fact-cite">{{ isFactCited(f.id) ? '已引用' : '未引用' }}</div>
              </div>
            </label>
            <div v-if="!filteredTrustedFacts.length" class="ed-empty">
              {{ allFacts.length ? '没有匹配的材料' : '知识库暂无事实，请先去补充' }}
            </div>
          </div>
          <div class="ed-left-foot">
            <el-button
              type="primary"
              :loading="busy === 'facts'"
              :disabled="!selectedFactIds.length"
              @click="saveFacts"
            >
              绑定已选材料（{{ selectedFactIds.length }}）
            </el-button>
          </div>
        </div>
      </aside>

      <main class="ed-center">
        <div class="ed-doc">
          <el-tabs
            v-if="editorSurface.showChannelVariants"
            :model-value="docTab"
            class="ed-doc-tabs"
            @tab-change="onDocTabChange"
          >
            <el-tab-pane label="母稿" name="master" />
            <el-tab-pane
              v-for="v in variants"
              :key="v.channel"
              :name="v.channel"
              :label="`${channelLabel(v.channel)}${v.stale ? ' *' : ''}`"
            />
          </el-tabs>
          <div class="ed-doc-note">正在编辑：{{ docTab === 'master' ? '母稿' : channelLabel(docTab) }}</div>

          <el-alert
            v-if="activeJob && ['pending', 'running'].includes(activeJob.status)"
            type="info"
            show-icon
            class="mb"
            :closable="false"
            :title="`后台任务 #${activeJob.id} · ${activeJob.status}`"
          />
          <div v-if="generateHint" class="ed-hint mb">{{ generateHint }}</div>

          <template v-if="docTab === 'master'">
            <el-input
              v-model="article.title"
              class="ed-doc-title"
              placeholder="文章标题"
            />
            <RichTextMarkdownEditor
              :key="`master-body-${task?.article?.version_no || 0}`"
              v-model="article.body_markdown"
              :min-height="320"
              max-height="min(58vh, 640px)"
              placeholder="在这里编辑母稿正文…"
            />
            <div class="ed-doc-status">
              <span>{{ (article.body_markdown || '').replace(/\s/g, '').length }} 字</span>
              <span v-if="task.article">v{{ task.article.version_no }}</span>
              <span>{{ saveHint }}</span>
            </div>
          </template>
          <template v-else-if="editorSurface.showChannelVariants">
            <el-input v-model="variantEdit.title" class="ed-doc-title" placeholder="渠道稿标题" />
            <div class="variant-html-preview" v-html="variantEdit.body_html || '<p class=muted>暂无预览，请先生成渠道稿</p>'" />
            <div class="ed-doc-status">
              <el-button size="small" @click="copyCurrentDoc">复制成稿</el-button>
              <el-button v-if="composeUrl" size="small" @click="openCompose">打开发布页</el-button>
            </div>
          </template>
        </div>
      </main>

      <aside v-if="showCheckDrawer && !focusMode" class="ed-check">
        <div class="ed-check-head">
          <div>
            <div class="ed-check-score">就绪度 {{ scoreMeta.score != null ? scoreMeta.headline : '—' }}</div>
            <div class="ed-check-sub">{{ mustIssues.length }} 项需要处理</div>
          </div>
          <el-button size="small" :loading="busy === 'check'" @click="runCheck">重新检查</el-button>
        </div>

        <div v-if="mustIssues.length" class="ed-iss-block">
          <div class="ed-iss-label must">必须处理</div>
          <div v-for="c in mustIssues" :key="c.code" class="ed-iss">
            <div class="ed-iss-title">{{ c.label || c.message }}</div>
            <div class="ed-iss-msg">{{ c.message }}</div>
            <div class="ed-iss-acts">
              <button type="button" @click="locateIssue(c)">定位正文</button>
              <button type="button" @click="fixCheck(c.code)">查看建议</button>
              <button type="button" @click="markHandled(c.code)">标记已处理</button>
            </div>
          </div>
        </div>

        <div v-if="suggestIssues.length" class="ed-iss-block">
          <div class="ed-iss-label warn">建议优化</div>
          <div v-for="a in suggestIssues" :key="a.code || a.message" class="ed-iss">
            <div class="ed-iss-title">{{ a.message }}</div>
            <div v-if="a.action" class="ed-iss-msg">{{ a.action }}</div>
            <div class="ed-iss-acts">
              <button type="button" @click="locateIssue(a)">定位正文</button>
              <button type="button" @click="markHandled(a.code || a.message)">标记已处理</button>
            </div>
          </div>
        </div>

        <div v-if="!mustIssues.length && checks.length" class="ed-all-ok">结构项已全部通过，仍建议人工过目</div>

        <button
          v-if="passedChecks.length"
          type="button"
          class="ed-passed-toggle"
          @click="showPassedChecks = !showPassedChecks"
        >
          {{ showPassedChecks ? '收起' : '已通过' }} {{ passedChecks.length }} 项
        </button>
        <ul v-if="showPassedChecks && passedChecks.length" class="ed-passed">
          <li v-for="c in passedChecks" :key="c.code">{{ c.label }}</li>
        </ul>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.ed-shell {
  --ed-blue: #2563eb;
  --ed-purple: #7c3aed;
  --ed-green: #059669;
  --ed-orange: #d97706;
  --ed-red: #dc2626;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  height: calc(100vh - 8px);
  min-width: 0;
  overflow: hidden;
  padding: 10px 12px 12px;
  background: #f4f5f8;
  color: #1f2937;
}
.ed-top {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: none;
  min-height: 56px;
  padding: 8px 4px 10px;
}
.ed-back {
  border: 0;
  background: transparent;
  color: var(--ed-blue);
  font-weight: 650;
  cursor: pointer;
  white-space: nowrap;
}
.ed-ident { min-width: 0; flex: 1; }
.ed-kicker { font-size: 12px; color: #6b7280; }
.ed-name {
  font-size: 16px;
  font-weight: 750;
  letter-spacing: -0.02em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ed-top-actions { display: flex; align-items: center; gap: 8px; flex: none; }
.ed-save { font-size: 12px; color: #9ca3af; }
.ed-top-actions :deep(.el-button--primary) {
  background: var(--ed-blue);
  border-color: var(--ed-blue);
  border-radius: 8px;
}
.ed-top-actions :deep(.el-button) { border-radius: 8px; }
.ed-top-actions .is-active { color: var(--ed-purple); border-color: #ddd6fe; background: #f5f3ff; }
.ed-alert { margin: 0 0 8px; }
.ed-body {
  display: grid;
  grid-template-columns: 312px minmax(720px, 1fr);
  gap: 12px;
  min-height: 0;
  flex: 1;
}
.ed-shell.check-open .ed-body {
  grid-template-columns: 312px minmax(0, 1fr) 340px;
}
.ed-shell.focus .ed-body { grid-template-columns: minmax(0, 1fr); }
.ed-left, .ed-check, .ed-center, .ed-doc, .ed-pane {
  min-height: 0;
}
.ed-left, .ed-check {
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid #e7e9ee;
  border-radius: 12px;
  overflow: hidden;
}
.ed-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid #eef0f4;
  flex: none;
}
.ed-tabs button {
  flex: 1;
  border: 0;
  background: transparent;
  padding: 10px 8px;
  font-size: 13px;
  font-weight: 650;
  color: #6b7280;
  cursor: pointer;
}
.ed-tabs button.on { color: var(--ed-purple); box-shadow: inset 0 -2px 0 var(--ed-purple); }
.ed-pane {
  flex: 1;
  overflow: auto;
  padding: 12px;
}
.ed-left-foot {
  display: flex;
  gap: 8px;
  padding-top: 10px;
}
.ed-adv {
  border: 0;
  background: transparent;
  color: #6b7280;
  font-size: 12px;
  padding: 4px 0 10px;
  cursor: pointer;
}
.ed-link { margin-left: 8px; color: var(--ed-blue); font-size: 12px; }
.ed-fact-status { font-size: 12px; color: #6b7280; margin-bottom: 8px; }
.ed-fact-status.ready { color: var(--ed-green); }
.ed-fact-list { display: flex; flex-direction: column; gap: 8px; }
.ed-fact {
  display: flex;
  gap: 8px;
  padding: 10px;
  border: 1px solid #eef0f4;
  border-radius: 8px;
  cursor: pointer;
}
.ed-fact.selected { border-color: #ddd6fe; background: #faf8ff; }
.ed-fact-top { display: flex; justify-content: space-between; gap: 8px; }
.ed-fact-title { font-weight: 650; font-size: 13px; }
.ed-fact-sum { font-size: 12px; color: #6b7280; margin-top: 4px; line-height: 1.45; }
.ed-fact-cite { font-size: 11px; color: #9ca3af; margin-top: 4px; }
.ed-pill { font-size: 11px; border-radius: 6px; padding: 1px 6px; }
.ed-pill.ok { color: var(--ed-green); background: #ecfdf5; }
.ed-pill.warn { color: var(--ed-orange); background: #fffbeb; }
.ed-empty { font-size: 12px; color: #9ca3af; padding: 16px 0; }
.ed-center {
  display: flex;
  background: #fff;
  border: 1px solid #e7e9ee;
  border-radius: 12px;
  overflow: hidden;
}
.ed-doc {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  padding: 8px 0 0;
}
.ed-doc-tabs { padding: 0 24px; }
.ed-doc-note { padding: 0 24px 8px; font-size: 12px; color: #9ca3af; }
.ed-doc-title :deep(.el-input__wrapper) {
  box-shadow: none !important;
  background: transparent;
  padding: 4px 24px;
}
.ed-doc-title :deep(.el-input__inner) {
  font-size: 22px;
  font-weight: 750;
  letter-spacing: -0.03em;
}
.ed-doc :deep(.rich-editor) {
  border: 0;
  border-radius: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.ed-doc :deep(.rich-toolbar) {
  position: sticky;
  top: 0;
  z-index: 2;
}
.ed-doc :deep(.rich-content) {
  max-width: 840px;
  margin: 0 auto;
  font-size: 16px;
  line-height: 1.7;
}
.ed-doc-status {
  display: flex;
  gap: 12px;
  padding: 8px 24px;
  border-top: 1px solid #eef0f4;
  color: #9ca3af;
  font-size: 12px;
  flex: none;
}
.ed-check { width: 340px; }
.ed-check-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  border-bottom: 1px solid #eef0f4;
}
.ed-check-score { font-weight: 750; }
.ed-check-sub { font-size: 12px; color: #6b7280; }
.ed-iss-block { padding: 10px 12px 0; }
.ed-iss-label { font-size: 12px; font-weight: 700; margin-bottom: 6px; }
.ed-iss-label.must { color: var(--ed-red); }
.ed-iss-label.warn { color: var(--ed-orange); }
.ed-iss {
  border: 1px solid #f3f4f6;
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 8px;
}
.ed-iss-title { font-size: 13px; font-weight: 650; }
.ed-iss-msg { font-size: 12px; color: #6b7280; margin-top: 4px; line-height: 1.45; }
.ed-iss-acts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.ed-iss-acts button {
  border: 0;
  background: #f3f4f6;
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 12px;
  cursor: pointer;
}
.ed-all-ok { margin: 12px; padding: 10px; border-radius: 8px; background: #ecfdf5; color: var(--ed-green); font-size: 13px; }
.ed-passed-toggle {
  border: 0;
  background: transparent;
  color: #6b7280;
  font-size: 12px;
  padding: 10px 12px;
  cursor: pointer;
  text-align: left;
}
.ed-passed { margin: 0 12px 12px; padding-left: 18px; font-size: 12px; color: #6b7280; }
.ed-hint { font-size: 12px; color: var(--ed-blue); line-height: 1.45; }
.mb { margin-bottom: 10px; }
@media (max-width: 1280px) {
  .ed-body,
  .ed-shell.check-open .ed-body {
    grid-template-columns: 280px minmax(0, 1fr);
  }
  .ed-check { grid-column: 1 / -1; width: auto; max-height: 280px; }
}
@media (max-width: 900px) {
  .ed-body,
  .ed-shell.check-open .ed-body { grid-template-columns: 1fr; }
  .ed-left { max-height: 320px; }
}
.editor {
  box-sizing: border-box;
  width: 100%;
  max-width: none;
  min-width: 0;
  overflow-x: hidden;
  min-height: calc(100vh - 24px);
  padding: 16px 20px 40px;
  background:
    radial-gradient(900px 320px at 12% -8%, rgba(124, 58, 237, 0.07), transparent 60%),
    radial-gradient(700px 280px at 92% 0%, rgba(99, 102, 241, 0.05), transparent 55%),
    linear-gradient(180deg, #f5f6fa 0%, #f7f8fb 100%);
}
.toolbar {
  display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap;
  margin-bottom: 14px; align-items: center;
}
.page-toolbar {
  min-height: 58px;
  padding: 10px 14px 10px 10px;
  border: 1px solid rgba(232, 234, 240, 0.95);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(10px);
  box-shadow: 0 8px 24px rgba(30, 35, 48, 0.04);
}
.left, .right, .row-actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.channel-next-hint {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid #ebe4f8;
  border-radius: 10px;
  background: #fbf9ff;
  color: #5b5670;
  font-size: 12px;
  line-height: 1.55;
}
.channel-next-hint a { color: #6d28d9; font-weight: 600; }
.meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding-left: 14px;
  border-left: 1px solid #ebecef;
}
.title { font-size: 16px; font-weight: 750; color: #161b26; letter-spacing: -0.02em; line-height: 1.3; }
.sub {
  max-width: min(520px, 46vw);
  overflow: hidden;
  color: #8a93a3;
  font-size: 12px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.back-button { font-weight: 600; }
.task-state {
  padding: 5px 10px;
  border: 1px solid #ebe4f8;
  border-radius: 999px;
  background: linear-gradient(180deg, #fbf9ff, #f6f2fc);
  color: #6b5b8a;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.refresh-button { margin-left: 2px; }
.editor :deep(.el-button) {
  --el-button-size: 36px;
  height: 36px;
  padding: 0 16px;
  font-size: 13px;
  font-weight: 650;
  border-radius: 10px;
}
.editor :deep(.el-button--small) {
  --el-button-size: 32px;
  height: 32px;
  padding: 0 12px;
  font-size: 12px;
}
.editor :deep(.el-button.is-text) {
  height: auto;
  padding: 6px 10px;
}
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
  grid-template-columns: minmax(240px, 300px) minmax(0, 1fr) minmax(280px, 340px);
  grid-template-areas: "brief doc rail";
  gap: 16px;
  align-items: start;
  width: 100%;
  min-width: 0;
}
.col-left { grid-area: brief; }
.col-main { grid-area: doc; min-width: 0; }
.col-main > .card:first-child {
  max-height: calc(100vh - 108px);
  display: flex;
  flex-direction: column;
}
.col-main > .card:first-child :deep(.el-card__header) {
  flex: none;
}
.col-main > .card:first-child :deep(.el-card__body) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}
.col-rail { grid-area: rail; }
@media (min-width: 1800px) {
  .grid {
    grid-template-columns: 320px minmax(0, 1fr) 340px;
    gap: 20px;
  }
}
/* 侧栏约 216px：1680 视口时内容区才够三列；笔记本先两列 */
@media (max-width: 1679px) {
  .grid {
    grid-template-columns: minmax(240px, 280px) minmax(0, 1fr);
    grid-template-areas:
      "brief doc"
      "rail rail";
    gap: 14px;
  }
  .col-rail {
    position: static;
    max-height: none;
  }
  .rail-card { max-height: none; }
}
@media (max-width: 1099px) {
  .grid {
    grid-template-columns: 1fr;
    grid-template-areas:
      "doc"
      "brief"
      "rail";
    gap: 12px;
  }
  .editor { padding: 10px 12px 28px; }
  .page-toolbar {
    align-items: stretch;
    min-height: 0;
    padding: 10px 12px;
  }
  .page-toolbar .left,
  .page-toolbar .right {
    width: 100%;
    justify-content: space-between;
  }
  .meta { padding-left: 10px; }
  .sub {
    max-width: 100%;
    white-space: normal;
  }
  .doc-card-head { flex-wrap: wrap; }
  .doc-heading-sub { display: none; }
  .next-step {
    flex-direction: column;
    align-items: stretch;
  }
  .card :deep(.el-card__header),
  .card :deep(.el-card__body) {
    padding: 12px 14px;
  }
}
@media (max-width: 720px) {
  .editor { padding: 8px 8px 24px; }
  .title { font-size: 15px; }
  .row-actions { width: 100%; }
}
.col { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
@media (min-width: 1680px) {
  .col-rail {
    position: sticky;
    top: 14px;
    align-self: start;
    max-height: calc(100vh - 88px);
  }
  .rail-card { max-height: calc(100vh - 88px); }
}
.rail-card {
  overflow: auto;
  border: 1px solid #ebe6f5 !important;
  background: linear-gradient(180deg, #fffeff 0%, #fbfaff 100%) !important;
  box-shadow: 0 10px 28px rgba(88, 60, 160, 0.05) !important;
}
.rail-card :deep(.el-card__header) {
  position: sticky;
  top: 0;
  z-index: 1;
  background: linear-gradient(180deg, #fffeff, #fbfaff);
  border-bottom-color: #efeaf8;
}
.card {
  border: 1px solid #e8eaef;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 8px 26px rgba(30, 35, 48, 0.045);
  background: #fff;
}
.card :deep(.el-card__header) {
  padding: 16px 18px;
  border-bottom-color: #f0f2f6;
  background: linear-gradient(180deg, #fcfcfd 0%, #fff 100%);
}
.card :deep(.el-card__body) {
  padding: 18px 18px 20px;
}
.card :deep(.el-form-item) {
  margin-bottom: 16px;
}
.card :deep(.el-form-item__label) {
  font-size: 12px !important;
  color: #647082 !important;
  font-weight: 650 !important;
}
.card :deep(.el-input__wrapper),
.card :deep(.el-select__wrapper) {
  border-radius: 9px;
  box-shadow: 0 0 0 1px #e4e7ee inset;
}
.card :deep(.el-input__wrapper:hover),
.card :deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px #cfc6e8 inset;
}
.card :deep(.el-input__wrapper.is-focus),
.card :deep(.el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 1px #8b5cf6 inset, 0 0 0 3px rgba(124, 58, 237, 0.1) !important;
}
.card-head {
  display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;
  font-weight: 650;
  color: #151a24;
}
.doc-card-head { flex-wrap: nowrap; }
.col-main > .card:first-child {
  box-shadow: 0 10px 32px rgba(30, 35, 48, 0.05);
  border-color: #e4e7ef;
}
.doc-heading { color: #121826; font-size: 15px; font-weight: 750; letter-spacing: -0.02em; line-height: 1.3; }
.doc-heading-sub { margin-top: 3px; color: #95a0b0; font-size: 12px; font-weight: 400; }
.doc-form :deep(.el-form-item__label) {
  height: auto;
  margin-bottom: 7px;
  color: #586274;
  font-weight: 650;
  line-height: 1.35;
}
.title-form-item { margin-bottom: 18px !important; }
.body-form-item { margin-bottom: 8px !important; }
.body-form-item :deep(.rich-content) {
  overscroll-behavior: contain;
}
.article-title-input :deep(.el-input__wrapper) {
  min-height: 48px;
  padding: 0 16px;
  border-radius: 10px;
  box-shadow: 0 0 0 1px #e2e6ee inset;
  background: #fafbfd;
}
.article-title-input :deep(.el-input__wrapper.is-focus) {
  background: #fff;
}
.article-title-input :deep(.el-input__inner) {
  color: #121826;
  font-size: 16px;
  font-weight: 650;
  letter-spacing: -0.01em;
}
.document-meta {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin: 2px 0 10px;
  color: #98a1af;
  font-size: 11px;
}
.document-meta span + span::before {
  margin-right: 8px;
  color: #d4d8df;
  content: '·';
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
  font-size: 12.5px;
  line-height: 1.6;
  color: #7c4a1e;
  background: linear-gradient(180deg, #fffaf3, #fff6eb);
  border: 1px solid #f0d9b5;
  border-radius: 10px;
  padding: 10px 14px;
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
.rail-title { font-weight: 750; font-size: 14px; color: #161b26; letter-spacing: -0.01em; line-height: 1.3; }
.rail-sub { font-size: 11px; color: #8f98a8; margin-top: 3px; }
.draft-banner {
  font-size: 12px;
  line-height: 1.55;
  color: #6b4c1f;
  background: linear-gradient(180deg, #fffaf2, #fff7eb);
  border: 1px solid #eed9b5;
  border-radius: 10px;
  padding: 10px 12px;
}
.score-block {
  border-radius: 14px;
  padding: 14px;
  margin-bottom: 14px;
  background: linear-gradient(160deg, #f8f6ff 0%, #f5f7fb 100%);
  border: 1px solid #ebe4f7;
}
.score-block.tone-good { background: linear-gradient(160deg, #f0fdf7, #f7faf8); border-color: #b7ebd0; }
.score-block.tone-warn { background: linear-gradient(160deg, #fff9ef, #faf8f4); border-color: #f0d9a0; }
.score-block.tone-bad { background: linear-gradient(160deg, #fff5f5, #faf7f7); border-color: #f3c4c4; }
.score-row { display: flex; gap: 14px; align-items: center; }
.score-num { min-width: 78px; }
.score-big { font-size: 36px; font-weight: 780; color: #161b26; line-height: 1; font-variant-numeric: tabular-nums; letter-spacing: -0.03em; }
.score-den { font-size: 13px; color: #9aa3b2; margin-left: 2px; }
.muted-num { color: #cbd5e1; }
.score-label { font-size: 13px; font-weight: 700; color: #2f3747; }
.score-hint { font-size: 11px; color: #748094; margin-top: 3px; line-height: 1.45; }
.score-bar {
  height: 7px; border-radius: 999px; background: rgba(15, 23, 42, 0.08); margin-top: 12px; overflow: hidden;
}
.score-bar-fill { height: 100%; background: linear-gradient(90deg, #8b5cf6, #7c3aed); border-radius: 999px; }
.tone-good .score-bar-fill { background: linear-gradient(90deg, #34d399, #059669); }
.tone-warn .score-bar-fill { background: linear-gradient(90deg, #fbbf24, #d97706); }
.tone-bad .score-bar-fill { background: linear-gradient(90deg, #f87171, #dc2626); }
.score-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.score-chip {
  font-size: 11px; color: #4b5563; background: rgba(255,255,255,0.88); border: 1px solid #e7eaf0;
  border-radius: 999px; padding: 3px 9px; font-variant-numeric: tabular-nums; font-weight: 600;
}
.score-chip.low { color: #b45309; border-color: #f5d78a; background: #fff8e8; }
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
.check-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
.check-list > li {
  display: flex; gap: 10px; padding: 10px 11px; border: 1px solid #f0ecf8; border-radius: 10px;
  background: #fffeff; font-size: 12px;
}
.issue-points {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.issue-points li {
  display: block;
  margin: 0;
  padding: 6px 8px;
  border: 1px dashed #f0c9c9;
  border-radius: 8px;
  background: #fff;
  color: #9f1239;
  font-size: 12px;
  line-height: 1.45;
}
.fail-list > li { border-color: #f3e0e0; background: #fffbfb; }
.pass-list > li { border-color: #e7f3ec; background: #fbfefc; }
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
.trusted-materials {
  margin-top: 6px;
  padding: 14px;
  border-radius: 12px;
  background: linear-gradient(180deg, #faf9ff, #f7f8fc);
  border: 1px solid #ebe7f5;
}
.trusted-materials-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 10px;
}
.trusted-materials-title {
  font-size: 13px;
  font-weight: 750;
  color: #3f3558;
}
.trusted-materials .hint {
  margin-top: 3px;
  margin-bottom: 0;
  line-height: 1.45;
}
.facts-link {
  flex: none;
  font-size: 12px;
  font-weight: 650;
  color: #7c3aed;
  text-decoration: none;
  white-space: nowrap;
}
.facts-link:hover { text-decoration: underline; }
.trusted-status {
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #9a3412;
  font-size: 12px;
}
.trusted-status.ready {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #047857;
}
.trusted-filters {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
}
.trusted-search { width: 100%; }
.fact-picker {
  max-height: 280px;
  overflow: auto;
  margin-bottom: 10px;
  padding: 4px;
  border: 1px solid #e8eaf0;
  border-radius: 10px;
  background: #fff;
}
.fact-pick-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin: 0;
  padding: 10px;
  border-radius: 8px;
  cursor: pointer;
  border: 1px solid transparent;
}
.fact-pick-row + .fact-pick-row { border-top: 1px solid #f1f3f7; }
.fact-pick-row:hover { background: #f8f7fc; }
.fact-pick-row.selected {
  background: #f5f0ff;
  border-color: #ddd6fe;
}
.fact-pick-check {
  margin-top: 3px;
  width: 15px;
  height: 15px;
  flex: none;
  accent-color: #7c3aed;
}
.fact-pick-main { min-width: 0; flex: 1; }
.fact-pick-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.fact-pick-title {
  font-size: 13px;
  font-weight: 650;
  color: #1f2937;
  line-height: 1.35;
  word-break: break-word;
}
.fact-pick-trust {
  flex: none;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 650;
  background: #f1f5f9;
  color: #64748b;
}
.fact-pick-trust.verified { background: #ecfdf5; color: #047857; }
.fact-pick-trust.needs_review { background: #fff7ed; color: #c2410c; }
.fact-pick-meta {
  margin-top: 2px;
  font-size: 11px;
  color: #94a3b8;
}
.fact-pick-snippet {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.fact-pick-empty {
  padding: 18px 12px;
  text-align: center;
  font-size: 12px;
  color: #94a3b8;
}
.trusted-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.check-body { flex: 1; min-width: 0; }
.check-fix-row {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
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
  margin-bottom: 0;
}
.cite-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.cite-help, .cite-sum {
  font-size: 12px;
  color: #1e40af;
  line-height: 1.45;
  margin: 0 0 8px;
}
.cite-sum { font-weight: 650; }
.cite-row.block { background: #fff7ed; margin: 0 -8px; padding: 6px 8px; border-radius: 6px; }
.cite-link { font-size: 12px; color: #1d4ed8; }
.variant-fail-list {
  margin: 6px 0 10px;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.5;
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
@media (max-width: 1099px) {
  .card :deep(.el-card__header),
  .card :deep(.el-card__body) {
    padding: 12px 14px;
  }
  .doc-card-head { flex-wrap: wrap; }
}
</style>
