import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { useDashboardOrchestrator } from './useDashboardOrchestrator.js'
let host, control, reduced = false
beforeEach(() => {
 vi.useFakeTimers()
 vi.stubGlobal('matchMedia', () => ({ matches: reduced }))
 host = mount(defineComponent({ setup() {
   const root = ref(null)
   control = useDashboardOrchestrator({ root, pulse:vi.fn(), getData:()=>({cards:[],modules:[],revision:1}) })
   return () => h('div',{ref:root})
 }}))
})
afterEach(() => { host.unmount(); vi.useRealTimers(); vi.unstubAllGlobals(); reduced=false })
test('cancel during scanning invalidates pending result and restores overview', async () => {
 const ticket=control.begin('SEM'), pending=control.present(ticket,'SEM',{})
 await vi.advanceTimersByTimeAsync(180)
 expect(control.aiState.value).toBe('scanning')
 control.reset(); await vi.runAllTimersAsync()
 expect(await pending).toBe(false)
 expect(control.dashboardMode.value).toBe('overview'); expect(control.plan.value).toBe(null)
})
test('new question wins over an older delayed response', async () => {
 const old=control.begin('SEM')
 const next=control.begin('GEO'), pending=control.present(next,'GEO',{})
 expect(await control.present(old,'SEM',{})).toBe(false)
 await vi.runAllTimersAsync(); expect(await pending).toBe(true)
 expect(control.dashboardMode.value).toBe('geo-focus'); expect(control.aiState.value).toBe('ready')
})
test('return round trip clears focus; new scope reset cancels return safely', async () => {
 const ticket=control.begin('SEM'), pending=control.present(ticket,'SEM',{})
 await vi.runAllTimersAsync(); await pending
 const back=control.returnOverview(); await vi.runAllTimersAsync(); await back
 expect(control.dashboardMode.value).toBe('overview'); expect(control.returning.value).toBe(false)
 const next=control.begin('GEO'), response=control.present(next,'GEO',{})
 await vi.runAllTimersAsync(); await response
 const interrupted=control.returnOverview(); control.reset()
 await vi.runAllTimersAsync(); await interrupted
 expect(control.aiState.value).toBe('idle'); expect(control.plan.value).toBe(null)
})
test('reduced motion still reaches ready and returns with the same evidence state', async () => {
 reduced=true
 const ticket=control.begin('今天关注什么'), pending=control.present(ticket,'今天关注什么',{})
 await vi.runAllTimersAsync(); expect(await pending).toBe(true)
 expect(control.dashboardMode.value).toBe('priority')
 const back=control.returnOverview(); await vi.runAllTimersAsync(); await back
 expect(control.aiState.value).toBe('idle')
})
