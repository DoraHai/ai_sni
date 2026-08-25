<script setup>
import { onMounted, onBeforeUnmount, ref, computed, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { init, use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { fetchDashboardToday, fetchDashboardInsight } from '../../api/dashboard'
import { session } from '../../store/session'
import MetricLabel from '../../components/MetricLabel.vue'
import { ElMessage } from 'element-plus'
import { DataAnalysis } from '@element-plus/icons-vue'

const router = useRouter()
use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const TENANT_ID = computed(() => session.tenantId) // 当前客户，顶栏切换器驱动

const loading = ref(false)
const error = ref('')
const data = ref(null)
const insight = ref(null)
const pad = (n) => String(n).padStart(2, '0')
const isoOf = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
function todayRange(now = new Date()) {
  const today = isoOf(now)
  return [today, today]
}
const quickOptions = [
  {
    key: 'today',
    label: '今日',
    range: () => {
      const t = isoOf(new Date())
      return [t, t]
    },
  },
  {
    key: 'yesterday',
    label: '昨日',
    range: () => {
      const y = new Date()
      y.setDate(y.getDate() - 1)
      const d = isoOf(y)
      return [d, d]
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
  {
    key: 'last30',
    label: '最近30天',
    range: () => {
      const end = new Date()
      const start = new Date()
      start.setDate(end.getDate() - 29)
      return [isoOf(start), isoOf(end)]
    },
  },
]
const dateRange = ref(todayRange())
const activeQuickKey = ref('today')
const trendChartEl = ref(null)
let trendChart = null
let autoRefreshTimer = null
let lastTodayEmptyNoticeKey = ''
let loadVersion = 0
const AUTO_REFRESH_MS = 5 * 60 * 1000
const handleResize = () => trendChart?.resize()

const fmtMoney = (v) => (v == null ? '—' : '¥ ' + Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 }))
const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))
const fmtPct = (v) => (v == null ? '—' : (v * 100).toFixed(2) + '%')
const periodDataIncomplete = computed(() => data.value?.freshness?.requested_data_complete === false)
const connectionAlert = computed(() => {
  const connection = data.value?.connection
  if (!connection || connection.state === 'ready') {
    if (!periodDataIncomplete.value) return null
    return {
      type: 'warning',
      title: `所选区间数据尚未同步完整，最新可用数据截至 ${data.value?.freshness?.latest_report_date || '—'}。缺失日期不计为 0 消费或下降。`,
    }
  }
  const severe = ['not_connected', 'sync_failed'].includes(connection.state)
  const counts = connection.asset_counts || {}
  return {
    type: severe ? 'error' : 'warning',
    title: `${connection.message}。当前资产：计划 ${counts.campaigns || 0}、单元 ${counts.adgroups || 0}、关键词 ${counts.keywords || 0}、搜索词 ${counts.search_terms || 0}。`,
  }
})

// ===== 顶部工具栏：媒体 + 自定义日期区间 =====
const media = ref('baidu')
function onMediaChange(v) {
  if (v === 'bing') {
    ElMessage.warning('必应广告即将开放，预计 2026 Q3')
    media.value = 'baidu'
  }
}

function onGenerateReport() {
  router.push('/delivery/report')
}

function applyQuickRange(opt) {
  activeQuickKey.value = opt.key
  dateRange.value = opt.range()
}

function syncQuickKey() {
  const matched = quickOptions.find((opt) => {
    const [s, e] = opt.range()
    return dateRange.value?.[0] === s && dateRange.value?.[1] === e
  })
  activeQuickKey.value = matched ? matched.key : ''
}

const kpiCards = computed(() => {
  if (!data.value) return []
  const k = data.value.kpi
  return [
    { label: '消费', metric: 'cost', value: fmtMoney(k.cost.current), change: k.cost.change_pct, prev: '上期 ' + fmtMoney(k.cost.previous), goodWhenDown: false },
    { label: '点击', metric: 'click', value: fmtInt(k.click.current), change: k.click.change_pct, prev: '上期 ' + fmtInt(k.click.previous), goodWhenDown: false },
    { label: '展现', metric: 'impression', value: fmtInt(k.impression.current), change: k.impression.change_pct, prev: '上期 ' + fmtInt(k.impression.previous), goodWhenDown: false },
    { label: '线索', metric: 'lead', value: fmtInt(data.value.lead?.current ?? 0), change: data.value.lead?.change_pct ?? null, prev: '上期 ' + fmtInt(data.value.lead?.previous ?? 0), goodWhenDown: false },
    { label: '平均点击成本（CPC）', metric: 'cpc', value: fmtMoney(k.cpc.current), change: k.cpc.change_pct, prev: '上期 ' + fmtMoney(k.cpc.previous), goodWhenDown: true },
    { label: '线索成本（CPL）', metric: 'cpl', value: data.value.cpl?.current == null ? '—' : fmtMoney(data.value.cpl.current), change: data.value.cpl?.change_pct ?? null, prev: '上期 ' + (data.value.cpl?.previous == null ? '—' : fmtMoney(data.value.cpl.previous)), goodWhenDown: true },
  ]
})

function deltaClass(card) {
  if (card.change == null) return 'neutral'
  // 此处颜色表达数值方向，而非业务优劣：上升绿、下降红、持平灰。
  if (card.change > 0) return 'up'
  if (card.change < 0) return 'down'
  return 'neutral'
}

function deltaText(card) {
  if (periodDataIncomplete.value) return '数据未同步'
  if (card.change == null) return '—'
  return (card.change >= 0 ? '↑ ' : '↓ ') + Math.abs(card.change).toFixed(1) + '%'
}

// 看板顶部异常卡：只展示有未处理告警的优先级（原型 alert-strip）
const alertCards = computed(() => {
  const counts = data.value?.alert_counts || {}
  const meta = {
    P0: { label: 'P0 最高紧急 · 待处理', cls: 'p0' },
    P1: { label: 'P1 立即执行 · 待处理', cls: 'p1' },
    P2: { label: 'P2 本周处理', cls: 'p2' },
    P3: { label: 'P3 观察', cls: 'p3' },
    P4: { label: 'P4 低', cls: 'p3' },
    P5: { label: 'P5 提示', cls: 'p3' },
  }
  return Object.entries(meta)
    .filter(([p]) => counts[p] > 0)
    .map(([p, m]) => ({ priority: p, count: counts[p], ...m }))
})

const campaignMax = computed(() => {
  const list = data.value?.top_campaigns || []
  return list.length ? list[0].cost : 1
})

const DEVICE_META = {
  计算机: { icon: '💻', cls: 'device-pc' },
  移动: { icon: '📱', cls: 'device-mobile' },
}

function renderTrend() {
  if (!trendChartEl.value || !data.value) return
  if (!trendChart) trendChart = init(trendChartEl.value)
  const trend = data.value.trend || data.value.trend_7d || []
  trendChart.setOption({
    grid: { left: 56, right: 40, top: 30, bottom: 28 },
    tooltip: { trigger: 'axis' },
    legend: { data: ['消费', '点击'], top: 0 },
    xAxis: { type: 'category', data: trend.map((t) => t.date.slice(5)) },
    yAxis: [
      { type: 'value', name: '消费（¥）', axisLabel: { formatter: '¥{value}' } },
      { type: 'value', name: '点击', splitLine: { show: false } },
    ],
    series: [
      {
        name: '消费', type: 'line', smooth: true, data: trend.map((t) => t.cost),
        itemStyle: { color: '#E86F1C' },
        lineStyle: { width: 3 },
        areaStyle: { color: 'rgba(232, 111, 28, 0.16)' },
      },
      {
        name: '点击', type: 'line', smooth: true, yAxisIndex: 1, data: trend.map((t) => t.click),
        itemStyle: { color: '#159B78' }, lineStyle: { type: 'dashed', width: 2 },
      },
    ],
  })
}

function isAllZero(d) {
  const kpi = d?.kpi
  if (!kpi) return true
  return !kpi.cost?.current && !kpi.click?.current && !kpi.impression?.current
}

async function load() {
  const version = ++loadVersion
  const tenantId = TENANT_ID.value
  if (!tenantId) return
  loading.value = true
  error.value = ''
  try {
    const [d, ins] = await Promise.all([
      fetchDashboardToday({
        tenantId,
        startDate: dateRange.value?.[0],
        endDate: dateRange.value?.[1],
      }),
      fetchDashboardInsight({
        tenantId,
        targetDate: dateRange.value?.[1],
      }).catch(() => null),
    ])
    if (version !== loadVersion || tenantId !== TENANT_ID.value) return
    data.value = d
    insight.value = ins
    const noticeKey = dateRange.value?.join(':') || ''
    if (activeQuickKey.value === 'today' && isAllZero(d) && lastTodayEmptyNoticeKey !== noticeKey) {
      ElMessage.info('今日数据尚未同步（数据通常在次日凌晨更新），可切换到"昨日"查看最新完整数据')
      lastTodayEmptyNoticeKey = noticeKey
    } else if (activeQuickKey.value !== 'today' || !isAllZero(d)) {
      lastTodayEmptyNoticeKey = ''
    }
    await nextTick()
    renderTrend()
  } catch (e) {
    if (version !== loadVersion || tenantId !== TENANT_ID.value) return
    error.value = e.code === 'PERMISSION_DENIED'
      ? '当前账号无权查看该客户看板'
      : '看板数据暂时无法加载，请稍后重试'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

async function manualRefresh() {
  await load()
  if (!error.value) ElMessage.success('看板数据已刷新')
}

watch(dateRange, () => {
  syncQuickKey()
  load()
})
// 顶栏切换客户后重新拉数
watch(TENANT_ID, load)

onMounted(() => {
  load()
  window.addEventListener('resize', handleResize)
  autoRefreshTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible' && !loading.value) load()
  }, AUTO_REFRESH_MS)
})

onBeforeUnmount(() => {
  if (autoRefreshTimer) window.clearInterval(autoRefreshTimer)
  window.removeEventListener('resize', handleResize)
  trendChart?.dispose()
  trendChart = null
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">数据看板</div>
        <div v-if="data" class="page-desc">
          {{ data.tenant.name }} · {{ data.period.start_date }} ~ {{ data.period.end_date }}（{{ data.period.days }} 天）
        </div>
      </div>
      <div class="dash-toolbar">
        <div class="media-filter">
          <span class="media-label">媒体</span>
          <el-select v-model="media" @change="onMediaChange" style="width: 132px">
            <el-option label="百度推广" value="baidu" />
            <el-option label="必应（即将开放）" value="bing" disabled />
          </el-select>
        </div>
        <div class="date-quick-options">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            range-separator="至"
            unlink-panels
            :clearable="false"
            aria-label="选择看板日期区间"
            style="width: 268px"
          />
          <div class="quick-btns">
            <button
              v-for="opt in quickOptions"
              :key="opt.key"
              class="quick-btn"
              :class="{ active: activeQuickKey === opt.key }"
              @click="applyQuickRange(opt)"
            >
              {{ opt.label }}
            </button>
          </div>
        </div>
        <span
          v-if="data?.freshness?.last_synced_at"
          class="freshness"
          :title="`完整同步时间：${data.freshness.last_synced_at}`"
        >
          <i class="freshness-dot" aria-hidden="true"></i>
          数据截至 {{ data.freshness.latest_report_date?.slice(5) || '—' }}
          · {{ data.freshness.last_synced_at.slice(11, 16) }} 更新
          · 每 {{ data.freshness.sync_interval_minutes }} 分钟
        </span>
        <el-button :loading="loading" aria-label="立即刷新数据看板" @click="manualRefresh">立即刷新</el-button>
        <el-button type="primary" @click="onGenerateReport">生成完整报告</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />
    <el-alert
      v-if="connectionAlert"
      :title="connectionAlert.title"
      :type="connectionAlert.type"
      :closable="false"
      show-icon
      class="data-state-alert"
    />

    <div v-if="insight?.enabled" class="ai-insight">
      <div class="aii-head">
        <span class="aii-icon">💡</span>
        <span class="aii-title">AI 每日洞察</span>
        <span class="aii-date">{{ insight.insight_date }}</span>
      </div>
      <div class="aii-summary">{{ insight.summary }}</div>
      <div class="aii-cols">
        <div v-if="insight.detail.highlights?.length" class="aii-block">
          <div class="aii-label">关键发现</div>
          <ul><li v-for="(h, i) in insight.detail.highlights" :key="i">{{ h }}</li></ul>
        </div>
        <div v-if="insight.detail.actions?.length" class="aii-block">
          <div class="aii-label">建议动作</div>
          <ul><li v-for="(a, i) in insight.detail.actions" :key="i">{{ a }}</li></ul>
        </div>
      </div>
      <div v-if="insight.detail.fluctuations?.length" class="aii-block aii-flux">
        <div class="aii-label">波动归因（百度官方）</div>
        <ul>
          <template v-for="(e, i) in insight.detail.fluctuations" :key="i">
            <li v-for="(f, j) in e.factors" :key="j">
              <span class="aii-flux-tag">{{ e.campaign }} · {{ e.dimension }}</span>
              {{ f.reason }}
              <span v-if="f.top_keywords?.length" class="aii-flux-kw">（{{ f.top_keywords.join('、') }}）</span>
            </li>
          </template>
        </ul>
      </div>
    </div>

    <template v-if="data">
      <!-- 账户实时状态 -->
      <el-alert
        v-if="data.account.status === 'error'"
        :title="data.account.message"
        type="warning"
        :closable="false"
        style="margin-bottom: 14px"
      />
      <div v-else class="panel account-panel">
        <span>百度账户：<b>{{ data.account.baidu_username }}</b></span>
        <span>余额 <b class="num">{{ fmtMoney(data.account.balance) }}</b></span>
        <span>累计消费 <b class="num">{{ fmtMoney(data.account.cost_total) }}</b></span>
        <span>日预算 <b class="num">{{ fmtMoney(data.account.daily_budget) }}</b></span>
        <span class="sub">授权到期 {{ data.account.token_expires_at?.slice(0, 10) }}</span>
      </div>

      <!-- 异常快捷条（原型 alert-strip） -->
      <div v-if="alertCards.length" class="alert-strip">
        <div
          v-for="c in alertCards"
          :key="c.priority"
          class="alert-card"
          :class="c.cls"
          @click="router.push('/monitor/alerts')"
        >
          <span class="alert-num">{{ c.count }}</span>
          <span class="alert-info">
            <span class="alert-title">{{ c.label }}</span>
            <span class="alert-label">点击进入异常提醒处理</span>
          </span>
          <span class="alert-arrow">→</span>
        </div>
      </div>

      <!-- KPI 六卡 -->
      <div class="kpi-grid">
        <div v-for="c in kpiCards" :key="c.label" class="kpi-card">
          <div class="kpi-label">
            <MetricLabel :label="c.label" :metric="c.metric" />
            <span v-if="c.pending" class="kpi-tip">M2</span>
          </div>
          <div class="kpi-value" :class="{ pending: c.pending }">{{ c.value }}</div>
          <div class="kpi-cmp">
            <span class="kpi-delta" :class="deltaClass(c)">{{ deltaText(c) }}</span>
            <span class="kpi-vs">{{ c.prev }}</span>
          </div>
        </div>
      </div>

      <!-- 趋势 + 预算/设备 -->
      <div class="row-2col">
        <div class="panel">
          <div class="panel-head">
            <span class="panel-title">消费与点击趋势<span class="panel-sub">{{ data.period.days }} 天 · {{ data.period.start_date }} 至 {{ data.period.end_date }}</span></span>
          </div>
          <div ref="trendChartEl" style="height: 280px" />
        </div>

        <div class="col-stack">
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title"><MetricLabel label="月预算耗用" metric="budget_usage" /><span class="panel-sub">{{ data.period.end_date.slice(0, 7) }} 月</span></span>
            </div>
            <template v-if="data.budget.monthly_budget">
              <div class="plan-bar-bg budget-bar">
                <div
                  class="plan-bar-fill"
                  :class="{ bad: data.budget.usage_pct > 90, warn: data.budget.usage_pct > 75 && data.budget.usage_pct <= 90 }"
                  :style="{ width: Math.min(data.budget.usage_pct, 100) + '%' }"
                />
              </div>
              <div class="budget-line">
                <b class="num">{{ fmtMoney(data.budget.month_cost) }}</b> / {{ fmtMoney(data.budget.monthly_budget) }}
                <span class="budget-pct" :class="{ bad: data.budget.usage_pct > 90 }">{{ data.budget.usage_pct }}%</span>
              </div>
            </template>
            <div v-else class="empty-line">未设置月预算</div>
          </div>

          <div class="panel">
            <div class="panel-head">
              <span class="panel-title">设备维度<span class="panel-sub">按消费占比</span></span>
            </div>
            <div class="device-row">
              <div v-for="d in data.device_split" :key="d.device" class="device-card">
                <div class="device-head">
                  <span class="device-icon" :class="DEVICE_META[d.device]?.cls || 'device-pc'">{{ DEVICE_META[d.device]?.icon || '🖥' }}</span>
                  <div>
                    <div class="device-name">{{ d.device }}</div>
                    <div class="device-share"><MetricLabel label="消费占比" metric="device_share" /> {{ d.cost_share_pct }}%</div>
                  </div>
                </div>
                <div class="device-stats">
                  <div><div class="device-stat-label">消费</div><div class="device-stat-value">{{ fmtMoney(d.cost) }}</div></div>
                  <div><div class="device-stat-label">点击</div><div class="device-stat-value">{{ fmtInt(d.click) }}</div></div>
                  <div><div class="device-stat-label"><MetricLabel label="点击成本（CPC）" metric="cpc" /></div><div class="device-stat-value">{{ fmtMoney(d.cpc) }}</div></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 计划消费分布（原型 plan-bar-row） -->
      <div class="panel" style="margin-top: 14px">
        <div class="panel-head">
          <span class="panel-title plan-section-title">
            <span class="section-title-icon" aria-hidden="true"><DataAnalysis /></span>
            <span>计划消费分布</span><span class="panel-sub">前 6 · 按消费降序</span>
          </span>
        </div>
        <div v-for="row in data.top_campaigns" :key="row.campaign_name" class="plan-bar-row">
          <div>
            <div class="plan-name">{{ row.campaign_name }}</div>
            <div class="plan-product">点击 {{ fmtInt(row.click) }} · 点击成本（CPC）{{ fmtMoney(row.cpc) }} · 点击率（CTR）{{ fmtPct(row.ctr) }}</div>
          </div>
          <div class="plan-amount">{{ fmtMoney(row.cost) }}</div>
          <div class="plan-bar-bg">
            <div class="plan-bar-fill" :style="{ width: Math.round((row.cost / campaignMax) * 100) + '%' }" />
          </div>
          <div class="plan-pct">{{ Math.round((row.cost / campaignMax) * 100) }}%</div>
        </div>
        <div v-if="!data.top_campaigns?.length" class="empty-line">该时段没有计划消费数据</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; display: flex; justify-content: space-between; align-items: flex-end; }
.data-state-alert { margin-bottom: 14px; }
.dash-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.media-filter { display: flex; align-items: center; gap: 4px; padding: 2px 6px 2px 10px; background: #f3f4f6; border-radius: 6px; }
.media-label { font-size: 12px; color: #606266; white-space: nowrap; }
.media-filter :deep(.el-select .el-input__wrapper) { box-shadow: none; background: transparent; padding-left: 4px; }
.date-quick-options { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.quick-btns { display: flex; align-items: center; gap: 6px; }
.quick-btn {
  height: 30px; padding: 0 10px; border: 1px solid var(--sem-border); border-radius: 6px;
  background: #fff; color: var(--sem-text-sub); font-size: 12px; cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.quick-btn:hover { border-color: var(--sem-primary); color: var(--sem-primary); }
.quick-btn.active { background: var(--sem-primary); border-color: var(--sem-primary); color: #fff; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }
.num { font-variant-numeric: tabular-nums; }

/* 通用面板（原型 panel） */
.panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 16px 18px; }
.panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.panel-title { font-size: 14px; font-weight: 600; color: var(--sem-text); }
.panel-sub { font-size: 11px; color: #9ca3af; margin-left: 8px; font-weight: 400; }

.account-panel { display: flex; gap: 24px; font-size: 13px; align-items: center; margin-bottom: 14px; padding: 13px 18px; }
.account-panel .sub { color: var(--sem-text-sub); margin-left: auto; font-size: 12px; }

/* 异常快捷条（原型 alert-strip / alert-card） */
.alert-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 14px; }
.alert-card {
  background: #fff; border: 1px solid var(--sem-border); border-radius: 8px;
  padding: 14px 16px; display: flex; align-items: center; gap: 14px;
  cursor: pointer; transition: all 0.15s;
}
.alert-card:hover { border-color: var(--sem-primary); box-shadow: 0 2px 8px rgba(24, 95, 165, 0.06); }
.alert-card.p0 { border-left: 4px solid var(--sem-danger); background: linear-gradient(90deg, #fef6f6 0%, #fff 30%); }
.alert-card.p1 { border-left: 4px solid var(--sem-danger); }
.alert-card.p2 { border-left: 4px solid #ba7517; }
.alert-card.p3 { border-left: 4px solid #9ca3af; }
.alert-num { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1; }
.p0 .alert-num, .p1 .alert-num { color: var(--sem-danger); }
.p2 .alert-num { color: #ba7517; }
.p3 .alert-num { color: var(--sem-text-sub); }
.alert-info { display: flex; flex-direction: column; gap: 3px; }
.alert-title { font-size: 13px; font-weight: 600; color: var(--sem-text); }
.alert-label { font-size: 11px; color: var(--sem-text-sub); }
.alert-arrow { margin-left: auto; color: #9ca3af; }

/* KPI 卡（原型 kpi-card） */
.kpi-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 14px; }
@media (max-width: 1280px) { .kpi-grid { grid-template-columns: repeat(3, 1fr); } }
.kpi-card { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 14px 16px; }
.kpi-label { font-size: 11px; color: var(--sem-text-sub); display: flex; align-items: center; gap: 4px; }
.kpi-tip { font-size: 9px; padding: 1px 6px; background: #f3f4f6; color: var(--sem-text-sub); border-radius: 3px; }
.kpi-value { font-size: 22px; font-weight: 700; color: var(--sem-text); margin-top: 8px; font-variant-numeric: tabular-nums; }
.kpi-value.pending { color: #9ca3af; font-size: 16px; }
.kpi-cmp { font-size: 11px; margin-top: 6px; display: flex; align-items: center; gap: 6px; }
.kpi-delta { font-weight: 600; }
.kpi-delta.up { color: var(--sem-success); }
.kpi-delta.down { color: var(--sem-danger); }
.kpi-delta.neutral { color: var(--sem-text-sub); }
.kpi-vs { color: #9ca3af; }

.row-2col { display: grid; grid-template-columns: 2fr 1fr; gap: 14px; }
@media (max-width: 1100px) { .row-2col { grid-template-columns: 1fr; } }
.col-stack { display: flex; flex-direction: column; gap: 14px; }

/* 预算条（复用原型 plan-bar） */
.budget-bar { margin-top: 4px; }
.budget-line { font-size: 13px; margin-top: 10px; color: var(--sem-text-sub); display: flex; align-items: center; gap: 6px; }
.budget-line b { color: var(--sem-text); }
.budget-pct { margin-left: auto; font-weight: 600; color: var(--sem-primary); font-variant-numeric: tabular-nums; }
.budget-pct.bad { color: var(--sem-danger); }
.empty-line { font-size: 12px; color: #9ca3af; padding: 14px 0; text-align: center; }

/* 设备维度（原型 device-card） */
.device-row { display: flex; flex-direction: column; gap: 10px; }
.device-card { background: #fafbfc; border-radius: 6px; padding: 12px 14px; }
.device-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.device-icon {
  width: 28px; height: 28px; border-radius: 6px; display: flex;
  align-items: center; justify-content: center; font-size: 13px;
}
.device-pc { background: #fff0e4; box-shadow: inset 0 0 0 1px rgba(232, 111, 28, 0.12); }
.device-mobile { background: #e5f4ed; box-shadow: inset 0 0 0 1px rgba(29, 158, 117, 0.1); }
.device-name { font-size: 13px; font-weight: 600; color: var(--sem-text); }
.device-share { font-size: 11px; color: var(--sem-text-sub); margin-top: 1px; }
.device-stats { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; font-size: 11px; }
.device-stat-label { color: var(--sem-text-sub); }
.device-stat-value { color: var(--sem-text); font-weight: 600; font-variant-numeric: tabular-nums; margin-top: 2px; }

/* 计划消费分布（原型 plan-bar-row） */
.plan-bar-row {
  display: grid; grid-template-columns: 1fr 90px 1fr 56px; gap: 12px;
  padding: 10px 0; align-items: center; font-size: 12px; border-bottom: 1px solid #f3f4f6;
}
.plan-section-title { display: inline-flex; align-items: center; }
.section-title-icon {
  width: 20px; height: 20px; margin-right: 7px; border-radius: 5px;
  display: inline-flex; align-items: center; justify-content: center;
  background: #fff0e4; color: #d86a1c;
}
.section-title-icon :deep(svg) { width: 13px; height: 13px; }
.plan-bar-row:last-child { border-bottom: none; }
.plan-name { color: var(--sem-text); font-weight: 500; }
.plan-product { font-size: 10px; color: #9ca3af; margin-top: 2px; }
.plan-bar-bg { height: 8px; background: #f3f4f6; border-radius: 4px; overflow: hidden; }
.plan-bar-fill { height: 100%; background: linear-gradient(90deg, #e86f1c 0%, #f5a344 100%); border-radius: 4px; }
.plan-bar-fill.bad { background: linear-gradient(90deg, #e24b4a 0%, #ee7472 100%); }
.plan-bar-fill.warn { background: linear-gradient(90deg, #ba7517 0%, #dc9a47 100%); }
.plan-amount { color: var(--sem-text); font-weight: 600; font-variant-numeric: tabular-nums; text-align: right; }
.plan-pct { color: #9ca3af; text-align: right; font-variant-numeric: tabular-nums; }
.ai-insight { margin-bottom: 14px; padding: 14px 18px; background: linear-gradient(135deg, #f0f7ff, #f7faff); border: 1px solid #d4e6fb; border-radius: 10px; }
.freshness {
  display: inline-flex; align-items: center; gap: 5px; white-space: nowrap;
  padding: 6px 9px; border: 1px solid #dce9e3; border-radius: 999px;
  background: #f4faf7; color: #47705e; font-size: 11px; line-height: 1;
  font-variant-numeric: tabular-nums;
}
.freshness-dot {
  width: 6px; height: 6px; border-radius: 50%; background: var(--sem-success);
  box-shadow: 0 0 0 3px rgba(29, 158, 117, 0.12);
}
.aii-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.aii-icon { font-size: 16px; }
.aii-title { font-size: 15px; font-weight: 600; color: #185fa5; }
.aii-date { font-size: 12px; color: #909399; }
.aii-summary { font-size: 14px; color: #1f2937; line-height: 1.6; margin-bottom: 10px; }
.aii-cols { display: flex; gap: 24px; flex-wrap: wrap; }
.aii-block { flex: 1; min-width: 240px; }
.aii-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.aii-block ul { margin: 0; padding-left: 18px; }
.aii-block li { font-size: 13px; color: #5a5e66; line-height: 1.7; }
.aii-flux { margin-top: 10px; }
.aii-flux-tag { display: inline-block; padding: 0 6px; margin-right: 4px; font-size: 12px; color: #185fa5; background: #e8f1fb; border-radius: 4px; }
.aii-flux-kw { color: #909399; }
</style>
