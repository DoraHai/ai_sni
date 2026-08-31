<script setup>
import { computed } from 'vue'
import { session } from '../store/session'
import GeoObservationPeriod from './GeoObservationPeriod.vue'
import GeoPrototypePageHeader from './GeoPrototypePageHeader.vue'

defineProps({
  title: { type: String, required: true },
  sub: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  showPeriod: { type: Boolean, default: true },
})

const tenantHint = computed(() => {
  if (session.tenantId) return ''
  if ((session.tenants || []).length) return '请在顶部选择客户后再看数据'
  return ''
})
</script>

<template>
  <div class="geo-wb" v-loading="loading">
    <GeoPrototypePageHeader :title="title" :sub="tenantHint || sub">
      <template #actions>
        <GeoObservationPeriod v-if="showPeriod" />
        <slot name="actions" />
      </template>
    </GeoPrototypePageHeader>
    <div class="geo-content">
      <slot />
    </div>
  </div>
</template>
