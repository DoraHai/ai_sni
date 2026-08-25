<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const cards = [
  { title: '优化文章', desc: '【主路径】内容任务列表 + 母稿编辑器', path: '/geo/tasks', phase: 'Vue' },
  { title: '优化业务', desc: '业务 → 单元（关键词）→ 意图词', path: '/geo/businesses', phase: 'Vue' },
  { title: '优化意图词', desc: 'prompts · 探测题标记 / 问题组', path: '/geo/prompts', phase: 'Vue' },
  { title: '事实库', desc: 'facts 列表 / 新建 / 核验（生成需 ≥3 verified）', path: '/geo/facts', phase: 'Vue' },
  { title: '引擎', desc: '监测引擎开关 · sample_mode', path: '/geo/engines', phase: 'Vue' },
  { title: 'AI 能力配置', desc: '租户 LLM（百炼/DeepSeek）', path: '/geo/ai-settings', phase: 'Vue' },
  { title: '发布渠道', desc: '渠道目录 · Webhook 账号（公网 HTTPS）', path: '/geo/publishing', phase: 'Vue' },
  { title: '媒体阵地', desc: '权威信源 / 分发阵地 CRUD', path: '/geo/placements', phase: 'Vue' },
  { title: 'GEO 概览', desc: 'KPI · 可见性 vs 认知分列', path: '/geo/overview', phase: 'Vue' },
  { title: 'AI 可见度', desc: '仪表盘与采集判断', path: '/geo/visibility', phase: 'Vue' },
  { title: '期次对比', desc: 'before/after 可见性 Δ', path: '/geo/period-diff', phase: 'Vue' },
  { title: '交付摘要', desc: '周期报告 Markdown / 打印', path: '/geo/deliverables', phase: 'Vue' },
]

function go(card) {
  router.push(card.path)
}

const note = computed(() =>
  '快捷入口。日常请从「优化业务」进主轴：缺口 → 写稿 → 发布 → 本期效果。',
)
</script>

<template>
  <div class="geo-hub">
    <div class="page-header">
      <div>
        <div class="page-title">内容工作台</div>
        <div class="page-desc">{{ note }}</div>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="router.push('/geo/businesses')">优化业务</el-button>
        <el-button @click="router.push('/geo/tasks')">优化文章</el-button>
      </div>
    </div>

    <div class="card-grid">
      <button
        v-for="c in cards"
        :key="c.path"
        type="button"
        class="hub-card"
        @click="go(c)"
      >
        <div class="hub-title">{{ c.title }}</div>
        <div class="hub-desc">{{ c.desc }}</div>
        <el-tag size="small" type="success">{{ c.phase }}</el-tag>
      </button>
    </div>
  </div>
</template>

<style scoped>
/* 页头由 geo-page.css 提供 */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
}
.hub-card {
  text-align: left;
  border: 1px solid #e8edf5;
  background: linear-gradient(180deg, #fff 0%, #fafbfd 100%);
  border-radius: 14px;
  padding: 18px 16px 16px;
  cursor: pointer;
  transition: box-shadow 0.18s, border-color 0.18s, transform 0.15s;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.hub-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 8px 24px rgba(24, 95, 165, 0.1);
  transform: translateY(-1px);
}
.hub-title {
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 8px;
  font-size: 15px;
  letter-spacing: -0.01em;
}
.hub-desc {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 12px;
  min-height: 36px;
  line-height: 1.5;
}
</style>
