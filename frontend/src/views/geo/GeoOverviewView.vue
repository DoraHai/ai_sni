<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchGeoContentStats,
  geoContentHealth,
  staticGeoEditorUrl,
} from '../../api/geoContent'
import { session } from '../../store/session'

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const error = ref('')
const stats = ref(null)
const healthOk = ref(null)

const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))
const fmtPct = (v) => {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

const summaryCards = computed(() => {
  const s = stats.value
  if (!s) return []
  return [
    { label: '活跃提示词', value: fmtInt(s.prompts), hint: `探测题 ${fmtInt(s.prompts_probe)}` },
    { label: '内容任务', value: fmtInt(s.tasks), hint: `待修 ${fmtInt(s.todo_blocked)} · 待发 ${fmtInt(s.todo_publish)}` },
    { label: '已发布', value: fmtInt(s.published), hint: `就绪及以上 ${fmtInt(s.ready_or_beyond)}` },
    {
      label: '可见性提及率',
      value: fmtPct(s.visibility_mention_rate),
      hint: `排除探测 · 快照 ${fmtInt(s.snapshots_visibility)} · top1 ${fmtPct(s.visibility_top1_rate)}`,
    },
    {
      label: '品牌认知率',
      value: fmtPct(s.probe_recognition_rate),
      hint: `仅探测题 · 样本 ${fmtInt(s.snapshots_probe)}`,
    },
    {
      label: '引用域名',
      value: fmtInt(s.distinct_cited_domains),
      hint: `含引用快照 ${fmtInt(s.snapshots_with_citations)}`,
    },
    {
      label: '待复测提示词',
      value: fmtInt(s.prompts_need_recheck),
      hint: `品牌缺失标签 ${fmtInt(s.prompts_brand_missing)}`,
    },
  ]
})

const workbenchLinks = [
  { label: '内容任务', path: '/geo/tasks', desc: '主入口 · 列表 + 混合编辑器', vue: true, primary: true },
  { label: 'AI 可见度', path: '/geo/visibility', desc: '登记 / 多引擎探测', vue: true, primary: true },
  { label: '全自动巡检', path: '/geo/visibility/patrol', desc: '多词×多引擎自动探测落库', vue: true, primary: true },
  { label: '期次对比', path: '/geo/period-diff', desc: 'before/after 可见性 Δ', vue: true, primary: true },
  { label: '交付摘要', path: '/geo/deliverables', desc: '周期报告 Markdown / 打印', vue: true, primary: true },
  { label: '引用域名', path: '/geo/citations', desc: '引用聚合与蓝图对照', vue: true },
  { label: '竞品分析', path: '/geo/competitors', desc: '竞品出现与份额', vue: true },
  { label: '评价分析', path: '/geo/evaluation', desc: '情感与位置分布', vue: true },
  { label: '内容工作台', path: '/geo/workbench', desc: 'Vue 页枢纽', vue: true },
  { label: '机会词', path: '/geo/prompts', desc: 'prompts · 探测题标记', vue: true },
  { label: '事实库', path: '/geo/facts', desc: 'facts 管理', vue: true },
  { label: '发布渠道', path: '/geo/publishing', desc: '渠道与 Webhook', vue: true },
  {
    label: '静态编辑器（兼容）',
    path: 'static-editor',
    desc: '完整流水线后备 · :5176/geo/editor.html',
    static: true,
  },
  { label: '网站体检', path: '/diagnostic-center/', desc: '诊断 → 内容桥接', external: true },
]

const router = useRouter()

function openWorkbench(link) {
  if (link.vue) {
    router.push(link.path)
    return
  }
  if (link.external) {
    window.location.assign(link.path)
    return
  }
  if (link.static) {
    const tid = tenantId.value || 1
    // correct local path: /geo/editor.html not /editor.html or /dashboard.html
    window.open(staticGeoEditorUrl(tid), '_blank')
    return
  }
  window.open(link.path, '_blank')
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [s, h] = await Promise.all([
      fetchGeoContentStats(tenantId.value),
      geoContentHealth().catch(() => null),
    ])
    stats.value = s
    healthOk.value = h ? h.status === 'ok' : null
  } catch (e) {
    error.value = e.message || '加载失败'
    stats.value = null
  } finally {
    loading.value = false
  }
}

function refresh() {
  load().then(() => {
    if (!error.value) ElMessage.success('已刷新')
  })
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-overview">
    <div class="page-header">
      <div>
        <div class="page-title">GEO 概览</div>
        <div class="page-desc">
          内容与可见度状态一览；详细执行仍在 GEO 工作台完成。
          <span v-if="healthOk === true" class="health ok">API 正常</span>
          <span v-else-if="healthOk === false" class="health bad">API 异常</span>
        </div>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="refresh">刷新</el-button>
        <el-button type="primary" @click="openWorkbench(workbenchLinks[0])">打开工作台</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />

    <div v-if="stats" class="kpi-grid">
      <div v-for="card in summaryCards" :key="card.label" class="kpi">
        <div class="kpi-label">{{ card.label }}</div>
        <div class="kpi-value">{{ card.value }}</div>
        <div class="kpi-hint">{{ card.hint }}</div>
      </div>
    </div>

    <section v-if="stats" class="panel">
      <div class="panel-title">下一步</div>
      <ul class="next-list">
        <li v-if="stats.todo_blocked > 0">
          有 <b>{{ stats.todo_blocked }}</b> 个任务需规则补丁 / 审校后再发布。
        </li>
        <li v-if="stats.todo_publish > 0">
          有 <b>{{ stats.todo_publish }}</b> 个已导出任务可回填发布（含 Webhook）。
        </li>
        <li v-if="stats.prompts_need_recheck > 0">
          有 <b>{{ stats.prompts_need_recheck }}</b> 个提示词建议复测可见度。
        </li>
        <li v-if="!stats.todo_blocked && !stats.todo_publish && !stats.prompts_need_recheck">
          当前无阻塞待办；可继续登记快照或从诊断创建内容任务。
        </li>
      </ul>
    </section>

    <section class="panel">
      <div class="panel-title">工作台入口</div>
      <div class="link-grid">
        <button
          v-for="link in workbenchLinks"
          :key="link.path"
          type="button"
          class="link-item"
          @click="openWorkbench(link)"
        >
          <span class="link-label">{{ link.label }}</span>
          <span class="link-desc">{{ link.desc }}</span>
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.geo-overview {
  padding: 4px 2px 24px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}
.page-title {
  font-size: 20px;
  font-weight: 650;
  color: #1f2937;
}
.page-desc {
  margin-top: 4px;
  font-size: 13px;
  color: #6b7280;
}
.header-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.health {
  margin-left: 8px;
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 4px;
}
.health.ok {
  background: #ecfdf5;
  color: #047857;
}
.health.bad {
  background: #fef2f2;
  color: #b91c1c;
}
.mb {
  margin-bottom: 14px;
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.kpi {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 14px 16px;
}
.kpi-label {
  font-size: 12px;
  color: #6b7280;
}
.kpi-value {
  margin-top: 6px;
  font-size: 24px;
  font-weight: 650;
  color: #111827;
  font-variant-numeric: tabular-nums;
}
.kpi-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #9ca3af;
}
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px 18px;
  margin-bottom: 14px;
}
.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 10px;
}
.next-list {
  margin: 0;
  padding-left: 18px;
  color: #4b5563;
  font-size: 13px;
  line-height: 1.7;
}
.link-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.link-item {
  text-align: left;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f9fafb;
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.link-item:hover {
  border-color: #93c5fd;
  background: #eff6ff;
}
.link-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
}
.link-desc {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: #6b7280;
}
@media (max-width: 960px) {
  .kpi-grid,
  .link-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .page-header {
    flex-direction: column;
  }
}
@media (max-width: 640px) {
  .kpi-grid,
  .link-grid {
    grid-template-columns: 1fr;
  }
}
</style>
