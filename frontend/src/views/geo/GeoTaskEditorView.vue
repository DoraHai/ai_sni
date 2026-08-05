<script setup>
/**
 * Vue 母稿编辑器 · 第一刀
 * 覆盖：Brief / 事实绑定与召回 / 生成 / 保存 / 检查(Score) / AI 审稿
 * 渠道稿·审校·Webhook 仍可走静态 editor 完整页
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
  fetchGeoBriefCatalog,
  generateGeoContentTask,
  getGeoContentTask,
  listGeoFacts,
  patchGeoContentTask,
  retrieveGeoTaskFacts,
  saveGeoArticle,
  staticGeoEditorUrl,
  suggestGeoTaskBrief,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

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
    const [t, factsRes] = await Promise.all([
      getGeoContentTask(tenantId.value, taskId.value),
      listGeoFacts(tenantId.value, { status: 'active' }),
    ])
    task.value = t
    allFacts.value = factsRes.items || []
    applyBriefToForm(t.brief)
    applyArticleFromTask(t)
    selectedFactIds.value = (t.facts || []).map((f) => f.id)
    if (t.rule_result) {
      checkResult.value = {
        ready: t.rule_result.ready,
        checks: t.rule_result.checks || [],
        geo_score: t.rule_result.geo_score,
        geo_subscores: t.rule_result.geo_subscores,
        geo_actions: t.rule_result.geo_actions || [],
        ai_review: t.rule_result.ai_review,
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
    ElMessage.error(e.message || '保存 Brief 失败')
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
    ElMessage.error(e.message || '建议 Brief 失败')
  } finally {
    busy.value = ''
  }
}

async function saveFacts() {
  busy.value = 'facts'
  try {
    task.value = await bindGeoTaskFacts(
      tenantId.value,
      taskId.value,
      selectedFactIds.value,
    )
    ElMessage.success(`已绑定 ${selectedFactIds.value.length} 条事实`)
  } catch (e) {
    ElMessage.error(e.message || '绑定失败')
  } finally {
    busy.value = ''
  }
}

async function retrieveFacts() {
  busy.value = 'retrieve'
  try {
    await patchGeoContentTask(tenantId.value, taskId.value, { brief: briefPayload() })
    const res = await retrieveGeoTaskFacts(tenantId.value, taskId.value, {
      limit: 8,
      verified_only: false,
    })
    retrievePreview.value = res.items || []
    if (!retrievePreview.value.length) {
      ElMessage.warning('未召回到相关事实')
    } else {
      ElMessage.success(`召回 ${retrievePreview.value.length} 条`)
    }
  } catch (e) {
    ElMessage.error(e.message || '召回失败')
  } finally {
    busy.value = ''
  }
}

async function applyRetrieveTop() {
  const ids = retrievePreview.value.map((x) => x.fact_id).filter(Boolean)
  if (!ids.length) {
    ElMessage.warning('请先召回事实')
    return
  }
  busy.value = 'apply'
  try {
    task.value = await applyGeoRetrievedFacts(tenantId.value, taskId.value, ids)
    selectedFactIds.value = (task.value.facts || []).map((f) => f.id)
    ElMessage.success('已绑定召回事实')
  } catch (e) {
    ElMessage.error(e.message || '绑定失败')
  } finally {
    busy.value = ''
  }
}

async function generate() {
  busy.value = 'generate'
  try {
    await patchGeoContentTask(tenantId.value, taskId.value, { brief: briefPayload() })
    task.value = await generateGeoContentTask(tenantId.value, taskId.value)
    applyArticleFromTask(task.value)
    applyBriefToForm(task.value.brief)
    selectedFactIds.value = (task.value.facts || []).map((f) => f.id)
    ElMessage.success('母稿已生成')
  } catch (e) {
    ElMessage.error(e.message || '生成失败')
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
    ElMessage.error(e.message || '保存失败')
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
    ElMessage.error(e.message || '检查失败')
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
    ElMessage.error(e.message || '审稿失败')
  } finally {
    busy.value = ''
  }
}

async function applyPatch(code) {
  busy.value = 'patch'
  try {
    const res = await applyGeoContentPatch(tenantId.value, taskId.value, code)
    if (res.task) {
      task.value = res.task
      applyArticleFromTask(res.task)
    }
    checkResult.value = {
      ...(checkResult.value || {}),
      ...res,
      checks: res.checks || checkResult.value?.checks,
    }
    ElMessage.success(`已应用补丁 ${code}`)
  } catch (e) {
    ElMessage.error(e.message || '补丁失败')
  } finally {
    busy.value = ''
  }
}

function openStaticFull() {
  window.open(staticGeoEditorUrl(tenantId.value || 1, taskId.value), '_blank')
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

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />
    <el-alert
      type="info"
      show-icon
      class="mb"
      title="Vue 母稿编辑器第一刀：Brief / 事实 / 生成 / 检查(Score) / AI 审稿。渠道稿与发布审校请用「静态完整 editor」。"
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
                <el-button size="small" type="primary" :loading="busy === 'facts'" @click="saveFacts">
                  保存绑定
                </el-button>
              </div>
            </div>
          </template>
          <div class="hint mb">已绑 {{ boundFacts.length }} 条 · 生成需 ≥3 条可核验事实</div>
          <el-select
            v-model="selectedFactIds"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择事实卡"
            style="width: 100%"
          >
            <el-option
              v-for="f in allFacts"
              :key="f.id"
              :label="`#${f.id} [${f.trust_level}] ${f.title}`"
              :value="f.id"
            />
          </el-select>
          <div v-if="retrievePreview.length" class="retrieve mt">
            <div class="hint">召回预览：</div>
            <div v-for="r in retrievePreview" :key="r.fact_id" class="retrieve-row">
              #{{ r.fact_id }} · {{ r.title }} · score {{ r.score }}
            </div>
          </div>
        </el-card>
      </div>

      <!-- Right: article + check -->
      <div class="col wide">
        <el-card shadow="never" class="card">
          <template #header>
            <div class="card-head">
              <span>母稿</span>
              <div class="row-actions">
                <el-button
                  size="small"
                  type="primary"
                  :loading="busy === 'generate'"
                  @click="generate"
                >
                  生成母稿
                </el-button>
                <el-button size="small" :loading="busy === 'save'" @click="saveArticleBody">
                  保存正文
                </el-button>
                <el-button size="small" :loading="busy === 'check'" @click="runCheck">
                  检查就绪
                </el-button>
                <el-button size="small" :loading="busy === 'review'" @click="runAiReview">
                  AI 审稿
                </el-button>
              </div>
            </div>
          </template>
          <el-form label-width="56px" size="small">
            <el-form-item label="标题">
              <el-input v-model="article.title" />
            </el-form-item>
            <el-form-item label="正文">
              <el-input
                v-model="article.body_markdown"
                type="textarea"
                :rows="18"
                placeholder="Markdown 母稿"
              />
            </el-form-item>
          </el-form>
          <div v-if="task.article" class="hint">
            版本 v{{ task.article.version_no }} · {{ task.article.created_at || '' }}
          </div>
        </el-card>

        <el-card shadow="never" class="card">
          <template #header>
            <span>规则 · GEO Score · 审稿</span>
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
              插入修复 · {{ p.code }}
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
</style>
