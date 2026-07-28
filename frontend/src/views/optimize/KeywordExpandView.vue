<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addCandidateToPlan,
  candidatesExportUrl,
  evaluateCandidates,
  fetchCandidates,
  syncExpansion,
  syncUrlWords,
  updateCandidateStatus,
} from '../../api/expansion'
import { fetchAdgroupList, fetchCampaignList } from '../../api/keywords'
import { session } from '../../store/session'

const TENANT_ID = computed(() => session.tenantId) // 当前客户，顶栏切换器驱动

const loading = ref(false)
const syncing = ref(false)
const exporting = ref(false)
const evaluating = ref(false)
const error = ref('')
const data = ref(null)

// 4 源卡（原型 03-optimize/01-keyword-expand），二期已全部启用（2026-06-12）
const SOURCES = [
  { code: 'planner', name: '百度关键词规划师', icon: '🔍', cls: 'src-c-planner', desc: '种子词拓展 + 账户主动推荐，含官方搜索量与竞争度', enabled: true },
  { code: 'query', name: '搜索词转拓词', icon: '📝', cls: 'src-c-query', desc: '搜索词报告中已触发但未添加的高价值搜索词', enabled: true },
  { code: 'url', name: 'URL 爬取', icon: '🌐', cls: 'src-c-url', desc: '输入官网或产品页 URL，自研提词 + 百度流量回查', enabled: true },
  { code: 'cold', name: '冷门词识别', icon: '❄', cls: 'src-c-cold', desc: '低搜索量高意图 / 低展现有点击，自动识别归入', enabled: true },
]

const filters = reactive({
  source: '',
  status: 'pending',
  suggestedCategory: '',
  minScore: null,
  q: '',
  aiRelevance: '',
  page: 1,
  pageSize: 20,
})

const syncForm = reactive({ seeds: '', queryDays: 30 })
const urlForm = reactive({ urls: '' })
const crawling = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchCandidates({ tenantId: TENANT_ID.value, ...filters })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

watch(
  () => [filters.source, filters.status, filters.suggestedCategory, filters.minScore, filters.aiRelevance],
  () => { filters.page = 1; load() },
)
let qTimer = null
watch(() => filters.q, () => {
  clearTimeout(qTimer)
  qTimer = setTimeout(() => { filters.page = 1; load() }, 400)
})
watch(() => [filters.page, filters.pageSize], load)

function toggleSource(s) {
  if (!s.enabled) return
  filters.source = filters.source === s.code ? '' : s.code
}

async function runSync() {
  syncing.value = true
  try {
    const resp = await syncExpansion({
      tenantId: TENANT_ID.value,
      seeds: syncForm.seeds.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean).join(','),
      queryDays: syncForm.queryDays,
    })
    if (resp.status === 'error') throw new Error(resp.message)
    ElMessage.success(`拉取完成：规划师 ${resp.planner_candidates} 条 / 搜索词 ${resp.query_candidates} 条（种子词 ${resp.seeds.length} 个）`)
    load()
  } catch (e) {
    ElMessage.error('拉取失败：' + e.message)
  } finally {
    syncing.value = false
  }
}

async function runUrlCrawl() {
  const urls = urlForm.urls.split(/[\n,，\s]+/).map((s) => s.trim()).filter(Boolean)
  if (!urls.length) {
    ElMessage.warning('请先输入至少 1 个 URL')
    return
  }
  if (urls.length > 5) {
    ElMessage.warning('最多 5 个 URL')
    return
  }
  crawling.value = true
  try {
    const resp = await syncUrlWords({ tenantId: TENANT_ID.value, urls })
    if (resp.status === 'error') throw new Error(resp.message)
    const failed = resp.urls.filter((u) => u.error)
    let msg = `爬取完成：入库 ${resp.candidates_written} 个候选`
    if (failed.length) msg += `；${failed.length} 个 URL 失败`
    failed.length ? ElMessage.warning(msg) : ElMessage.success(msg)
    failed.forEach((u) => ElMessage.error(`${u.url}：${u.error}`))
    load()
  } catch (e) {
    ElMessage.error('爬取失败：' + e.message)
  } finally {
    crawling.value = false
  }
}

async function runEvaluate(force = false) {
  evaluating.value = true
  try {
    const resp = await evaluateCandidates({ tenantId: TENANT_ID.value, force })
    if (resp.enabled === false) {
      ElMessage.warning('未配置 DeepSeek，AI 评估不可用')
    } else if (resp.evaluated === 0) {
      ElMessage.info(force ? '没有可评估的候选' : '待处理候选都已评估过（重评请用「全部重评」）')
    } else {
      ElMessage.success(`AI 评估完成：${resp.distinct_words} 词去重 → ${resp.evaluated} 行已研判${resp.failed_batches ? `（${resp.failed_batches} 批失败已跳过）` : ''}`)
    }
    load()
  } catch (e) {
    ElMessage.error('AI 评估失败：' + e.message)
  } finally {
    evaluating.value = false
  }
}

async function setStatus(row, status, label) {
  try {
    await updateCandidateStatus({ tenantId: TENANT_ID.value, candidateId: row.id, status })
    ElMessage.success(`「${row.word}」${label}`)
    load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// 加入计划：候选词无所属单元，需选目标计划→单元 + 匹配 + 出价，再 addWord 写回
const planDialog = reactive({
  visible: false, row: null, campaignId: null, adgroupId: null,
  matchMode: 'phrase', price: null, submitting: false,
})
const planCampaigns = ref([])
const planAdgroups = ref([])

async function openAddToPlan(row) {
  Object.assign(planDialog, {
    visible: true, row, campaignId: null, adgroupId: null,
    matchMode: 'phrase',
    price: row.ai_suggested_bid ?? row.recommend_price_pc ?? null,
    submitting: false,
  })
  planAdgroups.value = []
  if (!planCampaigns.value.length) {
    try {
      planCampaigns.value = (await fetchCampaignList({ tenantId: TENANT_ID.value })).campaigns || []
    } catch (e) {
      ElMessage.error('加载计划失败：' + (e.message || ''))
    }
  }
}

async function onPlanCampaign(cid) {
  planDialog.adgroupId = null
  planAdgroups.value = []
  if (!cid) return
  try {
    planAdgroups.value = (await fetchAdgroupList({ tenantId: TENANT_ID.value, campaignId: cid })).adgroups || []
  } catch (e) {
    ElMessage.error('加载单元失败：' + (e.message || ''))
  }
}

async function submitAddToPlan() {
  if (!planDialog.adgroupId) return ElMessage.warning('请选择目标单元')
  if (!(Number(planDialog.price) > 0)) return ElMessage.warning('请输入有效出价')
  planDialog.submitting = true
  try {
    const res = await addCandidateToPlan({
      tenantId: TENANT_ID.value, candidateId: planDialog.row.id,
      adgroupId: planDialog.adgroupId, price: Number(planDialog.price), matchMode: planDialog.matchMode,
    })
    if (res.dry_run) ElMessage.warning('演练模式：已记入台账，未真改线上（候选保留待处理）')
    else ElMessage.success(`「${planDialog.row.word}」已加入计划`)
    planDialog.visible = false
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    planDialog.submitting = false
  }
}

async function exportCsv() {
  exporting.value = true
  try {
    const resp = await fetch(candidatesExportUrl({ tenantId: TENANT_ID.value, ...filters }), {
      headers: session.token
        ? { Authorization: `Bearer ${session.token}` }
        : { 'X-API-Key': import.meta.env.VITE_API_KEY || '' },
    })
    if (!resp.ok) throw new Error('导出失败 HTTP ' + resp.status)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `expansion_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    exporting.value = false
  }
}

const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))
const fmtMoney = (v) => (v == null ? '—' : '¥ ' + Number(v).toFixed(2))
const fmtTime = (v) => (v ? v.slice(5, 16).replace('T', ' ') : '—')

const pendingCount = (code) => data.value?.source_pending_counts?.[code] ?? 0
const catClass = computed(() => ({
  brand: 'cat-brand', focus: 'cat-focus', normal: 'cat-normal',
  longtail: 'cat-longtail', observe: 'cat-observe', negative: 'cat-negative',
}))

// AI 相关性徽章配色
const aiRelClass = { relevant: 'ai-relevant', generic: 'ai-generic', irrelevant: 'ai-irrelevant' }
const aiEnabled = computed(() => data.value?.ai_enabled === true)
const aiUnevaluated = computed(() => data.value?.ai_unevaluated ?? 0)
const aiRelCount = (code) => data.value?.ai_relevance_counts?.[code] ?? 0

// 顶栏切换客户后重新拉数
watch(TENANT_ID, () => { filters.page = 1; load() })

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">拓词</div>
        <div class="page-desc">
          4 源聚合候选关键词 ·「加入计划」一键加成关键词写回百度（dry-run 保护，演练模式不真改线上）
          <template v-if="data?.last_synced_at"> · 同步于 {{ fmtTime(data.last_synced_at) }}</template>
          <template v-if="aiEnabled && data?.last_ai_eval_at"> · AI 评估于 {{ fmtTime(data.last_ai_eval_at) }}</template>
        </div>
      </div>
      <div class="page-actions">
        <el-button :loading="exporting" @click="exportCsv">导出 CSV</el-button>
        <el-dropdown
          v-if="session.canEdit('optimize.expand') && aiEnabled"
          split-button
          type="primary"
          :loading="evaluating"
          @click="runEvaluate(false)"
        >
          {{ evaluating ? 'AI 研判中…' : `AI 评估${aiUnevaluated ? `（${aiUnevaluated} 待评）` : ''}` }}
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="runEvaluate(true)">全部重评（含已评估）</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-tooltip content="批量加入计划需统一指定目标单元，暂未支持，请逐条「加入计划」" placement="top">
          <span><el-button type="primary" disabled>批量加入计划</el-button></span>
        </el-tooltip>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />

    <!-- 4 源卡 -->
    <div class="source-tabs">
      <div
        v-for="s in SOURCES"
        :key="s.code"
        class="src-card"
        :class="{ active: filters.source === s.code, disabled: !s.enabled }"
        @click="toggleSource(s)"
      >
        <div class="src-icon" :class="s.cls">{{ s.icon }}</div>
        <div class="src-name">{{ s.name }}</div>
        <div class="src-desc">{{ s.desc }}</div>
        <span v-if="s.enabled" class="src-count">{{ fmtInt(pendingCount(s.code)) }} 待处理</span>
        <span v-else class="src-count dim-badge">二期</span>
      </div>
    </div>

    <!-- URL 爬取面板（选中 URL 爬取源时显示） -->
    <div v-if="session.canEdit('optimize.expand') && filters.source === 'url'" class="sync-panel url-panel">
      <span class="sync-label">URL 列表</span>
      <el-input
        v-model="urlForm.urls"
        type="textarea"
        :rows="3"
        placeholder="每行一个 URL，最多 5 个，示例：&#10;https://www.sulzer.com/zh-cn/products/pumps"
        style="flex: 1; max-width: 620px"
      />
      <el-button type="primary" :loading="crawling" @click="runUrlCrawl">
        {{ crawling ? '爬取中（约 20-60 秒）' : '开始爬取' }}
      </el-button>
      <span class="sync-hint">仅爬页面文本 · 单 URL 最多 30 个候选 · 自动回查百度搜索量</span>
    </div>

    <!-- 拉取面板 -->
    <div v-else-if="session.canEdit('optimize.expand')" class="sync-panel">
      <span class="sync-label">种子词</span>
      <el-input
        v-model="syncForm.seeds"
        placeholder="逗号分隔，最多 20 个；留空自动取累计展现最高的重点/一般词"
        clearable
        style="flex: 1; max-width: 520px"
      />
      <span class="sync-label">搜索词回看</span>
      <el-select v-model="syncForm.queryDays" style="width: 110px">
        <el-option label="近 30 天" :value="30" />
        <el-option label="近 60 天" :value="60" />
        <el-option label="近 91 天" :value="91" />
      </el-select>
      <el-button type="primary" :loading="syncing" @click="runSync">
        {{ syncing ? '拉取中（约 10-30 秒）' : '拉取最新候选' }}
      </el-button>
    </div>

    <!-- 筛选行 -->
    <div class="filter-row">
      <el-select v-model="filters.status" style="width: 130px">
        <el-option label="待处理" value="pending" />
        <el-option label="已采纳" value="adopted" />
        <el-option label="已忽略" value="ignored" />
        <el-option label="全部状态" value="" />
      </el-select>
      <el-select v-model="filters.suggestedCategory" placeholder="建议分类 · 全部" clearable style="width: 150px">
        <el-option
          v-for="o in data?.category_options || []"
          :key="o.code"
          :label="o.label"
          :value="o.code"
        />
      </el-select>
      <el-select v-model="filters.minScore" placeholder="潜力分 · 全部" clearable style="width: 130px">
        <el-option label="高（≥ 8）" :value="8" />
        <el-option label="中（≥ 5）" :value="5" />
        <el-option label="≥ 3" :value="3" />
      </el-select>
      <el-select
        v-if="aiEnabled"
        v-model="filters.aiRelevance"
        placeholder="AI 相关性 · 全部"
        clearable
        style="width: 170px"
      >
        <el-option
          v-for="o in data?.ai_relevance_options || []"
          :key="o.code"
          :value="o.code"
        >
          {{ o.label }}（{{ fmtInt(aiRelCount(o.code)) }}）
        </el-option>
      </el-select>
      <el-button
        v-if="aiEnabled"
        :type="filters.aiRelevance === 'relevant' ? 'primary' : 'default'"
        text
        @click="filters.aiRelevance = filters.aiRelevance === 'relevant' ? '' : 'relevant'"
      >
        {{ filters.aiRelevance === 'relevant' ? '✓ 已隐藏通用噪音' : '隐藏通用噪音' }}
      </el-button>
      <el-input v-model="filters.q" placeholder="搜索候选词" clearable style="width: 200px" />
    </div>

    <!-- 候选表 -->
    <div class="table-panel">
      <el-table :data="data?.candidates || []" class="kw-table" row-key="id">
        <el-table-column label="候选关键词" min-width="200">
          <template #default="{ row }">
            <div class="kw-cell-name">{{ row.word }}</div>
            <div class="kw-cell-sub">
              <template v-if="row.matched_keyword">触发词：{{ row.matched_keyword }}</template>
              <template v-else-if="row.seed_word && row.seed_word.startsWith('http')">来源页面：{{ row.seed_word }}</template>
              <template v-else-if="row.seed_word">种子词：{{ row.seed_word }}</template>
              <template v-else-if="row.source === 'planner'">账户主动推荐</template>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <span class="source-tag" :class="'tag-' + row.source">{{ row.source_label }}</span>
          </template>
        </el-table-column>
        <el-table-column label="月搜索量" width="100" align="right">
          <template #default="{ row }">
            <span class="num">{{ fmtInt(row.monthly_pv) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="竞争度" width="76" align="center">
          <template #default="{ row }">{{ row.competition_label || '—' }}</template>
        </el-table-column>
        <el-table-column label="指导价 PC/移动" width="130" align="right">
          <template #default="{ row }">
            <span class="num">{{ fmtMoney(row.recommend_price_pc) }}<template v-if="row.recommend_price_mobile != null"> / {{ Number(row.recommend_price_mobile).toFixed(2) }}</template></span>
          </template>
        </el-table-column>
        <el-table-column label="窗口展现/点击" width="120" align="right">
          <template #default="{ row }">
            <span class="num" v-if="row.impression != null">{{ fmtInt(row.impression) }} / {{ fmtInt(row.click) }}</span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="潜力分" width="110">
          <template #default="{ row }">
            <span class="heat-bar"><span class="heat-fill" :style="{ width: (row.potential_score ?? 0) * 10 + '%' }" /></span>
            <span class="num">{{ row.potential_score ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="建议分类" width="100">
          <template #default="{ row }">
            <span v-if="row.suggested_category" class="cat-pill" :class="catClass[row.suggested_category]">
              {{ row.suggested_category_label }}
            </span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="aiEnabled" label="AI 研判" width="150">
          <template #default="{ row }">
            <template v-if="row.ai_relevance">
              <el-tooltip :content="row.ai_reason || '—'" placement="top" :disabled="!row.ai_reason">
                <span class="ai-pill" :class="aiRelClass[row.ai_relevance]">
                  {{ row.ai_relevance_label }}
                </span>
              </el-tooltip>
              <span v-if="row.ai_recommend" class="ai-rec" :class="'rec-' + row.ai_recommend">
                {{ row.ai_recommend_label }}
              </span>
            </template>
            <span v-else class="dim">未评估</span>
          </template>
        </el-table-column>
        <el-table-column label="特色" min-width="110">
          <template #default="{ row }">
            <span v-if="row.show_reasons.length" class="reasons">{{ row.show_reasons.join(' / ') }}</span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <template v-if="session.canEdit('optimize.expand') && row.status === 'pending'">
                <el-tooltip content="选目标单元 + 匹配 + 出价，加成正式关键词写回百度（dry-run 保护）" placement="top">
                  <el-button size="small" type="primary" plain @click="openAddToPlan(row)">加入计划</el-button>
                </el-tooltip>
                <el-button size="small" @click="setStatus(row, 'ignored', '已忽略')">忽略</el-button>
              </template>
              <template v-else>
                <span class="status-mark" :class="row.status">{{ row.status_label }}</span>
                <el-button v-if="session.canEdit('optimize.expand')" size="small" text @click="setStatus(row, 'pending', '已恢复待处理')">恢复</el-button>
              </template>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-line">暂无候选词。点上方「拉取最新候选」从百度规划师 + 搜索词报告聚合。</div>
        </template>
      </el-table>
      <div class="table-footer">
        <span>共 {{ fmtInt(data?.total || 0) }} 条</span>
        <el-pagination
          v-model:current-page="filters.page"
          v-model:page-size="filters.pageSize"
          :total="data?.total || 0"
          :page-sizes="[10, 20, 50, 100]"
          layout="sizes, prev, pager, next, jumper"
          background
          small
        />
      </div>
    </div>

    <div class="note">
      <b>说明</b>：潜力分由搜索量/真实触发流量、竞争度、特色标签综合估算（启发式 v1）；建议分类仅供参考，
      加入计划后请在关键词工作台完成最终 5 类分级。月搜索量与指导价来自百度规划师；窗口展现/点击来自搜索词报告（已触发未添加）。
      <template v-if="aiEnabled"><br><b>AI 研判</b>：DeepSeek 对候选词做语义相关性判断（业务相关/通用噪音/不相关），
      帮你快速筛掉"设备""中心"、地名等通用词噪音；仅作参考，不影响潜力分排序。点「AI 评估」对未评估候选研判，同步时也会自动跟跑一次。</template>
    </div>

    <!-- 加入计划：候选词无所属单元，需选目标计划→单元 + 匹配 + 出价 -->
    <el-dialog v-model="planDialog.visible" title="加入计划" width="440px">
      <div v-if="planDialog.row" class="plan-form">
        <div class="pf-word">候选词：<b>{{ planDialog.row.word }}</b></div>
        <el-form label-width="72px" label-position="left">
          <el-form-item label="计划">
            <el-select v-model="planDialog.campaignId" placeholder="选择计划" style="width: 100%" @change="onPlanCampaign">
              <el-option v-for="c in planCampaigns" :key="c.campaign_id" :label="c.campaign_name" :value="c.campaign_id" />
            </el-select>
          </el-form-item>
          <el-form-item label="单元">
            <el-select v-model="planDialog.adgroupId" placeholder="先选计划" style="width: 100%" :disabled="!planDialog.campaignId">
              <el-option v-for="a in planAdgroups" :key="a.adgroup_id" :label="a.adgroup_name" :value="a.adgroup_id" />
            </el-select>
          </el-form-item>
          <el-form-item label="匹配方式">
            <el-radio-group v-model="planDialog.matchMode">
              <el-radio label="phrase">短语</el-radio>
              <el-radio label="exact">精确</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="出价">
            <el-input-number v-model="planDialog.price" :min="0.01" :max="999.99" :step="0.1" :precision="2" />
            <span v-if="planDialog.row.recommend_price_pc" class="pf-hint">指导价 ¥{{ planDialog.row.recommend_price_pc }}</span>
          </el-form-item>
          <div v-if="planDialog.row.ai_bid_reason" class="pf-ai">
            💡 AI 建议 <b>¥{{ planDialog.row.ai_suggested_bid }}</b>：{{ planDialog.row.ai_bid_reason }}
          </div>
        </el-form>
        <div class="pf-tip">受 ±20% 区间校验并记台账；演练模式下不真改线上。</div>
      </div>
      <template #footer>
        <el-button @click="planDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="planDialog.submitting" @click="submitAddToPlan">确认加入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; display: flex; justify-content: space-between; align-items: flex-end; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }
.page-actions { display: flex; gap: 8px; }

.plan-form { font-size: 13px; }
.pf-word { margin-bottom: 12px; color: var(--sem-text); }
.pf-hint { margin-left: 10px; font-size: 12px; color: #9ca3af; }
.pf-ai { font-size: 12px; color: var(--sem-primary); background: #eff4fb; border-radius: 4px; padding: 6px 10px; margin: 2px 0 4px; line-height: 1.5; }
.pf-tip { font-size: 12px; color: #ba7517; margin-top: 4px; }

.source-tabs { display: flex; gap: 12px; margin-bottom: 14px; }
.src-card { flex: 1; background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 14px 16px; cursor: pointer; transition: all 0.15s; position: relative; }
.src-card:hover { border-color: var(--sem-primary); box-shadow: 0 2px 8px rgba(24, 95, 165, 0.06); }
.src-card.active { border-color: var(--sem-primary); background: linear-gradient(135deg, #f4f8fd 0%, #fafbfc 100%); box-shadow: 0 4px 12px rgba(24, 95, 165, 0.1); }
.src-card.disabled { opacity: 0.55; cursor: not-allowed; }
.src-card.disabled:hover { border-color: var(--sem-border); box-shadow: none; }
.src-icon { width: 34px; height: 34px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 17px; color: #fff; margin-bottom: 8px; }
.src-c-url { background: linear-gradient(135deg, #185fa5 0%, #2c7cc8 100%); }
.src-c-planner { background: linear-gradient(135deg, #ba7517 0%, #dc9a47 100%); }
.src-c-query { background: linear-gradient(135deg, #1d9e75 0%, #4dbe99 100%); }
.src-c-cold { background: linear-gradient(135deg, #6b47b5 0%, #9474d4 100%); }
.src-name { font-size: 13px; font-weight: 600; color: var(--sem-text); margin-bottom: 3px; }
.src-desc { font-size: 11px; color: var(--sem-text-sub); line-height: 1.5; }
.src-count { position: absolute; top: 12px; right: 12px; background: #eff4fb; color: var(--sem-primary); padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.dim-badge { background: #f3f4f6; color: #9ca3af; }

.sync-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sync-label { font-size: 12px; color: var(--sem-text-sub); flex-shrink: 0; }
.url-panel { align-items: flex-start; }
.url-panel .sync-label { padding-top: 6px; }
.sync-hint { font-size: 11px; color: #9ca3af; padding-top: 8px; }

.filter-row { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }

.table-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; overflow: hidden; }
.kw-cell-name { font-weight: 500; color: var(--sem-text); }
.kw-cell-sub { font-size: 11px; color: var(--sem-text-sub); margin-top: 2px; }
.num { font-variant-numeric: tabular-nums; }
.dim { color: #c0c4cc; }

.source-tag { font-size: 11px; padding: 1px 7px; border-radius: 3px; }
.tag-planner { background: #fef1e1; color: #ba7517; }
.tag-query { background: #e5f4ed; color: #1d9e75; }
.tag-url { background: #eff4fb; color: #185fa5; }
.tag-cold { background: #f2ebfb; color: #6b47b5; }

.heat-bar { width: 40px; height: 4px; background: #f3f4f6; border-radius: 2px; overflow: hidden; display: inline-block; vertical-align: middle; margin-right: 6px; }
.heat-fill { height: 100%; display: block; background: linear-gradient(90deg, #1d9e75 0%, #185fa5 100%); }

.cat-pill { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.cat-brand { background: #eff4fb; color: #185fa5; }
.cat-focus { background: #fef1e1; color: #ba7517; }
.cat-normal { background: #f3f4f6; color: #4b5563; }
.cat-longtail { background: #e5f4ed; color: #1d9e75; }
.cat-observe { background: #f2ebfb; color: #6b47b5; }
.cat-negative { background: #fef6f6; color: #e24b4a; }

.ai-pill { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.ai-relevant { background: #e5f4ed; color: #1d9e75; }
.ai-generic { background: #fdf6e3; color: #b8860b; }
.ai-irrelevant { background: #fef6f6; color: #e24b4a; }
.ai-rec { display: block; margin-top: 3px; font-size: 10px; color: #9ca3af; }
.ai-rec.rec-adopt { color: #1d9e75; }
.ai-rec.rec-drop { color: #e24b4a; }

.reasons { font-size: 11px; color: #ba7517; }
.row-actions { display: flex; gap: 4px; align-items: center; }
.status-mark { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.status-mark.adopted { background: #e5f4ed; color: #1d9e75; }
.status-mark.ignored { background: #f3f4f6; color: #9ca3af; }

.table-footer { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; font-size: 12px; color: var(--sem-text-sub); border-top: 1px solid var(--sem-border); }
.empty-line { font-size: 12px; color: var(--sem-text-sub); padding: 18px 0; }
.note { margin-top: 12px; padding: 10px 12px; background: #f4f8fd; border-radius: 6px; font-size: 11px; color: #4b5563; line-height: 1.7; }
.note b { color: var(--sem-primary); }
</style>
