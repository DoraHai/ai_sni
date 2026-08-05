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
  pushGeoVariantWebhook,
  retrieveGeoTaskFacts,
  saveGeoArticle,
  formatGeoError,
  staticGeoEditorUrl,
  submitGeoTaskReview,
  suggestGeoTaskBrief,
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

function applyArticleFromTask(t) {
  const a = t?.article
  article.title = a?.title || t?.title || ''
  article.body_markdown = a?.body_markdown || ''
}

function applyVariantFromTask() {
  if (docTab.value === 'master') return
  const v = (task.value?.variants || []).find((x) => x.channel === docTab.value)
  variantEdit.title = v?.title || ''
  variantEdit.body_markdown = v?.body_markdown || ''
}

function onDocTabChange(name) {
  docTab.value = name
  applyVariantFromTask()
}

async function load() {
  if (!tenantId.value || !taskId.value) {
    error.value = '缺少租户或任务 ID'
    return
  }
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
    allFacts.value = (factsRes.items || []).map((f) => ({ ...f, id: Number(f.id) }))
    publishingChannels.value = chRes.items || []
    channelAccounts.value = accRes.items || []
    if (!webhookAccountId.value && channelAccounts.value.length) {
      webhookAccountId.value = channelAccounts.value[0].id
    }
    if (t.target_channels?.length) {
      channelPick.value = [...t.target_channels]
    }
    applyTaskPayload(t)
    // if status says bound but facts[] empty, one more GET
    if (
      (t.status === 'facts_bound' || (t.pipeline_step && t.pipeline_step !== 'opportunity')) &&
      !(t.facts || []).length
    ) {
      await refreshTaskDetail()
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
        patches: [],
      }
    }
  } catch (e) {
    error.value = e.message || '加载失败'
    task.value = null
  } finally {
    loading.value = false
  }
}

async function saveBrief() {
  busy.value = 'brief'
  try {
    task.value = await patchGeoContentTask(tenantId.value, taskId.value, {
      brief: briefPayload(),
    })
    applyBriefToForm(task.value.brief)
    ElMessage.success('Brief 已保存')
  } catch (e) {
    toastError(e, '保存 Brief 失败')
  } finally {
    busy.value = ''
  }
}

async function suggestBrief() {
  busy.value = 'suggest'
  try {
    const res = await suggestGeoTaskBrief(tenantId.value, taskId.value, {
      overwrite: false,
      use_llm: true,
    })
    if (res.suggested_brief) {
      applyBriefToForm(res.suggested_brief)
      ElMessage.success(
        `已填入建议（未保存）${res.used_llm ? ' · LLM' : ' · 启发式'} · 策略 ${Math.round((res.strategy_richness || 0) * 100)}%`,
      )
    }
  } catch (e) {
    toastError(e, '建议 Brief 失败')
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

function applyTaskPayload(t) {
  if (!t) return t
  // normalize fact id types so el-select / bound list stay consistent
  if (Array.isArray(t.facts)) {
    t.facts = t.facts.map((f) => ({ ...f, id: Number(f.id) }))
  } else {
    t.facts = []
  }
  task.value = t
  selectedFactIds.value = t.facts.map((f) => Number(f.id))
  applyBriefToForm(t.brief)
  applyArticleFromTask(t)
  return t
}

async function refreshTaskDetail() {
  const t = await getGeoContentTask(tenantId.value, taskId.value)
  return applyTaskPayload(t)
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

async function generate() {
  error.value = ''
  const pre = validateBeforeGenerate()
  if (pre) {
    error.value = pre
    ElMessage({ type: 'error', message: pre, duration: 6000, showClose: true })
    return
  }
  busy.value = 'generate'
  try {
    await patchGeoContentTask(tenantId.value, taskId.value, { brief: briefPayload() })
    const gen = await generateGeoContentTask(tenantId.value, taskId.value)
    applyTaskPayload(gen)
    error.value = ''
    ElMessage.success('母稿已生成')
  } catch (e) {
    const msg = toastError(e, '生成失败')
    error.value = msg
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
    checkResult.value = {
      ...(checkResult.value || {}),
      ai_review: res.ai_review,
      checks: task.value?.rule_result?.checks || checkResult.value?.checks || [],
      ready: task.value?.rule_result?.ready,
      geo_score: task.value?.rule_result?.geo_score ?? checkResult.value?.geo_score,
      geo_subscores: task.value?.rule_result?.geo_subscores || checkResult.value?.geo_subscores,
      geo_actions: task.value?.rule_result?.geo_actions || checkResult.value?.geo_actions || [],
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
      article.body_markdown = art.body_markdown
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
    task.value = await createGeoVariants(tenantId.value, taskId.value, channelPick.value)
    if (channelPick.value[0]) {
      docTab.value = channelPick.value[0]
      applyVariantFromTask()
    }
    ElMessage.success('渠道稿已生成')
  } catch (e) {
    toastError(e, '生成渠道稿失败')
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

async function recordPublication() {
  if (docTab.value === 'master') {
    ElMessage.warning('请切换到渠道页签再回填')
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
  } catch (e) {
    toastError(e, '回填失败')
  } finally {
    busy.value = ''
  }
}

async function pushWebhook() {
  if (docTab.value === 'master') {
    ElMessage.warning('请切换到渠道页签')
    return
  }
  if (!webhookAccountId.value) {
    ElMessage.warning('请选择 Webhook 账号')
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
    ElMessage.success('Webhook 推送完成')
  } catch (e) {
    toastError(e, '推送失败')
  } finally {
    busy.value = ''
  }
}

const scoreLine = computed(() => {
  const s = checkResult.value?.geo_score
  if (s == null) return '检查后显示 GEO Score'
  const subs = checkResult.value?.geo_subscores || {}
  const parts = Object.keys(subs)
    .map((k) => `${k}=${Math.round((subs[k] || 0) * 100)}`)
    .join(' · ')
  return `GEO Score ${s}/100${parts ? `（${parts}）` : ''}`
})

const checks = computed(() => checkResult.value?.checks || task.value?.rule_result?.checks || [])
const geoActions = computed(
  () => checkResult.value?.geo_actions || task.value?.rule_result?.geo_actions || [],
)
const aiReview = computed(
  () => checkResult.value?.ai_review || task.value?.rule_result?.ai_review || null,
)
const patches = computed(() => checkResult.value?.patches || [])
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
  // show all webhook accounts; backend validates match
  return (channelAccounts.value || []).filter((a) => a.auth_type === 'webhook' || !a.auth_type)
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
      <div class="col">
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
      </div>

      <!-- Right: article + check -->
      <div class="col wide">
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

          <el-tabs :model-value="docTab" class="mb" @tab-change="onDocTabChange">
            <el-tab-pane label="母稿" name="master" />
            <el-tab-pane
              v-for="v in variants"
              :key="v.channel"
              :name="v.channel"
              :label="`${v.channel}${v.stale ? ' *' : ''}`"
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
                  placeholder="Markdown 母稿"
                />
              </el-form-item>
            </el-form>
            <div v-if="task.article" class="hint">
              版本 v{{ task.article.version_no }} · {{ task.article.created_at || '' }}
              · 正文字数 {{ (article.body_markdown || '').length }}
            </div>
          </template>
          <template v-else>
            <div class="hint mb">
              渠道 {{ docTab }} · 状态 {{ variants.find((v) => v.channel === docTab)?.status || '—' }}
              <span v-if="variants.find((v) => v.channel === docTab)?.stale"> · 母稿已变需重生</span>
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
                  placeholder="渠道稿 Markdown"
                />
              </el-form-item>
            </el-form>
          </template>
        </el-card>

        <el-card shadow="never" class="card">
          <template #header>
            <div class="card-head">
              <span>渠道稿 · 审校 · 发布</span>
              <el-button size="small" type="primary" :loading="busy === 'variants'" @click="genVariants">
                生成所选渠道稿
              </el-button>
            </div>
          </template>
          <div class="hint mb">勾选渠道后生成；页签切换可编辑/导出/回填。</div>
          <el-checkbox-group v-model="channelPick" class="mb">
            <el-checkbox
              v-for="c in channelOptions"
              :key="c.key"
              :label="c.key"
            >
              {{ c.label }} ({{ c.key }})
            </el-checkbox>
          </el-checkbox-group>

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

          <el-divider content-position="left">回填 / Webhook</el-divider>
          <el-form label-width="100px" size="small">
            <el-form-item label="发布 URL">
              <el-input v-model="publishUrl" placeholder="https://..." />
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="publishNote" />
            </el-form-item>
            <el-form-item label="Webhook 账号">
              <el-select v-model="webhookAccountId" clearable style="width: 100%" placeholder="可选">
                <el-option
                  v-for="a in webhookAccountsForChannel"
                  :key="a.id"
                  :label="`${a.display_name} (#${a.id})`"
                  :value="a.id"
                />
              </el-select>
            </el-form-item>
          </el-form>
          <div class="row-actions">
            <el-button
              size="small"
              type="primary"
              :disabled="docTab === 'master'"
              :loading="busy === 'publish'"
              @click="recordPublication"
            >
              回填 URL
            </el-button>
            <el-button
              size="small"
              :disabled="docTab === 'master'"
              :loading="busy === 'push'"
              @click="pushWebhook"
            >
              Webhook 推送
            </el-button>
            <router-link class="el-button el-button--small" to="/geo/publishing">管理渠道账号</router-link>
          </div>
          <div class="hint mt">推送前通常需「导出」渠道稿；发布门禁含审校通过与规则就绪。</div>
        </el-card>

        <el-card shadow="never" class="card">
          <template #header>
            <span>规则 · GEO Score · AI 审稿</span>
          </template>
          <div class="score">{{ scoreLine }}</div>
          <ul class="check-list">
            <li v-for="c in checks" :key="c.code">
              <span :class="c.passed ? 'ok' : 'bad'">{{ c.passed ? '✓' : '✗' }}</span>
              <div>
                <strong>{{ c.code }}</strong> · {{ c.message }}
                <div v-if="!c.passed && c.action" class="hint">{{ c.action }}</div>
              </div>
            </li>
          </ul>
          <div v-if="geoActions.length" class="mt">
            <div class="sec">Score 改进项</div>
            <ul class="check-list">
              <li v-for="a in geoActions" :key="a.code">
                <span class="warn">⚠</span>
                <div>
                  <strong>{{ a.code }}</strong> · {{ a.message }}
                  <div v-if="a.action" class="hint">{{ a.action }}</div>
                </div>
              </li>
            </ul>
          </div>
          <div v-if="patches.length" class="mt row-actions">
            <el-button
              v-for="p in patches"
              :key="p.code"
              size="small"
              :loading="busy === 'patch'"
              @click="applyPatch(p.code)"
            >
              插入修复 · {{ p.label || p.code }}
            </el-button>
          </div>
          <div v-if="aiReview" class="mt">
            <div class="sec">
              AI 审稿 · block {{ aiReview.block_count || 0 }} · warn {{ aiReview.warn_count || 0 }}
            </div>
            <div class="hint">{{ aiReview.summary }}</div>
            <ul class="check-list">
              <li v-for="(iss, i) in aiReview.issues || []" :key="i">
                <span class="warn">{{ iss.severity }}</span>
                <div>
                  <strong>{{ iss.category }}</strong> · {{ iss.message }}
                  <div v-if="iss.fix_hint" class="hint">{{ iss.fix_hint }}</div>
                </div>
              </li>
            </ul>
          </div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<style scoped>
.editor { padding: 4px 2px 28px; }
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
  grid-template-columns: minmax(300px, 380px) 1fr;
  gap: 12px;
  align-items: start;
}
@media (max-width: 1100px) {
  .grid { grid-template-columns: 1fr; }
}
.col { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.card { border-radius: 12px; }
.card-head {
  display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;
}
.hint { font-size: 12px; color: #8b93a7; }
.sec { font-weight: 600; font-size: 13px; margin-bottom: 6px; }
.score { font-weight: 700; margin-bottom: 10px; color: #5b21b6; }
.check-list { list-style: none; padding: 0; margin: 0; }
.check-list li {
  display: flex; gap: 8px; padding: 6px 0; border-bottom: 1px solid #f3f0fa; font-size: 13px;
}
.ok { color: #059669; font-weight: 700; }
.bad { color: #dc2626; font-weight: 700; }
.warn { color: #d97706; font-size: 12px; font-weight: 600; }
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
