<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createSeoContentAsset, fetchSeoContentAssets, fetchSeoKeywords, updateSeoContentAsset } from '../../api/seo'
import { fetchSeoSites } from '../../api/moduleAssets'
import { currentTenantId, session } from '../../store/session'
import './seo-suite.css'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const activeStatus = ref('all')
const query = ref('')
const dialog = ref(false)
const templatesVisible = ref(false)
const selectedTemplate = ref('guide')
const sourceVisible = ref(false)
const sourceText = ref('')
const editing = ref(null)
const allItems = ref([])
const keywords = ref([])
const sites = ref([])
const siteId = ref(null)
const mode = computed(() => route.meta.contentMode || 'article')

const definitions = {
  article: {
    title: '原创文章',
    subtitle: '从关键词机会出发，生成全网唯一、可长期沉淀的搜索内容资产',
    eyebrow: 'ORIGINAL CONTENT',
    headline: '原创文章不是“从零写一篇”，而是把关键词机会变成可收录资产',
    copy: '系统组合品牌资料、目标用户、关键词意图与竞品缺口，AI 先生成初稿，再由运营在线编辑，最后按不同平台规则适配分发。',
    tags: ['全网唯一', '核心词优先', '官网首发', '支持多平台改版'],
    button: '新建文章',
    defaultType: 'article',
    types: ['article', 'guide', 'landing', 'comparison'],
    steps: [['选机会', '关键词与内容缺口'], ['AI 生成', '大纲、正文、FAQ'], ['在线编辑', '校对、内链、版本'], ['适配分发', '官网首发再同步']],
  },
  rewrite: {
    title: '文章改写',
    subtitle: '让已有内容保持事实不变，同时获得更自然、更适合搜索的表达',
    eyebrow: 'CONTENT REWRITE',
    headline: '文章改写不是“换一批词”，而是把旧内容重新变成增长资产',
    copy: '保留原文事实与核心观点，识别陈旧信息和表达问题，生成改写稿后进入人工审核，并保留每一次修改记录。',
    tags: ['事实不变', '表达自然', '结构优化', '人工终审'],
    button: '新建改写',
    defaultType: 'rewrite',
    types: ['rewrite'],
    steps: [['导入原文', '网址或已有稿件'], ['检查问题', '事实、结构、表达'], ['生成改写', '自然表达与新结构'], ['人工定稿', '审核后发布']],
  },
  qa: {
    title: '问答运营',
    subtitle: '围绕用户真实决策问题，持续建设可被搜索和引用的问答资产',
    eyebrow: 'SEARCH Q&A',
    headline: '问答运营不是“堆问题”，而是覆盖用户决策前的每一个搜索意图',
    copy: '从关键词和搜索结果中识别真实问题，组合品牌事实生成回答，经人工审核后沉淀为 FAQ、问答页或平台回答。',
    tags: ['真实问题', '品牌事实', '结构化回答', '多场景复用'],
    button: '新建问答',
    defaultType: 'qa',
    types: ['qa', 'faq'],
    steps: [['发现问题', '搜索词与用户提问'], ['组织事实', '品牌资料与证据'], ['生成回答', '短答、长答、FAQ'], ['审核发布', '站内与问答平台']],
  },
}

const config = computed(() => definitions[mode.value] || definitions.article)
const form = reactive({ title: '', keyword_ids: [], content_type: 'article', outline: '', draft: '', humanized_content: '', status: 'planned', page_url: '', author: '' })
const canEdit = computed(() => !session.isLoggedIn || session.canEdit('seo.content'))
const initials = computed(() => {
  const name = session.user?.name || session.user?.username || 'DZ'
  return String(name).slice(0, 2).toUpperCase()
})
const baseItems = computed(() => allItems.value.filter((item) => config.value.types.includes(item.content_type)))
const tabs = computed(() => [
  { key: 'all', label: '全部', count: baseItems.value.length },
  { key: 'draft', label: '草稿', count: baseItems.value.filter((item) => ['planned', 'drafting'].includes(item.status)).length },
  { key: 'review', label: '待发布', count: baseItems.value.filter((item) => item.status === 'review').length },
  { key: 'published', label: '已发布', count: baseItems.value.filter((item) => item.status === 'published').length },
])
const items = computed(() => {
  const needle = query.value.trim().toLowerCase()
  return baseItems.value.filter((item) => {
    const statusMatch = activeStatus.value === 'all'
      || (activeStatus.value === 'draft' && ['planned', 'drafting'].includes(item.status))
      || item.status === activeStatus.value
    const keywordText = keywordsFor(item).join(' ')
    return statusMatch && (!needle || item.title.toLowerCase().includes(needle) || keywordText.toLowerCase().includes(needle))
  })
})

const templates = [
  { id: 'guide', name: '完整选型指南', description: '定义、场景、选型维度、FAQ · 2,500 字' },
  { id: 'compare', name: '竞品对比评测', description: '对比维度、数据表、适用建议 · 2,200 字' },
  { id: 'solution', name: '行业解决方案', description: '痛点、方案、流程、案例 · 1,800 字' },
  { id: 'howto', name: '操作教程', description: '步骤、截图位、避坑清单 · 1,500 字' },
  { id: 'opinion', name: '行业观点', description: '趋势、数据、观点与结论 · 2,000 字' },
  { id: 'faq', name: '专题问答', description: '覆盖长尾搜索意图 · 1,200 字' },
]

const statusName = (value) => ({ planned: '草稿', drafting: '草稿', review: '待发布', published: '已发布', archived: '已归档' })[value] || value
const typeName = (value) => ({ article: '原创文章', guide: '深度指南', landing: '落地页', comparison: '对比内容', rewrite: '文章改写', qa: '问答内容', faq: 'FAQ' })[value] || value
const keywordIdsFor = (row) => row.keyword_ids?.length ? row.keyword_ids : row.keyword_id ? [row.keyword_id] : []
const keywordsFor = (row) => keywordIdsFor(row).map((id) => keywords.value.find((item) => item.id === id)?.keyword).filter(Boolean)
const contentText = (row) => row.humanized_content || row.draft || ''
const wordCount = (row) => Array.from(contentText(row).replace(/\s+/g, '')).length
const qualityScore = (row) => {
  if (!row.draft && !row.humanized_content) return null
  let score = 35
  if (keywordIdsFor(row).length) score += 10
  if (row.outline) score += 10
  if (row.draft?.length >= 500) score += 15
  if (row.draft?.length >= 1500) score += 10
  if (row.humanized_content) score += 10
  if (row.page_url) score += 10
  return Math.min(score, 100)
}
const platformFor = (row) => {
  if (!row.page_url) return ''
  try {
    const host = new URL(row.page_url).hostname.replace(/^www\./, '')
    return host || '官网'
  } catch { return '官网' }
}
const formatTime = (value) => {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date).replace('/', '-')
}

async function load() {
  if (!currentTenantId.value) { error.value = '请先选择客户'; return }
  if (!siteId.value) { error.value = '请先选择或创建 SEO 网站'; allItems.value = []; keywords.value = []; return }
  loading.value = true
  try {
    const [contentResult, keywordResult] = await Promise.all([
      fetchSeoContentAssets({ tenantId: currentTenantId.value, siteId: siteId.value }),
      fetchSeoKeywords({ tenantId: currentTenantId.value, siteId: siteId.value, pageSize: 200 }),
    ])
    allItems.value = contentResult.items
    keywords.value = keywordResult.items
    error.value = ''
  } catch (e) { error.value = e.message } finally { loading.value = false }
}

async function loadSites() {
  if (!currentTenantId.value) {
    sites.value = []
    siteId.value = null
    return load()
  }
  try {
    sites.value = (await fetchSeoSites(currentTenantId.value)).sites || []
    const selected = sites.value.some((item) => item.id === siteId.value)
      ? siteId.value
      : (sites.value.find((item) => item.status === 'active')?.id || sites.value[0]?.id || null)
    if (selected !== siteId.value) siteId.value = selected
    else await load()
  } catch (e) {
    error.value = e.message
  }
}

function open(row = null, preset = null) {
  editing.value = row
  Object.assign(form, {
    title: row?.title || '',
    keyword_ids: [...(row?.keyword_ids?.length ? row.keyword_ids : row?.keyword_id ? [row.keyword_id] : [])],
    content_type: row?.content_type || preset?.type || config.value.defaultType,
    outline: row?.outline || preset?.outline || '',
    draft: row?.draft || '',
    humanized_content: row?.humanized_content || '',
    status: row?.status || 'planned',
    page_url: row?.page_url || '',
    author: row?.author || session.user?.name || session.user?.username || '',
  })
  templatesVisible.value = false
  dialog.value = true
}

function openTemplates() {
  selectedTemplate.value = 'guide'
  templatesVisible.value = true
}

function useTemplate() {
  templatesVisible.value = false
  router.push({ path: '/seo/content/editor', query: { type: 'original', new: '1', template: selectedTemplate.value, site_id: siteId.value } })
}

function createByMode() {
  if (mode.value === 'article') return openTemplates()
  if (mode.value === 'rewrite') { sourceText.value = ''; sourceVisible.value = true; return }
  router.push({ path: '/seo/content/answer-editor', query: { type: 'qa', new: '1', site_id: siteId.value } })
}

function startRewrite() {
  if (!sourceText.value.trim()) return ElMessage.warning('请粘贴待改写原文')
  sessionStorage.setItem('seo_pending_rewrite_source', sourceText.value.trim())
  sourceVisible.value = false
  router.push({ path: '/seo/content/editor', query: { type: 'rewrite', new: '1', source: 'imported', site_id: siteId.value } })
}

async function save() {
  if (!form.title.trim()) return ElMessage.warning('请填写内容标题')
  if (mode.value === 'article' && !form.keyword_ids.length) return ElMessage.warning('原创文章请至少选择 1 个目标关键词')
  saving.value = true
  try {
    const payload = { ...form, keyword_id: form.keyword_ids[0] || null, outline: form.outline || null, draft: form.draft || null, humanized_content: form.humanized_content || null, page_url: form.page_url || null, author: form.author || null, published_at: form.status === 'published' ? new Date().toISOString() : null }
    if (editing.value) await updateSeoContentAsset({ contentId: editing.value.id, tenantId: currentTenantId.value, payload })
    else await createSeoContentAsset({ tenant_id: currentTenantId.value, site_id: siteId.value, ...payload })
    dialog.value = false
    ElMessage.success('内容资产已保存')
    await load()
  } catch (e) { ElMessage.error(e.message) } finally { saving.value = false }
}

async function copyContent(row) {
  const text = contentText(row)
  if (!text) return ElMessage.warning('这条内容还没有正文')
  await navigator.clipboard.writeText(text)
  ElMessage.success('正文已复制')
}

watch([siteId, mode], () => { activeStatus.value = 'all'; query.value = ''; load() })
watch(currentTenantId, loadSites)
onMounted(loadSites)
</script>

<template>
  <div class="content-prototype" v-loading="loading">
    <header class="content-page-head">
      <div>
        <h1>{{ config.title }}</h1>
        <p>{{ config.subtitle }}</p>
      </div>
      <div class="page-actions">
        <el-select v-model="siteId" class="content-site-picker" placeholder="选择 SEO 网站">
          <el-option v-for="site in sites" :key="site.id" :label="site.name || site.canonical_domain" :value="site.id" />
        </el-select>
        <button v-if="mode === 'article' && canEdit" class="ghost-action" type="button" @click="openTemplates">内容模板</button>
        <button v-if="canEdit" class="primary-action" type="button" @click="createByMode">AI 智能生成</button>
        <span class="user-avatar">{{ initials }}</span>
      </div>
    </header>

    <main class="content-body">
      <el-alert v-if="error" class="suite-error" :title="error" type="warning" :closable="false" />

      <section class="content-manifesto">
        <div class="manifesto-copy">
          <span>{{ config.eyebrow }}</span>
          <h2>{{ config.headline }}</h2>
          <p>{{ config.copy }}</p>
          <div class="manifesto-tags"><b v-for="tag in config.tags" :key="tag">{{ tag }}</b></div>
        </div>
        <ol class="content-steps">
          <li v-for="(step, index) in config.steps" :key="step[0]">
            <i>{{ index + 1 }}</i>
            <strong>{{ step[0] }}</strong>
            <small>{{ step[1] }}</small>
          </li>
        </ol>
      </section>

      <section class="content-task-card">
        <div class="task-toolbar">
          <div class="task-tabs">
            <h2>{{ config.title === '问答运营' ? '问答任务' : `${config.title.replace('文章', '')}任务` }}</h2>
            <button v-for="tab in tabs" :key="tab.key" :class="{ active: activeStatus === tab.key }" type="button" @click="activeStatus = tab.key">
              {{ tab.label }} <span>{{ tab.count }}</span>
            </button>
          </div>
          <div class="task-search">
            <input v-model="query" type="search" placeholder="搜索标题或目标关键词" />
            <button v-if="canEdit" class="primary-action" type="button" @click="createByMode">＋ {{ config.button }}</button>
          </div>
        </div>

        <div class="content-table-wrap">
          <table class="content-table">
            <thead><tr><th>内容</th><th>目标关键词</th><th>内容质量</th><th>状态</th><th>分发平台</th><th>更新时间</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="row in items" :key="row.id">
                <td class="article-cell">
                  <strong>{{ row.title }}</strong>
                  <small>{{ typeName(row.content_type) }}<template v-if="wordCount(row)"> · {{ wordCount(row).toLocaleString() }} 字</template><template v-if="row.author"> · 负责人 {{ row.author }}</template></small>
                </td>
                <td><template v-if="keywordsFor(row).length"><span v-for="keyword in keywordsFor(row)" :key="keyword" class="keyword-tag">{{ keyword }}</span></template><span v-else class="muted-text">待绑定</span></td>
                <td>
                  <div v-if="qualityScore(row) !== null" class="quality-score"><i><b :style="{ width: `${qualityScore(row)}%` }" /></i><span>{{ qualityScore(row) }}</span></div>
                  <span v-else class="muted-text">待评分</span>
                </td>
                <td><span class="status-pill" :class="`status-${row.status}`">{{ statusName(row.status) }}</span></td>
                <td><span v-if="platformFor(row)" class="platform-tag">{{ platformFor(row) }}</span><span v-else class="muted-tag">未选择</span></td>
                <td class="time-cell">{{ formatTime(row.updated_at || row.created_at) }}</td>
                <td><div class="row-actions">
                  <button v-if="canEdit && row.status !== 'published'" type="button" @click="open(row)">继续编辑</button>
                  <a v-if="row.status === 'published' && row.page_url" :href="row.page_url" target="_blank" rel="noopener">查看内容</a>
                  <button v-if="contentText(row)" type="button" @click="copyContent(row)">复制</button>
                  <button v-if="row.status === 'published'" type="button" @click="router.push('/seo/distribution')">分发记录</button>
                </div></td>
              </tr>
              <tr v-if="!items.length"><td class="table-empty" colspan="7">{{ query ? '没有匹配的内容任务' : `暂无${config.title}任务` }}</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </main>

    <div v-if="templatesVisible" class="prototype-overlay" role="dialog" aria-modal="true" @click.self="templatesVisible = false">
      <section class="prototype-dialog">
        <header><div><h2>选择原创内容模板</h2><p>模板只规定结构，AI 会结合当前关键词与品牌资料生成独立内容</p></div><button type="button" aria-label="关闭" @click="templatesVisible = false">×</button></header>
        <div class="prototype-dialog-body">
          <div class="template-grid">
            <button v-for="item in templates" :key="item.id" :class="{ selected: selectedTemplate === item.id }" type="button" @click="selectedTemplate = item.id">
              <i /><strong>{{ item.name }}</strong><small>{{ item.description }}</small>
            </button>
          </div>
        </div>
        <footer><button class="ghost-action" type="button" @click="templatesVisible = false">取消</button><button class="primary-action" type="button" @click="useTemplate">使用所选模板</button></footer>
      </section>
    </div>
    <div v-if="sourceVisible" class="prototype-overlay" role="dialog" aria-modal="true" @click.self="sourceVisible=false"><section class="prototype-dialog"><header><div><h2>导入待改写原文</h2><p>可粘贴客户已有文章或参考稿，改写过程会锁定原文事实</p></div><button type="button" @click="sourceVisible=false">×</button></header><div class="prototype-dialog-body"><label class="source-label">原文内容 *</label><textarea v-model="sourceText" class="source-import" placeholder="粘贴待改写文章正文…"/><div class="source-options"><label>原文来源<select><option>客户官网旧文</option><option>客户提供文档</option><option>历史文章库</option></select></label><label>改写强度<select><option>深度改写（推荐）</option><option>中度改写</option><option>轻度润色</option></select></label></div></div><footer><button class="ghost-action" @click="sourceVisible=false">取消</button><button class="primary-action" @click="startRewrite">导入并开始改写</button></footer></section></div>

    <el-dialog v-model="dialog" :title="editing ? `编辑${config.title}` : config.button" width="820px">
      <el-form label-position="top" class="suite-form">
        <el-form-item label="标题 / 问题" class="full"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="目标关键词（1–5个）"><el-select v-model="form.keyword_ids" multiple collapse-tags collapse-tags-tooltip :multiple-limit="5" clearable filterable placeholder="第一个为主关键词"><el-option v-for="item in keywords" :key="item.id" :label="item.keyword" :value="item.id" /></el-select><small class="form-guidance">建议：1 个品牌词 + 1–2 个产品词、应用词或行业词。</small></el-form-item>
        <el-form-item label="内容类型"><el-select v-model="form.content_type"><el-option v-for="item in config.types" :key="item" :label="typeName(item)" :value="item" /></el-select></el-form-item>
        <el-form-item label="负责人"><el-input v-model="form.author" /></el-form-item>
        <el-form-item label="状态"><el-select v-model="form.status"><el-option v-for="item in ['planned', 'drafting', 'review', 'published', 'archived']" :key="item" :label="statusName(item)" :value="item" /></el-select></el-form-item>
        <el-form-item :label="mode === 'qa' ? '回答结构 / 要点' : '内容大纲'" class="full"><el-input v-model="form.outline" type="textarea" :rows="4" /></el-form-item>
        <el-form-item :label="mode === 'rewrite' ? '原文 / 初稿' : '初始草稿'" class="full"><el-input v-model="form.draft" type="textarea" :rows="6" /></el-form-item>
        <el-form-item :label="mode === 'rewrite' ? '人工化改写稿' : '审核定稿'" class="full"><el-input v-model="form.humanized_content" type="textarea" :rows="6" /></el-form-item>
        <el-form-item label="发布页面" class="full"><el-input v-model="form.page_url" placeholder="https://" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.content-site-picker{width:220px}
.form-guidance{display:block;margin-top:6px;color:#8a919e;font-size:10px;line-height:1.5}
.content-prototype{min-height:100vh;background:#f4f6f9;color:#1e2330;font-family:-apple-system,"PingFang SC","Microsoft YaHei","Segoe UI",Roboto,sans-serif}.content-page-head{min-height:68px;padding:0 28px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #e8eaf0;background:#fff}.content-page-head h1{margin:0;font-size:17px;line-height:1.35}.content-page-head p{margin:1px 0 0;color:#6b7280;font-size:12px}.page-actions,.task-search{display:flex;align-items:center;gap:12px}.ghost-action,.primary-action{height:auto;padding:8px 14px;border-radius:9px;font-size:13px;font-weight:600;cursor:pointer}.ghost-action{border:1px solid #e8eaf0;background:#fff;color:#1e2330}.primary-action{border:1px solid #2563eb;background:#2563eb;color:#fff;box-shadow:none}.user-avatar{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:#2563eb;color:#fff;font-size:12px;font-weight:700}.content-body{padding:20px 24px 28px}.content-manifesto{min-height:138px;margin-bottom:16px;display:grid;grid-template-columns:minmax(0,1.5fr) minmax(420px,1fr);overflow:hidden;border-radius:8px;background:#202838;color:#fff;box-shadow:0 12px 30px rgba(28,37,54,.13)}.manifesto-copy{padding:24px 26px;border-right:1px solid rgba(255,255,255,.1)}.manifesto-copy>span{color:#9ec0ff;font-size:11px;font-weight:750;letter-spacing:.08em;text-transform:uppercase}.manifesto-copy h2{margin:8px 0 6px;max-width:720px;font-size:21px;line-height:1.35;letter-spacing:0}.manifesto-copy p{max-width:720px;margin:0;color:#b9c1cf;font-size:13px;line-height:1.5}.manifesto-tags{margin-top:15px;display:flex;flex-wrap:wrap;gap:7px}.manifesto-tags b{padding:4px 8px;border:1px solid rgba(255,255,255,.12);border-radius:5px;background:rgba(255,255,255,.05);color:#d8deea;font-size:11px;font-weight:500}.content-steps{margin:0;padding:20px 20px 20px 12px;display:grid;grid-template-columns:repeat(4,1fr);align-items:center;list-style:none}.content-steps li{position:relative;min-width:0;padding:8px 9px}.content-steps li:not(:last-child)::after{content:"";position:absolute;top:22px;right:-3px;width:12px;height:1px;background:rgba(255,255,255,.25)}.content-steps i{width:24px;height:24px;margin-bottom:8px;border-radius:50%;display:grid;place-items:center;background:#9ec0ff;color:#182237;font-size:11px;font-style:normal;font-weight:800}.content-steps strong,.content-steps small{display:block}.content-steps strong{margin-bottom:5px;font-size:12px}.content-steps small{color:#aab3c2;font-size:10.5px;line-height:1.45}.content-task-card{overflow:hidden;border:1px solid #dfe3ea;border-radius:8px;background:#fff}.task-toolbar{min-height:58px;padding:10px 14px;display:flex;align-items:center;justify-content:space-between;gap:10px;border-bottom:1px solid #e5e7eb}.task-tabs{display:flex;align-items:center;gap:10px}.task-tabs h2{margin:0 10px 0 0;font-size:14px}.task-tabs button{height:auto;padding:6px 10px;border:1px solid #e0e4eb;border-radius:6px;background:#fff;color:#697180;font-size:11px;cursor:pointer}.task-tabs button.active{border-color:#9bb9f6;background:#f0f5ff;color:#1d4ed8;font-weight:700}.task-tabs button span{margin-left:3px}.task-search input{width:230px;height:auto;padding:8px 12px;border:1px solid #e8eaf0;border-radius:9px;outline:none;background:#f6f7fb;color:#1e2330;font-size:13px}.task-search input:focus{border-color:#9bb9f6;background:#fff}.task-search .primary-action{height:auto;white-space:nowrap}.content-table-wrap{overflow-x:auto}.content-table{width:100%;border-collapse:collapse;table-layout:auto;font-size:13px}.content-table th{padding:12px 14px;border-bottom:1px solid #e8eaf0;color:#6b7280;font-size:12px;font-weight:600;text-align:left}.content-table td{padding:12px 14px;border-bottom:1px solid #e8eaf0;color:#1e2330;font-size:13px;vertical-align:middle}.content-table tbody tr:last-child td{border-bottom:0}.content-table tbody tr:hover{background:#f6f7fb}.content-table th:nth-child(1){width:auto}.content-table th:nth-child(2){width:auto}.content-table th:nth-child(3){width:auto}.content-table th:nth-child(4){width:auto}.content-table th:nth-child(5){width:auto}.content-table th:nth-child(6){width:auto}.content-table th:nth-child(7){width:auto}.article-cell{min-width:320px}.article-cell strong,.article-cell small{display:block}.article-cell strong{max-width:520px;margin-bottom:4px;overflow:hidden;color:#222938;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.article-cell small{margin-top:0;color:#8a919e;font-size:11px}.keyword-tag,.platform-tag,.muted-tag{display:inline-block;margin:2px 5px 2px 0;padding:3px 7px;border-radius:5px;background:#f0f2f6;color:#626c7b;font-size:10.5px}.platform-tag{background:#e9f7ef;color:#137f4a}.muted-tag{color:#626c7b}.muted-text{color:#8a919e;font-size:11px}.quality-score{display:inline-flex;align-items:center;gap:6px;color:#5e6675;font-size:11px}.quality-score i{width:48px;height:5px;overflow:hidden;border-radius:4px;background:#e9ecf1}.quality-score b{height:100%;display:block;background:#16a34a}.quality-score span{color:#5e6675}.status-pill{display:inline-flex;padding:3px 9px;border-radius:999px;font-size:12px;font-weight:600}.status-planned,.status-drafting{background:#fdf2e0;color:#d97706}.status-review{background:#eff4ff;color:#2563eb}.status-published{background:#e7f7ee;color:#16a34a}.status-archived{background:#f0f1f5;color:#6b7280}.time-cell{white-space:nowrap}.row-actions{display:flex;align-items:center;gap:6px;white-space:nowrap}.row-actions button,.row-actions a{padding:5px 7px;border:0;background:transparent;color:#2563eb;font-size:11.5px;font-weight:700;text-decoration:none;cursor:pointer}.row-actions button:hover,.row-actions a:hover{background:#eff4ff}.table-empty{height:150px!important;color:#8a919e!important;text-align:center}.prototype-overlay{position:fixed;z-index:12000;inset:0;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(19,27,41,.48);backdrop-filter:blur(2px)}.prototype-dialog{display:flex;width:min(780px,94vw);max-height:88vh;flex-direction:column;overflow:hidden;border-radius:8px;background:#fff;box-shadow:0 26px 70px rgba(17,24,39,.28)}.prototype-dialog>header{display:flex;align-items:flex-start;gap:12px;padding:17px 20px;border-bottom:1px solid #e5e8ed}.prototype-dialog>header h2{margin:0 0 3px;font-size:16px}.prototype-dialog>header p{margin:0;color:#7a8290;font-size:11px}.prototype-dialog>header button{display:grid;width:30px;height:30px;margin-left:auto;place-items:center;border:1px solid #e0e4e9;border-radius:6px;background:#fff;color:#68717e;font-size:18px;cursor:pointer}.prototype-dialog-body{padding:18px 20px;overflow:auto}.prototype-dialog footer{display:flex;justify-content:flex-end;gap:8px;padding:13px 20px;border-top:1px solid #e5e8ed;background:#fafbfc;box-shadow:0 -10px 24px rgba(15,23,42,.06)}.template-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.template-grid button{position:relative;min-height:92px;padding:12px;border:1px solid #dfe3e8;border-radius:7px;background:#fff;text-align:left;cursor:pointer}.template-grid button:hover{border-color:#adc3ef;background:#fff}.template-grid button.selected{border-color:#4c7fe4;background:#fff;box-shadow:0 0 0 2px #edf3ff inset}.template-grid button i{position:absolute;top:10px;right:10px;width:15px;height:15px;border:1px solid #cbd1da;border-radius:50%}.template-grid button.selected i{border:4px solid #2563eb}.template-grid strong,.template-grid small{display:block}.template-grid strong{margin-bottom:5px;font-size:12px}.template-grid small{color:#7d8592;font-size:10px;line-height:1.45}.source-label{display:block;margin-bottom:6px;color:#596272;font-size:11px;font-weight:700}.source-import{width:100%;min-height:160px;padding:10px;border:1px solid #dfe3e9;border-radius:6px;outline:none;resize:vertical}.source-options{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.source-options label{color:#697180;font-size:11px}.source-options select{width:100%;margin-top:6px;padding:8px;border:1px solid #dfe3e9;border-radius:6px;background:#fff}.suite-error{margin:0 0 16px}.suite-form{display:grid;grid-template-columns:1fr 1fr;gap:0 15px}.suite-form .full{grid-column:1/-1}.suite-form :deep(.el-select){width:100%}
@media(max-width:1200px){.content-manifesto{grid-template-columns:1fr}.content-steps{min-height:150px;border-top:1px solid #374155;border-left:0}.content-table{min-width:1120px}.task-toolbar{align-items:flex-start;flex-direction:column;padding-top:14px;padding-bottom:14px}}
@media(max-width:700px){.content-page-head{height:auto;padding:16px;align-items:flex-start;gap:15px}.content-page-head p{max-width:300px}.page-actions .ghost-action{display:none}.content-body{padding:14px}.manifesto-copy{padding:24px 20px}.manifesto-copy h2{font-size:20px}.content-steps{grid-template-columns:repeat(2,1fr);gap:22px;padding:22px}.content-steps li::after{display:none}.task-tabs{flex-wrap:wrap}.task-tabs h2{width:100%}.task-search{width:100%}.task-search input{min-width:0;flex:1}.template-grid{grid-template-columns:1fr}.suite-form{grid-template-columns:1fr}.suite-form .full{grid-column:auto}}
</style>
