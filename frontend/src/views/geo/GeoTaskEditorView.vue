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
  staticGeoEditorUrl,
  submitGeoTaskReview,
  suggestGeoTaskBrief,
  fetchChannelBlueprint,
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
  info_gaps: '',
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
})

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
}
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
  brief.info_gaps = joinCsv(x.info_gaps)
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
    info_gaps: splitCsv(brief.info_gaps),
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

function applyVariantFromTask() {
  if (docTab.value === 'master') return
  const v = (task.value?.variants || []).find((x) => x.channel === docTab.value)
  variantEdit.title = v?.title || ''
  variantEdit.body_markdown = sanitizeDraftHeadings(v?.body_markdown || '')
}

function onDocTabChange(name) {
  docTab.value = name
  applyVariantFromTask()
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
    allFacts.value = (factsRes.items || []).map((f) => ({ ...f, id: Number(f.id) }))
    publishingChannels.value = chRes.items || []
    channelAccounts.value = accRes.items || []
    if (!webhookAccountId.value && channelAccounts.value.length) {
      webhookAccountId.value = channelAccounts.value[0].id
    }
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
    const gen = await generateGeoContentTask(tenantId.value, taskId.value)
    applyTaskPayload(gen)
    docTab.value = 'master'
    const bodyLen = (article.body_markdown || '').length
    const st = gen?.status || task.value?.status || '—'
    error.value = ''
    // needs_fix is normal after first draft — not a failure
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

function openStaticFull() {
  window.open(staticGeoEditorUrl(tenantId.value || 1, taskId.value), '_blank')
}

async function genVariants() {
  if (!channelPick.value.length) {
    ElMessage.warning('请至少勾选一个渠道')
    return
  }
  busy.value = 'variants'
  try {
    const t = await createGeoVariants(tenantId.value, taskId.value, channelPick.value, {
      useLlm: true,
    })
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
    const polish = t?.variant_polish || {}
    const llmN = polish.llm ?? 0
    const fbN = polish.fallback ?? 0
    const names = channelPick.value.map((k) => channelLabel(k)).join('、')
    if (llmN && !fbN) {
      ElMessage.success(`已生成正式渠道稿：${names}。可直接复制发布或走下方推送。`)
    } else if (llmN && fbN) {
      ElMessage.warning(
        `渠道稿已生成：正式稿 ${llmN} 路，规则裁剪 ${fbN} 路。请对回退渠道重生成。`,
      )
    } else {
      ElMessage.warning(
        `仅生成了规则裁剪稿（未配置 LLM 或润色失败），不是正式成稿。请先配置 AI 后重生成。`,
      )
    }
  } catch (e) {
    toastError(e, '生成渠道稿失败')
  } finally {
    busy.value = ''
  }
}

const currentVariantMeta = computed(() => {
  if (docTab.value === 'master') return null
  const v = (task.value?.variants || []).find((x) => x.channel === docTab.value)
  return v?.adapt_meta || null
})
const isPublishReadyVariant = computed(() => {
  const m = currentVariantMeta.value
  if (!m) return false
  const q = m.quality || m.engine
  return (
    q === 'publish_ready' ||
    q === 'channel_copy' ||
    m.polish === 'llm_v2' ||
    m.polish === 'llm_v1'
  )
})
const currentVariantQualityLabel = computed(() => {
  if (isPublishReadyVariant.value) return '正式渠道稿 · 可发布'
  if (currentVariantMeta.value?.fallback || currentVariantMeta.value?.quality === 'adapted_draft') {
    return '规则裁剪稿 · 请重生成正式稿'
  }
  return null
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
    ElMessage.success('渠道稿已保存')
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
    ElMessage.success(`已导出 ${res.channel}（status=${res.status}）`)
  } catch (e) {
    toastError(e, '导出失败')
  } finally {
    busy.value = ''
  }
}

async function copyCurrentDoc() {
  const title = docTab.value === 'master' ? article.title : variantEdit.title
  const body = docTab.value === 'master' ? article.body_markdown : variantEdit.body_markdown
  try {
    await navigator.clipboard.writeText(`# ${title}\n\n${body}`)
    ElMessage.success('已复制到剪贴板')
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
    const res = await pushGeoVariantBatch(taskId.value, {
      tenant_id: tenantId.value,
      mode: 'publish',
      create_publication: true,
      targets,
      note: publishNote.value || null,
    })
    if (res.task) task.value = res.task
    else await load()
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
  let tone = 'muted'
  if (s != null) {
    if (s >= 80) tone = 'good'
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
const variants = computed(() => task.value?.variants || [])
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
            {{ task.title }} · {{ task.status }} · {{ task.pipeline_step || '—' }}
            <template v-if="task.brief_ready"> · Brief✓</template>
            <template v-if="task.strategy_richness != null">
              · 策略{{ Math.round(task.strategy_richness * 100) }}%
            </template>
          </span>
        </div>
      </div>
      <div class="right">
        <el-button @click="openStaticFull">静态完整 editor</el-button>
        <el-button @click="load" :disabled="!!busy">刷新</el-button>
      </div>
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
    <el-alert
      type="success"
      show-icon
      class="mb"
      title="Vue 母稿编辑器：Brief/事实/生成/Score/审稿 + 渠道/审校/回填。静态台正确地址为 :5176/geo/dashboard.html（不是 /dashboard.html）。"
    />

    <div v-if="task" class="grid">
      <!-- Left: brief + facts -->
      <aside class="col col-left">
        <el-card shadow="never" class="card">
          <template #header>
            <div class="card-head">
              <span>内容 Brief</span>
              <div class="row-actions">
                <el-button size="small" :loading="busy === 'suggest'" @click="suggestBrief">
                  AI 建议
                </el-button>
                <el-button size="small" type="primary" :loading="busy === 'brief'" @click="saveBrief">
                  保存 Brief
                </el-button>
              </div>
            </div>
          </template>
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
              <el-input v-model="brief.not_recommended_reasons" placeholder="逗号分隔" />
            </el-form-item>
            <el-form-item label="信息缺口">
              <el-input v-model="brief.info_gaps" placeholder="comparison,customer_case…" />
            </el-form-item>
            <el-form-item label="推荐场景">
              <el-input v-model="brief.recommend_when" />
            </el-form-item>
            <el-form-item label="竞品">
              <el-input v-model="brief.competitors" placeholder="逗号分隔" />
            </el-form-item>
            <el-form-item label="必须覆盖">
              <el-input v-model="brief.must_cover" placeholder="逗号分隔" />
            </el-form-item>
          </el-form>
        </el-card>

        <el-card shadow="never" class="card">
          <template #header>
            <div class="card-head">
              <span>事实绑定</span>
              <div class="row-actions">
                <el-button size="small" :loading="busy === 'retrieve'" @click="retrieveFacts">
                  召回
                </el-button>
                <el-button size="small" :loading="busy === 'apply'" @click="applyRetrieveTop">
                  绑定召回 Top
                </el-button>
                <el-button
                  size="small"
                  type="success"
                  plain
                  :loading="busy === 'facts'"
                  @click="bindTopVerified(3)"
                >
                  一键绑 3 条 verified
                </el-button>
                <el-button size="small" type="primary" :loading="busy === 'facts'" @click="saveFacts">
                  保存绑定
                </el-button>
              </div>
            </div>
          </template>
          <div class="hint mb">
            已绑 <strong>{{ boundFacts.length }}</strong> 条
            <span v-if="task?.status"> · 状态 {{ task.status }}</span>
            · 生成需 ≥3 条可核验事实 · 库中可选 {{ allFacts.length }} 条
          </div>
          <ul v-if="boundFacts.length" class="bound-list mb">
            <li v-for="f in boundFacts" :key="f.id">
              #{{ f.id }} [{{ f.trust_level }}] {{ f.title }}
            </li>
          </ul>
          <el-select
            v-model="selectedFactIds"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择事实卡（可多选）"
            style="width: 100%"
          >
            <el-option
              v-for="f in allFacts"
              :key="f.id"
              :label="`#${f.id} [${f.trust_level}] ${f.title}`"
              :value="Number(f.id)"
            />
          </el-select>
          <div class="retrieve mt">
            <div class="hint">
              召回候选
              <strong>{{ retrievePreview.length }}</strong>
              条
              <span v-if="!retrievePreview.length">（点「召回」加载；无结果时用本地库兜底）</span>
            </div>
            <div v-for="r in retrievePreview" :key="r.fact_id" class="retrieve-row">
              #{{ r.fact_id }} · {{ r.title }} · score {{ r.score }}
              <span v-if="r.trust_level" class="hint"> · {{ r.trust_level }}</span>
            </div>
          </div>
        </el-card>
      </aside>

      <!-- Center: article + publish -->
      <div class="col col-main">
        <el-card shadow="never" class="card">
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

          <div v-if="docTab === 'master'" class="doc-draft-banner mb">
            <b>自动生成母稿草案</b>
            — 供内部改稿与结构检查，<b>不能直接当正式发布文</b>。
            请润色语气、删模板痕迹、核对事实后再审校推送。
          </div>
          <div
            v-else-if="isPublishReadyVariant"
            class="channel-quality mb is-good"
          >
            <b>正式渠道稿</b>
            — 可直接复制到对应平台发布；推送前建议快速核对关键数字与来源是否仍准确。
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
              · 重新「生成母稿」会覆盖当前正文
            </div>
          </template>
          <template v-else>
            <div class="hint mb">
              渠道 {{ channelLabel(docTab) }} · 状态 {{ variants.find((v) => v.channel === docTab)?.status || '—' }}
              <span v-if="variants.find((v) => v.channel === docTab)?.stale"> · 母稿已变需重生</span>
              <span v-if="currentVariantQualityLabel"> · {{ currentVariantQualityLabel }}</span>
            </div>
            <el-form label-width="56px" size="small">
              <el-form-item label="标题">
                <el-input v-model="variantEdit.title" />
              </el-form-item>
              <el-form-item label="正文">
                <el-input
                  v-model="variantEdit.body_markdown"
                  type="textarea"
                  :rows="16"
                  placeholder="正式渠道稿 Markdown（可直接发布）"
                />
              </el-form-item>
            </el-form>
          </template>
        </el-card>

        <el-card shadow="never" class="card">
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
        </el-card>
      </div>

      <!-- Right: draft readiness (not publish-ready copy) -->
      <aside class="col col-rail">
        <el-card shadow="never" class="card rail-card">
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
.sub { font-size: 12px; color: #6b7280; }
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
.card { border-radius: 12px; }
.card-head {
  display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;
}
.hint { font-size: 12px; color: #8b93a7; }
.blueprint-box {
  background: #f8f7fc; border: 1px solid #e8e4f5; border-radius: 8px; padding: 10px 12px;
}
.blueprint-title { font-size: 12px; font-weight: 700; color: #5b21b6; margin-bottom: 6px; }
.blueprint-list { margin: 0; padding-left: 18px; font-size: 12px; color: #374151; }
.blueprint-list li { margin-bottom: 4px; }
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
.retrieve-row { padding: 2px 0; }
.bound-list {
  list-style: none; padding: 0; margin: 0 0 8px;
  font-size: 12px; color: #374151;
  max-height: 120px; overflow: auto;
  border: 1px solid #f0ecf9; border-radius: 8px; padding: 8px;
}
.bound-list li { padding: 2px 0; }
</style>
