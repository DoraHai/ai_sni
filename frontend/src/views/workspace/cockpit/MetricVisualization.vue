<script setup>
import { computed, ref, useId, watch } from 'vue'
import { visualizationIndexAfterKey } from './visualization-model.mjs'

const props = defineProps({ visualization: { type: Object, required: true }, metricLabel: { type: String, required: true } })
const emit = defineEmits(['select'])
const visualId = useId()
const selectedIndex = ref(0)
const finite = value => typeof value === 'number' && Number.isFinite(value)
const points = computed(() => props.visualization.type === 'trend' ? props.visualization.points : [])
const items = computed(() => props.visualization.type === 'trend' ? points.value : (props.visualization.stages || props.visualization.items || []))
const usable = computed(() => points.value.filter(point => finite(point.value)))
const low = computed(() => Math.min(0, ...usable.value.map(point => point.value)))
const high = computed(() => Math.max(1, ...usable.value.map(point => point.value)))
const coords = computed(() => points.value.map((point, index) => ({
  ...point, x: 12 + index * 276 / Math.max(1, points.value.length - 1),
  y: finite(point.value) ? 76 - (point.value - low.value) * 60 / (high.value - low.value) : null,
})))
const segments = computed(() => {
  const result = []; let current = []
  for (const point of coords.value) {
    if (point.y === null) { if (current.length) result.push(current); current = [] }
    else current.push(`${point.x},${point.y}`)
  }
  if (current.length) result.push(current)
  return result.map(segment => segment.join(' '))
})
const maxValue = computed(() => Math.max(1, ...items.value.filter(item => finite(item.value)).map(item => item.value)))
const selectedItem = computed(() => items.value[selectedIndex.value] || null)
function select(index, activate = true) {
  if (!items.value.length) return
  selectedIndex.value = Math.max(0, Math.min(items.value.length - 1, index))
  if (activate) emit('select', selectedItem.value)
}
function onKeydown(event) {
  if (!items.value.length) return
  if (['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown', 'Home', 'End'].includes(event.key)) { event.preventDefault(); select(visualizationIndexAfterKey(selectedIndex.value, items.value.length, event.key), false) }
  else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(selectedIndex.value, true) }
}
watch(() => props.visualization, () => { selectedIndex.value = 0 })
</script>

<template>
  <section class="metric-visual" :class="`visual-${visualization.type}`" tabindex="0" role="listbox" :aria-label="`${metricLabel}图形；方向键选择，回车确认`" :aria-activedescendant="selectedItem ? `visual-${visualId}-${visualization.type}-${selectedItem.key}` : undefined" @keydown="onKeydown">
    <template v-if="visualization.type === 'trend'">
      <svg v-if="usable.length" viewBox="0 0 300 90" class="trend" role="img" :aria-label="`${metricLabel}趋势，缺失日期不连线`">
        <path d="M12 76H288" class="baseline" /><polyline v-for="(segment, index) in segments" :key="index" :points="segment" class="trend-line" />
        <template v-for="(point, index) in coords" :key="point.key"><circle v-if="point.y !== null" :cx="point.x" :cy="point.y" :r="selectedIndex === index ? 5 : 3" class="trend-point"><title>{{ point.label }}：{{ point.display }}</title></circle></template>
      </svg><p v-else class="empty-visual">当前周期没有可绘制的观测点。</p>
      <div class="point-controls"><button v-for="(point, index) in points" :id="`visual-${visualId}-trend-${point.key}`" :key="point.key" type="button" tabindex="-1" role="option" :aria-label="`${point.label}：${point.display}`" :aria-selected="selectedIndex === index" @pointerenter="select(index, false)" @click="select(index)"></button></div>
      <p class="coverage" :class="`coverage-${visualization.coverage?.state}`">{{ visualization.coverage?.label }}</p>
    </template>
    <template v-else-if="visualization.type === 'funnel'">
      <div v-if="items.length" class="funnel-stages"><button v-for="(item, index) in items" :id="`visual-${visualId}-funnel-${item.key}`" :key="item.key" type="button" tabindex="-1" role="option" :aria-selected="selectedIndex === index" @pointerenter="select(index, false)" @click="select(index)"><span>{{ item.label }}</span><b>{{ item.display }}</b><i :style="{ width: `${Math.max(4, item.value / maxValue * 100)}%` }"></i></button></div>
      <p class="rate-copy">{{ visualization.rateLabel }}</p><p class="coverage">{{ visualization.coverage?.label }}</p>
    </template>
    <template v-else-if="visualization.type === 'distribution'">
      <div v-if="items.length" class="distribution"><button v-for="(item, index) in items" :id="`visual-${visualId}-distribution-${item.key}`" :key="item.key" type="button" tabindex="-1" role="option" :aria-selected="selectedIndex === index" @pointerenter="select(index, false)" @click="select(index)"><span>{{ item.label }}</span><i><em :style="{ width: `${Math.max(3, item.value / maxValue * 100)}%` }"></em></i><b>{{ item.display }}</b></button></div>
      <p class="coverage">{{ visualization.note }}</p>
    </template>
    <p v-if="selectedItem" class="visual-readout" aria-live="polite">当前选择 {{ selectedItem.label }} · {{ selectedItem.display }}</p>
  </section>
</template>

<style scoped>
.metric-visual{position:relative;margin-top:10px;padding:4px;border-radius:9px;color:#9daec0}.metric-visual:focus-visible{outline:2px solid #8ce2f1;outline-offset:2px}.trend{display:block;width:100%;height:90px;overflow:visible}.baseline{stroke:#29384b;fill:none}.trend-line{stroke:#67ddca;stroke-width:2.2;fill:none;stroke-linecap:round;stroke-linejoin:round}.trend-point{fill:#67ddca}.point-controls{position:absolute;inset:4px 4px 46px;display:flex}.point-controls button{flex:1;min-width:0;border:0;background:transparent;cursor:crosshair}.coverage,.rate-copy,.visual-readout,.empty-visual{margin:6px 0 0;font-size:10px;line-height:1.45}.coverage-partial,.rate-copy{color:#e5ba70}.empty-visual{min-height:55px;display:grid;place-items:center}.funnel-stages{display:grid;gap:7px}.funnel-stages button{position:relative;display:grid;grid-template-columns:1fr auto;gap:8px;overflow:hidden;padding:9px 10px;border:1px solid #2c4558;border-radius:9px;background:#0d1d2a;color:#c8d8e3;text-align:left;cursor:pointer}.funnel-stages button i{position:absolute;left:0;bottom:0;height:2px;background:#67ddca}.funnel-stages button:nth-child(2) i{background:#6f9ee8}.funnel-stages span{font-size:10px}.funnel-stages b{font-size:11px}.distribution{display:grid;gap:6px}.distribution button{display:grid;grid-template-columns:80px 1fr 48px;align-items:center;gap:7px;padding:3px 0;border:0;background:transparent;color:#a9bdca;text-align:left;cursor:pointer}.distribution span,.distribution b{font-size:9px}.distribution b{text-align:right}.distribution i{height:5px;border-radius:4px;background:#253849;overflow:hidden}.distribution em{display:block;height:100%;border-radius:inherit;background:#6f9ee8}.metric-visual button[aria-selected=true]{color:#eafffb}.visual-readout{color:#d4e8ef}@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
