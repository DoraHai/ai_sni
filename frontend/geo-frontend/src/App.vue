<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const shortcuts = [
  ['!', '诊断中心', '/diagnostic-center/'],
  ['S', 'SEO 内容工作台', '/seo/content/articles'],
  ['⌂', '全域驾驶舱', '/deal-sniper/hub/dashboard'],
  ['←', '返回平台门户', '/deal-sniper/portal'],
]

const groups = [
  {
    key: 'content',
    label: '内容生产',
    items: [
      ['优化业务', '/geo/businesses'],
      ['GEO 开户向导', '/geo/onboarding'],
      ['优化意图词', '/geo/prompts'],
      ['缺口工作台', '/geo/gaps'],
      ['事实库', '/geo/facts'],
      ['优化文章', '/geo/tasks'],
      ['发布渠道', '/geo/publishing'],
      ['媒体阵地', '/geo/placements'],
    ],
  },
  {
    key: 'monitor',
    label: '效果监测',
    items: [
      ['GEO 概览', '/geo/overview'],
      ['AI 可见度', '/geo/visibility'],
      ['全自动巡检', '/geo/visibility/patrol'],
      ['优化期次', '/geo/periods'],
      ['期次对比', '/geo/period-diff'],
      ['AI 引用分析', '/geo/citations'],
      ['竞品监测', '/geo/competitors'],
      ['评价与位置', '/geo/evaluation'],
      ['话题覆盖热度', '/geo/topic-heat'],
      ['交付摘要', '/geo/deliverables'],
    ],
  },
  {
    key: 'intelligence',
    label: '能力与情报',
    items: [
      ['引擎配置', '/geo/engines'],
      ['AI 配置', '/geo/ai-settings'],
      ['渠道成稿提示词', '/geo/channel-polish-prompts'],
      ['AI 动态与策略', '/geo/ai-trends'],
    ],
  },
]

function groupForPath(path) {
  return groups.find((group) => group.items.some(([, itemPath]) => (
    path === itemPath || path.startsWith(`${itemPath}/`)
  )))?.key || 'content'
}

const openGroup = ref(groupForPath(route.path))
watch(() => route.path, (path) => { openGroup.value = groupForPath(path) })

const title = computed(() => route.meta.title || 'GEO 工作台')
const bare = computed(() => route.meta.bare === true)

function isActive(path) {
  if (path === '/geo/visibility') return route.path === path
  if (path === '/geo/businesses') return route.path === path || /^\/geo\/businesses\/\d+/.test(route.path)
  if (path === '/geo/tasks') return route.path === path || /^\/geo\/tasks\/\d+/.test(route.path)
  return route.path === path
}

function toggle(key) {
  openGroup.value = openGroup.value === key ? '' : key
}

function shortcutHref(path) {
  if (import.meta.env.DEV && /^(localhost|127\.0\.0\.1)$/.test(window.location.hostname)) {
    return `http://127.0.0.1:5173${path}`
  }
  return path
}
</script>

<template>
  <router-view v-if="bare" />
  <div v-else class="geo-app-shell">
    <aside class="geo-side">
      <div class="brand">
        <div class="brand-mark">G</div>
        <div>
          <div class="brand-title">GEO 增长</div>
          <div class="brand-subtitle">内容与可见度</div>
        </div>
      </div>

      <div class="nav-caption">GEO 工作流</div>

      <nav class="geo-nav" aria-label="GEO 功能导航">
        <section v-for="group in groups" :key="group.key" class="nav-section">
          <button class="section-trigger" :class="{ active: openGroup === group.key }" @click="toggle(group.key)">
            <span>{{ group.label }}</span>
            <span class="chevron">›</span>
          </button>
          <div v-show="openGroup === group.key" class="section-items">
            <button
              v-for="item in group.items"
              :key="item[1]"
              class="nav-item"
              :class="{ active: isActive(item[1]) }"
              @click="router.push(item[1])"
            >
              <span class="nav-dot" />
              <span>{{ item[0] }}</span>
            </button>
          </div>
        </section>
      </nav>

      <footer class="geo-shortcuts" aria-label="跨模块快速跳转">
        <a
          v-for="shortcut in shortcuts"
          :key="shortcut[1]"
          :href="shortcutHref(shortcut[2])"
          class="shortcut-link"
        >
          <span class="shortcut-icon">{{ shortcut[0] }}</span>
          <span>{{ shortcut[1] }}</span>
        </a>
      </footer>
    </aside>

    <section class="geo-stage">
      <header class="topbar">
        <div>
          <div class="eyebrow">当前位置</div>
          <div class="breadcrumb"><span>GEO 增长</span><i>/</i><strong>{{ title }}</strong></div>
        </div>
        <div class="module-pill"><span class="pulse" /> 独立 GEO 工作区</div>
      </header>
      <main class="geo-main" :class="{ fluid: route.meta.fluidMain }">
        <router-view />
      </main>
    </section>
  </div>
</template>
