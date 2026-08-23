<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createGeoContentTask,
  expandGeoPromptCandidates,
  listGeoPrompts,
  promoteGeoPromptCandidates,
} from '../../api/geoContent'
import GeoV2Page from '../../components/GeoV2Page.vue'
import NeedHintAlert from '../../components/NeedHintAlert.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'

const route = useRoute()
const router = useRouter()
const { tenantId } = useGeoTenant()
const keyword = ref(String(route.query.keyword || 'CRM软件'))
const expanding = ref(false)
const promoting = ref(false)
const error = ref('')
const items = ref([])
const meta = ref(null)
const selected = ref([])
const gaps = ref([])

const suggestedQuestions = computed(() =>
  (items.value || [])
    .map((row) => row.question || row.term || row.text)
    .filter((q) => q && String(q).length >= 4)
    .slice(0, 8),
)

async function loadGaps() {
  if (!tenantId.value) return
  try {
    const data = await listGeoPrompts(tenantId.value, { status: 'active' })
    gaps.value = (data.items || []).filter(
      (p) => Array.isArray(p.tags) && p.tags.includes('brand_missing'),
    )
  } catch {
    gaps.value = []
  }
}

async function analyze() {
  if (!tenantId.value) return
  expanding.value = true
  error.value = ''
  try {
    const data = await expandGeoPromptCandidates({
      tenant_id: tenantId.value,
      market: 'cn',
      max_terms: 40,
      seed_from_tenant: true,
      products: keyword.value ? [keyword.value] : [],
      persist: true,
    })
    items.value = data.items || []
    meta.value = {
      total: data.total,
      new_count: data.new_count,
      errors: data.errors || [],
    }
    ElMessage.success(`已分析 ${items.value.length} 条建议`)
  } catch (e) {
    error.value = e.message || '分析失败'
  } finally {
    expanding.value = false
  }
}

async function promote(rows) {
  const pack = (rows || selected.value)
    .map((row) => ({
      question: row.question || row.term || row.text,
      question_group: row.question_group || row.group || null,
      market: 'cn',
      priority: 10,
      tags: ['from_expand'],
    }))
    .filter((x) => x.question && String(x.question).length >= 4)
  if (!pack.length) {
    ElMessage.warning('请先勾选要加入的提问')
    return
  }
  promoting.value = true
  try {
    const r = await promoteGeoPromptCandidates({ tenant_id: tenantId.value, items: pack })
    ElMessage.success(`已加入 ${r.created ?? pack.length} 条 AI 提问`)
    router.push('/geo/questions')
  } catch (e) {
    ElMessage.error(e.message || '加入失败')
  } finally {
    promoting.value = false
  }
}

async function makeArticle(prompt) {
  try {
    const task = await createGeoContentTask({
      tenant_id: tenantId.value,
      prompt_id: prompt.id,
      title: prompt.question,
    })
    router.push(`/geo/tasks/${task.id}`)
  } catch (e) {
    ElMessage.error(e.message || '创建文章失败')
  }
}

watch(tenantId, loadGaps)
watch(
  () => route.query.keyword,
  (v) => {
    if (v) keyword.value = String(v)
  },
)
onMounted(async () => {
  await loadGaps()
  if (route.query.keyword) analyze()
})
</script>

<template>
  <GeoV2Page
    tag="自动发现机会"
    title="输入一个关键词，系统帮你找到值得优化的提问、产品和解决方案。"
    desc="结合已有业务、意图词和知识库，自动推荐可加入优化的关键词与 AI 提问。"
    :steps="['输入关键词', '分析品牌资产', '生成建议清单', '一键加入优化']"
    :answer="{
      now: ['我现在怎么样？', gaps.length ? `${gaps.length} 条高价值提问品牌未被推荐。` : '先分析一个关键词，拿到可执行建议。'],
      why: ['为什么？', 'AI 更容易在选型和比较问题中推荐品牌。'],
      next: ['下一步怎么办？', '把高意图提问加入本周优化，并生成 GEO 文章。'],
    }"
  >
    <template #actions>
      <el-button type="primary" :loading="expanding" @click="analyze">重新分析</el-button>
    </template>

    <NeedHintAlert />
    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <section class="gv2-panel">
      <div class="gv2-panel-head">
        <div>
          <span class="gv2-kicker">AI推荐输入</span>
          <h2>关键词：{{ keyword || '未填写' }}</h2>
          <p class="sub">系统基于当前租户已有业务、提问和事实给出优化建议。</p>
        </div>
        <div style="display:flex;gap:8px;">
          <el-input v-model="keyword" placeholder="输入关键词" style="width: 220px" @keyup.enter="analyze" />
          <el-button type="primary" :loading="expanding" @click="analyze">分析</el-button>
        </div>
      </div>
      <div class="gv2-grid-3">
        <div class="gv2-card">
          <b>建议关键词</b>
          <p>{{ keyword }} 及相关购买决策词，适合加入关键词管理。</p>
        </div>
        <div class="gv2-card">
          <b>建议 AI 提问</b>
          <p>
            {{
              suggestedQuestions.slice(0, 2).join('；') ||
              '分析后会列出更接近真实用户问法的提问。'
            }}
          </p>
        </div>
        <div class="gv2-card">
          <b>建议内容任务</b>
          <p>{{ gaps.length ? `${gaps.length} 条品牌缺失提问可直接生成文章。` : '加入提问后可一键生成 GEO 文章。' }}</p>
        </div>
      </div>
    </section>

    <section class="gv2-panel">
      <div class="gv2-panel-head">
        <div>
          <span class="gv2-kicker">一键加入优化</span>
          <h2>推荐工作流</h2>
          <p class="sub">把建议直接转成 AI 提问和内容任务。{{ meta?.total != null ? `本次 ${meta.total} 条候选` : '' }}</p>
        </div>
        <el-button type="primary" :loading="promoting" :disabled="!selected.length" @click="promote()">
          加入选中提问
        </el-button>
      </div>
      <el-table
        :data="items"
        stripe
        empty-text="点「分析」后显示建议"
        @selection-change="selected = $event"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column label="建议提问" min-width="260">
          <template #default="{ row }">{{ row.question || row.term || row.text }}</template>
        </el-table-column>
        <el-table-column label="分组" width="120">
          <template #default="{ row }">{{ row.question_group || row.group || '—' }}</template>
        </el-table-column>
        <el-table-column label="下一步" width="140">
          <template #default>
            <span class="gv2-tag">加入AI提问</span>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section v-if="gaps.length" class="gv2-panel">
      <div class="gv2-panel-head">
        <div>
          <span class="gv2-kicker">已有缺口</span>
          <h2>品牌未被推荐的提问</h2>
        </div>
      </div>
      <el-table :data="gaps.slice(0, 12)" stripe>
        <el-table-column prop="question" label="AI提问" min-width="280" />
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link type="primary" @click="makeArticle(row)">生成GEO文章</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </GeoV2Page>
</template>
