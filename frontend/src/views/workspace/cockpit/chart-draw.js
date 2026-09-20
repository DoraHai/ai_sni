import { computed, inject } from 'vue'
import './chart-draw.css'
export const chartDrawScope = Symbol('cockpit-chart-draw-scope')
export function useChartDrawKey(local = () => '') {
  const scope = inject(chartDrawScope, null)
  return computed(() => [scope?.value, local()])
}
const states = new WeakMap()
const equal = (a,b) => Array.isArray(a) && Array.isArray(b) ? a.length === b.length && a.every((v,i)=>Object.is(v,b[i])) : Object.is(a,b)
const waiting = new Set()
let frame = null
function finish(el, state) {
  waiting.delete(el)
  state.observer?.disconnect()
  state.observer=null
  clearTimeout(state.timer)
  el.classList.remove('chart-draw-wait','chart-draw-active')
  el.dataset.drawState = 'complete'
}
function enqueue(el) {
  waiting.add(el)
  if(frame !== null) return
  frame = requestAnimationFrame(() => {
    frame = null
    const batch = [...waiting].sort((a,b)=>a.getBoundingClientRect().top-b.getBoundingClientRect().top || a.getBoundingClientRect().left-b.getBoundingClientRect().left)
    waiting.clear()
    batch.forEach((node,i)=>{
      const state=states.get(node)
      if(!state || state.media?.matches) return
      const delay=Math.min(i,4)*45
      node.style.setProperty('--draw-delay',`${delay}ms`)
      node.classList.remove('chart-draw-wait')
      node.classList.add('chart-draw-active')
      node.dataset.drawState='drawing'
      state.timer=setTimeout(()=>finish(node,state),1500+delay)
    })
  })
}
function arm(el, state, key) {
  finish(el,state)
  state.key=key
  if(state.media?.matches || typeof IntersectionObserver==='undefined' || typeof requestAnimationFrame==='undefined') return
  el.classList.add('chart-draw-wait')
  el.dataset.drawState='waiting'
  const observer = new IntersectionObserver(entries=>{
    if(states.get(el)!==state || state.observer!==observer)return
    if(entries.some(e=>e.isIntersecting && e.intersectionRatio>0)){
      state.observer.disconnect()
      state.observer=null
      enqueue(el)
    }
  },{threshold:0.01})
  state.observer=observer
  observer.observe(el.querySelector('.chart-surface, .china-map, .heatmap-wrap, .micro-visual, .coverage-rings, .distribution, .funnel-stages, .touch-flow') || el)
}
export const vChartDraw = {
  mounted(el,binding) {
    const state={key:binding.value, media:window.matchMedia?.('(prefers-reduced-motion: reduce)')}
    states.set(el,state)
    state.reduce=()=>{if(state.media.matches)finish(el,state)}
    state.interact=()=>finish(el,state)
    state.media?.addEventListener?.('change',state.reduce)
    el.addEventListener('focusin',state.interact)
    el.addEventListener('pointerdown',state.interact)
    arm(el,state,binding.value)
  },
  updated(el,binding) {const state=states.get(el);if(state && !equal(state.key,binding.value))arm(el,state,binding.value)},
  beforeUnmount(el) {
    const state=states.get(el);if(!state)return
    finish(el,state)
    state.media?.removeEventListener?.('change',state.reduce)
    el.removeEventListener('focusin',state.interact)
    el.removeEventListener('pointerdown',state.interact)
    states.delete(el)
    if(!waiting.size && frame!==null){cancelAnimationFrame(frame);frame=null}
  },
}
