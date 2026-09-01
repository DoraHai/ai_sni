<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createGeoArticleImportTask,
  listGeoPrompts,
  previewGeoArticleImportFile,
  previewGeoArticleImportUrl,
} from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const { tenantId } = useGeoTenant()

const method = ref('paste')
const stage = ref('import')
const title = ref('')
const bodyMarkdown = ref('')
const sourceUrl = ref('')
const selectedFile = ref(null)
const previewing = ref(false)
const creating = ref(false)
const error = ref('')
const preview = ref(null)
const prompts = ref([])
const promptId = ref(null)
const targetChannels = ref(['website', 'wechat', 'zhihu'])

const wordCount = computed(() => String(bodyMarkdown.value || '').replace(/\s/g, '').length)
const suggestedPromptIds = computed(() => new Set(
  (preview.value?.suggested_prompts || preview.value?.prompt_suggestions || [])
    .map((item) => Number(typeof item === 'object' ? item.id ?? item.prompt_id : item))
    .filter((id) => Number.isFinite(id) && id > 0),
))
const previewSummary = computed(() => {
  if (!preview.value) return ''
  const chars = String(preview.value.body_markdown || '').replace(/\s/g, '').length
  return `${chars.toLocaleString('zh-CN')} 字 · ${sourceLabel(preview.value.source_type)}`
})

function sourceLabel(value) {
  return { paste: '粘贴文章', manual: '粘贴文章', file: '上传文档', url: 'URL 导入' }[value] || '导入文章'
}

function normalizePreview(data, fallback) {
  const value = data?.preview || data || {}
  return {
    title: String(value.title || fallback.title || '').trim(),
    body_markdown: String(value.body_markdown || value.markdown || value.body || fallback.body_markdown || '').trim(),
    source_type: value.source_type || fallback.source_type,
    source_url: value.source_url || value.url || fallback.source_url || null,
    suggested_prompts: value.suggested_prompts || value.prompt_suggestions || [],
  }
}

async function loadPrompts() {
  if (!tenantId.value) return
  try {
    const data = await listGeoPrompts(tenantId.value, { status: 'active', limit: 200 })
    prompts.value = data.items || []
  } catch (e) {
    ElMessage.error(e.message || '加载目标问题失败')
  }
}

function onFileChange(uploadFile) {
  selectedFile.value = uploadFile.raw || uploadFile
}

function resetPreview() {
  preview.value = null
  stage.value = 'import'
  error.value = ''
}

async function previewArticle() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  previewing.value = true
  error.value = ''
  try {
    let data
    let fallback
    if (method.value === 'paste') {
      const body = String(bodyMarkdown.value || '').trim()
      if (!body) throw new Error('请粘贴文章正文')
      fallback = { title: title.value, body_markdown: body, source_type: 'paste', source_url: null }
      preview.value = normalizePreview(null, fallback)
    } else if (method.value === 'file') {
      if (!selectedFile.value) throw new Error('请选择要导入的文档')
      data = await previewGeoArticleImportFile(tenantId.value, selectedFile.value)
      fallback = { title: title.value, body_markdown: '', source_type: 'file', source_url: null }
      preview.value = normalizePreview(data, fallback)
    } else {
      const url = String(sourceUrl.value || '').trim()
      if (!url) throw new Error('请输入文章 URL')
      data = await previewGeoArticleImportUrl(tenantId.value, url)
      fallback = { title: title.value, body_markdown: '', source_type: 'url', source_url: url }
      preview.value = normalizePreview(data, fallback)
    }
    if (!preview.value.body_markdown) throw new Error('未识别到可导入的文章正文')
    title.value = preview.value.title
    bodyMarkdown.value = preview.value.body_markdown
    const suggested = [...suggestedPromptIds.value]
    if (!promptId.value && suggested.length && prompts.value.some((item) => item.id === suggested[0])) {
      promptId.value = suggested[0]
    } else if (!promptId.value && prompts.value.length) {
      promptId.value = prompts.value[0].id
    }
    stage.value = 'question'
  } catch (e) {
    error.value = e.message || '识别文章失败'
  } finally {
    previewing.value = false
  }
}

async function createTask() {
  if (!preview.value || !tenantId.value) return
  if (!promptId.value) {
    ElMessage.warning('请选择要关联的目标问题')
    return
  }
  creating.value = true
  error.value = ''
  try {
    const data = await createGeoArticleImportTask({
      tenant_id: tenantId.value,
      prompt_id: Number(promptId.value),
      title: preview.value.title,
      body_markdown: preview.value.body_markdown,
      source_type: preview.value.source_type,
      source_url: preview.value.source_url,
      target_channels: targetChannels.value,
    })
    const task = data?.task || data
    if (!task?.id) throw new Error('后端未返回已创建任务')
    ElMessage.success(`已导入任务 #${task.id}`)
    router.push(`/geo/tasks/${task.id}`)
  } catch (e) {
    error.value = e.message || '创建导入任务失败'
  } finally {
    creating.value = false
  }
}

onMounted(loadPrompts)
</script>

<template>
  <GeoWorkbenchPage title="导入已有文章" sub="导入现有文章或母稿，系统将进行 GEO 检测并给出优化建议。" :show-period="false" class="geo-article-import">
    <template #actions>
      <router-link class="gd-btn" to="/geo/tasks">返回文章工作台</router-link>
    </template>

    <div class="import-flow" aria-label="已有文章优化流程">
      <span :class="{ active: stage === 'import' }">1&nbsp; 导入文章</span><i />
      <span :class="{ active: stage === 'question' }">2&nbsp; 关联目标问题</span><i />
      <span>3&nbsp; 首次 GEO 检测</span>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon class="mb" />

    <section v-if="stage === 'import'" class="import-card">
      <header>
        <span class="eyebrow">已有内容 GEO 改造</span>
        <h2>选择导入方式</h2>
        <p>粘贴、文档和 URL 都会在创建任务前保留为可确认的预览。</p>
      </header>

      <div class="method-tabs" role="tablist" aria-label="文章导入方式">
        <button v-for="item in [
          { id: 'paste', label: '粘贴文章', hint: '支持 Markdown / 纯文本' },
          { id: 'file', label: '上传文档', hint: 'Word / PDF / TXT' },
          { id: 'url', label: 'URL 导入', hint: '官网文章链接' },
        ]" :key="item.id" type="button" :class="{ active: method === item.id }" @click="method = item.id; resetPreview()">
          <b>{{ item.label }}</b><small>{{ item.hint }}</small>
        </button>
      </div>

      <div v-if="method === 'paste'" class="import-panel">
        <label>文章标题 <small>选填，未填则保留为后续可编辑标题</small></label>
        <el-input v-model="title" placeholder="输入文章标题" class="mb" />
        <label>文章正文</label>
        <el-input v-model="bodyMarkdown" type="textarea" :rows="14" placeholder="粘贴需要进行 GEO 优化的文章内容……" />
        <p class="field-meta">支持 Markdown / 普通文本 <span>{{ wordCount.toLocaleString('zh-CN') }} 字</span></p>
      </div>
      <div v-else-if="method === 'file'" class="import-panel">
        <label>上传 Word / PDF / TXT</label>
        <el-upload drag :auto-upload="false" :show-file-list="true" :limit="1" accept=".doc,.docx,.pdf,.txt,.md" @change="onFileChange">
          <div class="upload-copy"><b>选择文档或拖到这里</b><small>系统会解析标题和正文供你确认。</small></div>
        </el-upload>
      </div>
      <div v-else class="import-panel">
        <label>文章 URL</label>
        <el-input v-model="sourceUrl" placeholder="https://example.com/article" />
        <p class="field-meta">将识别标题、正文和原始来源；仅导入你有权使用的公开内容。</p>
      </div>

      <footer>
        <router-link class="gd-btn" to="/geo/tasks">取消</router-link>
        <button class="gd-btn primary" type="button" :disabled="previewing" @click="previewArticle">
          {{ previewing ? '识别中…' : '识别文章并继续 →' }}
        </button>
      </footer>
    </section>

    <section v-else class="import-card">
      <header class="question-head">
        <div>
          <span class="eyebrow">AI 已完成内容识别</span>
          <h2>关联目标问题</h2>
          <p>选择这篇文章主要希望覆盖的 GEO 用户问题。</p>
        </div>
        <div class="preview-meta"><b>{{ preview?.title || '未命名导入文章' }}</b><small>{{ previewSummary }}</small></div>
      </header>

      <div class="question-panel">
        <label>目标问题</label>
        <el-select v-model="promptId" filterable placeholder="选择优化意图词 / 用户问题" style="width: 100%">
          <el-option v-for="prompt in prompts" :key="prompt.id" :value="prompt.id" :label="`#${prompt.id} ${prompt.question}`">
            <span>{{ prompt.question }}</span>
            <small v-if="suggestedPromptIds.has(prompt.id)" class="recommended">推荐</small>
          </el-option>
        </el-select>
        <p v-if="!prompts.length" class="field-meta">暂无可关联的问题，请先在提问监控中创建优化意图词。</p>

        <label class="channel-label">目标渠道</label>
        <el-checkbox-group v-model="targetChannels">
          <el-checkbox label="website">官网</el-checkbox>
          <el-checkbox label="wechat">微信</el-checkbox>
          <el-checkbox label="zhihu">知乎</el-checkbox>
        </el-checkbox-group>
      </div>

      <div class="detection-note"><b>进入编辑器后将进行首次 GEO 检测</b><span>检查 AI 可引用性、问题覆盖度、事实支撑和内容结构。</span></div>
      <footer>
        <button class="gd-btn" type="button" @click="stage = 'import'">上一步</button>
        <button class="gd-btn primary" type="button" :disabled="creating || !prompts.length" @click="createTask">
          {{ creating ? '创建中…' : '进入编辑器并检测 →' }}
        </button>
      </footer>
    </section>
  </GeoWorkbenchPage>
</template>

<style scoped>
.geo-article-import { max-width: 1040px; margin: 0 auto; }
.import-flow { display: flex; align-items: center; gap: 10px; margin: 4px 0 18px; color: #94a3b8; font-size: 13px; font-weight: 700; }
.import-flow span { white-space: nowrap; }
.import-flow span.active { color: #7c3aed; }
.import-flow i { width: 42px; height: 1px; background: #dbe1ea; }
.import-card { overflow: hidden; border: 1px solid #e5e7eb; border-radius: 12px; background: #fff; box-shadow: 0 12px 32px rgba(15, 23, 42, .05); }
.import-card > header { padding: 24px 26px 8px; }
.import-card h2 { margin: 4px 0 7px; color: #172033; font-size: 20px; }
.import-card p { margin: 0; color: #64748b; font-size: 13px; line-height: 1.6; }
.eyebrow { color: #7c3aed; font-size: 12px; font-weight: 800; letter-spacing: .04em; }
.method-tabs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; padding: 18px 26px; }
.method-tabs button { min-height: 76px; border: 1px solid #dbe1ea; border-radius: 9px; background: #fff; color: #334155; cursor: pointer; text-align: left; padding: 14px; }
.method-tabs button.active { border-color: #7c3aed; background: #faf8ff; color: #6d28d9; box-shadow: 0 0 0 2px rgba(124, 58, 237, .08); }
.method-tabs b, .method-tabs small { display: block; }
.method-tabs small { margin-top: 6px; color: #94a3b8; }
.import-panel, .question-panel { padding: 4px 26px 22px; }
label { display: block; margin: 10px 0 7px; color: #334155; font-size: 13px; font-weight: 700; }
label small, .field-meta { font-weight: 400; }
.field-meta { display: flex; justify-content: space-between; gap: 12px; margin-top: 8px !important; }
.upload-copy { display: grid; gap: 6px; color: #475569; }
.upload-copy small { color: #94a3b8; }
.import-card footer { display: flex; justify-content: flex-end; gap: 10px; padding: 16px 26px; border-top: 1px solid #eef2f7; background: #fafbfc; }
.question-head { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; }
.preview-meta { max-width: 300px; display: grid; gap: 5px; padding: 9px 12px; border-radius: 8px; background: #f8fafc; color: #334155; font-size: 13px; }
.preview-meta small { color: #64748b; }
.recommended { float: right; color: #7c3aed; font-weight: 700; }
.channel-label { margin-top: 22px; }
.detection-note { display: grid; gap: 4px; margin: 0 26px 22px; padding: 13px 15px; border: 1px solid #ddd6fe; border-radius: 8px; background: #faf8ff; color: #5b21b6; font-size: 13px; }
.detection-note span { color: #6b7280; font-size: 12px; }
.mb { margin-bottom: 12px; }
@media (max-width: 720px) { .method-tabs { grid-template-columns: 1fr; } .question-head { display: block; } .preview-meta { margin-top: 14px; } .import-flow i { width: 18px; } }
</style>
