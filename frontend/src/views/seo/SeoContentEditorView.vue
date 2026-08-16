<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { assistSeoContent, createSeoContentAsset, fetchSeoContentAssets, fetchSeoKeywords, updateSeoContentAsset } from '../../api/seo'
import { currentTenantId, session } from '../../store/session'

const route = useRoute()
const router = useRouter()
const editor = ref(null)
const saving = ref(false)
const saveState = ref('尚未保存')
const prompt = ref('')
const aiMessage = ref('')
const aiBusy = ref('')
const keywords = ref([])
const engine = ref('百度')
const sourceText = ref('')
const assetId = ref(Number(route.query.id) || null)
const assetVersion = ref(1)
const mode = computed(() => route.query.type === 'rewrite' ? 'rewrite' : route.query.type === 'qa' ? 'qa' : 'original')
const pageTitle = computed(() => mode.value === 'rewrite' ? '文章改写编辑' : mode.value === 'qa' ? '问答编辑器' : '原创文章编辑')
const backPath = computed(() => mode.value === 'rewrite' ? '/seo/content/rewrites' : mode.value === 'qa' ? '/seo/content/qa' : '/seo/content/articles')

const templateMap = {
  guide: { name: '完整选型指南', type: 'guide', outline: '一、用户为什么关注这个问题\n二、核心概念与选择标准\n三、关键能力逐项验证\n四、不同场景的适用建议\n五、常见问题' },
  compare: { name: '竞品对比评测', type: 'comparison', outline: '一、对比对象与选择标准\n二、核心能力对比\n三、成本与实施难度\n四、适用场景\n五、选择建议' },
  solution: { name: '行业解决方案', type: 'article', outline: '一、行业现状与痛点\n二、解决方案架构\n三、实施流程\n四、业务价值\n五、客户案例' },
  howto: { name: '操作教程', type: 'article', outline: '一、准备工作\n二、操作步骤\n三、配置说明\n四、常见错误\n五、检查清单' },
  opinion: { name: '行业观点', type: 'article', outline: '一、趋势背景\n二、关键数据\n三、核心观点\n四、影响分析\n五、结论' },
  faq: { name: '专题问答', type: 'faq', outline: '问题一\n问题二\n问题三\n问题四\n问题五' },
}
const selectedTemplate = computed(() => templateMap[route.query.template] || templateMap.guide)
const form = reactive({ title: '', keyword_id: null, outline: '', draft: '', author: session.user?.name || session.user?.username || '' })
const wordCount = computed(() => Array.from(form.draft.replace(/<[^>]+>/g, '').replace(/\s+/g, '')).length)
const keywordName = computed(() => keywords.value.find((item) => item.id === form.keyword_id)?.keyword || '尚未选择')
const primaryAiAction = computed(() => mode.value === 'rewrite' ? 'rewrite' : 'generate')
const primaryAiLabel = computed(() => {
  if (aiBusy.value === primaryAiAction.value) return mode.value === 'rewrite' ? 'DeepSeek 改写中…' : 'DeepSeek 生成中…'
  return mode.value === 'rewrite' ? 'DeepSeek 开始改写' : 'AI 生成初稿'
})

async function load() {
  if (!currentTenantId.value) return
  try {
    const [wordResult,contentResult] = await Promise.all([
      fetchSeoKeywords({ tenantId: currentTenantId.value, pageSize: 200 }),
      assetId.value ? fetchSeoContentAssets({ tenantId: currentTenantId.value }) : Promise.resolve({items:[]}),
    ])
    keywords.value = wordResult.items
    if (assetId.value) {
      const item = contentResult.items.find((row) => row.id === assetId.value)
      if (!item) return ElMessage.warning('改写任务不存在或已被删除')
      Object.assign(form,{title:item.title||'',keyword_id:item.keyword_id||null,outline:item.outline||'',draft:item.humanized_content||item.draft||'',author:item.author||form.author})
      sourceText.value=item.source_text||''
      assetVersion.value=item.version_count||1
      await nextTick()
      if(editor.value)editor.value.innerHTML=form.draft
      saveState.value='已载入任务'
    }
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

async function assist(action) {
  if (!currentTenantId.value) return ElMessage.warning('请先选择客户')
  syncDraft()
  aiBusy.value = action
  aiMessage.value = ''
  try {
    const result = await assistSeoContent({
      tenant_id: currentTenantId.value,
      action,
      mode: mode.value,
      keyword_id: form.keyword_id,
      title: form.title || null,
      outline: form.outline || null,
      draft: form.draft || null,
      source_text: sourceText.value || null,
      instruction: prompt.value || null,
      template: selectedTemplate.value.name,
      engine: engine.value,
    })
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
  } catch (e) {
    aiMessage.value = e.message
    ElMessage.error(e.message)
  } finally { aiBusy.value = '' }
}

async function save(status = 'drafting') {
  syncDraft()
  if (!currentTenantId.value) return ElMessage.warning('请先选择客户')
  if (!form.title.trim()) return ElMessage.warning('请填写文章标题')
  saving.value = true
  try {
    const payload = {
      tenant_id: currentTenantId.value,
      title: form.title,
      keyword_id: form.keyword_id,
      content_type: mode.value === 'rewrite' ? 'rewrite' : mode.value === 'qa' ? 'qa' : selectedTemplate.value.type,
      outline: form.outline || selectedTemplate.value.outline,
      draft: form.draft || null,
      humanized_content: mode.value === 'rewrite' ? form.draft || null : null,
      source_text: mode.value === 'rewrite' ? sourceText.value || null : null,
      rewrite_progress: mode.value === 'rewrite' ? (form.draft ? 100 : 0) : null,
      originality_score: null,
      target_platforms: [],
      version_count: assetVersion.value,
      status,
      page_url: null,
      author: form.author || null,
      published_at: null,
    }
    if(assetId.value){
      const {tenant_id,...values}=payload
      await updateSeoContentAsset({contentId:assetId.value,tenantId:currentTenantId.value,payload:values})
    }else{
      const created=await createSeoContentAsset(payload)
      assetId.value=created.id
    }
    saveState.value = status === 'review' ? '已提交审核' : '刚刚已保存'
    ElMessage.success(status === 'review' ? '文章已提交审核' : '文章草稿已保存')
    if (status === 'review') router.push(backPath.value)
  } catch (e) { ElMessage.error(e.message) } finally { saving.value = false }
}

function loadPendingRewrite() {
  sourceText.value = sessionStorage.getItem('seo_pending_rewrite_source') || ''
  if (mode.value !== 'rewrite') return
  try {
    const options = JSON.parse(sessionStorage.getItem('seo_pending_rewrite_options') || '{}')
    prompt.value = [
      options.sourceOrigin ? `原文来源：${options.sourceOrigin}` : '',
      options.rewriteStrength ? `改写强度：${options.rewriteStrength}` : '',
      options.targetKeywords ? `重点自然植入这些关键词：${options.targetKeywords}` : '',
    ].filter(Boolean).join('；')
  } catch {
    prompt.value = ''
  }
}

onMounted(() => { form.outline = selectedTemplate.value.outline; loadPendingRewrite(); load() })
</script>

<template>
  <div class="editor-page">
    <header class="editor-topbar">
      <button class="editor-back" type="button" @click="router.push(backPath)">← 返回{{ mode==='rewrite'?'文章改写':mode==='qa'?'问答运营':'原创文章' }}</button>
      <div><h1>{{ pageTitle }}</h1><p>{{ mode==='rewrite'?'基于导入原文 · 深度改写':mode==='qa'?'搜索问答 · 新建回答':`${selectedTemplate.name} · 新建内容` }}</p></div>
      <div class="editor-top-actions"><span>{{ saveState }}</span><button type="button" @click="save('drafting')">保存草稿</button><button class="primary" type="button" :disabled="saving" @click="save('review')">提交审核</button><b>{{ String(session.user?.name || session.user?.username || 'DZ').slice(0, 2).toUpperCase() }}</b></div>
    </header>

    <main class="editor-workspace">
      <aside class="editor-side">
        <section class="side-section"><h3>内容 Brief</h3><label>搜索引擎</label><div class="engine-picks"><button v-for="item in ['百度', 'Google', 'Bing']" :key="item" :class="{ selected: engine === item }" type="button" @click="engine = item">{{ item }}</button></div><label>目标关键词</label><select v-model="form.keyword_id"><option :value="null">请选择关键词</option><option v-for="item in keywords" :key="item.id" :value="item.id">{{ item.keyword }}</option></select><label>内容模式</label><input :value="mode==='rewrite'?'深度改写':mode==='qa'?'专题问答':selectedTemplate.name" readonly><label>负责人</label><input v-model="form.author" placeholder="负责人"></section>
        <section v-if="mode==='rewrite'" class="side-section"><h3>原文事实基础</h3><div class="source-box">{{sourceText||'尚未导入原文'}}</div></section>
        <section class="side-section"><h3>文章结构</h3><textarea v-model="form.outline" rows="10" /><button class="side-action" type="button" @click="insertOutline">应用大纲到正文</button></section>
        <section class="side-section brief-score"><div><b>{{ keywords.length }}</b><span>可选关键词</span></div><div><b>{{ wordCount }}</b><span>当前字数</span></div></section>
      </aside>

      <section class="editor-center">
        <div class="document-frame">
          <div class="editor-toolbar"><button type="button" title="标题 2" @click="command('formatBlock', 'h2')">H2</button><button type="button" title="标题 3" @click="command('formatBlock', 'h3')">H3</button><i /><button type="button" title="加粗" @click="command('bold')">B</button><button type="button" title="斜体" @click="command('italic')">I</button><button type="button" title="无序列表" @click="command('insertUnorderedList')">•</button><button type="button" title="有序列表" @click="command('insertOrderedList')">1.</button></div>
          <div class="document-scroll"><input v-model="form.title" class="document-title" :placeholder="mode==='qa'?'输入问题标题':'输入文章标题'"><div ref="editor" class="article-editor" contenteditable="true" :data-placeholder="mode==='qa'?'从这里开始撰写回答…':'从这里开始撰写正文…'" @input="syncDraft" /></div>
          <footer class="document-status"><span>{{ wordCount.toLocaleString() }} 字</span><span>{{ engine }}</span><span>{{ keywordName }}</span><span>{{ saveState }}</span></footer>
        </div>
      </section>

      <aside class="ai-side">
        <header><h3>AI 内容助手</h3><p>结合关键词、模板与品牌资料辅助创作</p></header>
        <div class="ai-body"><textarea v-model="prompt" placeholder="输入你的内容要求，例如：保留事实并深度重构表达…" /><button class="ai-primary" type="button" :disabled="!!aiBusy" @click="assist(primaryAiAction)">{{ primaryAiLabel }}</button><div class="quick-actions"><button type="button" :disabled="!!aiBusy" @click="assist('outline')">{{aiBusy==='outline'?'生成中…':'生成大纲'}}</button><button type="button" :disabled="!!aiBusy" @click="assist('title')">{{aiBusy==='title'?'优化中…':'优化标题'}}</button><button type="button" :disabled="!!aiBusy" @click="assist('keywords')">{{aiBusy==='keywords'?'检查中…':'检查关键词'}}</button><button type="button" :disabled="!!aiBusy" @click="assist('rewrite')">{{aiBusy==='rewrite'?'改写中…':'重新改写'}}</button></div><div v-if="aiMessage" class="ai-message">{{ aiMessage }}</div><ul><li><span>AI 服务</span><b class="ok">DeepSeek</b></li><li><span>标题完整</span><b :class="{ ok: form.title }">{{ form.title ? '通过' : '待完善' }}</b></li><li><span>目标关键词</span><b :class="{ ok: form.keyword_id }">{{ form.keyword_id ? '已绑定' : '待选择' }}</b></li><li><span>正文内容</span><b :class="{ ok: wordCount > 300 }">{{ wordCount > 300 ? '已形成' : '待完善' }}</b></li></ul></div>
      </aside>
    </main>
  </div>
</template>

<style scoped>
.editor-page{min-height:100vh;background:#eef2f7;color:#1e2330;font-family:-apple-system,"PingFang SC","Microsoft YaHei","Segoe UI",Roboto,sans-serif}.editor-topbar{position:relative;z-index:5;min-height:76px;padding:0 24px 0 28px;display:flex;align-items:center;gap:18px;border-bottom:1px solid #dde3ec;background:linear-gradient(180deg,#fff 0%,#fbfcff 100%)}.editor-back{min-height:34px;padding:0 10px;border:1px solid transparent;border-radius:7px;background:transparent;color:#596272;font-size:12px;font-weight:650;cursor:pointer}.editor-back:hover{border-color:#d9e4fb;background:#f3f7ff;color:#1d4ed8}.editor-topbar h1{margin:0;font-size:16px}.editor-topbar p{margin:2px 0 0;color:#6b7280;font-size:12px}.editor-top-actions{margin-left:auto;display:flex;align-items:center;gap:10px}.editor-top-actions span{min-width:82px;color:#6f7785;font-size:11px;text-align:right}.editor-top-actions button,.side-action,.ai-primary{padding:8px 14px;border:1px solid #e8eaf0;border-radius:9px;background:#fff;color:#1e2330;font-size:12px;font-weight:600;cursor:pointer}.editor-top-actions button.primary,.side-action,.ai-primary{border-color:#2563eb;background:#2563eb;color:#fff}.editor-top-actions b{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:#2563eb;color:#fff;font-size:12px}.editor-workspace{height:calc(100vh - 76px);min-height:650px;padding:14px;display:grid;grid-template-columns:252px minmax(520px,1fr) 306px;gap:14px;overflow:hidden;background:#eef2f7}.editor-side,.ai-side{overflow-y:auto;border:1px solid #dce2eb;border-radius:8px;background:#fff;box-shadow:0 10px 24px rgba(31,41,55,.06)}.side-section{padding:16px;border-bottom:1px solid #e8eaf0}.side-section h3{margin:0 0 12px;color:#303746;font-size:12px}.side-section label{display:block;margin:11px 0 5px;color:#777f8d;font-size:10.5px;font-weight:650}.side-section :is(input,select,textarea),.ai-body textarea{width:100%;padding:8px 9px;border:1px solid #dfe3e9;border-radius:6px;outline:none;background:#fff;color:#303746;font:inherit;font-size:11.5px}.side-section textarea{resize:vertical;line-height:1.6}.source-box{max-height:150px;overflow:auto;padding:9px;border:1px solid #dfe3e9;border-radius:6px;background:#f7f8fa;color:#66707e;font-size:10.5px;line-height:1.6}.engine-picks{display:flex;flex-wrap:wrap;gap:6px}.engine-picks button{padding:5px 7px;border:1px solid #dfe3e9;border-radius:5px;background:#f8f9fb;color:#626b79;font-size:10.5px;cursor:pointer}.engine-picks button.selected{border-color:#9bb9f6;background:#eff4ff;color:#1d4ed8}.side-action{width:100%;margin-top:9px}.brief-score{display:grid;grid-template-columns:1fr 1fr;gap:7px}.brief-score div{padding:8px;border-left:2px solid #2563eb;background:#f5f7fb}.brief-score div:last-child{border-color:#16a34a}.brief-score b,.brief-score span{display:block}.brief-score b{font-size:16px}.brief-score span{color:#7d8592;font-size:9.5px}.editor-center{min-width:0;display:flex;flex-direction:column;overflow:hidden}.document-frame{width:min(820px,100%);min-height:0;margin:0 auto;display:flex;flex:1;flex-direction:column;overflow:hidden;border:1px solid #d7dce4;border-radius:8px;background:#fff;box-shadow:0 14px 32px rgba(34,43,60,.09)}.editor-toolbar{min-height:44px;padding:6px 10px;display:flex;align-items:center;gap:3px;border-bottom:1px solid #e4e7ec;background:#fbfcfd}.editor-toolbar button{width:30px;height:30px;padding:0;border:1px solid transparent;border-radius:5px;background:transparent;color:#505866;font-size:12px;font-weight:750;cursor:pointer}.editor-toolbar button:hover{border-color:#d4dff5;background:#eff4ff;color:#1d4ed8}.editor-toolbar i{width:1px;height:20px;margin:0 4px;background:#e1e4e9}.document-scroll{flex:1;overflow-y:auto;padding:38px clamp(32px,6vw,70px) 60px}.document-title{width:100%;margin-bottom:22px;padding:0 0 14px;border:0;border-bottom:1px solid #edf0f3;outline:none;background:transparent;color:#1d2432;font-size:25px;font-weight:750;line-height:1.35}.article-editor{min-height:420px;outline:none;color:#313846;font-size:14px;line-height:1.92}.article-editor:empty::before{color:#a0a7b2;content:attr(data-placeholder)}.article-editor :deep(h2){margin:28px 0 10px;color:#1f2735;font-size:19px}.article-editor :deep(h3){margin:22px 0 8px;font-size:16px}.article-editor :deep(p){margin:0 0 12px}.document-status{min-height:34px;padding:6px 12px;display:flex;align-items:center;gap:16px;border-top:1px solid #e8eaf0;background:#fbfcfd;color:#7c8491;font-size:10.5px}.document-status span:last-child{margin-left:auto}.ai-side>header{padding:17px 16px 14px;border-bottom:1px solid #e8eaf0;background:#202838}.ai-side>header h3{margin:0 0 4px;color:#fff;font-size:13px}.ai-side>header p{margin:0;color:#aeb7c6;font-size:10.5px}.ai-body{padding:14px}.ai-body textarea{min-height:78px;resize:vertical;line-height:1.55}.ai-primary{width:100%;margin-top:8px}.quick-actions{margin:13px 0;display:grid;grid-template-columns:1fr 1fr;gap:7px}.quick-actions button{min-height:48px;padding:8px;border:1px solid #e0e4ea;border-radius:6px;background:#f8f9fb;color:#4e5868;font-size:10.5px;text-align:left;cursor:pointer}.quick-actions button:hover{border-color:#adc3ef;background:#f0f5ff;color:#1d4ed8}.ai-message{margin-top:10px;padding:10px;border-left:2px solid #16a34a;background:#f0faf4;color:#5f6877;font-size:10.5px;line-height:1.55}.ai-body ul{margin:14px 0 0;padding:0;list-style:none}.ai-body li{padding:8px 0;display:flex;align-items:center;border-bottom:1px solid #eceef2;color:#626b79;font-size:10.5px}.ai-body li b{margin-left:auto;color:#d97706}.ai-body li b.ok{color:#16a34a}@media(max-width:1280px){.editor-workspace{grid-template-columns:232px minmax(460px,1fr) 280px}}@media(max-width:1020px){.editor-workspace{height:auto;grid-template-columns:1fr;overflow:visible}.editor-center{min-height:760px}}@media(max-width:700px){.editor-topbar{padding:12px 14px;flex-wrap:wrap}.editor-top-actions{width:100%;margin-left:0}.editor-top-actions span{display:none}.editor-workspace{padding:10px}.document-scroll{padding:28px 24px}}
</style>
