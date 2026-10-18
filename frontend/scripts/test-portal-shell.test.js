import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import DealSniperShell from '../src/views/deal/DealSniperShell.vue'

const { route } = vi.hoisted(() => ({ route: { path: '/deal-sniper/portal', params: {} } }))
vi.mock('vue-router', () => ({ useRoute: () => reactive(route) }))

let wrapper
beforeEach(() => {
  vi.useFakeTimers()
  route.path = '/deal-sniper/portal'
  route.params = {}
})
afterEach(() => {
  wrapper?.unmount()
  vi.useRealTimers()
})

function frameDocument(doc) {
  Object.defineProperty(wrapper.get('iframe').element, 'contentDocument', { configurable: true, value: doc })
}
function portalDocument() {
  const doc = document.implementation.createHTMLDocument()
  doc.body.innerHTML = '<div class="hero"><h1>平台门户</h1></div><div class="cards"><a class="module">SEO 模块</a></div>'
  return doc
}

describe('portal frame recovery', () => {
  it('shows useful content while loading, then reveals the actual portal', async () => {
    wrapper = mount(DealSniperShell)
    expect(wrapper.text()).toContain('正在打开平台门户')
    expect(wrapper.get('a').attributes('href')).toBe('/deal-sniper-prototype/index.html?rev=portal-20260809-v1')
    frameDocument(portalDocument())
    await wrapper.get('iframe').trigger('load')
    expect(wrapper.find('.portal-status').exists()).toBe(false)
    expect(wrapper.get('iframe').classes()).not.toContain('portal-pending')
    expect(vi.getTimerCount()).toBe(0)
  })

  it.each(['blocked', '404', 'empty SPA'])('recovers from a %s frame without trusting the load event', async kind => {
    wrapper = mount(DealSniperShell)
    const doc = document.implementation.createHTMLDocument()
    doc.body.innerHTML = kind === '404' ? '<h1>404 Not Found</h1>' : '<div id="app"></div>'
    frameDocument(kind === 'blocked' ? null : doc)
    await wrapper.get('iframe').trigger('load')
    expect(wrapper.text()).toContain('平台门户暂时无法显示')
    expect(wrapper.text()).toContain('请联系平台管理员处理')
    expect(wrapper.get('iframe').classes()).toContain('portal-pending')
  })

  it('offers retry after a timeout and can recover when the next load succeeds', async () => {
    wrapper = mount(DealSniperShell)
    const oldFrame = wrapper.get('iframe').element
    await vi.advanceTimersByTimeAsync(10000)
    expect(wrapper.text()).toContain('平台门户暂时无法显示')
    await wrapper.get('button').trigger('click')
    expect(wrapper.text()).toContain('正在打开平台门户')
    expect(wrapper.get('iframe').element).not.toBe(oldFrame)
    frameDocument(portalDocument())
    await wrapper.get('iframe').trigger('load')
    expect(wrapper.find('.portal-status').exists()).toBe(false)
  })

  it('cleans up the pending timeout on unmount', () => {
    wrapper = mount(DealSniperShell)
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
    wrapper = null
  })

  it('preserves other prototype pages', async () => {
    route.path = '/deal-sniper/geo/dashboard'
    route.params = { section: 'geo', page: 'dashboard' }
    wrapper = mount(DealSniperShell)
    expect(wrapper.get('iframe').attributes('src')).toBe('/deal-sniper-prototype/geo/dashboard.html')
    expect(wrapper.find('.portal-status').exists()).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
  })
})
