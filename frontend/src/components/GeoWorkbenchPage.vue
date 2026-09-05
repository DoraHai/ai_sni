<script setup>
import { computed } from 'vue'
import { session } from '../store/session'
import GeoObservationPeriod from './GeoObservationPeriod.vue'

defineProps({
  title: { type: String, required: true },
  sub: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  showPeriod: { type: Boolean, default: true },
})

const tenantHint = computed(() => {
  if (session.tenantId) return ''
  if ((session.tenants || []).length) return '请先在顶部选择客户后再查看数据'
  return ''
})
</script>

<template>
  <div class="geo-wb" v-loading="loading">
    <header class="geo-page-banner" :aria-label="`${title} 页面工具栏`">
      <div class="geo-page-banner-copy">
        <h1>{{ title }}</h1>
        <div v-if="tenantHint" class="sub">{{ tenantHint }}</div>
        <div v-else-if="sub" class="sub">{{ sub }}</div>
      </div>
      <div class="geo-page-banner-tools right">
        <GeoObservationPeriod v-if="showPeriod" />
        <slot name="actions" />
      </div>
    </header>
    <div class="geo-content">
      <slot />
    </div>
  </div>
</template>
