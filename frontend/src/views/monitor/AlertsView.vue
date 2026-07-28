<script setup>
import { onMounted, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchAlerts, resolveAlert } from '../../api/alerts'
import { session } from '../../store/session'

const router = useRouter()

const TENANT_ID = computed(() => session.tenantId) // 当前客户，顶栏切换器驱动

const loading = ref(false)
const error = ref('')
const alerts = ref([])
const openCounts = ref({})
const statusFilter = ref('open')
const priorityFilter = ref('')

// 原型 p-badge / alert-card 配色：P0/P1 红、P2 琥珀、P3 蓝、P4 绿、P5 灰
const PRIORITY_META = {
  P0: { label: '最高紧急', cls: 'p-0' },
  P1: { label: '立即执行', cls: 'p-1' },
  P2: { label: '本周处理', cls: 'p-2' },
  P3: { label: '观察', cls: 'p-3' },
  P4: { label: '低', cls: 'p-4' },
  P5: { label: '提示', cls: 'p-5' },
}

const STATUS_META = {
  open: { label: '未处理', cls: 'st-open' },
  resolved: { label: '已处理', cls: 'st-resolved' },
  merged: { label: '已归并', cls: 'st-merged' },
}

const STATUS_TABS = [
  { value: 'open', label: '未处理' },
  { value: 'resolved', label: '已处理' },
  { value: 'merged', label: '已归并' },
  { value: 'all', label: '全部' },
]

const fmtMetric = (v) => (typeof v === 'number' ? v.toLocaleString('zh-CN') : v)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchAlerts({
      tenantId: TENANT_ID.value,
      status: statusFilter.value,
      priority: priorityFilter.value,
    })
    alerts.value = data.alerts
    openCounts.value = data.open_counts
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function setPriority(p) {
  priorityFilter.value = p
  load()
}

function setStatus(s) {
  statusFilter.value = s
  load()
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

// 顶栏切换客户后重新拉数
watch(TENANT_ID, load)

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">异常提醒</div>
        <div class="page-desc">规则引擎每日 02:00 自动巡检 · 同词多天触发自动归并</div>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />

    <!-- 过滤栏：P0-P5 chips + 状态 tabs（原型 p-chips / view-tabs） -->
    <div class="filter-row">
      <div class="p-chips">
        <div class="p-chip" :class="{ active: priorityFilter === '' }" @click="setPriority('')">
          全部
        </div>
        <div
          v-for="(m, p) in PRIORITY_META"
          :key="p"
          class="p-chip"
          :class="[m.cls, { active: priorityFilter === p }]"
          @click="setPriority(p)"
        >
          {{ p }} {{ m.label }}
          <span v-if="openCounts[p]" class="p-count">{{ openCounts[p] }}</span>
        </div>
      </div>
      <div class="view-tabs">
        <div
          v-for="t in STATUS_TABS"
          :key="t.value"
          class="view-tab"
          :class="{ active: statusFilter === t.value }"
          @click="setStatus(t.value)"
        >{{ t.label }}</div>
      </div>
    </div>

    <!-- 告警卡片流（原型 alert-card） -->
    <div
      v-for="row in alerts"
      :key="row.id"
      class="alert-card"
      :class="PRIORITY_META[row.priority]?.cls || 'p-5'"
    >
      <div class="ac-body">
        <div class="ac-head">
          <span class="p-badge" :class="'p-badge-' + (row.priority?.slice(1) || '5')">{{ row.priority }}</span>
          <!-- 关键词作主标题（醒目、可点下钻）；告警类型降为次级标签 -->
          <template v-if="row.keyword_id">
            <a class="ac-kw" @click="router.push(`/monitor/keywords/${row.keyword_id}?from=alerts`)">{{ row.keyword || row.keyword_id }} →</a>
            <span class="ac-type" :class="'ac-type-' + (row.priority?.slice(1) || '5')">{{ row.title }}</span>
          </template>
          <span v-else class="ac-title">{{ row.title }}</span>
          <span class="ac-source" :class="{ ai: row.source === 'ai' }">{{ row.source === 'ai' ? '✨ AI 发现' : '自研规则' }}</span>
          <span class="status-tag" :class="STATUS_META[row.status]?.cls">{{ STATUS_META[row.status]?.label || row.status }}</span>
          <span class="ac-time">数据日期 {{ row.report_date }}</span>
        </div>
        <div class="ac-detail">{{ row.message }}</div>
        <div v-if="row.streak" class="ac-conflict">
          ⏱ 该词近期累计 <b>{{ row.streak.days }} 天</b>触发（最早 {{ row.streak.first_date }}），旧告警已自动归并
        </div>
        <div class="ac-grid">
          <template v-if="row.campaign_name">
            <span class="ac-grid-label">所属计划</span>
            <span class="ac-grid-value">{{ row.campaign_name }}</span>
          </template>
          <template v-if="Object.keys(row.metrics || {}).length">
            <span class="ac-grid-label">关键指标</span>
            <span class="ac-grid-value">
              <span v-for="(v, k) in row.metrics" :key="k" class="pill">{{ k }} {{ fmtMetric(v) }}</span>
            </span>
          </template>
        </div>
      </div>
      <div v-if="row.status === 'open'" class="ac-foot">
        <span>检出于 {{ row.detected_at?.slice(0, 16).replace('T', ' ') }}</span>
        <span class="ac-foot-spacer" />
        <button v-if="row.keyword_id" class="row-action" @click="router.push(`/monitor/keywords/${row.keyword_id}?from=alerts`)">查看详情</button>
        <button v-if="session.canEdit('monitor.alerts')" class="row-action primary" @click="onResolve(row)">标记已处理</button>
      </div>
    </div>

    <div v-if="!loading && !alerts.length" class="empty-group">
      当前筛选条件下没有告警
    </div>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; display: flex; justify-content: space-between; align-items: flex-end; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }

/* 过滤栏（原型 p-chips + view-tabs） */
.filter-row { display: flex; gap: 12px; margin-bottom: 14px; align-items: center; flex-wrap: wrap; justify-content: space-between; }
.p-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.p-chip {
  padding: 6px 12px; border-radius: 16px; font-size: 12px; cursor: pointer;
  background: #fff; border: 1px solid var(--sem-border); color: #4b5563;
  display: inline-flex; align-items: center; gap: 6px; transition: all 0.1s; user-select: none;
}
.p-chip:hover { border-color: var(--sem-primary); }
.p-chip.active { background: var(--sem-primary); color: #fff; border-color: var(--sem-primary); }
.p-count { background: rgba(0, 0, 0, 0.06); color: var(--sem-text-sub); padding: 0 6px; border-radius: 8px; font-size: 10px; font-weight: 600; }
.p-chip.p-0 .p-count, .p-chip.p-1 .p-count { background: #fef6f6; color: var(--sem-danger); }
.p-chip.p-2 .p-count { background: #fcf6ea; color: #ba7517; }
.p-chip.p-3 .p-count { background: #eff4fb; color: var(--sem-primary); }
.p-chip.p-4 .p-count { background: #e5f4ed; color: var(--sem-success); }
.p-chip.active .p-count { background: rgba(255, 255, 255, 0.25); color: #fff; }
.view-tabs { display: flex; gap: 4px; background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 4px; }
.view-tab { padding: 6px 14px; border-radius: 5px; font-size: 12px; cursor: pointer; color: var(--sem-text-sub); font-weight: 500; user-select: none; }
.view-tab:hover { background: #f9fafb; color: var(--sem-primary); }
.view-tab.active { background: #eff4fb; color: var(--sem-primary); }

/* 告警卡片（原型 alert-card） */
.alert-card {
  background: #fff; border: 1px solid var(--sem-border); border-radius: 8px;
  margin-bottom: 10px; overflow: hidden; transition: all 0.1s;
}
.alert-card:hover { border-color: #c5d7ee; box-shadow: 0 2px 8px rgba(24, 95, 165, 0.05); }
.alert-card.p-0, .alert-card.p-1 { border-left: 4px solid var(--sem-danger); }
.alert-card.p-2 { border-left: 4px solid #ba7517; }
.alert-card.p-3 { border-left: 4px solid var(--sem-primary); }
.alert-card.p-4 { border-left: 4px solid var(--sem-success); }
.alert-card.p-5 { border-left: 4px solid #9ca3af; }
.ac-body { padding: 14px 18px; }
.ac-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.ac-title { font-size: 14px; font-weight: 600; color: var(--sem-text); }
/* 关键词作主标题：醒目、可点 */
.ac-kw { font-size: 16px; font-weight: 700; color: var(--sem-primary); cursor: pointer; }
.ac-kw:hover { text-decoration: underline; }
/* 告警类型次级标签：按优先级配色，深字高对比，一眼可读 + 体现严重度 */
.ac-type { font-size: 12px; font-weight: 600; padding: 2px 9px; border-radius: 4px; }
.ac-type-0, .ac-type-1 { background: #fde4e4; color: #b91c1c; }
.ac-type-2 { background: #fbeccb; color: #92600a; }
.ac-type-3 { background: #dde9f8; color: #1d5aa0; }
.ac-type-4 { background: #d8efe2; color: #15724b; }
.ac-type-5 { background: #e7e9ed; color: #404652; }
.ac-time { font-size: 11px; color: #9ca3af; margin-left: auto; }
.ac-source { font-size: 10px; padding: 1px 6px; background: #eff4fb; color: var(--sem-primary); border-radius: 3px; }
.ac-source.ai { background: #f2ebfb; color: #6b47b5; }
.ac-detail { font-size: 12px; color: #4b5563; line-height: 1.7; }

.p-badge { font-size: 11px; padding: 2px 8px; border-radius: 4px; font-weight: 700; color: #fff; }
.p-badge-0 { background: linear-gradient(135deg, #e24b4a 0%, #c73e3d 100%); }
.p-badge-1 { background: var(--sem-danger); }
.p-badge-2 { background: #ba7517; }
.p-badge-3 { background: var(--sem-primary); }
.p-badge-4 { background: var(--sem-success); }
.p-badge-5 { background: #9ca3af; }

.status-tag { font-size: 10px; padding: 1px 6px; border-radius: 3px; }
.st-open { background: #fef6f6; color: var(--sem-danger); }
.st-resolved { background: #e5f4ed; color: var(--sem-success); }
.st-merged { background: #f3f4f6; color: var(--sem-text-sub); }

/* 归并提示（原型 ac-conflict） */
.ac-conflict {
  background: #fffbf4; border: 1px dashed #fed7aa; border-radius: 5px;
  padding: 8px 10px; font-size: 11px; color: #ba7517; margin-top: 8px; line-height: 1.6;
}
.ac-conflict b { color: #9a3412; }

/* 指标网格（原型 ac-grid） */
.ac-grid { display: grid; grid-template-columns: 70px 1fr; gap: 6px 12px; margin-top: 10px; font-size: 12px; }
.ac-grid-label { color: #9ca3af; font-size: 11px; padding-top: 2px; }
.ac-grid-value { color: var(--sem-text); }
.kw-link { color: var(--sem-primary); cursor: pointer; font-weight: 500; }
.kw-link:hover { text-decoration: underline; }
.pill {
  display: inline-block; padding: 1px 8px; background: #f3f4f6; border-radius: 3px;
  font-size: 11px; margin: 0 4px 4px 0; color: #4b5563; font-variant-numeric: tabular-nums;
}

/* 卡片底部操作条（原型 ac-foot） */
.ac-foot {
  padding: 10px 18px; background: #fafbfc; border-top: 1px solid #f3f4f6;
  display: flex; gap: 8px; align-items: center; font-size: 11px; color: var(--sem-text-sub);
}
.ac-foot-spacer { flex: 1; }
.row-action {
  font-size: 11px; padding: 4px 11px; border-radius: 4px;
  border: 1px solid var(--sem-border); background: #fff; color: #4b5563; cursor: pointer;
}
.row-action:hover { border-color: var(--sem-primary); color: var(--sem-primary); }
.row-action.primary { background: var(--sem-primary); color: #fff; border-color: var(--sem-primary); font-weight: 500; }
.row-action.primary:hover { background: #1a6bab; color: #fff; }

/* 空状态（原型 empty-group） */
.empty-group {
  padding: 28px; text-align: center; color: #9ca3af; font-size: 12px;
  background: #fafbfc; border-radius: 8px; border: 1px dashed var(--sem-border);
}
</style>
