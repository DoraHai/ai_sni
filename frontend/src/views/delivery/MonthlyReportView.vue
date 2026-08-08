<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { analysisReportExportUrl, fetchAnalysisReport } from '../../api/reports'
import { session } from '../../store/session'

const TENANT_ID = computed(() => session.tenantId)

const loading = ref(false)
const regenerating = ref(false)
const exporting = ref('')
const error = ref('')
const report = ref(null)
const pad = (n) => String(n).padStart(2, '0')
const isoOf = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
function currentMonthRange(now = new Date()) {
  return [`${now.getFullYear()}-${pad(now.getMonth() + 1)}-01`, isoOf(now)]
}
const dateRange = ref(currentMonthRange())
// 绑定单客户的账号（品牌方客户）锁定客户版；无绑定（内部团队）默认内部版可切
const version = ref(session.user?.tenant_id ? 'client' : 'internal')
const versionLocked = computed(() => !!session.user?.tenant_id)

const fmtMoney = (v) => (v == null ? '—' : '¥ ' + Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 }))
const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))
const fmtPct = (v) => (v == null ? '—' : (v * 100).toFixed(2) + '%')
const fmtChange = (v) => (v == null ? '' : (v >= 0 ? '↑' : '↓') + Math.abs(v) + '%')

const data = computed(() => report.value?.data || null)
const narrative = computed(() => report.value?.narrative || null)

// AI 叙述里裸写的英文缩写补中文全称（如 CPC → CPC（平均点击成本））。
// 显示时展开，对历史缓存文案也即时生效；已带（中文）或字母串内的不重复加。
const CN_TERMS = { OCPC: '目标转化出价', CPC: '平均点击成本', CTR: '点击率', CPL: '线索成本', CPM: '千次展现成本', ROI: '投资回报' }
const ABBR_RE = /(?<![A-Za-z（(])(OCPC|CPC|CTR|CPL|CPM|ROI)(?![A-Za-z（(])/g
function withCn(text) {
  return text ? String(text).replace(ABBR_RE, (m) => `${m}（${CN_TERMS[m]}）`) : text
}

const comment = (key) => withCn(narrative.value?.module_comments?.[key] || '')
const aiEnabled = computed(() => report.value?.ai_enabled === true)

// 内部版才显示的模块（异常处置回顾 / 竞品占位）
const showInternal = computed(() => version.value === 'internal')

async function load(force = false) {
  if (!dateRange.value?.[0] || !dateRange.value?.[1]) return
  force ? (regenerating.value = true) : (loading.value = true)
  error.value = ''
  try {
    report.value = await fetchAnalysisReport({
      tenantId: TENANT_ID.value,
      startDate: dateRange.value[0],
      endDate: dateRange.value[1],
      force,
    })
    if (force) ElMessage.success('AI 报告已重新生成')
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
    regenerating.value = false
  }
}

watch(dateRange, () => load())

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

async function exportReport(format) {
  if (!dateRange.value?.[0] || !dateRange.value?.[1] || exporting.value) return
  exporting.value = format
  try {
    const resp = await fetch(analysisReportExportUrl({
      tenantId: TENANT_ID.value,
      startDate: dateRange.value[0],
      endDate: dateRange.value[1],
      format,
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
    ElMessage.error(e.message)
  } finally {
    exporting.value = ''
  }
}

watch(TENANT_ID, () => load())

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
  items.push({ key: 'operations', label: '优化操作 & 后续计划' })
  items.push({ key: 'pending', label: '待接入模块' })
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
              <el-dropdown-item command="xls">Excel 表格</el-dropdown-item>
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

        <!-- 模块 6 优化操作 & 后续计划 -->
        <section id="mod-operations" class="mod">
          <h3>优化操作 & 后续计划</h3>
          <div class="num-cards">
            <div class="num-card"><div class="nc-num">{{ data.operations.total }}</div><div class="nc-label">区间操作</div></div>
            <div class="num-card warn"><div class="nc-num">{{ data.operations.over_limit }}</div><div class="nc-label">超 20% 上限</div></div>
            <div class="num-card"><div class="nc-num">{{ data.operations.ai_suggestions_adopted }}</div><div class="nc-label">AI 建议采纳</div></div>
          </div>
          <div v-if="Object.keys(data.operations.by_level).length" class="op-levels">
            <span v-for="(n, lvl) in data.operations.by_level" :key="lvl" class="op-chip">{{ lvl }} {{ n }}</span>
          </div>
          <p v-if="comment('operations')" class="mod-comment">{{ comment('operations') }}</p>
          <div v-if="narrative?.next_period_plan?.length" class="plan">
            <div class="plan-title">后续优化计划</div>
            <ol><li v-for="(p, i) in narrative.next_period_plan" :key="i">{{ withCn(p) }}</li></ol>
          </div>
        </section>

        <!-- 待接入模块占位 -->
        <section id="mod-pending" class="mod">
          <h3>待接入模块</h3>
          <div class="pending-grid">
            <div class="pending-card">转化报告（TOP 转化词 / CPL）<span>待 M2 爱番番线索</span></div>
            <div class="pending-card">时段数据<span>时段绩效报告未同步</span></div>
            <div class="pending-card">地域数据<span>地域绩效报告未同步</span></div>
            <div v-if="showInternal" class="pending-card">竞品监控 <span>无数据源 · 内部人工补充</span></div>
          </div>
        </section>

        <div class="rm-foot">
          <span v-if="report.generated_at">AI 叙述生成于 {{ report.generated_at.slice(0, 16).replace('T', ' ') }} · 模型 deepseek-chat</span>
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
