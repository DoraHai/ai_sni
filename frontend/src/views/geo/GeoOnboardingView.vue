<script setup>
/**
 * GEO 开户向导：官网 URL → 业务线 / 意图词 / 事实草稿 → 确认写入
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  applyGeoOnboarding,
  fetchOnboardingReadiness,
  formatGeoError,
  previewGeoOnboarding,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { needQuery } from '../../utils/geoEmptyReason'

const router = useRouter()
const { tenantId } = useGeoTenant()

const step = ref(1)
const websiteUrl = ref('')
const expand = ref(true)
const loading = ref(false)
const applying = ref(false)
const preview = ref(null)
const error = ref('')

const selectedBiz = ref([])
const selectedPrompts = ref([])
const selectedFacts = ref([])
const readiness = ref(null)

const bizOptions = computed(() => preview.value?.businesses || [])
const promptOptions = computed(() => preview.value?.prompt_candidates || [])
const factOptions = computed(() => preview.value?.fact_drafts || [])

async function runPreview() {
  if (!tenantId.value) {
    error.value = '请先选择客户'
    return
  }
  if (!websiteUrl.value.trim()) {
    ElMessage.warning('请填写官网 URL')
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await previewGeoOnboarding({
      tenant_id: tenantId.value,
      website_url: websiteUrl.value.trim(),
      expand: expand.value,
      max_prompt_candidates: 24,
    })
    preview.value = data
    selectedBiz.value = (data.businesses || [])
      .filter((b) => b.selected !== false)
      .map((b) => b.name)
    selectedPrompts.value = (data.prompt_candidates || [])
      .filter((p) => p.selected)
      .map((p) => p.question)
    selectedFacts.value = (data.fact_drafts || [])
      .filter((f) => f.selected)
      .map((f) => f.title)
    step.value = 2
    ElMessage.success('已解析官网，请确认草稿')
  } catch (e) {
    error.value = formatGeoError(e, '预览失败')
  } finally {
    loading.value = false
  }
}

async function runApply(dryRun = false) {
  if (!preview.value) return
  applying.value = true
  error.value = ''
  try {
    const businesses = bizOptions.value
      .filter((b) => selectedBiz.value.includes(b.name))
      .map((b) => ({ name: b.name, description: b.description || null }))
    const prompts = promptOptions.value
      .filter((p) => selectedPrompts.value.includes(p.question))
      .map((p) => ({
        question: p.question,
        question_group: p.question_group,
        priority: p.priority || 10,
        tags: p.tags || ['from_onboarding', 'brand_missing'],
        business_name: businesses[0]?.name || null,
      }))
    const facts = factOptions.value
      .filter((f) => selectedFacts.value.includes(f.title))
      .map((f) => ({
        title: f.title,
        statement: f.statement,
        fact_type: f.fact_type || 'product',
        source_name: f.source_name,
        source_url: f.source_url,
        trust_level: f.trust_level || 'needs_review',
      }))
    const body = {
      tenant_id: tenantId.value,
      website_url: preview.value.source_url || websiteUrl.value.trim(),
      brand_terms: preview.value.brand_guess ? [preview.value.brand_guess] : [],
      businesses,
      prompts,
      facts,
      create_website_channel: true,
      dry_run: dryRun,
    }
    const res = await applyGeoOnboarding(body)
    if (dryRun) {
      ElMessage.info(
        `演练：将创建 业务 ${res.counts?.businesses} · 意图词 ${res.counts?.prompts} · 事实 ${res.counts?.facts}`,
      )
      return
    }
    ElMessage.success(
      `已写入：业务 ${res.counts?.businesses} · 意图词 ${res.counts?.prompts} · 事实 ${res.counts?.facts}`,
    )
    step.value = 3
    preview.value = { ...preview.value, applyResult: res }
    try {
      readiness.value = await fetchOnboardingReadiness(tenantId.value)
    } catch {
      readiness.value = null
    }
  } catch (e) {
    error.value = formatGeoError(e, '写入失败')
  } finally {
    applying.value = false
  }
}

async function loadReadiness() {
  if (!tenantId.value) {
    readiness.value = null
    return
  }
  try {
    readiness.value = await fetchOnboardingReadiness(tenantId.value)
  } catch {
    readiness.value = null
  }
}

function goNeed(it) {
  router.push(needQuery(it))
}

watch(tenantId, loadReadiness)
onMounted(loadReadiness)
</script>

<template>
  <div class="onboard">
    <div class="page-head">
      <div>
        <h1 class="page-title">GEO 开户向导</h1>
        <p class="page-desc">
          输入官网 URL，自动抽取业务线候选、意图词与事实卡草稿；确认后写入，即可进入监测与内容生产。
        </p>
      </div>
      <router-link class="el-button el-button--small" to="/geo/businesses">优化业务</router-link>
    </div>

    <el-steps :active="step - 1" finish-status="success" align-center class="mb">
      <el-step title="输入官网" />
      <el-step title="确认草稿" />
      <el-step title="完成" />
    </el-steps>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <el-card v-if="step === 1 && readiness?.items?.length" shadow="never" class="mb">
      <div class="ready-head">
        当前客户还差什么 · {{ readiness.ready_count }}/{{ readiness.total }}
        <el-tag v-if="readiness.ready" type="success" size="small">已就绪</el-tag>
        <el-tag v-else type="warning" size="small">未就绪</el-tag>
      </div>
      <div
        v-for="it in readiness.items.filter((x) => !x.ok)"
        :key="it.key"
        class="ready-row"
      >
        <span class="ready-mark">!</span>
        <div class="ready-body">
          <div class="ready-title">{{ it.title }}</div>
          <div class="ready-hint">{{ it.hint }}</div>
        </div>
        <el-button v-if="it.href" size="small" @click="goNeed(it)">去处理</el-button>
      </div>
    </el-card>

    <el-card v-if="step === 1" shadow="never">
      <el-form label-width="100px">
        <el-form-item label="官网 URL" required>
          <el-input
            v-model="websiteUrl"
            placeholder="https://www.example.com"
            style="max-width: 480px"
          />
        </el-form-item>
        <el-form-item label="拓词">
          <el-switch v-model="expand" />
          <span class="hint">开启后用百度下拉扩展意图词候选（稍慢）</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="runPreview">解析官网</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <template v-if="step === 2 && preview">
      <el-card shadow="never" class="mb">
        <div class="meta">
          <b>{{ preview.page_title || '—' }}</b>
          <span class="muted"> · {{ preview.domain }} · 品牌猜 {{ preview.brand_guess || '—' }}</span>
        </div>
        <p class="hint">关键词：{{ (preview.keywords || []).slice(0, 12).join('、') || '—' }}</p>
        <ul v-if="preview.hints?.length" class="hints">
          <li v-for="(h, i) in preview.hints" :key="i">{{ h }}</li>
        </ul>
      </el-card>

      <el-card v-if="preview.audit" shadow="never" class="mb audit-card">
        <template #header>
          <div class="audit-head">
            <span>官网 GEO 体检</span>
            <el-tag
              v-if="preview.audit.score != null"
              :type="preview.audit.score >= 80 ? 'success' : preview.audit.score >= 60 ? 'warning' : 'danger'"
              size="small"
            >
              {{ preview.audit.score }} 分
            </el-tag>
            <span v-if="preview.audit.total != null" class="muted">
              通过 {{ preview.audit.passed }}/{{ preview.audit.total }}
            </span>
          </div>
        </template>
        <p v-if="preview.audit.error" class="hint">体检失败：{{ preview.audit.error }}</p>
        <template v-else>
          <p v-if="preview.audit.description" class="hint">{{ preview.audit.description }}</p>
          <div v-if="preview.audit.top_issues?.length" class="issues">
            <div class="issue-title">优先修复</div>
            <ul>
              <li v-for="(iss, i) in preview.audit.top_issues" :key="i">
                <el-tag size="small" :type="iss.severity === 'critical' || iss.severity === 'high' ? 'danger' : 'info'">
                  {{ iss.severity || '—' }}
                </el-tag>
                <b>{{ iss.title }}</b>
                <span class="muted"> — {{ iss.recommendation }}</span>
              </li>
            </ul>
          </div>
          <p v-else class="hint">未发现未通过项（或检查项全部通过）。</p>
        </template>
      </el-card>

      <el-card shadow="never" class="mb">
        <template #header>业务线（勾选写入）</template>
        <el-checkbox-group v-model="selectedBiz">
          <div v-for="b in bizOptions" :key="b.name" class="check-row">
            <el-checkbox :label="b.name">
              <b>{{ b.name }}</b>
              <span class="muted"> · {{ b.description }}</span>
            </el-checkbox>
          </div>
        </el-checkbox-group>
      </el-card>

      <el-card shadow="never" class="mb">
        <template #header>
          意图词候选（{{ selectedPrompts.length }}/{{ promptOptions.length }}）
        </template>
        <el-checkbox-group v-model="selectedPrompts">
          <div v-for="p in promptOptions" :key="p.question" class="check-row">
            <el-checkbox :label="p.question">
              {{ p.question }}
              <el-tag size="small" class="ml">{{ p.question_group || '—' }}</el-tag>
            </el-checkbox>
          </div>
        </el-checkbox-group>
      </el-card>

      <el-card shadow="never" class="mb">
        <template #header>事实卡草稿（{{ selectedFacts.length }}）</template>
        <el-checkbox-group v-model="selectedFacts">
          <div v-for="f in factOptions" :key="f.title + f.statement.slice(0, 20)" class="check-row fact">
            <el-checkbox :label="f.title">
              <b>{{ f.title }}</b>
              <div class="fact-st">{{ f.statement }}</div>
            </el-checkbox>
          </div>
        </el-checkbox-group>
      </el-card>

      <el-card shadow="never" class="mb">
        <template #header>建议监测引擎</template>
        <el-table :data="preview.engine_suggestions || []" size="small">
          <el-table-column prop="display_name" label="引擎" width="120" />
          <el-table-column prop="sample_mode" label="默认模式" width="120" />
          <el-table-column prop="note" label="说明" />
          <el-table-column label="推荐" width="80">
            <template #default="{ row }">
              <el-tag v-if="row.recommended" type="success" size="small">是</el-tag>
              <span v-else class="muted">可选</span>
            </template>
          </el-table-column>
        </el-table>
        <p class="hint mt">真采样请到「引擎配置」填写 Key；商业定位见引擎页「监测定位」。</p>
      </el-card>

      <div class="actions">
        <el-button @click="step = 1">上一步</el-button>
        <el-button :loading="applying" @click="runApply(true)">演练（不写库）</el-button>
        <el-button type="primary" :loading="applying" @click="runApply(false)">确认写入</el-button>
      </div>
    </template>

    <el-card v-if="step === 3" shadow="never">
      <el-result icon="success" title="开户草稿已写入" sub-title="先补齐下面还缺的项，再开始巡检和写稿">
        <template #extra>
          <el-button type="primary" @click="router.push('/geo/businesses')">看优化业务</el-button>
          <el-button @click="router.push('/geo/gaps')">缺口工作台</el-button>
        </template>
      </el-result>
      <div v-if="readiness?.items?.length" class="ready-list">
        <div class="ready-head">
          还差什么 · {{ readiness.ready_count }}/{{ readiness.total }}
          <el-tag v-if="readiness.ready" type="success" size="small">可以开干</el-tag>
          <el-tag v-else type="warning" size="small">未就绪</el-tag>
        </div>
        <div
          v-for="it in readiness.items"
          :key="it.key"
          class="ready-row"
          :class="{ ok: it.ok }"
        >
          <span class="ready-mark">{{ it.ok ? '✓' : '!' }}</span>
          <div class="ready-body">
            <div class="ready-title">{{ it.title }}</div>
            <div class="ready-hint">{{ it.hint }}</div>
          </div>
          <el-button v-if="!it.ok && it.href" size="small" @click="goNeed(it)">
            去处理
          </el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.onboard { padding: 4px 2px 40px; max-width: 960px; }
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.page-title { margin: 0 0 6px; font-size: 20px; font-weight: 700; }
.page-desc { margin: 0; font-size: 13px; color: #64748b; max-width: 560px; line-height: 1.5; }
.mb { margin-bottom: 14px; }
.mt { margin-top: 8px; }
.ml { margin-left: 6px; }
.hint { font-size: 12px; color: #94a3b8; margin-left: 8px; }
.muted { color: #94a3b8; font-size: 12px; }
.meta { font-size: 14px; margin-bottom: 6px; }
.hints { font-size: 12px; color: #64748b; padding-left: 18px; }
.audit-card { border-color: #bfdbfe; }
.audit-head { display: flex; align-items: center; gap: 10px; font-weight: 650; }
.issues { margin-top: 8px; }
.issue-title { font-size: 12px; font-weight: 650; margin-bottom: 6px; color: #1e40af; }
.issues ul { margin: 0; padding-left: 18px; font-size: 12px; line-height: 1.55; color: #334155; }
.issues li { margin-bottom: 4px; }
.check-row { margin-bottom: 8px; }
.check-row.fact { align-items: flex-start; }
.fact-st { font-size: 12px; color: #64748b; margin-top: 2px; max-width: 720px; line-height: 1.45; }
.actions { display: flex; gap: 10px; flex-wrap: wrap; }
.ready-list { max-width: 640px; margin: 0 auto 16px; }
.ready-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 650;
  margin-bottom: 10px;
}
.ready-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 0;
  border-top: 1px solid #e2e8f0;
}
.ready-mark {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #fff7ed;
  color: #c2410c;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}
.ready-row.ok .ready-mark { background: #ecfdf5; color: #047857; }
.ready-title { font-size: 13px; font-weight: 650; }
.ready-hint { font-size: 12px; color: #64748b; margin-top: 2px; }
.result-pre {
  background: #f8fafc;
  border-radius: 8px;
  padding: 12px;
  font-size: 12px;
}
</style>
