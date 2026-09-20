import { beforeEach, afterEach, expect, test, vi } from 'vitest'
import { vChartDraw } from './chart-draw'
let observers, media, reduceHandler, elements
beforeEach(()=>{
 vi.useFakeTimers();observers=[];elements=[]
 media={matches:false,addEventListener:vi.fn((_,fn)=>reduceHandler=fn),removeEventListener:vi.fn()}
 vi.stubGlobal('matchMedia',()=>media)
 vi.stubGlobal('requestAnimationFrame',cb=>setTimeout(cb,16));vi.stubGlobal('cancelAnimationFrame',clearTimeout)
 vi.stubGlobal('IntersectionObserver',class{
  constructor(cb){this.cb=cb;this.disconnect=vi.fn();observers.push(this)}
  observe(el){this.el=el}
  enter(){this.cb([{target:this.el,isIntersecting:true,intersectionRatio:1}])}
 })
})
afterEach(()=>{elements.forEach(el=>vChartDraw.beforeUnmount(el));vi.useRealTimers();vi.unstubAllGlobals()})
function mount(key=['all',1]){const el=document.createElement('section');elements.push(el);vChartDraw.mounted(el,{value:key});return el}
test('waits for viewport, draws once, does not replay after hover/update/scroll',()=>{
 const el=mount();expect(el.dataset.drawState).toBe('waiting')
 vi.advanceTimersByTime(2000);expect(el.dataset.drawState).toBe('waiting')
 observers[0].enter();vi.advanceTimersByTime(16);expect(el.dataset.drawState).toBe('drawing')
 vi.advanceTimersByTime(1800);expect(el.dataset.drawState).toBe('complete')
 vChartDraw.updated(el,{value:['all',1]});el.dispatchEvent(new Event('pointerenter'));observers[0].enter();vi.advanceTimersByTime(20)
 expect(el.dataset.drawState).toBe('complete');expect(observers).toHaveLength(1)
})
test('new scope re-arms and stale viewport callbacks cannot restart it',()=>{
 const el=mount();const old=observers[0];vChartDraw.updated(el,{value:['sem',2]});old.enter();vi.advanceTimersByTime(20)
 expect(el.dataset.drawState).toBe('waiting');observers[1].enter();vi.advanceTimersByTime(16);expect(el.dataset.drawState).toBe('drawing')
})
test('focus reveals immediately and reduced motion finishes drawings',()=>{
 const el=mount();el.dispatchEvent(new Event('focusin'));expect(el.dataset.drawState).toBe('complete')
 vChartDraw.updated(el,{value:['sem',2]});observers.at(-1).enter();vi.advanceTimersByTime(16)
 media.matches=true;reduceHandler();expect(el.dataset.drawState).toBe('complete');expect(el.classList.contains('chart-draw-active')).toBe(false)
})
test('reduced motion and missing observers keep content visible',()=>{
 media.matches=true;const el=mount();expect(el.dataset.drawState).toBe('complete');expect(observers).toHaveLength(0)
 media.matches=false;vi.stubGlobal('IntersectionObserver',undefined);const second=mount();expect(second.dataset.drawState).toBe('complete')
})
test('unmount cancels observers, timers and queued animation work',()=>{
 const el=mount();observers[0].enter();vChartDraw.beforeUnmount(el);vi.advanceTimersByTime(2000)
 expect(el.classList.contains('chart-draw-active')).toBe(false);expect(media.removeEventListener).toHaveBeenCalled()
})
