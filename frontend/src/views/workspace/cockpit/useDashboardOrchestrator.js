import { ref, nextTick, onBeforeUnmount } from 'vue'
import { createCommandEpoch, createDashboardPlan, MOTION } from './dashboard-orchestrator.mjs'

// One owner for intent, cancellation, layout transitions and background feedback.
export function useDashboardOrchestrator({ root, pulse, getData }) {
  const dashboardMode = ref('overview'), aiState = ref('idle'), plan = ref(null), returning = ref(false)
  const epoch = createCommandEpoch(), animations = new Set(), sleepers = new Map(), cleanups = new Set()
  let sources = new Map(), overviewScroll = 0, scanStarted = 0
  const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches
  function sleep(ms) { return new Promise(resolve => { const timer = setTimeout(() => { sleepers.delete(timer); resolve() }, reduced() ? 0 : ms); sleepers.set(timer, resolve) }) }
  function animate(element, frames, options) {
    if (!element?.animate || reduced()) return Promise.resolve()
    const animation = element.animate(frames, { easing: 'cubic-bezier(.2,.8,.2,1)', ...options })
    animations.add(animation)
    return animation.finished.catch(() => {}).finally(() => { animations.delete(animation); animation.cancel() })
  }
  function reset() {
    epoch.cancel()
    for (const [timer, resolve] of sleepers) { clearTimeout(timer); resolve() }
    sleepers.clear()
    for (const animation of animations) animation.cancel()
    animations.clear()
    for (const cleanup of cleanups) cleanup()
    cleanups.clear()
    sources.clear(); plan.value = null; dashboardMode.value = 'overview'; aiState.value = 'idle'; returning.value = false
  }
  function capture() {
    const map = new Map(), bounds = root.value?.getBoundingClientRect()
    if (!bounds) return map
    for (const element of root.value.querySelectorAll('[data-shared-metric]')) {
      const rect = element.getBoundingClientRect()
      if (!rect.width || !rect.height || rect.bottom < bounds.top || rect.top > bounds.bottom || rect.right < bounds.left || rect.left > bounds.right) continue
      const id = element.dataset.sharedMetric
      if (!map.has(id)) map.set(id, { rect, text: element.dataset.metricValue || element.textContent, color: getComputedStyle(element).color, font: getComputedStyle(element).font })
    }
    return map
  }
  async function sharedFlight(from, duration) {
    if (reduced()) return
    const jobs = [], seen = new Set()
    for (const target of root.value?.querySelectorAll('[data-shared-metric]') || []) {
      const id = target.dataset.sharedMetric, source = from.get(id), rect = target.getBoundingClientRect()
      if (!source || seen.has(id) || !rect.width || !rect.height) continue
      seen.add(id)
      const ghost = document.createElement('span')
      ghost.setAttribute('aria-hidden', 'true')
      ghost.className = 'shared-metric-flight'
      ghost.textContent = source.text
      Object.assign(ghost.style, { position: 'fixed', left: `${source.rect.left}px`, top: `${source.rect.top}px`, width: `${source.rect.width}px`, height: `${source.rect.height}px`, font: source.font, color: source.color, zIndex: '100', pointerEvents: 'none', transformOrigin: 'top left', whiteSpace: 'nowrap' })
      document.body.appendChild(ghost)
      const oldVisibility = target.style.visibility
      target.style.visibility = 'hidden'
      const cleanup = () => { target.style.visibility = oldVisibility; ghost.remove(); cleanups.delete(cleanup) }
      cleanups.add(cleanup)
      jobs.push(animate(ghost, [{ transform: 'translate(0,0) scale(1)', opacity: 1 }, { transform: `translate(${rect.left-source.rect.left}px,${rect.top-source.rect.top}px) scale(${rect.width/source.rect.width},${rect.height/source.rect.height})`, opacity: 1 }], { duration }).finally(cleanup))
    }
    await Promise.all(jobs)
  }
  function ripple() { if (!reduced()) pulse() }
  async function commandFlow() {
    if (reduced()) return
    const source = document.querySelector('.composer button'), destination = root.value
    if (!source || !destination) return
    const a = source.getBoundingClientRect(), b = destination.getBoundingClientRect()
    const dot = document.createElement('i')
    dot.setAttribute('aria-hidden', 'true')
    Object.assign(dot.style, { position:'fixed', left:`${a.left+a.width/2}px`, top:`${a.top+a.height/2}px`, width:'5px', height:'5px', borderRadius:'50%', background:'#8bccff', boxShadow:'0 0 14px #64baff', pointerEvents:'none', zIndex:'90' })
    document.body.appendChild(dot)
    const cleanup = () => { dot.remove(); cleanups.delete(cleanup) }; cleanups.add(cleanup)
    await animate(dot, [{ opacity:0,transform:'translate(0,0)' },{opacity:.75,offset:.3},{opacity:0,transform:`translate(${b.left+b.width*.45-a.left}px,${b.top+b.height*.3-a.top}px)`}],{duration:400})
    cleanup()
  }
  function begin(text) {
    const from = capture(), previousMode = dashboardMode.value, previousPlan = plan.value
    if (previousMode === 'overview') overviewScroll = root.value?.scrollTop || 0
    reset()
    // Keep the current view visible while scanning instead of swapping components immediately.
    dashboardMode.value = previousMode; plan.value = previousPlan; sources = from
    const ticket = epoch.next()
    aiState.value = 'thinking'
    commandFlow()
    sleep(MOTION.thinking).then(() => { if (epoch.current(ticket)) { aiState.value = 'scanning'; scanStarted = performance.now(); ripple() } })
    return ticket
  }
  async function present(ticket, text, command) {
    // Network latency is real: keep scanning until evidence is available.
    if (!epoch.current(ticket)) return false
    if (aiState.value === 'thinking') await sleep(MOTION.thinking)
    if (!epoch.current(ticket)) return false
    await sleep(Math.max(0, MOTION.scanning - (performance.now() - scanStarted)))
    if (!epoch.current(ticket)) return false
    const outgoing = [...(root.value?.querySelectorAll('.signal-kpis > button, .command-panel, .floating-metric') || [])]
      .filter(element => { const rect = element.getBoundingClientRect(); const bounds = root.value.getBoundingClientRect(); return rect.height && rect.bottom > bounds.top && rect.top < bounds.bottom })
    await Promise.all(outgoing.slice(0, 14).map((element, index) => animate(element, [{ opacity: 1, filter: 'blur(0px)' }, { opacity: 0, filter: 'blur(8px)' }], { duration: 240, delay: Math.min(index, 6) * 60, fill: 'forwards' })))
    if (!epoch.current(ticket)) return false
    const next = createDashboardPlan({ text, command, ...getData() })
    aiState.value = 'assembling'; plan.value = next; dashboardMode.value = next.mode
    await nextTick()
    if (!epoch.current(ticket)) return false
    if (root.value) root.value.scrollTop = 0
    ripple()
    await Promise.all([sharedFlight(sources, 720), sleep(MOTION.assemble)])
    if (!epoch.current(ticket)) return false
    sources.clear(); aiState.value = 'ready'
    return true
  }
  async function returnOverview() {
    const from = capture()
    const ticket = epoch.next()
    for (const animation of animations) animation.cancel()
    for (const cleanup of cleanups) cleanup()
    returning.value = true; aiState.value = 'assembling'
    await sleep(280)
    if (!epoch.current(ticket)) return
    dashboardMode.value = 'overview'; plan.value = null
    await nextTick()
    if (!epoch.current(ticket)) return
    if (root.value) root.value.scrollTop = overviewScroll
    ripple()
    await sharedFlight(from, MOTION.return)
    if (!epoch.current(ticket)) return
    returning.value = false; aiState.value = 'idle'
  }
  onBeforeUnmount(reset)
  return { dashboardMode, aiState, plan, returning, begin, present, reset, returnOverview, isCurrent: epoch.current }
}
