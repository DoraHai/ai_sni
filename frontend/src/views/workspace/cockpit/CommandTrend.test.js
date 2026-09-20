import { expect, test } from 'vitest'
import { mount } from '@vue/test-utils'
import CommandTrend from './CommandTrend.vue'
const card=(id,moduleCode,values)=>({id,moduleCode,moduleLabel:moduleCode.toUpperCase(),state:'available',label:moduleCode==='sem'?'广告点击量':'品牌提及率',visualization:{type:'trend',state:'available',coverage:{label:'核验'},points:values.map((value,i)=>({key:`2026-09-${14+i}`,label:`09-${14+i}`,value,display:value===null?'缺报':String(value)}))}})
test('keyboard cursor reports raw values and missing observations, then opens evidence',async()=>{
 const w=mount(CommandTrend,{props:{cards:[card('click','sem',[100,null,200]),card('geo','geo',[.1,.2,.3])]}})
 await w.get('.chart-surface').trigger('keydown',{key:'ArrowRight'})
 expect(w.get('.chart-tooltip').text()).toContain('缺报')
 await w.get('.chart-surface').trigger('keydown',{key:'End'})
 expect(w.get('.chart-tooltip').text()).toContain('2026-09-16')
 expect(w.get('.chart-tooltip').text()).toContain('0.3')
 await w.get('.chart-surface').trigger('keydown',{key:'Enter'})
 expect(w.emitted('focus')[0]).toEqual(['click']);w.unmount()
})
test('changing scope drops the previous dates and selected module',async()=>{
 const w=mount(CommandTrend,{props:{cards:[card('click','sem',[100,200])],initialModule:'sem'}})
 await w.get('.chart-surface').trigger('keydown',{key:'End'})
 await w.setProps({cards:[card('geo','geo',[20,30,40])]})
 expect(w.get('.chart-tooltip').text()).toContain('2026-09-14')
 expect(w.get('.chart-tooltip').text()).not.toContain('SEM')
 expect(w.get('.chart-tabs button').attributes('aria-pressed')).toBe('true');w.unmount()
})
test('zero baseline and snapshots show their correct boundary without invented lines',()=>{
 const zero=mount(CommandTrend,{props:{cards:[card('click','sem',[0,0])]}})
 expect(zero.text()).toContain('当前序列无法基准化');expect(zero.find('.series-line').exists()).toBe(false);zero.unmount()
 const snapshot=mount(CommandTrend,{props:{cards:[{id:'x',moduleCode:'geo',state:'available',display:'12'}]}})
 expect(snapshot.text()).toContain('历史序列等待接入');expect(snapshot.find('.series-line').exists()).toBe(false);snapshot.unmount()
})
