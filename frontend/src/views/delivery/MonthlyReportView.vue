<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { analysisReportExportUrl, fetchAnalysisReport } from '../../api/reports'
import { session } from '../../store/session'
import { formatUtcTimestamp } from '../../utils/dateTime'

const TENANT_ID = computed(() => session.tenantId)
const router = useRouter()

const loading = ref(false)
const regenerating = ref(false)
const exporting = ref('')
const error = ref('')
const report = ref(null)
let loadVersion = 0
const pad = (n) => String(n).padStart(2, '0')
const isoOf = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
function getMonday(d) {
  const date = new Date(d)
  const day = date.getDay() || 7
  if (day !== 1) date.setDate(date.getDate() - day + 1)
  return date
}
const quickOptions = [
  {
    key: 'today',
    label: '今日',
    range: () => {
      const today = new Date()
      return [isoOf(today), isoOf(today)]
    },
  },
  {
    key: 'week',
    label: '本周',
    range: () => {
      const monday = getMonday(new Date())
      const sunday = new Date(monday)
      sunday.setDate(monday.getDate() + 6)
      return [isoOf(monday), isoOf(sunday)]
    },
  },
  {
    key: 'lastWeek',
    label: '上周',
    range: () => {
      const thisMonday = getMonday(new Date())
      const lastMonday = new Date(thisMonday)
      lastMonday.setDate(thisMonday.getDate() - 7)
      const lastSunday = new Date(lastMonday)
      lastSunday.setDate(lastMonday.getDate() + 6)
      return [isoOf(lastMonday), isoOf(lastSunday)]
    },
  },
  {
    key: 'last7',
    label: '最近7天',
    range: () => {
      const end = new Date()
      const start = new Date()
      start.setDate(end.getDate() - 6)
      return [isoOf(start), isoOf(end)]
    },
  },
]
const activeRangeKey = ref('week')
const dateRange = ref(quickOptions.find((opt) => opt.key === activeRangeKey.value).range())
// 绑定单客户的账号（品牌方客户）锁定客户版；无绑定（内部团队）默认内部版可切
const version = ref(session.user?.tenant_id ? 'client' : 'internal')
const versionLocked = computed(() => !!session.user?.tenant_id)

const fmtMoney = (v) => (v == null ? '—' : '¥ ' + Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 }))
const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))
const fmtPct = (v) => (v == null ? '—' : (v * 100).toFixed(2) + '%')
const fmtChange = (v) => (v == null ? '' : (v >= 0 ? '↑' : '↓') + Math.abs(v) + '%')

const data = computed(() => report.value?.data || null)
const narrative = computed(() => report.value?.narrative || null)
// 前后端发布存在短暂时差时，旧响应缺少新模块也不得让整页崩溃。
const clientDelivery = computed(() => data.value?.client_delivery || {
  completed_count: 0, ready_effects: 0, observing_effects: 0, completed_actions: [],
})
const operationalFocus = computed(() => data.value?.operational_focus || {
  pending_suggestions: 0, pending_writebacks: 0, sync_risks: [], priority_suggestions: [],
  suggestions_path: '/optimize/keywords?has_suggestion=true', queue_path: '/verify/pending',
})

// AI 叙述里裸写的英文缩写补中文全称（如 CPC → CPC（平均点击成本））。
// 显示时展开，对历史缓存文案也即时生效；已带（中文）或字母串内的不重复加。
const CN_TERMS = { OCPC: '目标转化出价', CPC: '平均点击成本', CTR: '点击率', CPL: '线索成本', CPM: '千次展现成本', ROI: '投资回报' }
const ABBR_RE = /(?<![A-Za-z（(])(OCPC|CPC|CTR|CPL|CPM|ROI)(?![A-Za-z（(])/g
function withCn(text) {
  return text ? String(text).replace(ABBR_RE, (m) => `${m}（${CN_TERMS[m]}）`) : text
}

const comment = (key) => withCn(narrative.value?.module_comments?.[key] || '')
const aiEnabled = computed(() => report.value?.ai_enabled === true)
const WORK_STATUS_LABELS = { todo: '待处理', in_progress: '处理中', waiting_writeback: '待回写', completed: '已完成', rejected: '已驳回' }
const fmtDeadline = (value) => value ? value.slice(0, 16).replace('T', ' ') : '未设置截止时间'

// 内部版才显示的模块（异常处置回顾 / 竞品占位）
const showInternal = computed(() => version.value === 'internal')
const openWorkItem = (path) => router.push(path)

async function load(force = false) {
  if (!dateRange.value?.[0] || !dateRange.value?.[1]) return
  const requestVersion = ++loadVersion
  const tenantId = TENANT_ID.value
  if (!tenantId) return
  force ? (regenerating.value = true) : (loading.value = true)
  error.value = ''
  try {
    report.value = await fetchAnalysisReport({
      tenantId,
      startDate: dateRange.value[0],
      endDate: dateRange.value[1],
      force,
      version: version.value,
    })
    if (requestVersion !== loadVersion || tenantId !== TENANT_ID.value) return
    if (force) ElMessage.success('AI 报告已重新生成')
  } catch (e) {
    if (requestVersion !== loadVersion || tenantId !== TENANT_ID.value) return
    error.value = e.code === 'PERMISSION_DENIED'
      ? '当前账号无权查看该客户报告'
      : '报告暂时无法加载，请稍后重试。看板和验证数据不受影响。'
  } finally {
    if (requestVersion === loadVersion) {
      loading.value = false
      regenerating.value = false
    }
  }
}

watch(dateRange, () => load())
watch(version, () => load())

function printReport() {
  window.print()
}

function handleExportCommand(format) {
  if (format === 'pdf') {
    printReport()
    return
  }
  exportReport(format)
}

function applyQuickRange(opt) {
  activeRangeKey.value = opt.key
  dateRange.value = opt.range()
}

function clearQuickRange() {
  activeRangeKey.value = ''
}

async function exportReport(format) {
  if (!dateRange.value?.[0] || !dateRange.value?.[1] || exporting.value) return
  exporting.value = format
  try {
    const resp = await fetch(analysisReportExportUrl({
      tenantId: TENANT_ID.value,
      startDate: dateRange.value[0],
      endDate: dateRange.value[1],
      format,
      version: version.value,
    }), {
      headers: session.token
        ? { Authorization: `Bearer ${session.token}` }
        : { 'X-API-Key': import.meta.env.VITE_API_KEY || '' },
    })
    if (!resp.ok) throw new Error('导出失败 HTTP ' + resp.status)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `analysis_report_${TENANT_ID.value}_${dateRange.value[0]}_${dateRange.value[1]}.${format}`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error('报告导出失败，请稍后重试')
  } finally {
    exporting.value = ''
  }
}

watch(TENANT_ID, () => {
  report.value = null
  load()
})

onMounted(() => load())

// 趋势条形最大值（CSS 柱状）
const trendMax = computed(() => Math.max(1, ...(data.value?.trend || []).map((d) => d.cost)))

// 报告目录（按版本过滤）
const toc = computed(() => {
  const items = [
    { key: 'overview', label: '整体数据' },
    { key: 'by_category', label: '分类报告' },
    { key: 'top_keywords', label: 'TOP10 消费词' },
    { key: 'device', label: '设备分布' },
  ]
  if (showInternal.value) items.push({ key: 'alerts', label: '异常处置回顾' })
  if (showInternal.value) items.push({ key: 'today_focus', label: '今日执行焦点' })
  items.push({ key: 'operations', label: showInternal.value ? '优化操作 & 后续计划' : '已完成优化与效果' })
  if (showInternal.value) items.push({ key: 'pending', label: '待接入模块' })
  return items
})

function scrollTo(key) {
  document.getElementById('mod-' + key)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <div v-loading="loading" class="report-wrap">
    <!-- 工具栏（打印时隐藏） -->
    <div class="toolbar no-print">
      <div>
        <div class="page-title">投放分析报告</div>
        <div class="page-desc">客户交付 · 自定义区间效果数据 + AI 分析叙述</div>
      </div>
      <div class="tb-actions">
        <div class="quick-range-buttons" aria-label="快捷日期范围">
          <button
            v-for="opt in quickOptions"
            :key="opt.key"
            :class="{ active: activeRangeKey === opt.key }"
            type="button"
            @click="applyQuickRange(opt)"
          >
            {{ opt.label }}
          </button>
        </div>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          range-separator="至"
          unlink-panels
          :clearable="false"
          aria-label="选择报告日期区间"
          style="width: 268px"
          @change="clearQuickRange"
        />
        <el-radio-group v-if="!versionLocked" v-model="version" size="small">
          <el-radio-button label="internal">内部版</el-radio-button>
          <el-radio-button label="client">客户版</el-radio-button>
        </el-radio-group>
        <el-button v-if="session.canEdit('delivery.report') && aiEnabled" :loading="regenerating" @click="load(true)">重新生成 AI</el-button>
        <el-dropdown trigger="click" :disabled="!!exporting" @command="handleExportCommand">
          <el-button :loading="!!exporting">
            {{ exporting ? '导出中…' : '导出' }}<span class="dropdown-mark">▾</span>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="csv">CSV 表格</el-dropdown-item>
              <el-dropdown-item command="xls">Excel 兼容表格</el-dropdown-item>
              <el-dropdown-item command="xlsx">Excel 文件</el-dropdown-item>
              <el-dropdown-item command="pdf">PDF 文件</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button type="primary" @click="printReport">打印</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />

    <div v-if="data" class="report-layout">
      <!-- 左：目录 -->
      <div class="toc no-print">
        <div class="toc-title">报告目录</div>
        <div v-for="t in toc" :key="t.key" class="toc-item" @click="scrollTo(t.key)">{{ t.label }}</div>
      </div>

      <!-- 中：报告正文 -->
      <div class="report-main">
        <!-- 报告头 -->
        <div class="rm-head">
          <div class="rm-title">{{ data.tenant.name }} · SEM 投放分析报告</div>
          <div class="rm-sub">
            统计区间 {{ data.period.start_date }} ~ {{ data.period.end_date }} · 投放 {{ data.period.active_days }}/{{ data.period.days }} 天
            <span v-if="version === 'internal'" class="ver-tag">内部版</span>
            <span v-else class="ver-tag client">客户版</span>
          </div>
        </div>

        <!-- AI 总览摘要 -->
        <div v-if="narrative?.summary" class="ai-summary">
          <div class="ai-tag">AI 总览</div>
          <div class="ai-summary-text">{{ withCn(narrative.summary) }}</div>
        </div>
        <div v-else-if="!aiEnabled" class="ai-disabled no-print">未配置 AI（DeepSeek），仅展示数据模块、无 AI 叙述。</div>

        <!-- 模块 1 整体数据 -->
        <section id="mod-overview" class="mod">
          <h3>整体数据</h3>
          <div class="kpi-grid">
            <div v-for="kc in [
              { k: 'cost', label: '消费', fmt: fmtMoney },
              { k: 'click', label: '点击', fmt: fmtInt },
              { k: 'impression', label: '展现', fmt: fmtInt },
              { k: 'cpc', label: '平均点击成本（CPC）', fmt: fmtMoney },
              { k: 'ctr', label: '点击率（CTR）', fmt: fmtPct },
            ]" :key="kc.k" class="kpi-card">
              <div class="kpi-label">{{ kc.label }}</div>
              <div class="kpi-value">{{ kc.fmt(data.kpi[kc.k].current) }}</div>
              <div class="kpi-change" :class="(data.kpi[kc.k].change_pct ?? 0) >= 0 ? 'up' : 'down'">
                {{ fmtChange(data.kpi[kc.k].change_pct) || '上期无可比数据' }}
              </div>
            </div>
          </div>
          <div v-if="data.budget.monthly_budget" class="budget-line">
            区间消费 {{ fmtMoney(data.budget.period_cost ?? data.budget.month_cost) }}
            · 月预算参考 {{ fmtMoney(data.budget.monthly_budget) }}
            · 比例 {{ data.budget.usage_pct }}%
            <span class="bud-bar"><span class="bud-fill" :style="{ width: Math.min(100, data.budget.usage_pct || 0) + '%' }" /></span>
          </div>
          <!-- 日趋势 CSS 柱 -->
          <div class="trend">
            <div v-for="d in data.trend" :key="d.date" class="trend-col" :title="`${d.date}　消费 ${fmtMoney(d.cost)}　点击 ${d.click}`">
              <span class="trend-bar" :style="{ height: (d.cost / trendMax * 56 + 1) + 'px' }" />
            </div>
          </div>
          <div class="trend-axis"><span>{{ data.trend[0]?.date.slice(5) }}</span><span>日消费趋势</span><span>{{ data.trend[data.trend.length - 1]?.date.slice(5) }}</span></div>
          <p v-if="comment('overview')" class="mod-comment">{{ comment('overview') }}</p>
        </section>

        <!-- 模块 2 分类报告 -->
        <section id="mod-by_category" class="mod">
          <h3>分类报告（按关键词分级）</h3>
          <table class="rep-table">
            <thead><tr><th>分级</th><th>消费</th><th>占比</th><th>点击</th><th>展现</th><th>点击率</th><th>平均点击成本</th></tr></thead>
            <tbody>
              <tr v-for="c in data.by_category" :key="c.category">
                <td>{{ c.category_label }}</td><td>{{ fmtMoney(c.cost) }}</td><td>{{ c.cost_share_pct }}%</td>
                <td>{{ fmtInt(c.click) }}</td><td>{{ fmtInt(c.impression) }}</td><td>{{ fmtPct(c.ctr) }}</td><td>{{ fmtMoney(c.cpc) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="comment('by_category')" class="mod-comment">{{ comment('by_category') }}</p>
        </section>

        <!-- 模块 3 TOP10 消费词 -->
        <section id="mod-top_keywords" class="mod">
          <h3>TOP10 关键词 · 消费</h3>
          <table class="rep-table">
            <thead><tr><th>#</th><th>关键词</th><th>消费</th><th>点击</th><th>展现</th><th>点击率</th><th>均排名</th></tr></thead>
            <tbody>
              <tr v-for="(c, i) in data.top_keywords" :key="c.keyword_id">
                <td>{{ i + 1 }}</td><td>{{ c.keyword }}</td><td>{{ fmtMoney(c.cost) }}</td>
                <td>{{ fmtInt(c.click) }}</td><td>{{ fmtInt(c.impression) }}</td><td>{{ fmtPct(c.ctr) }}</td><td>{{ c.avg_rank ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="comment('top_keywords')" class="mod-comment">{{ comment('top_keywords') }}</p>
        </section>

        <!-- 模块 4 设备分布 -->
        <section id="mod-device" class="mod">
          <h3>设备分布</h3>
          <div class="device-row">
            <div v-for="d in data.device_split" :key="d.device" class="device-card">
              <div class="dev-name">{{ d.device }}</div>
              <div class="dev-share">{{ d.cost_share_pct }}%</div>
              <div class="dev-meta">消费 {{ fmtMoney(d.cost) }} · 点击率 {{ fmtPct(d.ctr) }} · 平均点击成本 {{ fmtMoney(d.cpc) }}</div>
            </div>
          </div>
          <p v-if="comment('device')" class="mod-comment">{{ comment('device') }}</p>
        </section>

        <!-- 模块 5 异常处置回顾（内部版） -->
        <section v-if="showInternal" id="mod-alerts" class="mod">
          <h3>异常处置回顾 <span class="internal-badge">内部</span></h3>
          <div class="num-cards">
            <div class="num-card"><div class="nc-num">{{ data.alerts_review.open || 0 }}</div><div class="nc-label">未处理</div></div>
            <div class="num-card success"><div class="nc-num">{{ data.alerts_review.resolved || 0 }}</div><div class="nc-label">已处理</div></div>
            <div class="num-card"><div class="nc-num">{{ data.alerts_review.merged || 0 }}</div><div class="nc-label">已归并</div></div>
          </div>
          <p v-if="comment('alerts')" class="mod-comment">{{ comment('alerts') }}</p>
        </section>

        <section v-if="showInternal" id="mod-today_focus" class="mod">
          <h3>今日执行焦点 <span class="internal-badge">内部</span></h3>
          <div class="num-cards">
            <div class="num-card work-link" @click="openWorkItem(operationalFocus.suggestions_path)"><div class="nc-num">{{ operationalFocus.pending_suggestions }}</div><div class="nc-label">待审建议 →</div></div>
            <div class="num-card warn work-link" @click="openWorkItem(operationalFocus.queue_path)"><div class="nc-num">{{ operationalFocus.pending_writebacks }}</div><div class="nc-label">待回写 →</div></div>
            <div class="num-card"><div class="nc-num">{{ operationalFocus.sync_risks.length }}</div><div class="nc-label">同步风险</div></div>
          </div>
          <div v-if="operationalFocus.sync_risks.length" class="op-levels"><button v-for="risk in operationalFocus.sync_risks" :key="risk.message" class="op-chip work-link" @click="openWorkItem(risk.path)">{{ risk.message }} →</button></div>
          <p v-else class="mod-comment">当前五层只读资产未发现明显断层。</p>
          <div v-if="operationalFocus.priority_suggestions.length" class="focus-list">
            <button v-for="item in operationalFocus.priority_suggestions" :key="item.id" class="focus-item" @click="openWorkItem(item.path)">
              <b>{{ item.priority }} · {{ item.type }} · {{ item.keyword || '账户建议' }}</b>
              <strong>{{ item.impact }}</strong><span>{{ item.reason }}</span><em>{{ item.report_date }} · 查看并处理 →</em>
              <small>负责人：{{ item.assignee_name || '未分配' }} · {{ WORK_STATUS_LABELS[item.handling_status] || item.handling_status }} · {{ fmtDeadline(item.due_at) }}</small>
            </button>
          </div>
          <button v-if="operationalFocus.pending_suggestions > operationalFocus.priority_suggestions.length" class="view-all-work work-link" @click="openWorkItem(operationalFocus.suggestions_path)">查看全部 {{ operationalFocus.pending_suggestions }} 条待审建议 →</button>
        </section>

        <!-- 模块 6 优化操作 & 后续计划 -->
        <section id="mod-operations" class="mod">
          <h3>{{ showInternal ? '优化操作 & 后续计划' : '已完成优化与效果' }}</h3>
          <div v-if="showInternal" class="num-cards">
            <div class="num-card"><div class="nc-num">{{ data.operations.total }}</div><div class="nc-label">区间操作</div></div>
            <div class="num-card warn"><div class="nc-num">{{ data.operations.over_limit }}</div><div class="nc-label">超 20% 上限</div></div>
            <div class="num-card"><div class="nc-num">{{ data.operations.ai_suggestions_adopted }}</div><div class="nc-label">AI 建议采纳</div></div>
          </div>
          <div v-else class="num-cards">
            <div class="num-card success"><div class="nc-num">{{ clientDelivery.completed_count }}</div><div class="nc-label">已确认完成</div></div>
            <div class="num-card success"><div class="nc-num">{{ clientDelivery.ready_effects }}</div><div class="nc-label">效果可展示</div></div>
            <div class="num-card"><div class="nc-num">{{ clientDelivery.observing_effects }}</div><div class="nc-label">效果观察中</div></div>
          </div>
          <div v-if="showInternal && Object.keys(data.operations.by_level).length" class="op-levels">
            <span v-for="(n, lvl) in data.operations.by_level" :key="lvl" class="op-chip">{{ lvl }} {{ n }}</span>
          </div>
          <p v-if="showInternal && comment('operations')" class="mod-comment">{{ comment('operations') }}</p>
          <div v-if="!showInternal" class="client-actions">
            <article v-for="action in clientDelivery.completed_actions" :key="action.id" class="client-action">
              <div class="client-action-head"><b>{{ action.action }} · {{ action.object }}</b><time>{{ action.time.slice(0, 16).replace('T', ' ') }}</time></div>
              <div class="client-action-evidence">{{ action.evidence }}<template v-if="action.old_value != null || action.new_value != null"> · {{ action.old_value || '—' }} → {{ action.new_value || '—' }}</template></div>
              <div v-if="action.effect?.sample?.state === 'ready'" class="effect-result">
                <span>日均消费 {{ fmtMoney(action.effect.before?.cost_per_day) }} → {{ fmtMoney(action.effect.after?.cost_per_day) }}</span>
                <span>日均点击 {{ action.effect.before?.click_per_day ?? '—' }} → {{ action.effect.after?.click_per_day ?? '—' }}</span>
                <span>点击率 {{ fmtPct(action.effect.before?.ctr) }} → {{ fmtPct(action.effect.after?.ctr) }}</span>
                <span>平均排名 {{ action.effect.before?.avg_rank ?? '—' }} → {{ action.effect.after?.avg_rank ?? '—' }}</span>
              </div>
              <div v-else-if="action.effect" class="effect-observing">效果观察中：{{ action.effect.sample?.message }}</div>
              <div v-else class="effect-confirmed">动作已由百度操作记录确认。</div>
            </article>
            <el-empty v-if="!clientDelivery.completed_actions.length" description="本区间暂无可确认的已完成优化动作" />
          </div>
          <div v-if="showInternal && narrative?.next_period_plan?.length" class="plan">
            <div class="plan-title">后续优化计划</div>
            <ol><li v-for="(p, i) in narrative.next_period_plan" :key="i">{{ withCn(p) }}</li></ol>
          </div>
        </section>

        <!-- 待接入模块占位 -->
        <section v-if="showInternal" id="mod-pending" class="mod">
          <h3>待接入模块</h3>
          <div class="pending-grid">
            <div class="pending-card">转化报告（TOP 转化词 / CPL）<span>待 M2 爱番番线索</span></div>
            <div class="pending-card">时段数据<span>时段绩效报告未同步</span></div>
            <div class="pending-card">地域数据<span>地域绩效报告未同步</span></div>
            <div v-if="showInternal" class="pending-card">竞品监控 <span>无数据源 · 内部人工补充</span></div>
          </div>
        </section>

        <div class="rm-foot">
          <span v-if="report.generated_at">AI 叙述生成于 {{ formatUtcTimestamp(report.generated_at) }} · 模型 deepseek-chat</span>
          <span v-else>仅数据模块（未生成 AI 叙述）</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 14px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }
.tb-actions { display: flex; gap: 8px; align-items: center; justify-content: flex-end; flex-wrap: wrap; }
.dropdown-mark { margin-left: 6px; font-size: 11px; color: #909399; }
.quick-range-buttons { display: flex; gap: 6px; align-items: center; }
.quick-range-buttons button {
  height: 32px;
  padding: 0 10px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #fff;
  color: #606266;
  cursor: pointer;
  font-size: 12px;
}
.work-link { cursor: pointer; }
.focus-list { display: grid; gap: 7px; margin-top: 12px; }
.focus-item { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 3px 14px; padding: 9px 11px; border: 1px solid var(--sem-border); border-radius: 6px; background: #fff; text-align: left; cursor: pointer; }
.focus-item b { color: var(--sem-text); font-size: 12px; }
.focus-item strong { grid-column: 1; color: #b15f00; font-size: 11px; }
.focus-item span { grid-column: 1; color: var(--sem-text-sub); font-size: 11px; }
.focus-item small { grid-column: 1; color: #667085; font-size: 10px; }
.focus-item em { grid-column: 2; grid-row: 1 / span 4; align-self: center; color: var(--sem-primary); font-size: 10px; font-style: normal; }
.view-all-work { margin-top: 10px; border: 0; background: transparent; color: var(--sem-primary); font-size: 12px; }
.client-actions { display: grid; gap: 9px; margin-top: 12px; }
.client-action { padding: 11px 12px; border: 1px solid var(--sem-border); border-radius: 7px; background: #fff; }
.client-action-head { display: flex; justify-content: space-between; gap: 12px; color: var(--sem-text); font-size: 12px; }
.client-action-head time { color: var(--sem-text-sub); font-size: 10px; white-space: nowrap; }
.client-action-evidence { margin-top: 4px; color: #287a55; font-size: 10px; }
.effect-result { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 5px 12px; margin-top: 8px; padding: 8px; border-radius: 5px; background: #f0f8f4; color: #315f4b; font-size: 10px; }
.effect-observing { margin-top: 8px; padding: 7px 8px; border-radius: 5px; background: #fff8e6; color: #8a5a00; font-size: 10px; }
.effect-confirmed { margin-top: 8px; color: var(--sem-text-sub); font-size: 10px; }
.quick-range-buttons button:hover { border-color: var(--sem-primary); color: var(--sem-primary); }
.quick-range-buttons button.active { border-color: var(--sem-primary); background: var(--sem-primary); color: #fff; }

.report-layout { display: flex; gap: 16px; align-items: flex-start; }
.toc { width: 150px; flex-shrink: 0; background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 12px; position: sticky; top: 12px; }
.toc-title { font-size: 12px; font-weight: 600; color: var(--sem-text-sub); margin-bottom: 8px; }
.toc-item { font-size: 13px; color: var(--sem-text); padding: 6px 8px; border-radius: 6px; cursor: pointer; }
.toc-item:hover { background: #f4f8fd; color: var(--sem-primary); }

.report-main { flex: 1; background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 28px 32px; min-width: 0; }
.rm-head { border-bottom: 2px solid var(--sem-primary); padding-bottom: 14px; margin-bottom: 18px; }
.rm-title { font-size: 19px; font-weight: 700; color: var(--sem-text); }
.rm-sub { font-size: 12px; color: var(--sem-text-sub); margin-top: 6px; }
.ver-tag { margin-left: 8px; font-size: 11px; padding: 1px 7px; border-radius: 4px; background: #fef1e1; color: #ba7517; }
.ver-tag.client { background: #e5f4ed; color: #1d9e75; }

.ai-summary { background: linear-gradient(135deg, #f4f8fd 0%, #eef6ff 100%); border-left: 3px solid var(--sem-primary); border-radius: 6px; padding: 14px 16px; margin-bottom: 22px; }
.ai-tag { font-size: 11px; font-weight: 700; color: var(--sem-primary); margin-bottom: 6px; }
.ai-summary-text { font-size: 13px; line-height: 1.8; color: var(--sem-text); white-space: pre-wrap; }
.ai-disabled { font-size: 12px; color: #9ca3af; padding: 8px 0; margin-bottom: 12px; }

.mod { margin-bottom: 26px; }
.mod h3 { font-size: 15px; font-weight: 600; color: var(--sem-text); margin: 0 0 12px; padding-left: 9px; border-left: 3px solid var(--sem-primary); }
.internal-badge, .num-card.warn .nc-num { color: #ba7517; }
.internal-badge { font-size: 10px; background: #fef1e1; color: #ba7517; padding: 1px 6px; border-radius: 4px; font-weight: 400; }
.mod-comment { font-size: 12.5px; line-height: 1.75; color: #4b5563; background: #fafbfc; border-radius: 6px; padding: 10px 12px; margin: 12px 0 0; }

.kpi-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
.kpi-card { border: 1px solid var(--sem-border); border-radius: 8px; padding: 12px; text-align: center; }
.kpi-label { font-size: 12px; color: var(--sem-text-sub); }
.kpi-value { font-size: 18px; font-weight: 700; color: var(--sem-text); margin: 5px 0; font-variant-numeric: tabular-nums; }
.kpi-change { font-size: 11px; }
.kpi-change.up { color: #e24b4a; }
.kpi-change.down { color: #1d9e75; }

.budget-line { font-size: 12px; color: var(--sem-text-sub); margin-top: 14px; display: flex; align-items: center; gap: 10px; }
.bud-bar { flex: 1; max-width: 240px; height: 8px; background: #f3f4f6; border-radius: 4px; overflow: hidden; }
.bud-fill { display: block; height: 100%; background: linear-gradient(90deg, #1d9e75, #185fa5); }

.trend { display: flex; align-items: flex-end; gap: 3px; height: 60px; margin-top: 16px; padding: 0 2px; }
.trend-col { flex: 1; display: flex; align-items: flex-end; justify-content: center; height: 100%; }
.trend-bar { width: 70%; max-width: 22px; min-width: 2px; background: linear-gradient(180deg, #2c7cc8, #185fa5); border-radius: 2px 2px 0 0; display: block; }
.trend-axis { display: flex; justify-content: space-between; font-size: 10px; color: #9ca3af; margin-top: 4px; }

.rep-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.rep-table th { text-align: left; color: var(--sem-text-sub); font-weight: 500; padding: 7px 8px; border-bottom: 1px solid var(--sem-border); background: #fafbfc; }
.rep-table td { padding: 7px 8px; border-bottom: 1px solid #f3f4f6; font-variant-numeric: tabular-nums; }

.device-row { display: flex; gap: 12px; }
.device-card { flex: 1; border: 1px solid var(--sem-border); border-radius: 8px; padding: 14px; }
.dev-name { font-size: 13px; font-weight: 600; color: var(--sem-text); }
.dev-share { font-size: 22px; font-weight: 700; color: var(--sem-primary); margin: 4px 0; }
.dev-meta { font-size: 11px; color: var(--sem-text-sub); }

.num-cards { display: flex; gap: 12px; }
.num-card { flex: 1; border: 1px solid var(--sem-border); border-radius: 8px; padding: 14px; text-align: center; }
.num-card.success { background: #f3faf6; }
.num-card.warn { background: #fdf6e3; }
.nc-num { font-size: 22px; font-weight: 700; color: var(--sem-text); }
.num-card.success .nc-num { color: #1d9e75; }
.nc-label { font-size: 11px; color: var(--sem-text-sub); margin-top: 3px; }
.op-levels { margin-top: 12px; display: flex; gap: 6px; }
.op-chip { font-size: 11px; background: #eff4fb; color: var(--sem-primary); padding: 2px 9px; border-radius: 10px; }

.plan { margin-top: 16px; background: #f4f8fd; border-radius: 8px; padding: 14px 16px; }
.plan-title { font-size: 13px; font-weight: 600; color: var(--sem-primary); margin-bottom: 8px; }
.plan ol { margin: 0; padding-left: 20px; }
.plan li { font-size: 12.5px; line-height: 1.9; color: var(--sem-text); }

.pending-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.pending-card { border: 1px dashed var(--sem-border); border-radius: 8px; padding: 12px 14px; font-size: 12.5px; color: #9ca3af; }
.pending-card span { display: block; font-size: 11px; margin-top: 3px; }

.rm-foot { margin-top: 24px; padding-top: 12px; border-top: 1px solid var(--sem-border); font-size: 11px; color: #9ca3af; text-align: right; }

@media print {
  .no-print { display: none !important; }
  .report-main { border: none; padding: 0; }
  .report-layout { display: block; }
  .mod { page-break-inside: avoid; }
}
</style>
