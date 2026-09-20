<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { metricDisplay } from './dashboard-orchestrator.mjs'
const props = defineProps({ metric: { type:Object, required:true }, animate: Boolean })
const value = ref('—')
let frame = 0
watch(() => [props.metric, props.animate], () => {
  cancelAnimationFrame(frame)
  const final = metricDisplay(props.metric)
  value.value = final
  if (!props.animate || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  const match = final.match(/^([¥￥]?)(-?[\d,]+(?:\.\d+)?)(.*)$/)
  if (!match) return
  const target = Number(match[2].replaceAll(',', ''))
  if (!Number.isFinite(target)) return
  const digits = (match[2].split('.')[1] || '').length
  const start = performance.now()
  function tick(now) {
    const progress = Math.min(1,(now-start)/640)
    value.value = progress === 1 ? final : `${match[1]}${new Intl.NumberFormat('zh-CN',{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(target*(1-(1-progress)**3))}${match[3]}`
    if (progress<1) frame=requestAnimationFrame(tick)
  }
  frame=requestAnimationFrame(tick)
}, { immediate:true })
onBeforeUnmount(()=>cancelAnimationFrame(frame))
</script>
<template><strong class="shared-value" :data-shared-metric="metric.id" :data-metric-value="metricDisplay(metric)" :aria-label="metricDisplay(metric)"><span class="metric-reserve" aria-hidden="true">{{ metricDisplay(metric) }}</span><span class="metric-count" aria-hidden="true">{{ value }}</span></strong></template>
<style scoped>.shared-value{position:relative;display:inline-block;font-variant-numeric:tabular-nums;font-weight:500;letter-spacing:-.04em;line-height:1.15;color:inherit}.metric-reserve{visibility:hidden}.metric-count{position:absolute;inset:0;white-space:nowrap}</style>
