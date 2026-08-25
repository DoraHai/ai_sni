<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { GEO_VISIBILITY_DASH, GEO_VISIBILITY_SNAPSHOTS } from '../utils/geoRoutes'

const route = useRoute()

const tabs = [
  { label: '数据仪表盘', path: GEO_VISIBILITY_DASH },
  { label: '采集与判断', path: GEO_VISIBILITY_SNAPSHOTS },
]

function isActive(path) {
  if (path === GEO_VISIBILITY_DASH) return route.path === GEO_VISIBILITY_DASH
  return route.path === path || route.path.startsWith(`${path}/`)
}

const activePath = computed(() => tabs.find((t) => isActive(t.path))?.path || '')
</script>

<template>
  <nav class="geo-vis-nav" aria-label="AI 可见度子导航">
    <router-link
      v-for="tab in tabs"
      :key="tab.path"
      class="geo-vis-nav-tab"
      :class="{ 'is-active': isActive(tab.path) }"
      :to="tab.path"
      :aria-current="activePath === tab.path ? 'page' : undefined"
    >
      {{ tab.label }}
    </router-link>
  </nav>
</template>

<style scoped>
.geo-vis-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 0 16px;
}
.geo-vis-nav-tab {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  border-radius: 9px;
  font-size: 12px;
  font-weight: 500;
  color: #5b6270;
  text-decoration: none;
  border: 1px solid #e8eaf0;
  background: #fff;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.geo-vis-nav-tab:hover {
  color: #7c3aed;
  border-color: #ddd6fe;
}
.geo-vis-nav-tab.is-active {
  color: #7c3aed;
  background: #f5f0ff;
  border-color: #7c3aed;
  font-weight: 600;
}
</style>
