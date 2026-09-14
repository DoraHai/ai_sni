<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import elementalMarksSource from './elemental-marks.html?raw'

const props = defineProps({
  speed: { type: Number, default: 1 },
  size: { type: Number, default: 1 },
  particleAmount: { type: Number, default: 1 },
  opacity: { type: Number, default: 1 },
  hue: { type: Number, default: 0 },
  saturation: { type: Number, default: 1 },
  brightness: { type: Number, default: 1 },
})

const iframeRef = ref(null)
const hostVisible = ref(true)
const documentVisible = ref(typeof document === 'undefined' || !document.hidden)
let observer

const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, Number.isFinite(value) ? value : minimum))

const waterMarkShader = `  // the mark, seen through the surface
  float logo = smoothstep(0.005, -0.005, d);
  float glow = exp(-max(d, 0.0) / 0.09) * 0.26;
  vec3 markCol = mix(vec3(0.55, 0.92, 1.0), vec3(0.95, 1.0, 1.0), logo * 0.6);
  col += markCol * (logo * 0.92 + glow);`

const waterMarkRemovedShader = `  // The cockpit uses the original water simulation without rendering the source mark.
  float logo = 0.0;
  float glow = 0.0;
  col += vec3(0.0);`

function buildFocusedDocument() {
  const zoom = 1.56 / clamp(props.size, 0.65, 1.5)
  const particleCount = Math.max(0, Math.round(160 * clamp(props.particleAmount, 0, 2)))
  const focusStyles = `<style data-elements-focus>
html, body, main { width: 100%; height: 100%; margin: 0; overflow: hidden; background: #060708; }
header, .hint, .info, .kanji { display: none !important; }
main { display: block; }
.panel { display: none; }
.panel[data-fx="water"] {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
  opacity: 1;
  transform: none;
  animation: none;
}
.panel[data-fx="water"] canvas { width: 100%; height: 100%; }
</style>`
  const controls = `<script data-elements-controls>
(function () {
  var nativeNow = performance.now.bind(performance);
  var last = nativeNow();
  var virtual = last;
  var state = { speed: 1, paused: false };
  window.__ELEMENTS_PAUSED = false;
  performance.now = function () {
    var real = nativeNow();
    if (!state.paused) virtual += (real - last) * state.speed;
    last = real;
    return virtual;
  };
  window.addEventListener('message', function (event) {
    if (!event.data) return;
    if (event.data.type === 'elements-controls') {
      var next = event.data.controls || {};
      if (Number.isFinite(next.speed)) state.speed = Math.max(0, Math.min(3, next.speed));
      state.paused = Boolean(next.paused);
      window.__ELEMENTS_PAUSED = state.paused;
      return;
    }
    if (event.data.type === 'elements-pointer') {
      var pointer = event.data.pointer || {};
      var list = typeof panels !== 'undefined' ? panels : [];
      var panel = list.find(function (item) { return item.el && item.el.dataset.fx === 'water'; });
      if (!panel) return;
      if (pointer.leave) {
        panel.pointer.active = 0;
        panel.windTarget = 0;
        window.__ELEMENTS_LAST_POINTER = null;
        return;
      }
      var x = Math.max(0, Math.min(1, Number(pointer.x) || 0));
      var y = Math.max(0, Math.min(1, Number(pointer.y) || 0));
      var now = performance.now();
      var lastPoint = window.__ELEMENTS_LAST_POINTER;
      panel.pointer.x = x;
      panel.pointer.y = y;
      panel.pointer.active = pointer.pulse ? 1.9 : pointer.down ? 1.35 : 0.88;
      if (pointer.down && panel.opts.sim) {
        panel.dropQueue.push({ x: x, y: y, s: pointer.pulse ? 0.72 : 0.48 });
      } else if (lastPoint) {
        var dt = Math.max(8, now - lastPoint.t);
        var dx = x - lastPoint.x;
        var dy = y - lastPoint.y;
        var speed = Math.hypot(dx, dy) / (dt / 1000);
        if (panel.opts.sim && speed > 0.05 && panel.dropQueue.length < 6)
          panel.dropQueue.push({ x: x, y: y, s: Math.min(speed * 0.075, 0.28) });
        panel.windTarget = Math.max(-1, Math.min(1, dx / (dt / 1000) * 0.26));
      }
      window.__ELEMENTS_LAST_POINTER = { x: x, y: y, t: now };
    }
  });
})();
<\/script>`

  return elementalMarksSource
    .replace(/<link[^>]+fonts\.googleapis\.com[^>]*>/gi, '')
    .replace(/<link[^>]+fonts\.gstatic\.com[^>]*>/gi, '')
    .replace(waterMarkShader, waterMarkRemovedShader)
    .replace('</head>', `${focusStyles}${controls}</head>`)
    .replace('count: 160', `count: ${particleCount}`)
    .replace('zoom: 1.06', `zoom: ${zoom.toFixed(4)}`)
    .replace(
      'for (const p of panels) p.draw(t);',
      'if (!window.__ELEMENTS_PAUSED) for (const p of panels) p.draw(t);',
    )
}

const source = computed(buildFocusedDocument)
const paused = computed(() => !hostVisible.value || !documentVisible.value)
const filter = computed(() => `hue-rotate(${clamp(props.hue, -180, 180)}deg) saturate(${clamp(props.saturation, 0, 2)}) brightness(${clamp(props.brightness, 0.35, 1.8)})`)

function postControls() {
  iframeRef.value?.contentWindow?.postMessage({
    type: 'elements-controls',
    controls: { speed: clamp(props.speed, 0, 3), paused: paused.value },
  }, '*')
}

function postPointer(event, options = {}) {
  const iframe = iframeRef.value
  const target = iframe?.contentWindow
  if (!iframe || !target) return
  if (options.leave) {
    target.postMessage({ type: 'elements-pointer', pointer: { leave: true } }, '*')
    return
  }
  const rect = iframe.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  target.postMessage({
    type: 'elements-pointer',
    pointer: {
      x: clamp((event.clientX - rect.left) / rect.width, 0, 1),
      y: clamp(1 - ((event.clientY - rect.top) / rect.height), 0, 1),
      down: Boolean(options.down),
      pulse: Boolean(options.pulse),
    },
  }, '*')
}

function updateDocumentVisible() {
  documentVisible.value = !document.hidden
}

onMounted(() => {
  if (typeof IntersectionObserver !== 'undefined' && iframeRef.value) {
    observer = new IntersectionObserver(([entry]) => { hostVisible.value = entry?.isIntersecting ?? true })
    observer.observe(iframeRef.value)
  }
  document.addEventListener('visibilitychange', updateDocumentVisible)
  postControls()
})

onBeforeUnmount(() => {
  observer?.disconnect()
  document.removeEventListener('visibilitychange', updateDocumentVisible)
})

watch([paused, () => props.speed, source], postControls)

defineExpose({
  postPointer,
})
</script>

<template>
  <div class="threeui-water-background" aria-hidden="true">
    <iframe
      ref="iframeRef"
      title="Water element background"
      :srcdoc="source"
      sandbox="allow-scripts"
      tabindex="-1"
      :style="{ opacity: clamp(opacity, 0.05, 1), filter }"
      @load="postControls"
    />
  </div>
</template>

<style scoped>
.threeui-water-background{
  position:absolute;
  inset:0;
  overflow:hidden;
  background:#060708;
  pointer-events:auto;
}
.threeui-water-background iframe{
  position:absolute;
  inset:0;
  display:block;
  width:100%;
  height:100%;
  border:0;
  background:#060708;
}
</style>
