<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createGeoAnswerSnapshot,
  extractGeoAnswerSnapshotUrls,
  listGeoAnswerSnapshots,
  listGeoPrompts,
  listGeoTrackingEngines,
  patchGeoAnswerSnapshot,
  probeGeoAnswerSnapshot,
  probeGeoAnswerSnapshotBatch,
  suggestGeoAnswerSnapshotFields,
} from '../../api/geoContent'
import { session } from '../../store/session'

const route = useRoute()
const router = useRouter()

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const probing = ref(false)
const batchProbing = ref(false)
const saving = ref(false)
const error = ref('')
const engines = ref([])
const prompts = ref([])
const snapshots = ref([])
const batchDrafts = ref([])

const filterPromptId = ref(route.query.prompt_id ? Number(route.query.prompt_id) : null)
const filterEngine = ref('')
const queueMode = computed(() => route.query.queue === 'recheck')

const form = ref({
  prompt_id: null,
  engine: 'deepseek',
  raw_text: '',
  captured_at: '',
  mentions_brand: false,
  brand_position: 'unknown',
  sentiment: 'unknown',
  competitors: '',
  cited_urls: '',
  note: '',
})

const enabledEngines = computed(() => {
  const enabled = engines.value.filter((e) => e.enabled)
  return enabled.length ? enabled : engines.value
})

const posLabel = { first: '首位', mentioned: '提及', absent: '未出现', unknown: '—' }
const sentLabel = { positive: '正', neutral: '中', negative: '负', unknown: '—' }

function snippet(text) {
  const s = String(text || '').replace(/\s+/g, ' ').trim()
  return s.length > 80 ? `${s.slice(0, 80)}…` : s
}

function applySuggest(draft) {
  if (!draft) return
  if (typeof draft.suggested_mentions_brand === 'boolean') {
    form.value.mentions_brand = draft.suggested_mentions_brand
  }
  if (draft.suggested_brand_position) form.value.brand_position = draft.suggested_brand_position
  if (draft.suggested_sentiment) form.value.sentiment = draft.suggested_sentiment
  const comps = draft.suggested_competitors || draft.competitors
  if (comps) form.value.competitors = (comps || []).join(', ')
  if (draft.suggested_cited_urls) form.value.cited_urls = (draft.suggested_cited_urls || []).join('\n')
}

function loadDraftIntoForm(draft) {
  if (!draft?.ok && draft?.error) {
    ElMessage.error(`${draft.engine}: ${draft.error}`)
    return
  }
  form.value.raw_text = draft.raw_text || ''
  if (draft.engine) form.value.engine = draft.engine
  form.value.note = draft.simulated
    ? `${draft.engine} 模拟探测草稿（待确认）`
    : `${draft.engine || 'deepseek'} 探测草稿（待确认）`
  applySuggest(draft)
}

async function loadEngines() {
  const data = await listGeoTrackingEngines(tenantId.value)
  engines.value = data.items || []
  if (!enabledEngines.value.some((e) => e.engine_key === form.value.engine)) {
    form.value.engine = enabledEngines.value[0]?.engine_key || 'deepseek'
  }
}

async function loadPrompts() {
  const data = queueMode.value
    ? await listGeoPrompts(tenantId.value, { need_recheck: true })
    : await listGeoPrompts(tenantId.value, { status: 'active' })
  prompts.value = data.items || []
  if (!queueMode.value && !prompts.value.length) {
    const all = await listGeoPrompts(tenantId.value)
    prompts.value = all.items || []
  }
  if (filterPromptId.value && prompts.value.some((p) => p.id === filterPromptId.value)) {
    form.value.prompt_id = filterPromptId.value
  } else if (!form.value.prompt_id && prompts.value.length) {
    form.value.prompt_id = prompts.value[0].id
  }
}

async function loadSnapshots() {
  const params = {}
  if (filterPromptId.value) params.prompt_id = filterPromptId.value
  if (filterEngine.value) params.engine = filterEngine.value
  const data = await listGeoAnswerSnapshots(tenantId.value, params)
  snapshots.value = data.items || []
}

async function reloadAll() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await loadEngines()
    await loadPrompts()
    await loadSnapshots()
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function setPromptFilter(id) {
  filterPromptId.value = id
  form.value.prompt_id = id
  const q = { ...route.query, prompt_id: String(id) }
  router.replace({ query: q })
  loadSnapshots().catch((e) => { error.value = e.message })
}

function clearPromptFilter() {
  filterPromptId.value = null
  const q = { ...route.query }
  delete q.prompt_id
  router.replace({ query: q })
  loadSnapshots().catch((e) => { error.value = e.message })
}

async function onProbe() {
  if (!form.value.prompt_id) {
    ElMessage.warning('请选择机会问题')
    return
  }
  probing.value = true
  error.value = ''
  try {
    const draft = await probeGeoAnswerSnapshot({
      tenant_id: tenantId.value,
      prompt_id: form.value.prompt_id,
      engine: form.value.engine,
    })
    loadDraftIntoForm({ ...draft, ok: true })
    ElMessage.success('已填入探测草稿，请确认后保存')
  } catch (e) {
    error.value = e.message
  } finally {
    probing.value = false
  }
}

async function onProbeBatch() {
  if (!form.value.prompt_id) {
    ElMessage.warning('请选择机会问题')
    return
  }
  batchProbing.value = true
  error.value = ''
  batchDrafts.value = []
  try {
    const result = await probeGeoAnswerSnapshotBatch({
      tenant_id: tenantId.value,
      prompt_id: form.value.prompt_id,
    })
    batchDrafts.value = result.items || []
    const firstOk = batchDrafts.value.find((i) => i.ok)
    if (firstOk) loadDraftIntoForm(firstOk)
    ElMessage.success(
      `多引擎探测完成：成功 ${result.ok_count || 0}，失败 ${result.error_count || 0}`,
    )
  } catch (e) {
    error.value = e.message
  } finally {
    batchProbing.value = false
  }
}

async function onSuggest() {
  if (!form.value.raw_text.trim()) {
    ElMessage.warning('请先粘贴或探测回答正文')
    return
  }
  try {
    const draft = await suggestGeoAnswerSnapshotFields({
      tenant_id: tenantId.value,
      raw_text: form.value.raw_text,
      prompt_id: form.value.prompt_id || null,
      use_llm: true,
    })
    applySuggest(draft)
    ElMessage.success('已填入标注建议')
  } catch (e) {
    error.value = e.message
  }
}

async function onExtractUrls() {
  if (!form.value.raw_text.trim()) {
    ElMessage.warning('请先粘贴或探测回答正文')
    return
  }
  try {
    const data = await extractGeoAnswerSnapshotUrls({
      tenant_id: tenantId.value,
      raw_text: form.value.raw_text,
    })
    form.value.cited_urls = (data.suggested_cited_urls || []).join('\n')
    ElMessage.success(
      data.suggested_cited_urls?.length
        ? `已抽取 ${data.suggested_cited_urls.length} 条 URL`
        : '正文中未识别到链接',
    )
  } catch (e) {
    error.value = e.message
  }
}

async function onSave() {
  if (!form.value.prompt_id) {
    ElMessage.warning('请选择机会问题')
    return
  }
  saving.value = true
  error.value = ''
  try {
    await createGeoAnswerSnapshot({
      tenant_id: tenantId.value,
      prompt_id: form.value.prompt_id,
      engine: form.value.engine,
      raw_text: form.value.raw_text,
      captured_at: form.value.captured_at || null,
      mentions_brand: form.value.mentions_brand,
      brand_position: form.value.brand_position,
      sentiment: form.value.sentiment,
      competitors: form.value.competitors.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
      cited_urls: form.value.cited_urls.split(/\n+/).map((s) => s.trim()).filter(Boolean),
      note: form.value.note || null,
    })
    form.value.raw_text = ''
    form.value.cited_urls = ''
    form.value.competitors = ''
    form.value.note = ''
    form.value.mentions_brand = false
    form.value.brand_position = 'unknown'
    form.value.sentiment = 'unknown'
    ElMessage.success('快照已保存')
    await loadSnapshots()
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function toggleMention(row) {
  try {
    await patchGeoAnswerSnapshot(tenantId.value, row.id, {
      mentions_brand: !row.mentions_brand,
    })
    await loadSnapshots()
  } catch (e) {
    error.value = e.message
  }
}

async function saveBatchItem(draft) {
  if (!draft.ok || !form.value.prompt_id) return
  saving.value = true
  try {
    await createGeoAnswerSnapshot({
      tenant_id: tenantId.value,
      prompt_id: form.value.prompt_id,
      engine: draft.engine,
      raw_text: draft.raw_text,
      mentions_brand: !!draft.suggested_mentions_brand,
      brand_position: draft.suggested_brand_position || 'unknown',
      sentiment: draft.suggested_sentiment || 'unknown',
      competitors: draft.suggested_competitors || [],
      cited_urls: draft.suggested_cited_urls || [],
      note: draft.simulated
        ? `${draft.engine} 模拟探测（批量确认）`
        : `${draft.engine} 探测（批量确认）`,
    })
    ElMessage.success(`已保存 ${draft.engine}`)
    draft._saved = true
    await loadSnapshots()
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

watch(filterEngine, () => loadSnapshots())
watch(tenantId, reloadAll)
onMounted(reloadAll)
</script>

<template>
  <div v-loading="loading" class="geo-vis">
    <div class="page-header">
      <div>
        <div class="page-title">AI 可见度</div>
        <div class="page-desc">
          粘贴或探测回答快照；多引擎探测共用租户 LLM，按引擎人设生成草稿（不写库）。
        </div>
      </div>
      <div class="header-actions">
        <el-button @click="reloadAll">刷新</el-button>
        <router-link class="el-button" to="/geo/citations">引用域名</router-link>
        <router-link class="el-button" to="/geo/overview">GEO 概览</router-link>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />
    <el-alert
      v-if="queueMode"
      type="info"
      :closable="false"
      class="mb"
      :title="`待复核队列 · ${prompts.length} 条（已发布但无快照，或快照早于最近发布）`"
    />

    <div class="layout">
      <section class="panel">
        <div class="panel-title">登记回答快照</div>
        <el-form label-position="top" @submit.prevent>
          <el-form-item label="机会问题">
            <el-select v-model="form.prompt_id" filterable style="width: 100%">
              <el-option
                v-for="p in prompts"
                :key="p.id"
                :label="`#${p.id} · ${p.question}`"
                :value="p.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="引擎">
            <el-select v-model="form.engine" style="width: 100%">
              <el-option
                v-for="e in enabledEngines"
                :key="e.engine_key"
                :label="e.display_name || e.engine_key"
                :value="e.engine_key"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="回答原文">
            <el-input v-model="form.raw_text" type="textarea" :rows="7" placeholder="粘贴模型回答…" />
          </el-form-item>
          <el-form-item label="观测时间（可选 ISO）">
            <el-input v-model="form.captured_at" placeholder="留空则用当前时间" />
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="form.mentions_brand">提及我方品牌</el-checkbox>
          </el-form-item>
          <div class="row2">
            <el-form-item label="我方位置">
              <el-select v-model="form.brand_position" style="width: 100%">
                <el-option label="未知" value="unknown" />
                <el-option label="首位推荐" value="first" />
                <el-option label="有提及" value="mentioned" />
                <el-option label="未出现" value="absent" />
              </el-select>
            </el-form-item>
            <el-form-item label="情感倾向">
              <el-select v-model="form.sentiment" style="width: 100%">
                <el-option label="未知" value="unknown" />
                <el-option label="正面" value="positive" />
                <el-option label="中性" value="neutral" />
                <el-option label="负面" value="negative" />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item label="竞品名（逗号分隔）">
            <el-input v-model="form.competitors" placeholder="竞品A, 竞品B" />
          </el-form-item>
          <el-form-item label="引用 URL（每行一个）">
            <el-input v-model="form.cited_urls" type="textarea" :rows="3" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="form.note" />
          </el-form-item>
          <div class="actions">
            <el-button :loading="probing" @click="onProbe">用 AI 探测</el-button>
            <el-button :loading="batchProbing" type="warning" plain @click="onProbeBatch">
              多引擎探测
            </el-button>
            <el-button @click="onSuggest">AI 标注建议</el-button>
            <el-button @click="onExtractUrls">抽取 URL</el-button>
            <el-button type="primary" :loading="saving" @click="onSave">保存快照</el-button>
          </div>
          <p class="hint">
            探测 / 多引擎探测只填草稿；多引擎共用租户 LLM，按引擎人设模拟，非真实各厂 API。
          </p>
        </el-form>

        <div v-if="batchDrafts.length" class="batch">
          <div class="panel-title">多引擎草稿</div>
          <div v-for="d in batchDrafts" :key="d.engine" class="batch-item">
            <div class="batch-head">
              <strong>{{ d.engine }}</strong>
              <span v-if="d.ok && d.simulated" class="tag">模拟</span>
              <span v-if="!d.ok" class="tag bad">失败</span>
              <span v-if="d._saved" class="tag ok">已保存</span>
            </div>
            <p v-if="d.error" class="err-line">{{ d.error }}</p>
            <p v-else class="snip">{{ snippet(d.raw_text) }}</p>
            <div v-if="d.ok" class="actions">
              <el-button size="small" @click="loadDraftIntoForm(d)">填入表单</el-button>
              <el-button
                size="small"
                type="primary"
                :disabled="d._saved"
                :loading="saving"
                @click="saveBatchItem(d)"
              >
                确认保存
              </el-button>
            </div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="list-toolbar">
          <div class="panel-title" style="margin: 0">快照列表</div>
          <el-select v-model="filterEngine" clearable placeholder="全部引擎" style="width: 140px">
            <el-option
              v-for="e in engines"
              :key="e.engine_key"
              :label="e.display_name || e.engine_key"
              :value="e.engine_key"
            />
          </el-select>
          <el-button v-if="filterPromptId" @click="clearPromptFilter">清除问题过滤</el-button>
        </div>
        <p class="hint">
          {{ filterPromptId ? `过滤机会 #${filterPromptId}` : '显示全部快照' }}
          <template v-if="filterEngine"> · 引擎={{ filterEngine }}</template>
        </p>
        <el-table :data="snapshots" size="small" empty-text="暂无快照">
          <el-table-column label="问题" min-width="180">
            <template #default="{ row }">
              <div>{{ row.prompt_question || `#${row.prompt_id}` }}</div>
              <div class="snip">{{ snippet(row.raw_text) }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="engine" label="引擎" width="100" />
          <el-table-column label="提及" width="100">
            <template #default="{ row }">
              <el-button size="small" text @click="toggleMention(row)">
                {{ row.mentions_brand ? '是' : '否' }} · 切换
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="位置" width="80">
            <template #default="{ row }">{{ posLabel[row.brand_position] || row.brand_position }}</template>
          </el-table-column>
          <el-table-column label="情感" width="60">
            <template #default="{ row }">{{ sentLabel[row.sentiment] || row.sentiment }}</template>
          </el-table-column>
          <el-table-column label="竞品" min-width="120">
            <template #default="{ row }">{{ (row.competitors || []).join(', ') || '—' }}</template>
          </el-table-column>
          <el-table-column prop="captured_at" label="观测时间" width="160" />
        </el-table>

        <div v-if="queueMode && prompts.length" class="queue">
          <div class="panel-title">队列快捷</div>
          <button
            v-for="p in prompts"
            :key="p.id"
            type="button"
            class="queue-item"
            @click="setPromptFilter(p.id)"
          >
            #{{ p.id }} · {{ p.question }}
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.geo-vis { padding: 4px 2px 24px; }
.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.page-title { font-size: 20px; font-weight: 650; color: #1f2937; }
.page-desc { margin-top: 4px; font-size: 13px; color: #6b7280; }
.header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.mb { margin-bottom: 14px; }
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
}
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px 18px;
}
.panel-title { font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 12px; }
.row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.hint { margin: 0; font-size: 12px; color: #9ca3af; line-height: 1.5; }
.list-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.snip { font-size: 12px; color: #9ca3af; margin: 4px 0 0; }
.batch { margin-top: 18px; border-top: 1px solid #e5e7eb; padding-top: 14px; }
.batch-item {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: #f9fafb;
}
.batch-head { display: flex; gap: 8px; align-items: center; }
.tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #e0e7ff;
  color: #3730a3;
}
.tag.bad { background: #fef2f2; color: #b91c1c; }
.tag.ok { background: #ecfdf5; color: #047857; }
.err-line { color: #b91c1c; font-size: 12px; margin: 6px 0; }
.queue { margin-top: 16px; }
.queue-item {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 6px;
  cursor: pointer;
  font-size: 13px;
}
.queue-item:hover { border-color: #93c5fd; background: #eff6ff; }
@media (max-width: 960px) {
  .layout { grid-template-columns: 1fr; }
  .row2 { grid-template-columns: 1fr; }
}
</style>
