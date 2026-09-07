<script setup>
import { computed, ref, watch } from 'vue'

// Only accepts already-scoped, formatted data from a module adapter.
// No demo defaults, network requests, HTML injection or inferred attribution.
const props = defineProps({
  metric: { type: Object, required: true },
  contextRevision: { type: [String, Number], required: true },
})
const emit = defineEmits(['discuss', 'retry'])
const dialog = ref(null)
const selected = ref(null)
const trigger = ref(null)
const finite = value => typeof value === 'number' && Number.isFinite(value)
const points = computed(() => Array.isArray(props.metric.series) ? props.metric.series : [])
const usable = computed(() => points.value.filter(point => finite(point.value)))
const low = computed(() => Math.min(0, ...usable.value.map(point => point.value)))
const high = computed(() => Math.max(1, ...usable.value.map(point => point.value)))
const coords = computed(() => points.value.map((point, index) => ({
  ...point,
  x: 12 + index * 276 / Math.max(1, points.value.length - 1),
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
const status = computed(() => ({ loading: '读取中', available: '已读取', partial: '部分数据',
  no_data: '暂无数据', unavailable: '暂不可用', denied: '无查看权限' }[props.metric.state] ?? '待核验'))
const activePoint = computed(() => points.value[selected.value] ?? null)
const rows = computed(() => Array.isArray(props.metric.rows) ? props.metric.rows : [])
const columns = computed(() => Array.isArray(props.metric.columns) ? props.metric.columns : [])
const canDiscuss = computed(() => ['available', 'partial'].includes(props.metric.state))
function open() { dialog.value?.showModal() }
function close() { dialog.value?.close() }
function discuss() {
  if (!canDiscuss.value) return
  // Pass an object reference and revision; the parent resolves current evidence again.
  emit('discuss', { metricId: props.metric.id, contextRevision: props.contextRevision })
  close()
}
watch(() => props.contextRevision, () => { selected.value = null; close() }, { flush: 'sync' })
watch(() => props.metric, () => { selected.value = null; close() }, { flush: 'sync' })
</script>

<template>
  <article class="evidence-card" :class="`is-${metric.state}`" :aria-busy="metric.state === 'loading'">
    <div class="card-heading"><span class="module-name">{{ metric.moduleLabel }}</span><span class="read-status">{{ status }}</span></div>
    <button ref="trigger" class="metric-trigger" type="button" aria-haspopup="dialog" @click="open">
      <span class="metric-title">{{ metric.label }}</span>
      <span class="metric-number">{{ metric.display ?? '—' }}<small v-if="metric.unit">{{ metric.unit }}</small></span>
      <span v-if="metric.changeLabel" class="metric-change">{{ metric.changeLabel }}</span>
      <span class="expand-hint">查看明细 ↗</span>
    </button>
    <div v-if="usable.length" class="trend-wrap">
      <svg viewBox="0 0 300 90" class="trend" role="img" :aria-label="`${metric.label}趋势，缺失日期不连线`">
        <path d="M12 76H288" class="baseline" />
        <polyline v-for="(segment, index) in segments" :key="index" :points="segment" class="trend-line" />
        <template v-for="(point, index) in coords" :key="index">
          <circle v-if="point.y !== null" :cx="point.x" :cy="point.y" :r="selected === index ? 5 : 3" class="trend-point">
            <title>{{ point.label }}：{{ point.display ?? point.value }}</title>
          </circle>
        </template>
      </svg>
      <div class="point-controls" aria-label="逐期查看趋势数据">
        <button v-for="(point, index) in points" :key="index" type="button" :aria-label="`${point.label}：${point.display ?? (finite(point.value) ? point.value : '暂无数据')}`"
          :aria-pressed="selected === index" @focus="selected = index" @pointerenter="selected = index" @click="selected = index">
          <span>{{ point.label }}</span>
        </button>
      </div>
      <p class="point-readout" aria-live="polite">{{ activePoint ? `${activePoint.label} · ${activePoint.display ?? (finite(activePoint.value) ? activePoint.value : '暂无数据')}` : '移到趋势上查看每期数据' }}</p>
    </div>
    <p v-else class="empty-trend">{{ metric.reason || '当前没有可展示的趋势数据' }}</p>
    <div class="card-footer"><span>{{ metric.periodLabel || '统计周期待确认' }}</span><button type="button" :disabled="!canDiscuss" @click="discuss">就这项提问 ↗</button></div>

    <dialog ref="dialog" class="evidence-dialog" @click="event => { if (event.target === dialog) close() }" @close="trigger?.focus()">
      <header><div><span class="module-name">{{ metric.moduleLabel }} · {{ status }}</span><h2>{{ metric.label }}</h2></div><button type="button" class="close-button" aria-label="关闭明细" @click="close">×</button></header>
      <div class="detail-value">{{ metric.display ?? '—' }}<small v-if="metric.unit">{{ metric.unit }}</small></div>
      <p v-if="metric.reason" class="detail-reason">{{ metric.reason }}</p>
      <dl class="evidence-meta"><div><dt>统计范围</dt><dd>{{ metric.periodLabel || '未提供' }}</dd></div><div><dt>数据来源</dt><dd>{{ metric.sourceLabel || '未提供' }}</dd></div><div><dt>更新时间</dt><dd>{{ metric.updatedLabel || '未知' }}</dd></div></dl>
      <div v-if="rows.length && columns.length" class="detail-table"><table><thead><tr><th v-for="column in columns" :key="column.key" scope="col">{{ column.label }}</th></tr></thead><tbody><tr v-for="(row, index) in rows" :key="index"><td v-for="column in columns" :key="column.key">{{ row[column.key] ?? '—' }}</td></tr></tbody></table></div>
      <p v-else class="detail-empty">{{ metric.detailEmptyLabel || '当前没有明细记录' }}</p>
      <footer><button v-if="metric.state === 'unavailable'" type="button" @click="emit('retry', metric.id)">重新读取</button><button type="button" class="discuss-button" :disabled="!canDiscuss" @click="discuss">带着这项数据继续提问 ↗</button></footer>
    </dialog>
  </article>
</template>

<style scoped>
.evidence-card{--signal:#67ddca;position:relative;min-width:0;padding:22px;border:1px solid #27374c;border-radius:22px;background:linear-gradient(150deg,#142335,#0d1725);color:#e9f2fa;transition:transform .22s,border-color .22s,box-shadow .22s;font-variant-numeric:tabular-nums}
.evidence-card:hover{transform:translateY(-3px);border-color:#47647d;box-shadow:0 16px 42px #040a1240}.card-heading,.card-footer{display:flex;align-items:center;justify-content:space-between;gap:12px}.module-name{font-size:11px;letter-spacing:.08em;color:#9baec0}.read-status{font-size:11px;color:var(--signal);display:flex;align-items:center;gap:6px}.read-status:before{content:'';width:5px;height:5px;border-radius:50%;background:currentColor}.is-partial{--signal:#e5ba70}.is-denied,.is-no_data,.is-unavailable{--signal:#a5b3c3}.metric-trigger{width:100%;position:relative;text-align:left;border:0;background:none;color:inherit;padding:22px 0 8px;cursor:pointer}.metric-title{display:block;font-size:14px;color:#b2c2d2}.metric-number{display:block;font-size:clamp(30px,3.2vw,46px);font-weight:650;letter-spacing:-.04em;line-height:1.4}.metric-number small,.detail-value small{font-size:14px;font-weight:400;margin-left:7px;color:#adbed0;letter-spacing:0}.metric-change{font-size:12px;color:#c0cfdc}.expand-hint{position:absolute;right:0;bottom:12px;color:#9baec0;font-size:11px}.trend-wrap{position:relative;margin-top:10px}.trend{display:block;width:100%;height:90px;overflow:visible}.baseline{stroke:#29384b;fill:none}.trend-line{stroke:var(--signal);stroke-width:2.3;fill:none;stroke-linecap:round;stroke-linejoin:round}.trend-point{fill:var(--signal);transition:r .16s}.point-controls{position:absolute;inset:0 0 24px;display:flex}.point-controls button{flex:1;min-width:0;border:0;background:transparent;cursor:crosshair;color:transparent}.point-controls span{position:absolute;width:1px;height:1px;overflow:hidden}.point-readout{font-size:11px;min-height:16px;color:#9daec0;margin:5px 0 0}.empty-trend{min-height:70px;display:flex;align-items:center;font-size:12px;color:#98aabc}.card-footer{margin-top:16px;padding-top:14px;border-top:1px solid #253447;font-size:11px;color:#a1b4c6}.card-footer button{border:0;background:none;color:#9de5db;cursor:pointer;font-size:12px;padding:5px 0}button:disabled{opacity:.45;cursor:not-allowed}button:focus-visible{outline:2px solid #8ce2f1;outline-offset:4px;border-radius:5px}.evidence-dialog{box-sizing:border-box;width:min(850px,94vw);max-height:86vh;padding:28px;border:1px solid #3d526a;border-radius:24px;background:#101c2b;color:#e9f2fa;box-shadow:0 30px 100px #0009}.evidence-dialog::backdrop{background:#020813aa;backdrop-filter:blur(8px)}.evidence-dialog header{display:flex;justify-content:space-between;align-items:flex-start;gap:20px}.evidence-dialog h2{font-size:22px;margin:10px 0}.close-button{border:1px solid #3a4d64;background:#1a293b;color:inherit;border-radius:50%;width:34px;height:34px;font-size:22px;cursor:pointer}.detail-value{font-size:48px;letter-spacing:-.03em;margin:20px 0}.detail-reason{color:#e6c489;font-size:13px;line-height:1.7}.evidence-meta{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;padding:18px 0;border-top:1px solid #2c3c50;border-bottom:1px solid #2c3c50}.evidence-meta dt{font-size:11px;color:#97aabf}.evidence-meta dd{margin:8px 0 0;font-size:13px;overflow-wrap:anywhere}.detail-table{overflow:auto;margin:20px 0}table{border-collapse:collapse;width:100%;font-size:13px;text-align:left}th,td{padding:13px 14px;border-bottom:1px solid #2a394c;white-space:nowrap}th{color:#a8bbce;font-weight:500}.detail-empty{color:#a8bbce;padding:30px 0;font-size:13px}.evidence-dialog footer{display:flex;justify-content:flex-end;gap:12px}.evidence-dialog footer button{padding:12px 18px;border:1px solid #436474;border-radius:12px;background:#1e4149;color:#d7fffa;cursor:pointer}.is-loading .metric-number{opacity:.4;animation:breathe 1.6s ease-in-out infinite}@keyframes breathe{50%{opacity:.8}}@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}.evidence-card:hover{transform:none}}@media(max-width:600px){.evidence-meta{grid-template-columns:1fr}.evidence-dialog{padding:20px}.metric-number{font-size:34px}}
</style>
