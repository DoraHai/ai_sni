<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { assistSeoContent, createSeoContentAsset, fetchSeoContentAssets, fetchSeoKeywords, fetchSeoSitePages, updateSeoContentAsset } from '../../api/seo'
import { fetchSeoSites } from '../../api/moduleAssets'
import { currentTenantId, session } from '../../store/session'
import { currentSeoSiteId as siteId } from './seoSiteContext'

const route = useRoute()
const router = useRouter()
const editor = ref(null)
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
const wordCount = computed(() => Array.from(form.draft.replace(/<[^>]+>/g, '').replace(/\s+/g, '')).length)
const keywordNames = computed(() => form.keyword_ids.map((id) => keywords.value.find((item) => item.id === id)?.keyword).filter(Boolean))
const keywordSummary = computed(() => keywordNames.value.length ? keywordNames.value.join('、') : '尚未选择')
const primaryAiAction = computed(() => mode.value === 'rewrite' ? 'rewrite' : 'generate')
const primaryAiLabel = computed(() => {
  if (aiBusy.value === primaryAiAction.value) return mode.value === 'rewrite' ? 'DeepSeek 改写中…' : 'DeepSeek 生成中…'
  return mode.value === 'rewrite' ? 'DeepSeek 开始改写' : 'AI 生成初稿'
})

const editorAllowedTags = new Set(['P','H1','H2','H3','H4','H5','H6','A','IMG','UL','OL','LI','STRONG','B','EM','I','U','S','BLOCKQUOTE','PRE','CODE','BR','HR','TABLE','THEAD','TBODY','TR','TH','TD','FIGURE','FIGCAPTION'])
const editorBlockedTags = new Set(['SCRIPT','STYLE','IFRAME','OBJECT','EMBED','FORM','INPUT','BUTTON','LINK','META'])
const editorAllowedAttributes = new Set(['href','src','data-src','alt','title'])

function sanitizeEditorHtml(value) {
  const template = document.createElement('template')
  template.innerHTML = String(value || '')
  for (const node of [...template.content.querySelectorAll('*')]) {
    if (editorBlockedTags.has(node.tagName)) {
      node.remove()
      continue
    }
    if (!editorAllowedTags.has(node.tagName)) {
      node.replaceWith(...node.childNodes)
      continue
    }
    for (const attribute of [...node.attributes]) {
      const name = attribute.name.toLowerCase()
      if (!editorAllowedAttributes.has(name)) node.removeAttribute(attribute.name)
    }
    for (const name of ['href', 'src', 'data-src']) {
      const target = node.getAttribute(name)?.trim()
      if (target && !/^(https?:|\/|#)/i.test(target)) node.removeAttribute(name)
    }
  }
  return template.innerHTML.trim()
}

async function load() {
  if (!currentTenantId.value || !siteId.value) return
  try {
    const [wordResult,contentResult] = await Promise.all([
      fetchSeoKeywords({ tenantId: currentTenantId.value, siteId: siteId.value, pageSize: 200 }),
      assetId.value ? fetchSeoContentAssets({ tenantId: currentTenantId.value, siteId: siteId.value }) : Promise.resolve({items:[]}),
    ])
    keywords.value = wordResult.items
    if (assetId.value) {
      const item = contentResult.items.find((row) => row.id === assetId.value)
      if (!item) return ElMessage.warning('改写任务不存在或已被删除')
      Object.assign(form,{title:item.title||'',keyword_ids:[...(item.keyword_ids?.length?item.keyword_ids:item.keyword_id?[item.keyword_id]:[])],outline:item.outline||'',draft:sanitizeEditorHtml(item.humanized_content||item.draft||''),author:item.author||form.author})
      Object.assign(publishForm,{page_url:item.page_url||'',target_platforms:[...(item.target_platforms||[])]})
      publishedAt.value=item.published_at||null
      sourceText.value=item.source_text||''
      sourcePageId.value=item.source_page_id||sourcePageId.value||null
      assetVersion.value=item.version_count||1
      await nextTick()
      if(editor.value)editor.value.innerHTML=form.draft
      saveState.value='已载入任务'
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
    if (assetId.value) return
    if (!form.title) form.title = page.title_suggestion || page.title || ''
    if (!form.keyword_ids.length && page.target_keyword_id) form.keyword_ids = [page.target_keyword_id]
    prompt.value = `本内容任务来自站内页面优化：${page.url}。需要处理的问题：${(page.issue_codes || []).join('、') || '补充页面内容'}。建议 Title：${page.title_suggestion || '待完善'}；建议 Description：${page.description_suggestion || '待完善'}。请围绕已选关键词生成与该页面匹配、可供人工审核的内容。`
    saveState.value = '已关联站内优化任务'
  } catch (e) { ElMessage.warning(e.message) }
}

function syncDraft() {
  form.draft = editor.value?.innerHTML || ''
  saveState.value = '编辑中…'
}

function command(name, value = null) {
  editor.value?.focus()
  document.execCommand(name, false, value)
  syncDraft()
}

function insertOutline() {
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
  return (template.content.textContent || '').trim()
}

function buildAssistPayload(action, draftText) {
  const keywordIds = form.keyword_ids
    .map((id) => Number(id))
    .filter((id) => Number.isInteger(id) && id > 0)
  const payload = {
    tenant_id: Number(currentTenantId.value),
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
    payload.source_text = sourceText.value.trim() || null
  }
  return payload
}

async function assist(action) {
  if (!currentTenantId.value) return ElMessage.warning('请先选择客户')
  if (!siteId.value) return ElMessage.warning('请先选择或创建 SEO 网站')
  if (['generate','outline','title','keywords'].includes(action) && !form.keyword_ids.length) return ElMessage.warning('请至少选择 1 个目标关键词')
  syncDraft()
  const draftText = draftForAi()
  if (action === 'keywords' && !form.title.trim() && !draftText) return ElMessage.warning('请先输入标题或正文，再检查关键词')
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
      if (mode.value === 'rewrite') assetVersion.value += 1
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
      content_type: mode.value === 'rewrite' ? 'rewrite' : mode.value === 'qa' ? 'qa' : selectedTemplate.value.type,
      outline: form.outline || selectedTemplate.value.outline,
      draft: form.draft || null,
      humanized_content: mode.value === 'rewrite' ? form.draft || null : null,
      source_text: mode.value === 'rewrite' ? sourceText.value || null : null,
      rewrite_progress: mode.value === 'rewrite' ? (form.draft ? 100 : 0) : null,
      originality_score: null,
      target_platforms: options.targetPlatforms ?? publishForm.target_platforms,
      version_count: assetVersion.value,
      status,
      page_url: (options.pageUrl ?? publishForm.page_url) || null,
      author: form.author || null,
      published_at: options.publishedAt ?? publishedAt.value,
    }
    if(assetId.value){
      const {tenant_id,site_id,...values}=payload
      await updateSeoContentAsset({contentId:assetId.value,tenantId:currentTenantId.value,payload:values})
    }else{
      const created=await createSeoContentAsset(payload)
      assetId.value=created.id
      sourcePageId.value=created.source_page_id||null
      await router.replace({ query: { ...route.query, id: created.id, source_page_id: created.source_page_id || undefined } })
    }
    saveState.value = status === 'published' ? '已发布' : status === 'review' ? '已提交审核' : '刚刚已保存'
    if (!options.quiet) ElMessage.success(status === 'published' ? '文章发布记录已保存' : status === 'review' ? '文章已提交审核' : '文章草稿已保存')
    if (status === 'review') router.push(backPath.value)
    return true
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
      <div><h1>{{ pageTitle }}</h1><p>{{ mode==='rewrite'?'基于导入原文 · 深度改写':mode==='qa'?'搜索问答 · 新建回答':`${selectedTemplate.name} · 新建内容` }}</p></div>
      <div class="editor-top-actions"><span>{{ saveState }}</span><button v-if="sourcePageId" type="button" @click="router.push(sourcePageRoute)">返回来源页面</button><button type="button" @click="save('drafting')">保存草稿</button><button type="button" :disabled="saving" @click="save('review')">提交审核</button><button v-if="mode==='rewrite'" class="primary" type="button" :disabled="saving||!!aiBusy" @click="openPublish">发布</button><b>{{ String(session.user?.name || session.user?.username || 'DZ').slice(0, 2).toUpperCase() }}</b></div>
    </header>

    <main class="editor-workspace">
      <aside class="editor-side">
        <section class="side-section"><h3>内容 Brief</h3><div v-if="sourcePage" class="source-link"><b>来源站内页面 #{{ sourcePage.id }}</b><span>{{ sourcePage.title || sourcePage.url }}</span><button type="button" @click="router.push(sourcePageRoute)">查看页面优化记录</button></div><label>SEO 网站</label><el-select v-model="siteId" :disabled="!!assetId||!!sourcePageId" placeholder="选择 SEO 网站" @change="changeSite"><el-option v-for="site in sites" :key="site.id" :label="site.name || site.canonical_domain" :value="site.id" /></el-select><label>搜索引擎</label><div class="engine-picks"><button v-for="item in ['百度', 'Google', 'Bing']" :key="item" :class="{ selected: engine === item }" type="button" @click="engine = item">{{ item }}</button></div><label>目标关键词（1–5个）</label><el-select v-model="form.keyword_ids" class="brief-keywords" multiple collapse-tags collapse-tags-tooltip :max-collapse-tags="2" :multiple-limit="5" filterable placeholder="选择主关键词和辅助关键词"><el-option v-for="item in keywords" :key="item.id" :label="item.keyword" :value="item.id" /></el-select><small class="keyword-guidance">第一个为主关键词。建议选择 1 个品牌词，再搭配 1–2 个产品词、应用词或行业词。</small><label>内容模式</label><input :value="mode==='rewrite'?'深度改写':mode==='qa'?'专题问答':selectedTemplate.name" readonly><label>负责人</label><input v-model="form.author" placeholder="负责人"></section>
        <section v-if="mode==='rewrite'" class="side-section"><h3>原文事实基础</h3><div class="source-box">{{sourceText||'尚未导入原文'}}</div></section>
        <section class="side-section"><h3>文章结构</h3><textarea v-model="form.outline" rows="10" /><button class="side-action" type="button" @click="insertOutline">应用大纲到正文</button></section>
        <section class="side-section brief-score"><div><b>{{ keywords.length }}</b><span>可选关键词</span></div><div><b>{{ wordCount }}</b><span>当前字数</span></div></section>
      </aside>

      <section class="editor-center">
        <div class="document-frame">
          <div class="editor-toolbar"><button type="button" title="标题 2" @click="command('formatBlock', 'h2')">H2</button><button type="button" title="标题 3" @click="command('formatBlock', 'h3')">H3</button><i /><button type="button" title="加粗" @click="command('bold')">B</button><button type="button" title="斜体" @click="command('italic')">I</button><button type="button" title="无序列表" @click="command('insertUnorderedList')">•</button><button type="button" title="有序列表" @click="command('insertOrderedList')">1.</button></div>
          <div class="document-scroll"><input v-model="form.title" class="document-title" :placeholder="mode==='qa'?'输入问题标题':'输入文章标题'"><div ref="editor" class="article-editor" contenteditable="true" :data-placeholder="mode==='qa'?'从这里开始撰写回答…':'从这里开始撰写正文…'" @input="syncDraft" /></div>
          <footer class="document-status"><span>{{ wordCount.toLocaleString() }} 字</span><span>{{ engine }}</span><span :title="keywordSummary">{{ keywordNames.length }} 个目标词</span><span>{{ saveState }}</span></footer>
        </div>
      </section>

      <aside class="ai-side">
        <header><h3>AI 内容助手</h3><p>结合关键词、模板与品牌资料辅助创作</p></header>
        <div class="ai-body"><textarea v-model="prompt" maxlength="5000" placeholder="输入你的内容要求，例如：保留事实并深度重构表达…" /><button class="ai-primary" type="button" :disabled="!!aiBusy" @click="assist(primaryAiAction)">{{ primaryAiLabel }}</button><div class="quick-actions"><button type="button" :disabled="!!aiBusy" @click="assist('outline')">{{aiBusy==='outline'?'生成中…':'生成大纲'}}</button><button type="button" :disabled="!!aiBusy" @click="assist('title')">{{aiBusy==='title'?'优化中…':'标题优化'}}</button><button type="button" :disabled="!!aiBusy" @click="assist('keywords')">{{aiBusy==='keywords'?'检查中…':'检查关键词'}}</button><button type="button" :disabled="!!aiBusy" @click="assist('rewrite')">{{aiBusy==='rewrite'?'优化中…':'优化表达'}}</button></div><div v-if="aiMessage" class="ai-message">{{ aiMessage }}</div><ul><li><span>AI 服务</span><b class="ok">DeepSeek</b></li><li><span>标题完整</span><b :class="{ ok: form.title }">{{ form.title ? '通过' : '待完善' }}</b></li><li><span>目标关键词</span><b :class="{ ok: form.keyword_ids.length }">{{ form.keyword_ids.length ? `已绑定 ${form.keyword_ids.length} 个` : '待选择' }}</b></li><li><span>正文内容</span><b :class="{ ok: wordCount > 300 }">{{ wordCount > 300 ? '已形成' : '待完善' }}</b></li></ul></div>
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
.source-link{margin-bottom:10px;padding:9px;border:1px solid #cfe0ff;border-radius:7px;background:#f4f7ff}.source-link b,.source-link span{display:block}.source-link b{color:#1d4ed8;font-size:10.5px}.source-link span{margin:4px 0 7px;overflow:hidden;color:#667085;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.source-link button{padding:0;border:0;background:transparent;color:#2563eb;font-size:10px;cursor:pointer}
.keyword-guidance{display:block;margin-top:6px;color:#8a93a1;font-size:9.5px;line-height:1.55}.brief-keywords{width:100%}.side-section :deep(.brief-keywords .el-select__wrapper){min-height:34px;padding:4px 8px;border-radius:6px;box-shadow:0 0 0 1px #dfe3e9 inset}
.editor-page{min-height:100vh;background:#eef2f7;color:#1e2330;font-family:-apple-system,"PingFang SC","Microsoft YaHei","Segoe UI",Roboto,sans-serif}.editor-topbar{position:relative;z-index:5;min-height:76px;padding:0 24px 0 28px;display:flex;align-items:center;gap:18px;border-bottom:1px solid #dde3ec;background:linear-gradient(180deg,#fff 0%,#fbfcff 100%)}.editor-back{min-height:34px;padding:0 10px;border:1px solid transparent;border-radius:7px;background:transparent;color:#596272;font-size:12px;font-weight:650;cursor:pointer}.editor-back:hover{border-color:#d9e4fb;background:#f3f7ff;color:#1d4ed8}.editor-topbar h1{margin:0;font-size:16px}.editor-topbar p{margin:2px 0 0;color:#6b7280;font-size:12px}.editor-top-actions{margin-left:auto;display:flex;align-items:center;gap:10px}.editor-top-actions span{min-width:82px;color:#6f7785;font-size:11px;text-align:right}.editor-top-actions button,.side-action,.ai-primary{padding:8px 14px;border:1px solid #e8eaf0;border-radius:9px;background:#fff;color:#1e2330;font-size:12px;font-weight:600;cursor:pointer}.editor-top-actions button.primary,.side-action,.ai-primary{border-color:#2563eb;background:#2563eb;color:#fff}.editor-top-actions b{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:#2563eb;color:#fff;font-size:12px}.editor-workspace{height:calc(100vh - 76px);min-height:650px;padding:14px;display:grid;grid-template-columns:252px minmax(520px,1fr) 306px;gap:14px;overflow:hidden;background:#eef2f7}.editor-side,.ai-side{overflow-y:auto;border:1px solid #dce2eb;border-radius:8px;background:#fff;box-shadow:0 10px 24px rgba(31,41,55,.06)}.side-section{padding:16px;border-bottom:1px solid #e8eaf0}.side-section h3{margin:0 0 12px;color:#303746;font-size:12px}.side-section label{display:block;margin:11px 0 5px;color:#777f8d;font-size:10.5px;font-weight:650}.side-section :is(input,select,textarea),.ai-body textarea{width:100%;padding:8px 9px;border:1px solid #dfe3e9;border-radius:6px;outline:none;background:#fff;color:#303746;font:inherit;font-size:11.5px}.side-section textarea{resize:vertical;line-height:1.6}.source-box{max-height:150px;overflow:auto;padding:9px;border:1px solid #dfe3e9;border-radius:6px;background:#f7f8fa;color:#66707e;font-size:10.5px;line-height:1.6}.engine-picks{display:flex;flex-wrap:wrap;gap:6px}.engine-picks button{padding:5px 7px;border:1px solid #dfe3e9;border-radius:5px;background:#f8f9fb;color:#626b79;font-size:10.5px;cursor:pointer}.engine-picks button.selected{border-color:#9bb9f6;background:#eff4ff;color:#1d4ed8}.side-action{width:100%;margin-top:9px}.brief-score{display:grid;grid-template-columns:1fr 1fr;gap:7px}.brief-score div{padding:8px;border-left:2px solid #2563eb;background:#f5f7fb}.brief-score div:last-child{border-color:#16a34a}.brief-score b,.brief-score span{display:block}.brief-score b{font-size:16px}.brief-score span{color:#7d8592;font-size:9.5px}.editor-center{min-width:0;display:flex;flex-direction:column;overflow:hidden}.document-frame{width:min(820px,100%);min-height:0;margin:0 auto;display:flex;flex:1;flex-direction:column;overflow:hidden;border:1px solid #d7dce4;border-radius:8px;background:#fff;box-shadow:0 14px 32px rgba(34,43,60,.09)}.editor-toolbar{min-height:44px;padding:6px 10px;display:flex;align-items:center;gap:3px;border-bottom:1px solid #e4e7ec;background:#fbfcfd}.editor-toolbar button{width:30px;height:30px;padding:0;border:1px solid transparent;border-radius:5px;background:transparent;color:#505866;font-size:12px;font-weight:750;cursor:pointer}.editor-toolbar button:hover{border-color:#d4dff5;background:#eff4ff;color:#1d4ed8}.editor-toolbar i{width:1px;height:20px;margin:0 4px;background:#e1e4e9}.document-scroll{flex:1;overflow-y:auto;padding:38px clamp(32px,6vw,70px) 60px}.document-title{width:100%;margin-bottom:22px;padding:0 0 14px;border:0;border-bottom:1px solid #edf0f3;outline:none;background:transparent;color:#1d2432;font-size:25px;font-weight:750;line-height:1.35}.article-editor{min-height:420px;outline:none;color:#313846;font-size:14px;line-height:1.92}.article-editor:empty::before{color:#a0a7b2;content:attr(data-placeholder)}.article-editor :deep(h2){margin:28px 0 10px;color:#1f2735;font-size:19px}.article-editor :deep(h3){margin:22px 0 8px;font-size:16px}.article-editor :deep(p){margin:0 0 12px}.document-status{min-height:34px;padding:6px 12px;display:flex;align-items:center;gap:16px;border-top:1px solid #e8eaf0;background:#fbfcfd;color:#7c8491;font-size:10.5px}.document-status span:last-child{margin-left:auto}.ai-side>header{padding:17px 16px 14px;border-bottom:1px solid #e8eaf0;background:#202838}.ai-side>header h3{margin:0 0 4px;color:#fff;font-size:13px}.ai-side>header p{margin:0;color:#aeb7c6;font-size:10.5px}.ai-body{padding:14px}.ai-body textarea{min-height:78px;resize:vertical;line-height:1.55}.ai-primary{width:100%;margin-top:8px}.quick-actions{margin:13px 0;display:grid;grid-template-columns:1fr 1fr;gap:7px}.quick-actions button{min-height:48px;padding:8px;border:1px solid #e0e4ea;border-radius:6px;background:#f8f9fb;color:#4e5868;font-size:10.5px;text-align:left;cursor:pointer}.quick-actions button:hover{border-color:#adc3ef;background:#f0f5ff;color:#1d4ed8}.ai-message{margin-top:10px;padding:10px;border-left:2px solid #16a34a;background:#f0faf4;color:#5f6877;font-size:10.5px;line-height:1.55}.ai-body ul{margin:14px 0 0;padding:0;list-style:none}.ai-body li{padding:8px 0;display:flex;align-items:center;border-bottom:1px solid #eceef2;color:#626b79;font-size:10.5px}.ai-body li b{margin-left:auto;color:#d97706}.ai-body li b.ok{color:#16a34a}@media(max-width:1280px){.editor-workspace{grid-template-columns:232px minmax(460px,1fr) 280px}}@media(max-width:1020px){.editor-workspace{height:auto;grid-template-columns:1fr;overflow:visible}.editor-center{min-height:760px}}@media(max-width:700px){.editor-topbar{padding:12px 14px;flex-wrap:wrap}.editor-top-actions{width:100%;margin-left:0}.editor-top-actions span{display:none}.editor-workspace{padding:10px}.document-scroll{padding:28px 24px}}
</style>
