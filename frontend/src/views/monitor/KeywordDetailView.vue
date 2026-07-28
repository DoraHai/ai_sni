<script setup>
import { onMounted, ref, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { fetchKeywordDetail, updateKeywordCategory } from '../../api/keywords'
import { resolveAlert } from '../../api/alerts'
import { session } from '../../store/session'
import MetricLabel from '../../components/MetricLabel.vue'

const route = useRoute()
const router = useRouter()

const TENANT_ID = computed(() => session.tenantId) // 当前客户，顶栏切换器驱动

const loading = ref(false)
const error = ref('')
const data = ref(null)
// 首次加载不传日期，由后端锚定该词最近有数据的日期；加载后回填到选择器
const dateRange = ref(null)
const rankChartEl = ref(null)
const trendChartEl = ref(null)
const bidChartEl = ref(null)
const scheduleChartEl = ref(null)
const scheduleHourChartEl = ref(null)
const scheduleMetric = ref('impression')
let rankChart = null
let trendChart = null
let bidChart = null
let scheduleChart = null
let scheduleHourChart = null

const hasBidTrend = computed(() => (data.value?.bid_trend?.length || 0) > 0)
const hasPlacementAnalysis = computed(() => !!(data.value?.region_analysis || data.value?.schedule_analysis))
const regionRows = computed(() => data.value?.region_analysis?.rows || [])

const SCHEDULE_METRICS = {
  impression: {
    label: '展现', accent: '#185fa5', colors: ['#eef3f8', '#d7e7f5', '#80b2d7', '#185fa5'],
  },
  click: {
    label: '点击', accent: '#1d9e75', colors: ['#eef4f2', '#d8eee8', '#78c5ad', '#1d9e75'],
  },
  cost: {
    label: '消费', accent: '#ba7517', colors: ['#f6f2eb', '#f3dfbd', '#dfa855', '#ba7517'],
  },
}

const scheduleMetricMeta = computed(() => SCHEDULE_METRICS[scheduleMetric.value])
const scheduleCells = computed(() => data.value?.schedule_analysis?.cells || [])
const scheduleMetricTotal = computed(() => (
  data.value?.schedule_analysis?.totals?.[scheduleMetric.value] || 0
))
const scheduleMetricPeak = computed(() => Math.max(
  ...scheduleCells.value.map((cell) => Number(cell[scheduleMetric.value] || 0)),
  0,
))
const scheduleTopSlots = computed(() => {
  const peak = scheduleMetricPeak.value || 1
  return scheduleCells.value
    .filter((cell) => Number(cell[scheduleMetric.value] || 0) > 0)
    .sort((a, b) => Number(b[scheduleMetric.value] || 0) - Number(a[scheduleMetric.value] || 0))
    .slice(0, 4)
    .map((cell) => ({
      ...cell,
      ratio: Math.max(6, Math.round((Number(cell[scheduleMetric.value] || 0) / peak) * 100)),
    }))
})

// 统计区间快捷选项，锚定该词最近有数据的日期（不是 today，数据可能更早结束）
const pickerShortcuts = computed(() => {
  const first = data.value?.keyword?.first_date
  const last = data.value?.keyword?.last_date
  if (!last) return []
  const d = (s) => new Date(s + 'T00:00:00')
  const lastD = d(last)
  const minus = (n) => { const x = new Date(lastD); x.setDate(x.getDate() - n); return x }
  const out = []
  if (first) out.push({ text: '全部历史', value: [d(first), lastD] })
  out.push({ text: '近 7 天', value: [minus(6), lastD] })
  out.push({ text: '近 30 天', value: [minus(29), lastD] })
  out.push({ text: '本月', value: [new Date(lastD.getFullYear(), lastD.getMonth(), 1), lastD] })
  out.push({
    text: '上月',
    value: [
      new Date(lastD.getFullYear(), lastD.getMonth() - 1, 1),
      new Date(lastD.getFullYear(), lastD.getMonth(), 0),
    ],
  })
  return out
})

const fromAlerts = route.query.from === 'alerts'
const fromWorkbench = route.query.from === 'workbench'
const fromAdjustments = route.query.from === 'adjustments'

const fmtMoney = (v) => (v == null ? '—' : '¥ ' + Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 }))
const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))
const fmtPct = (v) => (v == null ? '—' : (v * 100).toFixed(2) + '%')
const fmtMetric = (v) => (typeof v === 'number' ? v.toLocaleString('zh-CN') : v)
const fmtScheduleMetric = (v, metric = scheduleMetric.value) => (
  metric === 'cost' ? fmtMoney(v) : fmtInt(v)
)
const scheduleSlotLabel = (cell) => (
  `${cell.weekday_label || `周${cell.weekday}`} ${String(cell.hour).padStart(2, '0')}:00-${String(cell.hour + 1).padStart(2, '0')}:00`
)

const PRIORITY_META = {
  P0: { label: 'P0 最高紧急', type: 'danger' },
  P1: { label: 'P1 立即执行', type: 'danger' },
  P2: { label: 'P2 本周处理', type: 'warning' },
  P3: { label: 'P3 观察', type: 'info' },
  P4: { label: 'P4 低', type: 'info' },
  P5: { label: 'P5 提示', type: 'info' },
}

const STATUS_META = {
  open: { label: '未处理', type: 'danger' },
  resolved: { label: '已处理', type: 'success' },
  merged: { label: '已归并', type: 'info' },
}

// 5 类分级展示。后端返回 {code,label,source}，code 为空表示未分级
const CATEGORY_META = {
  brand: { type: 'danger' },
  focus: { type: 'primary' },
  longtail: { type: 'warning' },
  new: { type: 'info' },
  normal: { type: 'success' },
}
const CATEGORY_OPTIONS = [
  { code: 'brand', label: '品牌词' },
  { code: 'focus', label: '重点词' },
  { code: 'normal', label: '一般词' },
  { code: 'longtail', label: '长尾精准词' },
  { code: 'new', label: '新词' },
  { code: 'auto', label: '恢复自动分级' },
]

const isBrand = computed(() => data.value?.keyword.category?.code === 'brand')

// 倍数阈值：> 3 橙色提示，> 4 红色预警（业务规则）
const multiplierClass = computed(() => {
  const m = data.value?.bid_coefficients?.effective?.max_multiplier
  if (m == null) return ''
  if (m > 4) return 'danger'
  if (m > 3) return 'warn'
  return ''
})

async function onChangeCategory(code) {
  try {
    await updateKeywordCategory({
      keywordId: route.params.keywordId,
      tenantId: TENANT_ID.value,
      category: code,
    })
    ElMessage.success(code === 'auto' ? '已恢复自动分级' : '分级已更新')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const kpiCards = computed(() => {
  if (!data.value) return []
  const k = data.value.kpi
  return [
    { label: '消费', metric: 'cost', value: fmtMoney(k.cost.current), change: k.cost.change_pct, prev: '上期 ' + fmtMoney(k.cost.previous), goodWhenDown: false },
    { label: '点击', metric: 'click', value: fmtInt(k.click.current), change: k.click.change_pct, prev: '上期 ' + fmtInt(k.click.previous), goodWhenDown: false },
    { label: '展现', metric: 'impression', value: fmtInt(k.impression.current), change: k.impression.change_pct, prev: '上期 ' + fmtInt(k.impression.previous), goodWhenDown: false },
    { label: '点击成本（CPC）', metric: 'cpc', value: fmtMoney(k.cpc.current), change: k.cpc.change_pct, prev: '上期 ' + fmtMoney(k.cpc.previous), goodWhenDown: true },
    { label: '点击率（CTR）', metric: 'ctr', value: fmtPct(k.ctr.current), change: k.ctr.change_pct, prev: '上期 ' + fmtPct(k.ctr.previous), goodWhenDown: false },
    { label: '平均排名', metric: 'avg_rank', value: k.avg_rank.current ?? '—', change: k.avg_rank.change_pct, prev: '上期 ' + (k.avg_rank.previous ?? '—'), goodWhenDown: true },
    { label: '转化（电话点击）', metric: 'conversions', value: fmtInt(k.conversions?.current ?? 0), change: k.conversions?.change_pct ?? null, prev: '上期 ' + fmtInt(k.conversions?.previous ?? 0), goodWhenDown: false },
    { label: '转化成本', metric: 'conv_cost', value: k.conv_cost?.current == null ? '—' : fmtMoney(k.conv_cost.current), change: k.conv_cost?.change_pct ?? null, prev: '上期 ' + (k.conv_cost?.previous == null ? '—' : fmtMoney(k.conv_cost.previous)), goodWhenDown: true },
  ]
})

function deltaClass(card) {
  if (card.change == null) return 'neutral'
  const up = card.change >= 0
  return (card.goodWhenDown ? !up : up) ? 'good' : 'bad'
}

function deltaText(card) {
  if (card.change == null) return '—'
  return (card.change >= 0 ? '↑ ' : '↓ ') + Math.abs(card.change).toFixed(1) + '%'
}

function renderRank() {
  if (!rankChartEl.value || !data.value) return
  if (!rankChart) rankChart = echarts.init(rankChartEl.value)
  const trend = data.value.trend
  rankChart.setOption({
    grid: { left: 44, right: 24, top: 30, bottom: 28 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: trend.map((t) => t.date.slice(5)) },
    // 排名数值越小越靠前，反转 Y 轴让"靠前"在视觉上方
    yAxis: { type: 'value', inverse: true, min: 1, name: '平均排名' },
    series: [
      {
        name: '平均排名',
        type: 'line',
        smooth: true,
        connectNulls: true,
        data: trend.map((t) => t.avg_rank),
        itemStyle: { color: '#185FA5' },
        ...(isBrand.value && {
          markLine: {
            symbol: 'none',
            lineStyle: { color: '#E24B4A', type: 'dashed' },
            label: { formatter: '品牌词阈值 1.5', position: 'insideEndTop', color: '#E24B4A' },
            data: [{ yAxis: 1.5 }],
          },
        }),
      },
    ],
  })
}

function renderTrend() {
  if (!trendChartEl.value || !data.value) return
  if (!trendChart) trendChart = echarts.init(trendChartEl.value)
  const trend = data.value.trend
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
        itemStyle: { color: '#185FA5' },
        areaStyle: { opacity: 0.12 },
      },
      {
        name: '点击', type: 'line', smooth: true, yAxisIndex: 1, data: trend.map((t) => t.click),
        itemStyle: { color: '#1D9E75' }, lineStyle: { type: 'dashed' },
      },
    ],
  })
}

function renderBid() {
  if (!bidChartEl.value || !data.value || !hasBidTrend.value) return
  if (!bidChart) bidChart = echarts.init(bidChartEl.value)
  const bt = data.value.bid_trend
  bidChart.setOption({
    grid: { left: 52, right: 24, top: 30, bottom: 28 },
    tooltip: { trigger: 'axis', valueFormatter: (v) => (v == null ? '—' : '¥ ' + Number(v).toFixed(2)) },
    xAxis: { type: 'category', data: bt.map((t) => t.date.slice(5)) },
    yAxis: { type: 'value', name: '出价（¥）', axisLabel: { formatter: '¥{value}' }, scale: true },
    series: [
      {
        name: '出价',
        type: 'line',
        // 出价是阶梯式变化（改一次保持到下次），step 更真实
        step: 'end',
        symbol: 'circle',
        symbolSize: 5,
        data: bt.map((t) => t.bid),
        itemStyle: { color: '#BA7517' },
        areaStyle: { opacity: 0.1 },
      },
    ],
  })
}

function renderSchedule() {
  if (!scheduleChartEl.value || !data.value?.schedule_analysis) return
  if (!scheduleChart) scheduleChart = echarts.init(scheduleChartEl.value)
  const rawCells = data.value.schedule_analysis.cells || []
  const metric = scheduleMetric.value
  const metricMeta = SCHEDULE_METRICS[metric]
  const hours = Array.from({ length: 24 }, (_, i) => `${i}`)
  const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
  const cellMap = new Map(rawCells.map((cell) => [`${cell.weekday}-${cell.hour}`, cell]))
  const cells = []
  for (let weekday = 1; weekday <= 7; weekday += 1) {
    for (let hour = 0; hour < 24; hour += 1) {
      cells.push(cellMap.get(`${weekday}-${hour}`) || {
        weekday,
        hour,
        active: false,
        impression: 0,
        click: 0,
        cost: 0,
        ctr: null,
        cpc: null,
      })
    }
  }
  const heatData = cells.map((cell) => [
    cell.hour,
    cell.weekday - 1,
    Number(cell[metric] || 0),
    cell.impression || 0,
    cell.click || 0,
    cell.cost || 0,
    cell.ctr,
    cell.cpc,
  ])
  const max = Math.max(...cells.map((cell) => Number(cell[metric] || 0)), 1)
  scheduleChart.setOption({
    grid: { left: 44, right: 10, top: 6, bottom: 28, containLabel: true },
    tooltip: {
      formatter: (p) => {
        const [hour, weekdayIdx, , impression, click, cost, ctr, cpc] = p.data
        const range = `${String(hour).padStart(2, '0')}:00-${String(hour + 1).padStart(2, '0')}:00`
        if (!impression && !click && !cost) return `${weekdays[weekdayIdx]} ${range}<br/>无投放数据`
        return [
          `${weekdays[weekdayIdx]} ${range}`,
          `展现：${fmtInt(impression)}`,
          `点击：${fmtInt(click)}`,
          `消费：${fmtMoney(cost)}`,
          `CTR：${fmtPct(ctr)}`,
          `CPC：${fmtMoney(cpc)}`,
        ].join('<br/>')
      },
    },
    xAxis: {
      type: 'category',
      data: hours,
      axisTick: { show: false },
      axisLabel: { color: '#8a96a8', interval: 1 },
    },
    yAxis: {
      type: 'category',
      data: weekdays,
      axisTick: { show: false },
      axisLabel: { color: '#6b7280' },
    },
    visualMap: {
      min: 0,
      max,
      dimension: 2,
      show: false,
      inRange: { color: metricMeta.colors },
    },
    series: [{
      type: 'heatmap',
      data: heatData,
      itemStyle: {
        borderColor: '#fff',
        borderWidth: 2,
        borderRadius: 3,
      },
      emphasis: {
        itemStyle: { shadowBlur: 8, shadowColor: 'rgba(24, 95, 165, 0.2)' },
      },
    }],
  })
}

function renderScheduleHourly() {
  if (!scheduleHourChartEl.value || !data.value?.schedule_analysis) return
  if (!scheduleHourChart) scheduleHourChart = echarts.init(scheduleHourChartEl.value)
  const metric = scheduleMetric.value
  const metricMeta = SCHEDULE_METRICS[metric]
  const hourly = Array.from({ length: 24 }, (_, hour) => ({
    hour,
    impression: 0,
    click: 0,
    cost: 0,
  }))
  for (const cell of data.value.schedule_analysis.cells || []) {
    const bucket = hourly[Number(cell.hour)]
    if (!bucket) continue
    bucket.impression += Number(cell.impression || 0)
    bucket.click += Number(cell.click || 0)
    bucket.cost += Number(cell.cost || 0)
  }
  scheduleHourChart.setOption({
    grid: { left: 38, right: 8, top: 10, bottom: 24, containLabel: true },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const item = params?.[0]
        const hour = Number(item?.axisValue || 0)
        return `${String(hour).padStart(2, '0')}:00-${String(hour + 1).padStart(2, '0')}:00<br/>${metricMeta.label}：${fmtScheduleMetric(item?.value || 0, metric)}`
      },
    },
    xAxis: {
      type: 'category',
      data: hourly.map((item) => item.hour),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#dce4ed' } },
      axisLabel: { color: '#8a96a8', interval: 2, fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      splitNumber: 3,
      axisLabel: { color: '#9aa4b2', fontSize: 10 },
      splitLine: { lineStyle: { color: '#eef2f6' } },
    },
    series: [{
      name: metricMeta.label,
      type: 'bar',
      data: hourly.map((item) => Number(item[metric] || 0)),
      barMaxWidth: 14,
      itemStyle: { color: metricMeta.accent, borderRadius: [3, 3, 0, 0], opacity: 0.88 },
      emphasis: { itemStyle: { opacity: 1 } },
    }],
  })
}

async function onScheduleMetricChange() {
  await nextTick()
  renderSchedule()
  renderScheduleHourly()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchKeywordDetail({
      keywordId: route.params.keywordId,
      tenantId: TENANT_ID.value,
      startDate: dateRange.value?.[0],
      endDate: dateRange.value?.[1],
    })
    dateRange.value = [data.value.period.start_date, data.value.period.end_date]
    await nextTick()
    renderRank()
    renderTrend()
    renderBid()
    renderSchedule()
    renderScheduleHourly()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function onResolve(row) {
  try {
    await resolveAlert(row.id)
    ElMessage.success('已标记为已处理')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(() => {
  load()
  window.addEventListener('resize', () => {
    rankChart?.resize()
    trendChart?.resize()
    bidChart?.resize()
    scheduleChart?.resize()
    scheduleHourChart?.resize()
  })
})
</script>

<template>
  <div v-loading="loading">
    <!-- 入口溯源 -->
    <el-alert
      v-if="fromAlerts"
      type="warning"
      :closable="false"
      style="margin-bottom: 14px"
    >
      <template #title>
        由异常提醒下钻进入 ·
        <el-link type="warning" underline="never" @click="router.push('/monitor/alerts')">← 返回异常提醒</el-link>
      </template>
    </el-alert>
    <el-alert
      v-if="fromWorkbench"
      type="info"
      :closable="false"
      style="margin-bottom: 14px"
    >
      <template #title>
        由关键词工作台下钻进入 ·
        <el-link type="primary" underline="never" @click="router.back()">← 返回工作台</el-link>
      </template>
    </el-alert>
    <el-alert
      v-if="fromAdjustments"
      type="info"
      :closable="false"
      style="margin-bottom: 14px"
    >
      <template #title>
        由调价台账下钻进入 ·
        <el-link type="primary" underline="never" @click="router.back()">← 返回调价台账</el-link>
      </template>
    </el-alert>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />

    <template v-if="data">
      <!-- 页头 -->
      <div class="head-row">
        <div>
          <span class="page-title">关键词「{{ data.keyword.keyword || data.keyword.keyword_id }}」</span>
          <el-tag
            v-if="data.keyword.category?.label"
            :type="CATEGORY_META[data.keyword.category.code]?.type || 'info'"
            size="small"
            effect="plain"
            style="margin-left: 8px"
          >{{ data.keyword.category.label }}<template v-if="data.keyword.category.source === 'manual'">（人工）</template></el-tag>
          <el-tag v-else size="small" type="info" effect="plain" style="margin-left: 8px">未分级</el-tag>
          <el-tag v-if="data.keyword.pause === true" size="small" type="info" style="margin-left: 4px">已暂停</el-tag>
          <el-dropdown trigger="click" style="margin-left: 8px" @command="onChangeCategory">
            <el-button size="small" link type="primary">编辑分级 ▾</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="o in CATEGORY_OPTIONS" :key="o.code" :command="o.code">
                  {{ o.label }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <div class="kw-path">
            所属 计划「{{ data.keyword.campaign_name || '—' }}」 / 单元「{{ data.keyword.adgroup_name || '—' }}」
            · 数据区间 {{ data.keyword.first_date }} ~ {{ data.keyword.last_date }}（有数据 {{ data.keyword.active_days }} 天）
          </div>
        </div>
        <div class="period-picker">
          <span class="pp-label">统计区间</span>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="~"
            start-placeholder="开始"
            end-placeholder="结束"
            :clearable="false"
            :shortcuts="pickerShortcuts"
            unlink-panels
            :prefix-icon="null"
            style="width: 250px"
            @change="load"
          />
        </div>
      </div>

      <!-- 基础信息条 -->
      <el-card shadow="never" class="info-strip">
        <div class="info-item">
          <div class="il-label">当前出价</div>
          <div class="il-value">{{ fmtMoney(data.latest.bid) }}</div>
        </div>
        <div class="info-item">
          <div class="il-label">质量度</div>
          <div class="il-value">
            <el-tooltip placement="bottom">
              <template #content>
                <div v-for="(d, name) in data.latest.quality_detail" :key="name">
                  {{ name }}：{{ d.label || '—' }}
                </div>
              </template>
              <span>{{ data.latest.quality ?? '—' }}</span>
            </el-tooltip>
          </div>
        </div>
        <div class="info-item">
          <div class="il-label">匹配方式</div>
          <div class="il-value">{{ data.keyword.match_type_label || data.keyword.match_type || '—' }}</div>
        </div>
        <div class="info-item">
          <div class="il-label">平均排名（最近有数日）</div>
          <div class="il-value" :class="{ danger: isBrand && data.latest.avg_rank > 1.5 }">
            {{ data.latest.avg_rank ?? '—' }}
          </div>
        </div>
        <div class="info-item">
          <div class="il-label">时段点击</div>
          <div class="il-value">{{ fmtInt(data.kpi.click.current) }}</div>
        </div>
        <div class="info-item">
          <div class="il-label">数据截至</div>
          <div class="il-value">{{ data.latest.report_date }}</div>
        </div>
      </el-card>

      <!-- 出价系数叠加 -->
      <el-card v-if="data.bid_coefficients" shadow="never" class="coef-card">
        <template #header>
          出价系数叠加
          <span class="card-sub">所属计划「{{ data.bid_coefficients.campaign_name }}」 · 实际生效 = 各层系数累乘<template v-if="data.bid_coefficients.missing_layers.length"> · {{ data.bid_coefficients.missing_layers.join('、') }}未接入按 1.0 计</template></span>
        </template>
        <div class="coef-flow">
          <div class="coef-box">
            <div class="coef-label">关键词出价</div>
            <div class="coef-value">{{ fmtMoney(data.bid_coefficients.base_price) }}</div>
            <div class="coef-meta">基础值</div>
          </div>
          <span class="coef-op">×</span>
          <div
            v-if="data.bid_coefficients.ranking_strategy?.enabled"
            class="coef-box"
            :class="{ warn: data.bid_coefficients.ranking_strategy.factor_cap > 1 }"
          >
            <div class="coef-label">优化排名策略系数</div>
            <div class="coef-value">≤ {{ data.bid_coefficients.ranking_strategy.factor_cap }}</div>
            <div class="coef-meta">
              策略「{{ data.bid_coefficients.ranking_strategy.strategy_name }}」 · 目标{{ data.bid_coefficients.ranking_strategy.target_rank_label }} · 抢不到才加价
            </div>
          </div>
          <div v-else class="coef-box">
            <div class="coef-label">优化排名策略系数</div>
            <div class="coef-value">1.0</div>
            <div class="coef-meta">该计划未绑定优化排名策略</div>
          </div>
          <span class="coef-op">×</span>
          <div class="coef-box" :class="{ warn: data.bid_coefficients.schedule.current_factor > 1 }">
            <div class="coef-label">分时段系数</div>
            <div class="coef-value">
              {{ data.bid_coefficients.schedule.current_factor ?? '不投放' }}
            </div>
            <div class="coef-meta">
              当前 {{ data.bid_coefficients.schedule.current_slot }} · 全周区间 {{ data.bid_coefficients.schedule.min }}~{{ data.bid_coefficients.schedule.max }}
            </div>
          </div>
          <span class="coef-op">×</span>
          <div class="coef-box" :class="{ warn: data.bid_coefficients.region.max > 1 }">
            <div class="coef-label">分地域系数</div>
            <div class="coef-value">{{ data.bid_coefficients.region.min }}~{{ data.bid_coefficients.region.max }}</div>
            <div class="coef-meta">{{ data.bid_coefficients.region.entries }} 个地域 · 因地而异</div>
          </div>
          <span class="coef-op">×</span>
          <div
            v-if="data.bid_coefficients.mobile?.ratio != null"
            class="coef-box"
            :class="{ warn: data.bid_coefficients.mobile.ratio > 1 }"
          >
            <div class="coef-label">移动比例</div>
            <div class="coef-value">{{ data.bid_coefficients.mobile.ratio }}</div>
            <div class="coef-meta">
              <template v-if="data.bid_coefficients.mobile.ratio === 0">移动端不投放（仅计算机计划）</template>
              <template v-else>{{ data.bid_coefficients.mobile.source === 'adgroup' ? '单元级覆盖' : '计划级' }} · 仅作用于移动流量</template>
            </div>
          </div>
          <div v-else class="coef-box">
            <div class="coef-label">移动比例</div>
            <div class="coef-value">1.0</div>
            <div class="coef-meta">数据未同步 · 按 1.0 计</div>
          </div>
          <span class="coef-op">=</span>
          <div v-if="data.bid_coefficients.effective" class="coef-box result" :class="multiplierClass">
            <div class="coef-label">实际生效出价（估算）</div>
            <div class="coef-value">
              <template v-if="data.bid_coefficients.effective.current_min === data.bid_coefficients.effective.current_max">
                {{ fmtMoney(data.bid_coefficients.effective.current_min) }}
              </template>
              <template v-else>
                {{ fmtMoney(data.bid_coefficients.effective.current_min) }} ~ {{ fmtMoney(data.bid_coefficients.effective.current_max) }}
              </template>
            </div>
            <div class="coef-meta">基础 × {{ data.bid_coefficients.effective.max_multiplier }}</div>
          </div>
          <div v-else class="coef-box">
            <div class="coef-label">实际生效出价</div>
            <div class="coef-value">—</div>
            <div class="coef-meta">当前时段不投放</div>
          </div>
        </div>
        <div v-if="data.bid_coefficients.effective?.max_multiplier > 3" class="coef-warn-line" :class="{ danger: data.bid_coefficients.effective.max_multiplier > 4 }">
          实际生效已达基础出价的 <b>{{ data.bid_coefficients.effective.max_multiplier }} 倍</b>（阈值 &gt; 3 提示，&gt; 4 预警），调价前注意系数放大效应。
        </div>
      </el-card>

      <!-- 地域 / 时段效果分析 -->
      <div v-if="hasPlacementAnalysis" class="analysis-grid">
        <el-card shadow="never" class="analysis-card region-card">
          <template #header>
            地域数据分析
            <span class="card-sub">按地域拆分展现 / 点击 / 消费</span>
          </template>
          <template v-if="data.region_analysis">
            <div class="analysis-summary">
              <div>
                <div class="analysis-title">{{ data.region_analysis.summary }}</div>
                <div class="analysis-note">按当前统计区间聚合，地域字段来自百度关键词地域报告。</div>
              </div>
              <div class="factor-pill">
                <span>点击</span>
                <b>{{ fmtInt(data.region_analysis.totals?.click || 0) }}</b>
              </div>
            </div>
            <el-table
              v-if="data.region_analysis.rows?.length"
              :data="regionRows"
              size="small"
              class="analysis-table region-table"
              :max-height="520"
            >
              <el-table-column label="地域" min-width="130">
                <template #default="{ row }">
                  <div class="region-name">{{ row.region_name }}</div>
                  <div class="region-id">{{ row.region_level === 'province' ? '省份' : '城市' }}</div>
                </template>
              </el-table-column>
              <el-table-column prop="impression" label="展现" width="100" align="right" :formatter="(_, __, v) => fmtInt(v)" />
              <el-table-column prop="click" label="点击" width="90" align="right" :formatter="(_, __, v) => fmtInt(v)" />
              <el-table-column label="消费" width="110" align="right">
                <template #default="{ row }">{{ fmtMoney(row.cost) }}</template>
              </el-table-column>
              <el-table-column label="CTR" width="90" align="right">
                <template #default="{ row }">{{ fmtPct(row.ctr) }}</template>
              </el-table-column>
            </el-table>
            <div v-else class="empty-compact">暂无地域维度效果数据。</div>
          </template>
        </el-card>

        <el-card shadow="never" class="analysis-card schedule-card">
          <template #header>
            <div class="schedule-card-head">
              <div>
                时间段分析
                <span class="card-sub">按星期 / 小时拆分效果</span>
              </div>
              <el-radio-group v-model="scheduleMetric" size="small" class="metric-switch" @change="onScheduleMetricChange">
                <el-radio-button label="impression">展现</el-radio-button>
                <el-radio-button label="click">点击</el-radio-button>
                <el-radio-button label="cost">消费</el-radio-button>
              </el-radio-group>
            </div>
          </template>
          <template v-if="data.schedule_analysis">
            <div class="analysis-summary">
              <div>
                <div class="analysis-title">{{ data.schedule_analysis.summary }}</div>
                <div class="analysis-note">
                  有展现 {{ data.schedule_analysis.active_hours }} / {{ data.schedule_analysis.total_hours }} 个星期小时
                  · 消费 {{ fmtMoney(data.schedule_analysis.totals?.cost || 0) }}
                </div>
              </div>
              <div class="factor-pill">
                <span>{{ scheduleMetricMeta.label }}峰值</span>
                <b>{{ fmtScheduleMetric(scheduleMetricPeak) }}</b>
              </div>
            </div>
            <div class="schedule-chart-shell">
              <div class="chart-section-head">
                <div>
                  <b>星期 × 小时</b>
                  <span>颜色越深，{{ scheduleMetricMeta.label }}越高</span>
                </div>
                <strong :style="{ color: scheduleMetricMeta.accent }">
                  合计 {{ fmtScheduleMetric(scheduleMetricTotal) }}
                </strong>
              </div>
              <div ref="scheduleChartEl" class="schedule-heatmap" />
              <div class="heatmap-legend">
                <span>低</span>
                <i :style="{ background: `linear-gradient(90deg, ${scheduleMetricMeta.colors.join(', ')})` }"></i>
                <span>高</span>
              </div>
            </div>
            <div class="schedule-breakdown">
              <section class="hourly-panel">
                <div class="subpanel-head">
                  <div>
                    <b>全天小时分布</b>
                    <span>汇总一周内相同小时的数据</span>
                  </div>
                </div>
                <div ref="scheduleHourChartEl" class="schedule-hour-chart" />
              </section>
              <section class="top-slots-panel">
                <div class="subpanel-head">
                  <div>
                    <b>高效时段</b>
                    <span>按{{ scheduleMetricMeta.label }}从高到低</span>
                  </div>
                </div>
                <div v-if="scheduleTopSlots.length" class="slot-list">
                  <div v-for="(slot, index) in scheduleTopSlots" :key="`${slot.weekday}-${slot.hour}`" class="slot-row">
                    <span class="slot-rank">{{ index + 1 }}</span>
                    <div class="slot-content">
                      <div class="slot-line">
                        <span>{{ scheduleSlotLabel(slot) }}</span>
                        <b>{{ fmtScheduleMetric(slot[scheduleMetric]) }}</b>
                      </div>
                      <div class="slot-bar">
                        <i :style="{ width: `${slot.ratio}%`, background: scheduleMetricMeta.accent }"></i>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-else class="slot-empty">当前指标暂无数据</div>
              </section>
            </div>
          </template>
        </el-card>
      </div>

      <!-- KPI 六卡（含环比） -->
      <div class="kpi-grid">
        <el-card v-for="c in kpiCards" :key="c.label" shadow="never" class="kpi-card">
          <div class="kpi-label"><MetricLabel :label="c.label" :metric="c.metric" /></div>
          <div class="kpi-value">{{ c.value }}</div>
          <div class="kpi-cmp">
            <span class="kpi-delta" :class="deltaClass(c)">{{ deltaText(c) }}</span>
            <span class="kpi-prev">{{ c.prev }}</span>
          </div>
        </el-card>
      </div>

      <!-- 排名走势 + 消费点击趋势 -->
      <div class="row-2col">
        <el-card shadow="never">
          <template #header>
            平均排名走势<span v-if="isBrand" class="card-sub">（品牌词要求稳定首位，超过 1.5 触发 P0）</span>
          </template>
          <div ref="rankChartEl" style="height: 260px" />
        </el-card>
        <el-card shadow="never">
          <template #header>消费与点击趋势</template>
          <div ref="trendChartEl" style="height: 260px" />
        </el-card>
      </div>

      <!-- 历史出价趋势（从该词首次有数据以来，阶梯式出价变化） -->
      <el-card v-if="hasBidTrend" shadow="never" style="margin-top: 14px">
        <template #header>
          历史出价趋势<span class="card-sub">（{{ data.keyword.first_date }} 起 · 来自每日报告出价，阶梯线表示出价维持到下次调整）</span>
        </template>
        <div ref="bidChartEl" style="height: 240px" />
      </el-card>

      <!-- 设备维度 -->
      <el-card shadow="never" style="margin-top: 14px">
        <template #header>设备维度</template>
        <el-table :data="data.device_split" size="small">
          <el-table-column prop="device" label="设备" width="100" />
          <el-table-column label="消费" width="120" align="right">
            <template #default="{ row }">{{ fmtMoney(row.cost) }}</template>
          </el-table-column>
          <el-table-column label="点击" width="100" align="right">
            <template #default="{ row }">{{ fmtInt(row.click) }}</template>
          </el-table-column>
          <el-table-column label="展现" width="100" align="right">
            <template #default="{ row }">{{ fmtInt(row.impression) }}</template>
          </el-table-column>
          <el-table-column width="110" align="right">
            <template #header><MetricLabel label="点击成本（CPC）" metric="cpc" /></template>
            <template #default="{ row }">{{ fmtMoney(row.cpc) }}</template>
          </el-table-column>
          <el-table-column width="110" align="right">
            <template #header><MetricLabel label="点击率（CTR）" metric="ctr" /></template>
            <template #default="{ row }">{{ fmtPct(row.ctr) }}</template>
          </el-table-column>
          <el-table-column label="平均排名" align="right">
            <template #default="{ row }">{{ row.avg_rank ?? '—' }}</template>
          </el-table-column>
          <template #empty>
            <el-empty description="时段内没有投放数据" :image-size="48" />
          </template>
        </el-table>
      </el-card>

      <!-- 关联告警 -->
      <el-card shadow="never" style="margin-top: 14px">
        <template #header>关联告警（最近 20 条，未处理优先）</template>
        <el-table :data="data.alerts" size="small">
          <el-table-column label="优先级" width="110">
            <template #default="{ row }">
              <el-tag :type="PRIORITY_META[row.priority]?.type || 'info'" size="small">
                {{ PRIORITY_META[row.priority]?.label || row.priority }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="告警内容" min-width="320">
            <template #default="{ row }">
              <div class="alert-title">{{ row.title }}</div>
              <div class="alert-message">{{ row.message }}</div>
            </template>
          </el-table-column>
          <el-table-column label="关键指标" min-width="150">
            <template #default="{ row }">
              <div v-for="(v, k) in row.metrics" :key="k" class="metric-line">{{ k }}：{{ fmtMetric(v) }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="report_date" label="数据日期" width="110" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="STATUS_META[row.status]?.type || 'info'" size="small" effect="plain">
                {{ STATUS_META[row.status]?.label || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'open'" size="small" type="primary" link @click="onResolve(row)">标记已处理</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="该关键词没有告警记录" :image-size="48" />
          </template>
        </el-table>
      </el-card>

      <!-- 触发搜索词（搜索词报告下钻，按触发词名称关联） -->
      <el-card v-if="data.search_queries && data.search_queries.length" shadow="never" style="margin-top: 14px">
        <template #header>
          触发搜索词
          <span style="font-size: 12px; color: #9ca3af; font-weight: 400; margin-left: 8px">按触发词名称关联（百度搜索词报告不提供关键词 ID）· 展现最高 30 条</span>
        </template>
        <el-table :data="data.search_queries" size="small">
          <el-table-column label="搜索词" prop="query_word" min-width="180" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">{{ row.status_label }}</template>
          </el-table-column>
          <el-table-column label="展现" width="90" align="right">
            <template #default="{ row }">{{ row.impression ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="点击" width="90" align="right">
            <template #default="{ row }">{{ row.click ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="消费" width="100" align="right">
            <template #default="{ row }">{{ row.cost == null ? '—' : '¥' + Number(row.cost).toFixed(2) }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 待接入区块占位 -->
      <el-card shadow="never" style="margin-top: 14px">
        <template #header>待接入能力</template>
        <div class="pending-grid">
          <div class="pending-item"><b>移动比例</b><span>出价系数最后一层，数据源待接入</span></div>
          <div class="pending-item"><b>转化漏斗 / 线索</b><span>依赖转化数据接入（M2）</span></div>
          <div class="pending-item"><b>调价台账 / AI 解读</b><span>依赖调价写回 + 操作记录（M2）</span></div>
        </div>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; gap: 16px; }
.page-title { font-size: 18px; font-weight: 700; }
.period-picker { display: flex; align-items: center; gap: 8px; background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 5px 10px 5px 12px; flex-shrink: 0; }
.pp-label { font-size: 12px; color: var(--sem-text-sub); white-space: nowrap; }
.period-picker :deep(.el-date-editor) { --el-input-border-color: transparent; box-shadow: none !important; }
.period-picker :deep(.el-range-separator) { color: var(--sem-text-sub); }
.kw-path { font-size: 12px; color: var(--sem-text-sub); margin-top: 6px; }
.info-strip { margin-bottom: 14px; }
.info-strip :deep(.el-card__body) { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px; }
.il-label { font-size: 12px; color: var(--sem-text-sub); }
.il-value { font-size: 16px; font-weight: 600; margin-top: 4px; font-variant-numeric: tabular-nums; }
.il-value.danger { color: var(--sem-danger); }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 14px; }
.kpi-label { font-size: 12px; color: var(--sem-text-sub); }
.kpi-value { font-size: 22px; font-weight: 700; margin-top: 6px; font-variant-numeric: tabular-nums; }
.kpi-cmp { font-size: 12px; margin-top: 6px; display: flex; gap: 6px; align-items: center; }
.kpi-delta.good { color: var(--sem-success); font-weight: 600; }
.kpi-delta.bad { color: var(--sem-danger); font-weight: 600; }
.kpi-delta.neutral { color: var(--sem-text-sub); }
.kpi-prev { color: #9ca3af; }
.coef-card { margin-bottom: 14px; }
.coef-flow { display: flex; align-items: stretch; gap: 10px; flex-wrap: wrap; }
.coef-box { background: var(--sem-bg); border: 1px solid var(--sem-border); border-radius: 6px; padding: 10px 14px; min-width: 150px; }
.coef-box.warn { background: #fffbf4; border-color: #fed7aa; }
.coef-box.danger { background: #fef6f6; border-color: #fecaca; }
.coef-box.result { border-width: 2px; border-color: #dc9a47; background: linear-gradient(135deg, #fffbf4 0%, #fef1e1 100%); }
.coef-label { font-size: 11px; color: var(--sem-text-sub); }
.coef-value { font-size: 17px; font-weight: 700; margin-top: 4px; font-variant-numeric: tabular-nums; }
.coef-box.warn .coef-value { color: #ba7517; }
.coef-box.danger .coef-value { color: var(--sem-danger); }
.coef-meta { font-size: 11px; color: var(--sem-text-sub); margin-top: 2px; }
.coef-op { font-size: 18px; color: #9ca3af; align-self: center; }
.coef-warn-line { margin-top: 12px; padding: 10px 14px; background: #fffbf4; border-left: 3px solid #ba7517; border-radius: 5px; font-size: 12px; }
.coef-warn-line.danger { background: #fef6f6; border-left-color: var(--sem-danger); }
.analysis-grid { display: grid; grid-template-columns: minmax(360px, 0.8fr) minmax(560px, 1.2fr); align-items: stretch; gap: 14px; margin-bottom: 14px; }
.analysis-card { height: 100%; }
.analysis-card :deep(.el-card__body) { padding-top: 14px; }
.schedule-card { min-width: 0; }
.schedule-card :deep(.el-card__header) { padding-top: 12px; padding-bottom: 12px; }
.schedule-card :deep(.el-card__body) { display: flex; flex-direction: column; }
.schedule-card-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.metric-switch { flex-shrink: 0; }
.metric-switch :deep(.el-radio-button__inner) { min-width: 54px; padding: 6px 12px; box-shadow: none; }
.analysis-summary { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; margin-bottom: 12px; }
.analysis-title { color: var(--sem-text); font-size: 13px; font-weight: 700; line-height: 1.6; }
.analysis-note { color: var(--sem-text-sub); font-size: 12px; line-height: 1.5; margin-top: 2px; }
.factor-pill { min-width: 64px; height: 52px; padding: 7px 10px; border: 1px solid #d8eaff; border-radius: 7px; background: #f5f9ff; display: grid; place-items: center; }
.factor-pill span { color: var(--sem-text-sub); font-size: 11px; }
.factor-pill b { color: var(--sem-primary); font-size: 17px; font-variant-numeric: tabular-nums; }
.analysis-table { margin-top: 4px; }
.region-name { color: var(--sem-text); font-weight: 600; }
.region-id { color: #9ca3af; font-size: 11px; margin-top: 2px; }
.factor-text { font-weight: 700; font-variant-numeric: tabular-nums; }
.factor-text.strong { color: #ba7517; }
.factor-text.low { color: #1d9e75; }
.empty-compact { min-height: 112px; border: 1px dashed #dce3ec; border-radius: 7px; display: grid; place-items: center; color: var(--sem-text-sub); font-size: 12px; background: #fafcff; }
.schedule-chart-shell { padding: 12px 14px 10px; border: 1px solid #e8eef5; border-radius: 8px; background: #fff; }
.chart-section-head,
.subpanel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.chart-section-head > div,
.subpanel-head > div { display: flex; flex-direction: column; gap: 2px; }
.chart-section-head b,
.subpanel-head b { color: var(--sem-text); font-size: 12px; }
.chart-section-head span,
.subpanel-head span { color: var(--sem-text-sub); font-size: 11px; }
.chart-section-head strong { font-size: 12px; font-variant-numeric: tabular-nums; }
.schedule-heatmap { height: 250px; width: 100%; }
.heatmap-legend { display: flex; align-items: center; justify-content: flex-end; gap: 7px; color: var(--sem-text-sub); font-size: 11px; margin-top: -2px; }
.heatmap-legend i { width: 96px; height: 7px; border-radius: 4px; display: inline-block; }
.schedule-breakdown { display: grid; grid-template-columns: minmax(0, 1fr) 270px; gap: 10px; margin-top: 10px; }
.hourly-panel,
.top-slots-panel { min-width: 0; padding: 12px 14px 10px; border: 1px solid #e8eef5; border-radius: 8px; background: #fbfcfe; }
.schedule-hour-chart { width: 100%; height: 168px; margin-top: 2px; }
.slot-list { display: grid; gap: 10px; margin-top: 13px; }
.slot-row { display: flex; align-items: center; gap: 9px; min-width: 0; }
.slot-rank { width: 22px; height: 22px; border-radius: 5px; display: grid; place-items: center; flex: 0 0 22px; background: #edf3f9; color: #607086; font-size: 11px; font-weight: 700; }
.slot-content { flex: 1; min-width: 0; }
.slot-line { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 11px; line-height: 1.4; }
.slot-line span { color: #4f5d70; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.slot-line b { color: var(--sem-text); flex-shrink: 0; font-variant-numeric: tabular-nums; }
.slot-bar { height: 4px; margin-top: 5px; overflow: hidden; border-radius: 3px; background: #e8edf3; }
.slot-bar i { display: block; height: 100%; border-radius: inherit; opacity: 0.9; }
.slot-empty { height: 146px; display: grid; place-items: center; color: var(--sem-text-sub); font-size: 12px; }
.row-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 1100px) {
  .row-2col,
  .analysis-grid { grid-template-columns: 1fr; }
  .schedule-breakdown { grid-template-columns: 1fr; }
}
.card-sub { font-size: 12px; color: var(--sem-text-sub); font-weight: 400; }
.alert-title { font-weight: 600; font-size: 13px; }
.alert-message { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; line-height: 1.6; }
.metric-line { font-size: 12px; color: var(--sem-text-sub); }
.pending-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.pending-item { display: flex; flex-direction: column; gap: 4px; font-size: 13px; padding: 10px 12px; background: var(--sem-bg); border-radius: 6px; }
.pending-item span { font-size: 12px; color: var(--sem-text-sub); }
</style>
