import { onMounted, onBeforeUnmount } from 'vue'

// Presentation-only observers; never read or mutate audit/request state.
export function useReportReadingMotion(root) {
  let intersection, mutation, resize, media, frame = 0
  let observed = new WeakSet()
  const selector = '.diagnosis-content .flow-stage-heading, .diagnosis-content .dashboard-radar, .diagnosis-content .radar-wrap, .diagnosis-content .seo-core-grid'
  function update() {
    frame = 0
    const report = root.value?.querySelector('.diagnosis-content')
    if (!report) { root.value?.style.setProperty('--report-read', '0'); return }
    const top = report.getBoundingClientRect().top + window.scrollY
    const distance = Math.max(0, report.scrollHeight - window.innerHeight)
    const progress = distance > 0 ? Math.min(1, Math.max(0, (window.scrollY - top) / distance)) : 1
    root.value.style.setProperty('--report-read', String(progress))
  }
  function schedule() { if (!frame) frame = requestAnimationFrame(update) }
  function discover() {
    root.value?.querySelectorAll(selector).forEach(element => {
      if (observed.has(element) || element.classList.contains('report-read-enter') || media.matches) return
      observed.add(element)
      if (!media.matches) intersection?.observe(element)
    })
    schedule()
  }
  function preferenceChanged() {
    if (media.matches) intersection?.disconnect()
    observed = new WeakSet()
    if (!media.matches) discover()
    // Content is never hidden; disabling motion requires no reveal bookkeeping.
  }
  onMounted(() => {
    media = window.matchMedia('(prefers-reduced-motion: reduce)')
    if ('IntersectionObserver' in window) {
      intersection = new IntersectionObserver(entries => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          if (!media.matches) entry.target.classList.add('report-read-enter')
          intersection.unobserve(entry.target)
        }
      }, { threshold:0.08 })
    }
    mutation = new MutationObserver(discover)
    if (root.value) mutation.observe(root.value, {childList:true, subtree:true})
    if ('ResizeObserver' in window && root.value) {
      resize = new ResizeObserver(schedule)
      resize.observe(root.value)
    }
    media.addEventListener('change', preferenceChanged)
    window.addEventListener('scroll', schedule, {passive:true})
    window.addEventListener('resize', schedule)
    discover()
  })
  onBeforeUnmount(() => {
    intersection?.disconnect(); mutation?.disconnect(); resize?.disconnect()
    media?.removeEventListener('change', preferenceChanged)
    window.removeEventListener('scroll', schedule)
    window.removeEventListener('resize', schedule)
    cancelAnimationFrame(frame)
  })
}
