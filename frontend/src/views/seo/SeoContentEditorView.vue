<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { assistSeoContent, createSeoContentAsset, fetchSeoContentAssets, fetchSeoKeywords, fetchSeoSitePages, submitSeoContentReview, updateSeoContentAsset } from '../../api/seo'
import { fetchSeoSites } from '../../api/moduleAssets'
import { currentTenantId, session } from '../../store/session'
import { currentSeoSiteId as siteId } from './seoSiteContext'
import { sanitizeSeoEditorHtml, seoContentWordCount, safeSeoUrl, seoPasteHtml } from './seoEditorHtml'
import { buildSourcePageAssistInstruction, sourcePageRemediationContext } from './seoContentRemediationContext'

import { createSeoTable, editSeoTable } from './seoEditorTable'

const route = useRoute()
const router = useRouter()
const editor = ref(null)
const editorComposing = ref(false)
const saving = ref(false)
const saveState = ref('尚未保存')
const prompt = ref('')
const aiMessage = ref('')
const aiBusy = ref('')
const keywords = ref([])
const sites = ref([])
if (Number(route.query.site_id) > 0) siteId.value = Number(route.query.site_id)
const engine = ref('百度')
const sourceText = ref('')
const publishVisible = ref(false)
const publishForm = reactive({ page_url: '', target_platforms: [] })
const publishedAt = ref(null)
const assetId = ref(Number(route.query.id) || null)
const sourcePageId = ref(Number(route.query.source_page_id) || null)
const sourcePage = ref(null)
const assetVersion = ref(1)
const assetStatus = ref('planned')
const assetContentType = ref(null)
const editingHumanized = ref(false)
const workflowLocked = computed(() => ['review', 'ready', 'published'].includes(assetStatus.value))
const landingBindingMissing = computed(() => assetContentType.value === 'landing' && !sourcePageId.value)
const mode = computed(() => route.query.type === 'rewrite' ? 'rewrite' : route.query.type === 'qa' ? 'qa' : 'original')
const pageTitle = computed(() => mode.value === 'rewrite' ? '文章改写编辑' : mode.value === 'qa' ? '问答编辑器' : '原创文章编辑')
const backPath = computed(() => mode.value === 'rewrite' ? '/seo/content/rewrites' : mode.value === 'qa' ? '/seo/content/qa' : '/seo/content/articles')
const sourcePageRoute = computed(() => ({ path: '/seo/site', query: { site_id: siteId.value, page_id: sourcePageId.value } }))

const templateMap = {
  guide: { name: '完整选型指南', type: 'guide', outline: '一、用户为什么关注这个问题\n二、核心概念与选择标准\n三、关键能力逐项验证\n四、不同场景的适用建议\n五、常见问题' },
  compare: { name: '竞品对比评测', type: 'comparison', outline: '一、对比对象与选择标准\n二、核心能力对比\n三、成本与实施难度\n四、适用场景\n五、选择建议' },
  solution: { name: '行业解决方案', type: 'article', outline: '一、行业现状与痛点\n二、解决方案架构\n三、实施流程\n四、业务价值\n五、客户案例' },
  howto: { name: '操作教程', type: 'article', outline: '一、准备工作\n二、操作步骤\n三、配置说明\n四、常见错误\n五、检查清单' },
  opinion: { name: '行业观点', type: 'article', outline: '一、趋势背景\n二、关键数据\n三、核心观点\n四、影响分析\n五、结论' },
  faq: { name: '专题问答', type: 'faq', outline: '问题一\n问题二\n问题三\n问题四\n问题五' },
}
const selectedTemplate = computed(() => templateMap[route.query.template] || templateMap.guide)
const form = reactive({ title: '', keyword_ids: [], outline: '', draft: '', author: session.user?.name || session.user?.username || '' })
const wordCount = computed(() => seoContentWordCount(form.draft))
const contentTypeLabel = computed(() => ({ article: '原创文章', guide: '深度指南', landing: '落地页', comparison: '对比内容', rewrite: '文章改写', qa: '问答内容', faq: 'FAQ' })[assetContentType.value] || selectedTemplate.value.name)
const keywordNames = computed(() => form.keyword_ids.map((id) => keywords.value.find((item) => item.id === id)?.keyword).filter(Boolean))
const keywordSummary = computed(() => keywordNames.value.length ? keywordNames.value.join('、') : '尚未选择')
const sourceRemediation = computed(() => sourcePageRemediationContext(sourcePage.value))
const primaryAiAction = computed(() => mode.value === 'rewrite' ? 'rewrite' : sourcePageId.value ? 'outline' : 'generate')
const primaryAiLabel = computed(() => {
  if (aiBusy.value === primaryAiAction.value) return mode.value === 'rewrite' ? 'DeepSeek 改写中…' : 'DeepSeek 生成中…'
  if (mode.value === 'rewrite') return 'DeepSeek 开始改写'
  return sourcePageId.value ? 'AI 生成整改大纲' : 'AI 生成初稿'
})

function sanitizeEditorHtml(value) {
  return sanitizeSeoEditorHtml(value)
}

function formatSourceCheckedAt(value) {
  if (!value) return '尚未检测'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '检测时间无效'
  return `存档 ${date.toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' })} CST`
}

async function load() {
  if (!currentTenantId.value || !siteId.value) return
  try {
    const [wordResult,contentResult] = await Promise.all([
      fetchSeoKeywords({ tenantId: currentTenantId.value, siteId: siteId.value, pageSize: 200 }),
      assetId.value ? fetchSeoContentAssets({ tenantId: currentTenantId.value, siteId: siteId.value, contentId: assetId.value, pageSize: 1 }) : Promise.resolve({items:[]}),
    ])
    keywords.value = wordResult.items
    if (assetId.value) {
      const item = contentResult.items.find((row) => row.id === assetId.value)
      if (!item) return ElMessage.warning('改写任务不存在或已被删除')
      assetContentType.value = item.content_type
      editingHumanized.value = Boolean(item.humanized_content)
      Object.assign(form,{title:item.title||'',keyword_ids:[...(item.keyword_ids?.length?item.keyword_ids:item.keyword_id?[item.keyword_id]:[])],outline:item.outline||'',draft:sanitizeEditorHtml(item.humanized_content||item.draft||''),author:item.author||form.author})
      Object.assign(publishForm,{page_url:item.page_url||'',target_platforms:[...(item.target_platforms||[])]})
      publishedAt.value=item.published_at||null
      sourceText.value=item.source_text||''
      sourcePageId.value=item.source_page_id||sourcePageId.value||null
      assetVersion.value=item.version_count||1
      assetStatus.value=item.status||'planned'
      await nextTick()
      if(editor.value)editor.value.innerHTML=form.draft
      historyCurrent = form.draft; history.length = 0; future.length = 0
      saveState.value = item.status === 'review' ? '待审核（只读）' : item.status === 'ready' ? '待发布（只读）' : item.status === 'published' ? '已发布（只读）' : '已载入任务'
    }
  } catch (e) { ElMessage.warning(e.message) }
}

async function loadSourcePageBrief() {
  if (!sourcePageId.value || !siteId.value) { sourcePage.value = null; return }
  try {
    const response = await fetchSeoSitePages({ tenantId: currentTenantId.value, siteId: siteId.value, pageId: sourcePageId.value, pageSize: 1 })
    const page = response.items?.[0]
    if (!page) { sourcePage.value = null; return }
    sourcePage.value = page
    if (assetId.value) {
      if (!prompt.value) prompt.value = buildSourcePageAssistInstruction(page, keywordNames.value)
      return
    }
    if (!form.title) form.title = page.title_suggestion || page.title || ''
    if (!form.keyword_ids.length && page.target_keyword_id) form.keyword_ids = [page.target_keyword_id]
    prompt.value = `本内容任务来自站内页面优化：${page.url}。需要处理的问题：${(page.issue_codes || []).join('、') || '补充页面内容'}。建议 Title：${page.title_suggestion || '待完善'}；建议 Description：${page.description_suggestion || '待完善'}。请围绕已选关键词生成与该页面匹配、可供人工审核的内容。`
    saveState.value = '已关联站内优化任务'
  } catch (e) { ElMessage.warning(e.message) }
}

function applySourcePageGuidance() {
  if (!sourcePage.value) return ElMessage.warning('尚未读取承接页检测记录')
  prompt.value = buildSourcePageAssistInstruction(sourcePage.value, keywordNames.value)
  ElMessage.success('程序整改依据已填入，未调用 AI')
}

function showSuccess(message) {
  ElMessage({ type: 'success', message, duration: 3500, showClose: true })
}

function startEditorComposition() {
  editorComposing.value = true
  saveState.value = '中文输入中…'
}

function finishEditorComposition() {
  editorComposing.value = false
  syncDraft()
}

// HTML snapshots cover native typing and custom DOM edits consistently, capped at 50.
const history = [], future = []
let historyCurrent = ''
const selectedCell = ref(null), selectedFigure = ref(null)
function rememberDraft() {
  const html = editor.value?.innerHTML || ''
  if (historyCurrent !== null && html !== historyCurrent) {
    history.push(historyCurrent); if (history.length > 50) history.shift()
    future.length = 0
  }
  historyCurrent = html
}
function editorSelection(event) {
  const node = event?.target?.closest?.('img') || window.getSelection()?.anchorNode
  const element = node?.nodeType === 1 ? node : node?.parentElement
  selectedCell.value = editor.value?.contains(element) ? element.closest('td,th') : null
  selectedFigure.value = editor.value?.contains(element) ? element.closest('figure') || element.closest('img') : null
}
function editorUndo(redo = false) {
  if (workflowLocked.value || editorComposing.value) return
  rememberDraft()
  const from = redo ? future : history, to = redo ? history : future
  if (!from.length) return
  to.push(historyCurrent); historyCurrent = from.pop()
  editor.value.innerHTML = historyCurrent; form.draft = historyCurrent
  selectedCell.value = null; selectedFigure.value = null
  editor.value.focus()
  const range = document.createRange(); range.selectNodeContents(editor.value); range.collapse(false)
  const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
}
function editorKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && ['z','y'].includes(event.key.toLowerCase()) && !editorComposing.value) {
    event.preventDefault(); editorUndo(event.key.toLowerCase() === 'y' || event.shiftKey)
  }
}
function pasteEditor(event) {
  event.preventDefault()
  if (workflowLocked.value || editorComposing.value) return
  command('insertHTML', seoPasteHtml(event.clipboardData.getData('text/html'), event.clipboardData.getData('text/plain')))
}
function insertLink() {
  if (workflowLocked.value || editorComposing.value) return
  const anchor = window.getSelection()?.anchorNode
  const link = (anchor?.nodeType === 1 ? anchor : anchor?.parentElement)?.closest('a')
  const url = window.prompt('链接 URL（http、https、/ 路径或 # 锚点）', link?.getAttribute('href') || '')
  if (url === null) return
  if (!safeSeoUrl(url.trim())) return ElMessage.warning('URL 不安全或格式不正确')
  if (link && editor.value.contains(link)) { rememberDraft(); link.setAttribute('href', url.trim()); syncDraft() }
  else command('createLink', url.trim())
}
function insertTable() {
  if (workflowLocked.value || editorComposing.value) return
  const size = window.prompt('表格行 × 列（1–20 × 1–10）', '3x3')
  if (size === null) return
  const match = size.match(/^\s*(\d+)\s*[x×*]\s*(\d+)\s*$/i)
  if (!match) return ElMessage.warning('请输入行 x 列，例如 3x3')
  try { command('insertHTML', createSeoTable(document, Number(match[1]), Number(match[2]), window.confirm('首行作为表头？')).outerHTML + '<p><br></p>') }
  catch (e) { ElMessage.warning(e.message) }
}
function tableAction(action) {
  if (workflowLocked.value || editorComposing.value) return
  try { rememberDraft(); editSeoTable(selectedCell.value, action); syncDraft(); editorSelection() }
  catch (e) { ElMessage.warning(e.message) }
}
function insertImage() {
  if (workflowLocked.value || editorComposing.value) return
  const url = window.prompt('图片 URL（http、https 或 / 路径）', '')
  if (url === null) return
  if (!safeSeoUrl(url.trim(), true)) return ElMessage.warning('URL 不安全或格式不正确')
  const alt = window.prompt('替代文本（建议填写，可留空）', '')
  if (alt === null) return
  const caption = window.prompt('图片说明（可留空）', '')
  if (caption === null) return
  const figure = document.createElement('figure'); figure.className = 'seo-figure seo-align-center seo-w-100'
  const img = document.createElement('img'); img.setAttribute('src', url.trim()); img.setAttribute('alt', alt); figure.append(img)
  if (caption) { const node = document.createElement('figcaption'); node.textContent = caption; figure.append(node) }
  command('insertHTML', figure.outerHTML + '<p><br></p>')
}
function imageLayout(token) {
  if (workflowLocked.value || editorComposing.value || !selectedFigure.value) return
  rememberDraft()
  let figure = selectedFigure.value
  if (figure.tagName === 'IMG') { const wrapper = document.createElement('figure'); figure.before(wrapper); wrapper.append(figure); figure = wrapper }
  figure.classList.add('seo-figure')
  const prefix = token.startsWith('seo-w-') ? 'seo-w-' : 'seo-align-'
  for (const name of [...figure.classList]) if (name.startsWith(prefix)) figure.classList.remove(name)
  figure.classList.add(token); selectedFigure.value = figure; syncDraft()
}
function syncDraft() {
  if (editorComposing.value) return
  rememberDraft()
  form.draft = editor.value?.innerHTML || ''
  saveState.value = '编辑中…'
}

function command(name, value = null) {
  if (workflowLocked.value) return ElMessage.warning('当前任务处于只读流程状态')
  if (editorComposing.value) return
  rememberDraft()
  editor.value?.focus()
  document.execCommand(name, false, value)
  syncDraft()
}

function insertOutline() {
  if (workflowLocked.value) return ElMessage.warning('当前任务处于只读流程状态')
  const html = selectedTemplate.value.outline.split('\n').map((line) => `<h2>${line}</h2><p><br></p>`).join('')
  form.draft = html
  nextTick(() => { if (editor.value) editor.value.innerHTML = html })
  saveState.value = '已应用模板大纲'
}

function textToHtml(value) {
  const escaped = String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return escaped.split(/\n{2,}/).map((block) => {
    const text = block.trim()
    if (!text) return ''
    if (/^###\s+/.test(text)) return `<h3>${text.replace(/^###\s+/, '')}</h3>`
    if (/^##\s+/.test(text)) return `<h2>${text.replace(/^##\s+/, '')}</h2>`
    if (/^#\s+/.test(text)) return `<h2>${text.replace(/^#\s+/, '')}</h2>`
    return `<p>${text.replace(/\n/g, '<br>')}</p>`
  }).join('')
}

async function loadSites() {
  if (!currentTenantId.value) return
  sites.value = (await fetchSeoSites(currentTenantId.value)).sites || []
  if (!sites.value.some((item) => item.id === siteId.value)) {
    siteId.value = sites.value.find((item) => item.status === 'active')?.id || sites.value[0]?.id || null
  }
  await load()
}

async function changeSite() {
  if (assetId.value) return
  form.keyword_ids = []
  await load()
}

function draftForAi() {
  const template = document.createElement('template')
  template.innerHTML = sanitizeEditorHtml(form.draft)
  template.content.querySelectorAll('img').forEach((image) => {
    const label = image.getAttribute('alt')?.trim()
    image.replaceWith(document.createTextNode(label ? `[图片：${label}]` : '[图片]'))
  })
  // Explicit editor breaks must survive conversion back to the AI's plain-text
  // input; textContent alone concatenates adjacent paragraphs and BR lines.
  template.content.querySelectorAll('br').forEach(node => node.replaceWith(document.createTextNode('\n')))
  template.content.querySelectorAll('p,div,h1,h2,h3,h4,h5,h6,li,blockquote,pre,tr,figure,figcaption').forEach(node => {
    if (node.previousSibling && !node.previousSibling.textContent.endsWith('\n')) node.before(document.createTextNode('\n'))
    if (node.nextSibling && !node.nextSibling.textContent.startsWith('\n')) node.after(document.createTextNode('\n'))
  })
  return (template.content.textContent || '').trim()
}

function buildAssistPayload(action, draftText) {
  const keywordIds = form.keyword_ids
    .map((id) => Number(id))
    .filter((id) => Number.isInteger(id) && id > 0)
  const payload = {
    tenant_id: Number(currentTenantId.value),
    site_id: Number(siteId.value),
    source_page_id: sourcePageId.value ? Number(sourcePageId.value) : null,
    action,
    mode: mode.value,
    keyword_id: keywordIds[0] || null,
    keyword_ids: keywordIds,
    instruction: prompt.value.trim() || null,
    template: selectedTemplate.value.name,
    engine: engine.value,
  }

  if (action === 'generate') {
    payload.title = form.title.trim() || null
    payload.outline = form.outline.trim() || null
  }
  if (action === 'outline') payload.title = form.title.trim() || null
  if (action === 'title') {
    payload.title = form.title.trim() || null
    payload.outline = form.outline.trim() || null
  }
  if (action === 'keywords') {
    payload.title = form.title.trim() || null
    payload.outline = form.outline.trim() || null
    payload.draft = draftText || null
  }
  if (action === 'rewrite') {
    payload.title = form.title.trim() || null
    payload.outline = form.outline.trim() || null
    payload.draft = draftText || null
    payload.source_text = mode.value === 'rewrite' ? sourceText.value.trim() || null : null
  }
  return payload
}

async function assist(action) {
  if (workflowLocked.value) return ElMessage.warning('待审核或待发布内容不能调用 AI 修改')
  if (!currentTenantId.value) return ElMessage.warning('请先选择客户')
  if (!siteId.value) return ElMessage.warning('请先选择或创建 SEO 网站')
  if (['generate','outline','title','keywords'].includes(action) && !form.keyword_ids.length) return ElMessage.warning('请至少选择 1 个目标关键词')
  if (action === 'generate' && sourcePageId.value) return ElMessage.warning('承接页任务请先生成整改大纲；完整正文需粘贴经核验的官网事实资料后使用“优化表达”')
  syncDraft()
  const draftText = draftForAi()
  if (action === 'keywords' && !form.title.trim() && !draftText) return ElMessage.warning('请先输入标题或正文，再检查关键词')
  if (action === 'rewrite' && sourcePageId.value && !draftText) return ElMessage.warning('请先将经核验的官网事实资料粘贴到正文，再使用“优化表达”')
  if (action === 'rewrite' && !draftText && !sourceText.value.trim()) return ElMessage.warning('请先输入正文，再优化表达')
  if (prompt.value.length > 5000) return ElMessage.warning('内容要求不能超过 5000 字')
  if (form.title.length > 300 && ['generate','outline','title','keywords','rewrite'].includes(action)) return ElMessage.warning('标题不能超过 300 字')
  if (form.outline.length > 20000 && ['generate','title','keywords','rewrite'].includes(action)) return ElMessage.warning('大纲不能超过 20000 字')
  if (draftText.length > 80000 && ['keywords','rewrite'].includes(action)) return ElMessage.warning('正文不能超过 80000 字，请精简后重试')
  if (sourceText.value.length > 80000 && action === 'rewrite') return ElMessage.warning('待改写原文不能超过 80000 字，请分段处理')
  aiBusy.value = action
  aiMessage.value = ''
  try {
    const result = await assistSeoContent(buildAssistPayload(action, draftText))
    if (result.title) form.title = result.title
    if (result.outline) form.outline = result.outline
    if (result.content) {
      const html = textToHtml(result.content)
      form.draft = html
      await nextTick()
      if (editor.value) editor.value.innerHTML = html
      saveState.value = 'AI 结果待保存'
    }
    const suggestions = Array.isArray(result.suggestions) ? result.suggestions.join('；') : ''
    aiMessage.value = result.feedback || suggestions || 'DeepSeek 已完成处理，请检查后保存。'
    ElMessage.success('DeepSeek 处理完成')
    return true
  } catch (e) {
    aiMessage.value = e.message
    ElMessage.error(e.message)
    return false
  } finally { aiBusy.value = '' }
}

async function save(status = 'drafting', options = {}) {
  if (workflowLocked.value) return ElMessage.warning('待审核或待发布内容不能直接编辑，请先退回修改')
  if (editorComposing.value) return ElMessage.warning('中文输入尚未完成，请选定文字后再保存')
  if (assetId.value && !assetContentType.value) return ElMessage.warning('任务尚未成功载入，请刷新后重试')
  syncDraft()
  if (!currentTenantId.value) return ElMessage.warning('请先选择客户')
  if (!siteId.value) return ElMessage.warning('请先选择或创建 SEO 网站')
  if (!form.title.trim()) return ElMessage.warning('请填写文章标题')
  if (mode.value === 'original' && !form.keyword_ids.length) return ElMessage.warning('原创文章请至少选择 1 个目标关键词')
  form.draft = sanitizeEditorHtml(form.draft)
  if (editor.value && editor.value.innerHTML !== form.draft) editor.value.innerHTML = form.draft
  saving.value = true
  try {
    const payload = {
      tenant_id: currentTenantId.value,
      site_id: siteId.value,
      source_page_id: sourcePageId.value,
      title: form.title,
      keyword_id: form.keyword_ids[0] || null,
      keyword_ids: form.keyword_ids,
      content_type: assetContentType.value || (mode.value === 'rewrite' ? 'rewrite' : mode.value === 'qa' ? 'qa' : selectedTemplate.value.type),
      outline: form.outline || selectedTemplate.value.outline,
      draft: form.draft || null,
      humanized_content: mode.value === 'rewrite' ? form.draft || null : null,
      source_text: mode.value === 'rewrite' ? sourceText.value || null : null,
      rewrite_progress: mode.value === 'rewrite' ? (form.draft ? 100 : 0) : null,
      originality_score: null,
      target_platforms: options.targetPlatforms ?? publishForm.target_platforms,
      status,
      page_url: (options.pageUrl ?? publishForm.page_url) || null,
      author: form.author || null,
      published_at: options.publishedAt ?? publishedAt.value,
    }
    if(assetId.value){
      // An existing record is not a new template: preserve its original draft
      // when editing the reviewed text, and retain non-editor metadata.
      const {tenant_id,site_id,draft,humanized_content,source_text,rewrite_progress,originality_score,...values}=payload
      values[editingHumanized.value ? 'humanized_content' : 'draft'] = form.draft || null
      values.outline = form.outline || null
      values.version_count = assetVersion.value
      const saved = await updateSeoContentAsset({contentId:assetId.value,tenantId:currentTenantId.value,payload:values})
      assetVersion.value = saved.version_count || assetVersion.value
    }else{
      const created=await createSeoContentAsset(payload)
      assetId.value=created.id
      assetContentType.value=created.content_type||payload.content_type
      editingHumanized.value=Boolean(payload.humanized_content)
      assetVersion.value=created.version_count||1
      sourcePageId.value=created.source_page_id||null
      await router.replace({ query: { ...route.query, id: created.id, source_page_id: created.source_page_id || undefined } })
    }
    assetStatus.value = status
    saveState.value = status === 'published' ? '已发布' : '刚刚已保存'
    if (!options.quiet) showSuccess(status === 'published' ? '文章发布记录已保存' : '文章草稿已保存')
    return true
  } catch (e) { ElMessage.error(e.message) } finally { saving.value = false }
}

async function submitReview() {
  if (!['planned', 'drafting'].includes(assetStatus.value)) return ElMessage.warning('当前状态不能重复提交审核')
  const saved = await save('drafting', { quiet: true })
  if (!saved || !assetId.value) return
  saving.value = true
  try {
    await submitSeoContentReview({ contentId: assetId.value, tenantId: currentTenantId.value })
    assetStatus.value = 'review'
    saveState.value = '已提交审核'
    showSuccess('文章已提交审核')
    router.push(backPath.value)
  } catch (e) { ElMessage.error(e.message) } finally { saving.value = false }
}

function loadPendingRewrite() {
  if (mode.value !== 'rewrite' || assetId.value) return null
  sourceText.value = sessionStorage.getItem('seo_pending_rewrite_source') || ''
  let options = {}
  try {
    options = JSON.parse(sessionStorage.getItem('seo_pending_rewrite_options') || '{}')
    if (options.sourceTitle && !form.title) form.title = `${options.sourceTitle}（改写）`
    if (options.keywordId) form.keyword_ids = [Number(options.keywordId)]
    prompt.value = [
      options.sourceOrigin ? `原文来源：${options.sourceOrigin}` : '',
      options.rewriteStrength ? `改写强度：${options.rewriteStrength}` : '',
      options.targetKeywords ? `重点自然植入这些关键词：${options.targetKeywords}` : '',
    ].filter(Boolean).join('；')
  } catch {
    prompt.value = ''
  }
  sessionStorage.removeItem('seo_pending_rewrite_source')
  sessionStorage.removeItem('seo_pending_rewrite_options')
  return options
}

function openPublish() {
  syncDraft()
  if (!form.title.trim()) return ElMessage.warning('请先填写文章标题')
  if (!form.draft.trim()) return ElMessage.warning('请先生成或填写改写正文')
  publishVisible.value = true
}

async function publish() {
  let url
  try { url = new URL(publishForm.page_url.trim()) } catch { return ElMessage.warning('请填写完整的发布地址') }
  if (!['http:', 'https:'].includes(url.protocol)) return ElMessage.warning('发布地址必须使用 http 或 https')
  const platforms = publishForm.target_platforms.length ? [...publishForm.target_platforms] : [url.hostname]
  const now = new Date().toISOString()
  const saved = await save('published', { pageUrl: url.toString(), targetPlatforms: platforms, publishedAt: now })
  if (!saved) return
  Object.assign(publishForm,{page_url:url.toString(),target_platforms:platforms})
  publishedAt.value=now
  publishVisible.value=false
  router.push('/seo/distribution')
}

onMounted(async () => {
  form.outline = selectedTemplate.value.outline
  if (route.query.keyword_id) form.keyword_ids = [Number(route.query.keyword_id)].filter(Number.isFinite)
  const pending = loadPendingRewrite()
  try { await loadSites() } catch (e) { ElMessage.error(e.message) }
  await loadSourcePageBrief()
  if (mode.value === 'rewrite' && pending?.autoGenerate && sourceText.value) {
    const generated = await assist('rewrite')
    if (generated) await save('drafting', { quiet: true })
  }
})
</script>

<template>
  <div class="editor-page">
    <header class="editor-topbar">
      <button class="editor-back" type="button" @click="router.push(backPath)">← 返回{{ mode==='rewrite'?'文章改写':mode==='qa'?'问答运营':'原创文章' }}</button>
      <div><h1>{{ pageTitle }}</h1><p>{{ assetId ? `${contentTypeLabel} · 任务 #${assetId}` : mode==='rewrite'?'基于导入原文 · 深度改写':mode==='qa'?'搜索问答 · 新建回答':`${selectedTemplate.name} · 新建内容` }}</p></div>
      <div class="editor-top-actions"><span>{{ saveState }}</span><button v-if="sourcePageId" type="button" @click="router.push(sourcePageRoute)">返回承接页</button><button v-if="['planned','drafting'].includes(assetStatus)" type="button" :disabled="saving || editorComposing" @click="save('drafting')">保存草稿</button><button v-if="['planned','drafting'].includes(assetStatus)" type="button" :disabled="saving || editorComposing" @click="submitReview">提交审核</button><button v-if="assetStatus==='ready' && landingBindingMissing" type="button" @click="router.push(backPath)">先绑定承接页</button><button v-if="assetStatus==='ready' && !landingBindingMissing" class="primary" type="button" @click="router.push('/seo/distribution')">进入发布流程</button><b>{{ String(session.user?.name || session.user?.username || 'DZ').slice(0, 2).toUpperCase() }}</b></div>
    </header>

    <main class="editor-workspace">
      <aside class="editor-side">
        <section class="side-section"><h3>内容 Brief</h3><div v-if="sourcePage" class="source-link"><b>来源站内页面 #{{ sourcePage.id }}</b><span>{{ sourcePage.title || sourcePage.url }}</span><button type="button" @click="router.push(sourcePageRoute)">查看页面优化记录</button></div><label>SEO 网站</label><el-select v-model="siteId" :disabled="!!assetId||!!sourcePageId" placeholder="选择 SEO 网站" @change="changeSite"><el-option v-for="site in sites" :key="site.id" :label="site.name || site.canonical_domain" :value="site.id" /></el-select><label>搜索引擎</label><div class="engine-picks"><button v-for="item in ['百度', 'Google', 'Bing']" :key="item" :class="{ selected: engine === item }" type="button" @click="engine = item">{{ item }}</button></div><label>目标关键词（1–5个）</label><el-select v-model="form.keyword_ids" class="brief-keywords" multiple collapse-tags collapse-tags-tooltip :max-collapse-tags="2" :multiple-limit="5" filterable placeholder="选择主关键词和辅助关键词"><el-option v-for="item in keywords" :key="item.id" :label="item.keyword" :value="item.id" /></el-select><small class="keyword-guidance">第一个为主关键词。建议选择 1 个品牌词，再搭配 1–2 个产品词、应用词或行业词。</small><label>内容模式</label><input :value="assetId ? contentTypeLabel : (mode==='rewrite'?'深度改写':mode==='qa'?'专题问答':selectedTemplate.name)" readonly><label>负责人</label><input v-model="form.author" placeholder="负责人"></section>
        <section v-if="sourceRemediation" class="side-section remediation-context"><h3>承接页整改依据 <em>检测：程序</em></h3><div class="remediation-meta"><b>{{ sourceRemediation.score == null ? '未评分' : `${sourceRemediation.score} 分` }}</b><span>{{ formatSourceCheckedAt(sourceRemediation.checkedAt) }}</span></div><dl><dt>当前 Title</dt><dd>{{ sourceRemediation.current.title }}</dd><dt>已存档 Title 建议</dt><dd class="suggested">{{ sourceRemediation.suggested.title }}</dd><dt>当前 Description</dt><dd>{{ sourceRemediation.current.description }}</dd><dt>已存档 Description 建议</dt><dd class="suggested">{{ sourceRemediation.suggested.description }}</dd><dt>当前 H1</dt><dd>{{ sourceRemediation.current.h1 }}</dd><dt>规则建议 H1 处理</dt><dd class="suggested">{{ sourceRemediation.suggested.h1 }}</dd></dl><div v-if="sourceRemediation.issues.length" class="remediation-issues"><article v-for="item in sourceRemediation.issues" :key="item.code"><b>{{ item.label }}</b><p>{{ item.action }}</p></article></div><p v-else class="remediation-empty">未记录结构化问题，仍需人工核对搜索意图。</p><button class="side-action" type="button" @click="applySourcePageGuidance">填入 AI 要求（不调用 AI）</button><small class="program-note">问题与规则动作由程序生成；TDK 建议是历史存档，可能经 AI 或人工编辑。AI 只在你主动点击生成后介入。</small></section>
        <section v-if="mode==='rewrite'" class="side-section"><h3>原文事实基础</h3><div class="source-box">{{sourceText||'尚未导入原文'}}</div></section>
        <section class="side-section"><h3>文章结构</h3><textarea v-model="form.outline" rows="10" /><button class="side-action" type="button" @click="insertOutline">应用大纲到正文</button></section>
        <section class="side-section brief-score"><div><b>{{ keywords.length }}</b><span>可选关键词</span></div><div><b>{{ wordCount }}</b><span>当前字数</span></div></section>
      </aside>

      <section class="editor-center">
        <div class="document-frame">
          <div class="editor-toolbar" @mousedown.prevent><button type="button" :disabled="workflowLocked || editorComposing" @click="command('formatBlock', 'p')">正文</button><button type="button" :disabled="workflowLocked || editorComposing" @click="command('formatBlock', 'h2')">H2</button><button type="button" :disabled="workflowLocked || editorComposing" @click="command('formatBlock', 'h3')">H3</button><button type="button" :disabled="workflowLocked || editorComposing" @click="command('formatBlock', 'blockquote')">引用</button><button type="button" :disabled="workflowLocked || editorComposing" @click="command('insertHorizontalRule')">分隔线</button><i /><button type="button" :disabled="workflowLocked || editorComposing" @click="command('bold')">B</button><button type="button" :disabled="workflowLocked || editorComposing" @click="command('italic')">I</button><button type="button" :disabled="workflowLocked || editorComposing" @click="command('insertUnorderedList')">无序列表</button><button type="button" :disabled="workflowLocked || editorComposing" @click="command('insertOrderedList')">有序列表</button><i /><button type="button" :disabled="workflowLocked || editorComposing" @click="insertLink">插入/编辑链接</button><button type="button" :disabled="workflowLocked || editorComposing" @click="command('unlink')">取消链接</button><button type="button" :disabled="workflowLocked || editorComposing" @click="editorUndo()">撤销</button><button type="button" :disabled="workflowLocked || editorComposing" @click="editorUndo(true)">重做</button><button type="button" :disabled="workflowLocked || editorComposing" @click="command('removeFormat')">清除格式</button><i /><button type="button" :disabled="workflowLocked || editorComposing" @click="insertTable">插入表格</button><button type="button" :disabled="workflowLocked || editorComposing" @click="insertImage">插入图片</button><button v-if="selectedCell" type="button" :disabled="workflowLocked || editorComposing" @click="tableAction('rowAbove')">上方插入行</button><button v-if="selectedCell" type="button" :disabled="workflowLocked || editorComposing" @click="tableAction('rowBelow')">下方插入行</button><button v-if="selectedCell" type="button" :disabled="workflowLocked || editorComposing" @click="tableAction('columnLeft')">左插入列</button><button v-if="selectedCell" type="button" :disabled="workflowLocked || editorComposing" @click="tableAction('columnRight')">右插入列</button><button v-if="selectedCell" type="button" :disabled="workflowLocked || editorComposing" @click="tableAction('deleteRow')">删除行</button><button v-if="selectedCell" type="button" :disabled="workflowLocked || editorComposing" @click="tableAction('deleteColumn')">删除列</button><button v-if="selectedCell" type="button" :disabled="workflowLocked || editorComposing" @click="tableAction('deleteTable')">删除表格</button><button v-if="selectedFigure" type="button" :disabled="workflowLocked || editorComposing" @click="imageLayout('seo-align-left')">左对齐</button><button v-if="selectedFigure" type="button" :disabled="workflowLocked || editorComposing" @click="imageLayout('seo-align-center')">居中</button><button v-if="selectedFigure" type="button" :disabled="workflowLocked || editorComposing" @click="imageLayout('seo-align-right')">右对齐</button><button v-if="selectedFigure" type="button" :disabled="workflowLocked || editorComposing" @click="imageLayout('seo-w-25')">25%</button><button v-if="selectedFigure" type="button" :disabled="workflowLocked || editorComposing" @click="imageLayout('seo-w-50')">50%</button><button v-if="selectedFigure" type="button" :disabled="workflowLocked || editorComposing" @click="imageLayout('seo-w-75')">75%</button><button v-if="selectedFigure" type="button" :disabled="workflowLocked || editorComposing" @click="imageLayout('seo-w-100')">100%</button></div>
          <div class="document-scroll"><input v-model="form.title" class="document-title" :readonly="workflowLocked" :placeholder="mode==='qa'?'输入问题标题':'输入文章标题'"><div ref="editor" class="article-editor" :contenteditable="!workflowLocked" :data-placeholder="mode==='qa'?'从这里开始撰写回答…':'从这里开始撰写正文…'" @compositionstart="startEditorComposition" @compositionend="finishEditorComposition" @input="syncDraft" @blur="syncDraft" @paste="pasteEditor" @keydown="editorKeydown" @keyup="editorSelection" @mouseup="editorSelection" @click="editorSelection" /></div>
          <footer class="document-status"><span>{{ wordCount.toLocaleString() }} 字</span><span>{{ engine }}</span><span :title="keywordSummary">{{ keywordNames.length }} 个目标词</span><span>{{ saveState }}</span></footer>
        </div>
      </section>

      <aside class="ai-side">
        <header><h3>AI 内容助手</h3><p>结合关键词、模板与品牌资料辅助创作</p></header>
        <div class="ai-body"><textarea v-model="prompt" maxlength="5000" placeholder="输入你的内容要求，例如：保留事实并深度重构表达…" /><p v-if="sourcePageId" class="grounding-note">承接页检测摘要不等于正文事实资料。AI 可先生成整改大纲；需生成正文时，请先将经核验的官网内容粘贴到正文，再点“优化表达”。</p><button class="ai-primary" type="button" :disabled="!!aiBusy" @click="assist(primaryAiAction)">{{ primaryAiLabel }}</button><div class="quick-actions"><button type="button" :disabled="!!aiBusy" @click="assist('outline')">{{aiBusy==='outline'?'生成中…':'生成大纲'}}</button><button type="button" :disabled="!!aiBusy" @click="assist('title')">{{aiBusy==='title'?'优化中…':'标题优化'}}</button><button type="button" :disabled="!!aiBusy" @click="assist('keywords')">{{aiBusy==='keywords'?'检查中…':'检查关键词'}}</button><button type="button" :disabled="!!aiBusy" @click="assist('rewrite')">{{aiBusy==='rewrite'?'优化中…':'优化表达'}}</button></div><div v-if="aiMessage" class="ai-message">{{ aiMessage }}</div><ul><li><span>AI 服务</span><b class="ok">DeepSeek</b></li><li><span>标题完整</span><b :class="{ ok: form.title }">{{ form.title ? '通过' : '待完善' }}</b></li><li><span>目标关键词</span><b :class="{ ok: form.keyword_ids.length }">{{ form.keyword_ids.length ? `已绑定 ${form.keyword_ids.length} 个` : '待选择' }}</b></li><li><span>正文内容</span><b :class="{ ok: wordCount > 300 }">{{ wordCount > 300 ? '已形成' : '待完善' }}</b></li></ul></div>
      </aside>
    </main>
    <el-dialog v-model="publishVisible" title="发布改写文章" width="620px">
      <el-form label-position="top">
        <el-alert title="系统登记发布结果，不会在未授权的第三方账号中自动发文。" type="info" :closable="false" show-icon />
        <el-form-item label="发布地址" required><el-input v-model="publishForm.page_url" placeholder="https://example.com/article" /></el-form-item>
        <el-form-item label="目标平台"><el-checkbox-group v-model="publishForm.target_platforms"><el-checkbox v-for="item in ['官网','微信公众号','知乎','百家号','头条号']" :key="item" :value="item">{{item}}</el-checkbox></el-checkbox-group></el-form-item>
      </el-form>
      <template #footer><el-button @click="publishVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="publish">确认发布</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.editor-toolbar{flex-wrap:wrap}.editor-toolbar button{width:auto!important;min-width:30px;padding:0 6px!important}.editor-toolbar button:disabled{opacity:.45;cursor:default}
.article-editor :deep(.seo-table){display:block;max-width:100%;overflow-x:auto;border-collapse:collapse;clear:both;margin:16px 0}
.article-editor :deep(th),.article-editor :deep(td){border:1px solid #cbd5e1;padding:8px;min-width:70px}
.article-editor :deep(th){background:#f1f5f9}
.article-editor :deep(.seo-figure){max-width:100%;margin:16px 0}
.article-editor :deep(img){max-width:100%;height:auto}
.article-editor :deep(.seo-figure img){display:block;width:100%}
.article-editor :deep(figcaption){color:#64748b;font-size:12px;text-align:center}
.article-editor :deep(.seo-align-left){float:left;margin:8px 16px 8px 0}
.article-editor :deep(.seo-align-center){float:none;clear:both;margin:16px auto}
.article-editor :deep(.seo-align-right){float:right;margin:8px 0 8px 16px}
.article-editor :deep(.seo-w-25){width:25%}.article-editor :deep(.seo-w-50){width:50%}.article-editor :deep(.seo-w-75){width:75%}.article-editor :deep(.seo-w-100){width:100%}
.article-editor :deep(blockquote){border-left:3px solid #cbd5e1;padding:8px 16px;background:#f8fafc;margin:16px 0;clear:both}
.article-editor :deep(hr){border:0;border-top:1px solid #cbd5e1;clear:both}
.article-editor::after{content:'';display:block;clear:both}
.article-editor { overflow-wrap: anywhere; }
.grounding-note{margin:8px 0 0;padding:8px;border-left:2px solid #d97706;background:#fff8ee;color:#705a3b;font-size:10px;line-height:1.55}
.source-link{margin-bottom:10px;padding:9px;border:1px solid #cfe0ff;border-radius:7px;background:#f4f7ff}.source-link b,.source-link span{display:block}.source-link b{color:#1d4ed8;font-size:10.5px}.source-link span{margin:4px 0 7px;overflow:hidden;color:#667085;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.source-link button{padding:0;border:0;background:transparent;color:#2563eb;font-size:10px;cursor:pointer}
.remediation-context h3{display:flex;align-items:center;justify-content:space-between}.remediation-context h3 em{padding:2px 5px;border-radius:4px;background:#e8f7f1;color:#187a5d;font-size:8.5px;font-style:normal}.remediation-meta{display:flex;align-items:center;justify-content:space-between;margin-bottom:9px;padding:8px;border-radius:6px;background:#f5f8f7}.remediation-meta b{color:#168b83;font-size:15px}.remediation-meta span{color:#7b8683;font-size:8.5px}.remediation-context dl{margin:0}.remediation-context dt{margin-top:8px;color:#7d8793;font-size:9px}.remediation-context dd{margin:2px 0 0;overflow-wrap:anywhere;color:#4d5665;font-size:10px;line-height:1.5}.remediation-context dd.suggested{color:#126e68}.remediation-issues{display:grid;gap:6px;margin-top:10px}.remediation-issues article{padding:7px;border-left:2px solid #d97706;background:#fff8ee}.remediation-issues b{font-size:9.5px}.remediation-issues p,.remediation-empty,.program-note{margin:3px 0 0;color:#707a87;font-size:9px;line-height:1.5}.program-note{display:block;margin-top:6px}
.keyword-guidance{display:block;margin-top:6px;color:#8a93a1;font-size:9.5px;line-height:1.55}.brief-keywords{width:100%}.side-section :deep(.brief-keywords .el-select__wrapper){min-height:34px;padding:4px 8px;border-radius:6px;box-shadow:0 0 0 1px #dfe3e9 inset}
.editor-page{min-height:100vh;background:#eef2f7;color:#1e2330;font-family:-apple-system,"PingFang SC","Microsoft YaHei","Segoe UI",Roboto,sans-serif}.editor-topbar{position:relative;z-index:5;min-height:76px;padding:0 24px 0 28px;display:flex;align-items:center;gap:18px;border-bottom:1px solid #dde3ec;background:linear-gradient(180deg,#fff 0%,#fbfcff 100%)}.editor-back{min-height:34px;padding:0 10px;border:1px solid transparent;border-radius:7px;background:transparent;color:#596272;font-size:12px;font-weight:650;cursor:pointer}.editor-back:hover{border-color:#d9e4fb;background:#f3f7ff;color:#1d4ed8}.editor-topbar h1{margin:0;font-size:16px}.editor-topbar p{margin:2px 0 0;color:#6b7280;font-size:12px}.editor-top-actions{margin-left:auto;display:flex;align-items:center;gap:10px}.editor-top-actions span{min-width:82px;color:#6f7785;font-size:11px;text-align:right}.editor-top-actions button,.side-action,.ai-primary{padding:8px 14px;border:1px solid #e8eaf0;border-radius:9px;background:#fff;color:#1e2330;font-size:12px;font-weight:600;cursor:pointer}.editor-top-actions button.primary,.side-action,.ai-primary{border-color:#2563eb;background:#2563eb;color:#fff}.editor-top-actions b{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:#2563eb;color:#fff;font-size:12px}.editor-workspace{height:calc(100vh - 76px);min-height:650px;padding:14px;display:grid;grid-template-columns:252px minmax(520px,1fr) 306px;gap:14px;overflow:hidden;background:#eef2f7}.editor-side,.ai-side{overflow-y:auto;border:1px solid #dce2eb;border-radius:8px;background:#fff;box-shadow:0 10px 24px rgba(31,41,55,.06)}.side-section{padding:16px;border-bottom:1px solid #e8eaf0}.side-section h3{margin:0 0 12px;color:#303746;font-size:12px}.side-section label{display:block;margin:11px 0 5px;color:#777f8d;font-size:10.5px;font-weight:650}.side-section :is(input,select,textarea),.ai-body textarea{width:100%;padding:8px 9px;border:1px solid #dfe3e9;border-radius:6px;outline:none;background:#fff;color:#303746;font:inherit;font-size:11.5px}.side-section textarea{resize:vertical;line-height:1.6}.source-box{max-height:150px;overflow:auto;padding:9px;border:1px solid #dfe3e9;border-radius:6px;background:#f7f8fa;color:#66707e;font-size:10.5px;line-height:1.6}.engine-picks{display:flex;flex-wrap:wrap;gap:6px}.engine-picks button{padding:5px 7px;border:1px solid #dfe3e9;border-radius:5px;background:#f8f9fb;color:#626b79;font-size:10.5px;cursor:pointer}.engine-picks button.selected{border-color:#9bb9f6;background:#eff4ff;color:#1d4ed8}.side-action{width:100%;margin-top:9px}.brief-score{display:grid;grid-template-columns:1fr 1fr;gap:7px}.brief-score div{padding:8px;border-left:2px solid #2563eb;background:#f5f7fb}.brief-score div:last-child{border-color:#16a34a}.brief-score b,.brief-score span{display:block}.brief-score b{font-size:16px}.brief-score span{color:#7d8592;font-size:9.5px}.editor-center{min-width:0;display:flex;flex-direction:column;overflow:hidden}.document-frame{width:min(820px,100%);min-height:0;margin:0 auto;display:flex;flex:1;flex-direction:column;overflow:hidden;border:1px solid #d7dce4;border-radius:8px;background:#fff;box-shadow:0 14px 32px rgba(34,43,60,.09)}.editor-toolbar{min-height:44px;padding:6px 10px;display:flex;align-items:center;gap:3px;border-bottom:1px solid #e4e7ec;background:#fbfcfd}.editor-toolbar button{width:30px;height:30px;padding:0;border:1px solid transparent;border-radius:5px;background:transparent;color:#505866;font-size:12px;font-weight:750;cursor:pointer}.editor-toolbar button:hover{border-color:#d4dff5;background:#eff4ff;color:#1d4ed8}.editor-toolbar i{width:1px;height:20px;margin:0 4px;background:#e1e4e9}.document-scroll{flex:1;overflow-y:auto;padding:38px clamp(32px,6vw,70px) 60px}.document-title{width:100%;margin-bottom:22px;padding:0 0 14px;border:0;border-bottom:1px solid #edf0f3;outline:none;background:transparent;color:#1d2432;font-size:25px;font-weight:750;line-height:1.35}.article-editor{min-height:420px;outline:none;color:#313846;font-size:14px;line-height:1.92}.article-editor:empty::before{color:#a0a7b2;content:attr(data-placeholder)}.article-editor :deep(h2){margin:28px 0 10px;color:#1f2735;font-size:19px}.article-editor :deep(h3){margin:22px 0 8px;font-size:16px}.article-editor :deep(p){margin:0 0 12px}.document-status{min-height:34px;padding:6px 12px;display:flex;align-items:center;gap:16px;border-top:1px solid #e8eaf0;background:#fbfcfd;color:#7c8491;font-size:10.5px}.document-status span:last-child{margin-left:auto}.ai-side>header{padding:17px 16px 14px;border-bottom:1px solid #e8eaf0;background:#202838}.ai-side>header h3{margin:0 0 4px;color:#fff;font-size:13px}.ai-side>header p{margin:0;color:#aeb7c6;font-size:10.5px}.ai-body{padding:14px}.ai-body textarea{min-height:78px;resize:vertical;line-height:1.55}.ai-primary{width:100%;margin-top:8px}.quick-actions{margin:13px 0;display:grid;grid-template-columns:1fr 1fr;gap:7px}.quick-actions button{min-height:48px;padding:8px;border:1px solid #e0e4ea;border-radius:6px;background:#f8f9fb;color:#4e5868;font-size:10.5px;text-align:left;cursor:pointer}.quick-actions button:hover{border-color:#adc3ef;background:#f0f5ff;color:#1d4ed8}.ai-message{margin-top:10px;padding:10px;border-left:2px solid #16a34a;background:#f0faf4;color:#5f6877;font-size:10.5px;line-height:1.55}.ai-body ul{margin:14px 0 0;padding:0;list-style:none}.ai-body li{padding:8px 0;display:flex;align-items:center;border-bottom:1px solid #eceef2;color:#626b79;font-size:10.5px}.ai-body li b{margin-left:auto;color:#d97706}.ai-body li b.ok{color:#16a34a}@media(max-width:1280px){.editor-workspace{grid-template-columns:232px minmax(460px,1fr) 280px}}@media(max-width:1020px){.editor-workspace{height:auto;grid-template-columns:1fr;overflow:visible}.editor-center{min-height:760px}}@media(max-width:700px){.editor-topbar{padding:12px 14px;flex-wrap:wrap}.editor-top-actions{width:100%;margin-left:0}.editor-top-actions span{display:none}.editor-workspace{padding:10px}.document-scroll{padding:28px 24px}}
</style>
