<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createGeoContentTask,
  fetchGeoCitationInsights,
  fetchGeoCompetitorInsights,
  fetchGeoEvaluationInsights,
  listGeoAnswerSnapshots,
  listGeoTrackingEngines,
} from '../../api/geoContent'
import GeoObjectSwitcher from '../../components/GeoObjectSwitcher.vue'
import GeoV2Page from '../../components/GeoV2Page.vue'
import { useGeoObjectScope } from '../../composables/useGeoObjectScope'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import { engineDisplay, fmtPct } from '../../utils/geoReportLabels'

const router = useRouter()
const { tenantId, promptId, currentPrompt, currentBusiness, currentUnit } = useGeoObjectScope()
const { days } = useObservationPeriod()
const loading = ref(false)
const error = ref('')
const snapshots = ref([])
const engines = ref([])
const cites = ref(null)
const comps = ref(null)
const evals = ref(null)

const objectLabel = computed(() => {
  const b = currentBusiness.value?.name || '全部业务'
  const u = currentUnit.value?.keyword || currentUnit.value?.name || '全部关键词'
  const q = currentPrompt.value?.question || '全部提问'
  return `${b} → ${u} → ${q}`
})

const mentionRate = computed(() => {
  const rows = snapshots.value
  if (!rows.length) return null
  const hit = rows.filter((s) => s.mentions_brand).length
  return hit / rows.length
})
const recommendRate = computed(() => {
  const rows = snapshots.value
  if (!rows.length) return null
  const hit = rows.filter((s) => s.brand_position === 'first' || s.brand_position === 'alternative').length
  return hit / rows.length
})
const firstShare = computed(() => {
  const rows = snapshots.value
  if (!rows.length) return null
  return rows.filter((s) => s.brand_position === 'first').length / rows.length
})

const byEngine = computed(() => {
  const map = new Map()
  for (const s of snapshots.value) {
    const key = s.engine || 'unknown'
    if (!map.has(key)) {
      map.set(key, { engine: key, total: 0, mentioned: 0, first: 0, cites: 0, text: '' })
    }
    const row = map.get(key)
    row.total += 1
    if (s.mentions_brand) row.mentioned += 1
    if (s.brand_position === 'first') row.first += 1
    row.cites += (s.cited_urls || []).length
    if (!row.text && s.raw_text) row.text = String(s.raw_text).slice(0, 80)
  }
  return [...map.values()].map((r) => ({
    engine: engineDisplay(r.engine),
    position: r.first ? '首位推荐' : r.mentioned ? '有提及' : '未出现',
    rate: r.total ? r.mentioned / r.total : null,
    cites: r.cites,
    reason: r.text || (r.mentioned ? '品牌已出现。' : '本模型未推荐品牌。'),
  }))
})

const findings = computed(() => {
  const rows = []
  const top = byEngine.value[0]
  if (top) rows.push(`${top.engine} 样本最多，推荐率 ${fmtPct(top.rate)}。`)
  const miss = byEngine.value.filter((r) => !r.rate)
  if (miss.length) rows.push(`${miss.map((m) => m.engine).join('、')} 尚未提到品牌。`)
  const comp = comps.value?.items?.[0] || comps.value?.competitors?.[0]
  if (comp) rows.push(`竞品「${comp.name || comp.competitor}」仍常被并列提及。`)
  if (!rows.length) rows.push('先选择一条 AI 提问，或跑一次巡检后再看拆解。')
  return rows
})

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const params = { limit: 80 }
    if (promptId.value) params.prompt_id = promptId.value
    const [snaps, eng, ci, co, ev] = await Promise.all([
      listGeoAnswerSnapshots(tenantId.value, params),
      listGeoTrackingEngines(tenantId.value, true).catch(() => ({ items: [] })),
      fetchGeoCitationInsights(tenantId.value, { days: days.value }).catch(() => null),
      fetchGeoCompetitorInsights(tenantId.value).catch(() => null),
      fetchGeoEvaluationInsights(tenantId.value, { days: days.value }).catch(() => null),
    ])
    snapshots.value = [...(snaps.items || snaps.snapshots || [])].sort((a, b) =>
      String(b.captured_at || '').localeCompare(String(a.captured_at || '')),
    )
    engines.value = eng.items || []
    cites.value = ci
    comps.value = co
    evals.value = ev
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function createTask() {
  if (!currentPrompt.value) {
    ElMessage.warning('请先选择一条 AI 提问')
    return
  }
  try {
    const task = await createGeoContentTask({
      tenant_id: tenantId.value,
      prompt_id: currentPrompt.value.id,
      title: currentPrompt.value.question,
    })
    router.push(`/geo/tasks/${task.id}`)
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
}

watch([tenantId, promptId], load)
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <GeoV2Page
      tag="AI可见性"
      title="逐条分析 AI 为什么推荐或不推荐你。"
      desc="围绕具体 AI 提问拆解回答内容、品牌出现位置、竞品出现原因和下一步补强动作。"
      :steps="['选择AI提问', '查看AI回答', '分析推荐原因', '加入内容任务']"
      :answer="{
        now: ['我现在怎么样？', mentionRate == null ? '还没有可分析的回答快照。' : `当前对象品牌出现率 ${fmtPct(mentionRate)}。`],
        why: ['为什么？', '推荐理由通常来自可验证事实、清晰结构和第三方来源。'],
        next: ['下一步怎么办？', currentPrompt ? '把这条提问生成 GEO 文章，并补案例证据。' : '先选一条提问再决定补什么。'],
      }"
    >
      <template #actions>
        <el-button @click="router.push('/geo/visibility/snapshots')">登记快照</el-button>
        <el-button type="primary" @click="createTask">生成优化建议</el-button>
      </template>

      <GeoObjectSwitcher />
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <section class="gv2-panel">
        <div class="gv2-panel-head">
          <div>
            <span class="gv2-kicker">核心分析</span>
            <h2>AI 回答拆解</h2>
            <p class="sub">当前对象：{{ objectLabel }}</p>
          </div>
        </div>
        <div class="model-strip" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px;">
          <span class="gv2-kicker" style="margin:0;">AI 模型</span>
          <span v-for="e in engines" :key="e.engine || e.key" class="gv2-tag">
            {{ engineDisplay(e.engine || e.key || e.name) }}
          </span>
        </div>
        <div class="gv2-grid-4">
          <article class="gv2-card">
            <span class="gv2-kicker">品牌出现率</span>
            <strong style="font-size:28px;">{{ fmtPct(mentionRate) }}</strong>
            <p>当前提问在已保存快照中的出现比例。</p>
          </article>
          <article class="gv2-card">
            <span class="gv2-kicker">推荐率</span>
            <strong style="font-size:28px;">{{ fmtPct(recommendRate) }}</strong>
            <p>进入前三推荐的快照占比。</p>
          </article>
          <article class="gv2-card">
            <span class="gv2-kicker">首位推荐率</span>
            <strong style="font-size:28px;">{{ fmtPct(firstShare) }}</strong>
            <p>brand_position = first 的快照占比。</p>
          </article>
          <article class="gv2-card">
            <span class="gv2-kicker">引用域名</span>
            <strong style="font-size:28px;">{{ cites?.items?.length ?? cites?.domains?.length ?? '—' }}</strong>
            <p>观察期内被引用来源数。</p>
          </article>
        </div>
        <div class="gv2-card" style="margin-top:14px;">
          <span class="gv2-kicker">关键发现</span>
          <ul>
            <li v-for="f in findings" :key="f">{{ f }}</li>
          </ul>
        </div>
      </section>

      <section class="gv2-panel">
        <div class="gv2-panel-head">
          <div>
            <span class="gv2-kicker">最新回答</span>
            <h2>{{ currentPrompt?.question || '请选择一条 AI 提问' }}</h2>
            <p class="sub">正文来自回答快照 raw_text。</p>
          </div>
        </div>
        <p v-if="snapshots[0]?.raw_text" class="sub" style="white-space:pre-wrap;max-height:160px;overflow:auto;">
          {{ snapshots[0].raw_text }}
        </p>
        <p v-else class="sub">没有快照。请先巡检或登记回答。</p>
        <p v-if="snapshots[0]?.competitors?.length" class="sub">
          竞品：{{ snapshots[0].competitors.join('、') }}
        </p>
      </section>

      <section class="gv2-panel">
        <div class="gv2-panel-head">
          <div>
            <span class="gv2-kicker">数据明细</span>
            <h2>各模型回答对比</h2>
          </div>
        </div>
        <el-table :data="byEngine" stripe empty-text="暂无快照。请先巡检或登记回答。">
          <el-table-column prop="engine" label="AI模型" width="140" />
          <el-table-column prop="position" label="品牌位置" width="120" />
          <el-table-column label="推荐率" width="100">
            <template #default="{ row }">{{ fmtPct(row.rate) }}</template>
          </el-table-column>
          <el-table-column prop="cites" label="引用数" width="90" />
          <el-table-column prop="reason" label="原因" min-width="220" />
        </el-table>
      </section>
    </GeoV2Page>
  </div>
</template>
