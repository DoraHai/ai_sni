<template>
  <div v-if="visible" class="drilldown-overlay" @click.self="close">
    <div class="drilldown-panel" role="dialog" aria-modal="true" :aria-label="`${categoryLabel}关键词明细`">
      <div class="drilldown-header">
        <h3>{{ categoryLabel }}关键词明细</h3>
        <button class="icon-btn" type="button" aria-label="关闭" @click="close">×</button>
      </div>

      <div v-if="loading" class="state">加载中...</div>
      <div v-else-if="error" class="state error">
        <div>{{ error }}</div>
        <button class="secondary-btn" type="button" @click="fetchData">重试</button>
      </div>

      <div v-else class="drilldown-body">
        <div class="summary">共 {{ total }} 个关键词，本页显示消费 TOP {{ rows.length }}</div>
        <table class="drilldown-table">
          <thead>
            <tr>
              <th>关键词</th>
              <th>7天消费</th>
              <th>7天点击</th>
              <th>7天展现</th>
              <th>CTR</th>
              <th>CPC</th>
              <th>平均排名</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="kw in rows" :key="kw.keyword_id">
              <td class="keyword-cell">{{ kw.keyword }}</td>
              <td>{{ fmtMoney(metrics(kw).cost) }}</td>
              <td>{{ fmtInt(metrics(kw).click) }}</td>
              <td>{{ fmtInt(metrics(kw).impression) }}</td>
              <td>{{ fmtCtr(metrics(kw).ctr) }}</td>
              <td>{{ fmtMoney(metrics(kw).cpc) }}</td>
              <td>{{ fmtRank(metrics(kw).avg_rank) }}</td>
            </tr>
            <tr v-if="rows.length === 0">
              <td colspan="7" class="empty-row">该分类下暂无关键词数据</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="drilldown-footer">
        <button class="secondary-btn" type="button" @click="close">关闭</button>
        <button class="primary-btn" type="button" @click="goToWorkbench">在工作台中查看并处理</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { fetchKeywordList } from '../api/keywords'

const props = defineProps({
  visible: { type: Boolean, default: false },
  tenantId: { type: [Number, String], required: true },
  category: { type: String, default: '' },
})

const emit = defineEmits(['update:visible'])
const router = useRouter()

const CATEGORY_LABELS = {
  brand: '品牌词',
  focus: '重点词',
  normal: '一般词',
  longtail: '长尾精准',
  new: '新词',
}

const categoryLabel = computed(() => CATEGORY_LABELS[props.category] || props.category || '分类')
const loading = ref(false)
const error = ref('')
const rows = ref([])
const total = ref(0)

function metrics(row) {
  return row?.metrics_7d || {}
}

function fmtMoney(v) {
  if (v == null) return '-'
  return `¥ ${Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

function fmtInt(v) {
  if (v == null) return '-'
  return Number(v).toLocaleString('zh-CN')
}

function fmtCtr(v) {
  if (v == null) return '-'
  const n = Number(v)
  if (!Number.isFinite(n)) return '-'
  return `${(n <= 1 ? n * 100 : n).toFixed(2)}%`
}

function fmtRank(v) {
  if (v == null) return '-'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(2) : '-'
}

async function fetchData() {
  if (!props.visible || !props.tenantId || !props.category) return
  loading.value = true
  error.value = ''
  try {
    const res = await fetchKeywordList({
      tenantId: props.tenantId,
      category: props.category,
      page: 1,
      pageSize: 50,
      sortBy: 'cost_7d',
      order: 'desc',
    })
    rows.value = res.keywords || []
    total.value = res.total || 0
  } catch (e) {
    error.value = e?.response?.data?.detail || e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.visible, props.tenantId, props.category],
  ([visible]) => {
    if (visible) fetchData()
  },
)

function close() {
  emit('update:visible', false)
}

function goToWorkbench() {
  router.push({
    path: '/optimize/keywords',
    query: {
      tenant_id: props.tenantId,
      category: props.category,
    },
  })
  close()
}
</script>

<style scoped>
.drilldown-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(17, 24, 39, 0.48);
}
.drilldown-panel {
  width: min(860px, 94vw);
  max-height: 84vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.22);
}
.drilldown-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #eef0f3;
}
.drilldown-header h3 {
  margin: 0;
  color: var(--sem-text);
  font-size: 16px;
  font-weight: 600;
}
.icon-btn {
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #8a94a6;
  cursor: pointer;
  font-size: 22px;
  line-height: 1;
}
.icon-btn:hover { background: #f3f6fa; color: #334155; }
.state {
  padding: 42px 20px;
  color: #667085;
  text-align: center;
}
.state.error {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: center;
  color: #b42318;
}
.drilldown-body {
  flex: 1;
  overflow: auto;
  padding: 16px 20px 18px;
}
.summary {
  margin-bottom: 12px;
  color: #667085;
  font-size: 12px;
}
.drilldown-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 13px;
}
.drilldown-table th,
.drilldown-table td {
  padding: 9px 8px;
  border-bottom: 1px solid #eef0f3;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.drilldown-table th {
  background: #f8fafc;
  color: #667085;
  font-size: 12px;
  font-weight: 600;
}
.drilldown-table th:first-child,
.drilldown-table td:first-child {
  width: 26%;
  text-align: left;
}
.keyword-cell {
  color: var(--sem-text);
  word-break: break-all;
}
.empty-row {
  height: 72px;
  color: #9ca3af;
  text-align: center !important;
}
.drilldown-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 13px 20px;
  border-top: 1px solid #eef0f3;
}
.secondary-btn,
.primary-btn {
  height: 32px;
  padding: 0 15px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.secondary-btn {
  border: 1px solid #d0d7de;
  background: #fff;
  color: #344054;
}
.primary-btn {
  border: 1px solid var(--sem-primary);
  background: var(--sem-primary);
  color: #fff;
}
</style>
