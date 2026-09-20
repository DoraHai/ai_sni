import{test,expect}from'vitest'
import{mount}from'@vue/test-utils'
import SemPlacement from './SemPlacement.vue'
import{tigerDemoCards}from'./tiger-demo.mjs'
const cards=()=>tigerDemoCards({dateStart:'2026-09-14',dateEnd:'2026-09-20',contextRevision:1,modules:['sem']})
test('shows 34 provinces, 168 hours, and selectable provincial values',async()=>{
 const w=mount(SemPlacement,{props:{cards:cards()}})
 expect(w.findAll('.map-region')).toHaveLength(34);expect(w.findAll('.heatmap-cells button')).toHaveLength(168)
 await w.find('[aria-label^="北京市，"]').trigger('click');expect(w.find('.map-detail').text()).toContain('北京市')
 expect(w.text()).toContain('模拟分布');w.unmount()
})
test('keyboard moves through hours and changing scope clears old values',async()=>{
 const w=mount(SemPlacement,{props:{cards:cards()},attachTo:document.body})
 await w.findAll('.heatmap-cells button')[0].trigger('keydown',{key:'ArrowDown'})
 expect(w.find('.time-detail').text()).toContain('周二')
 await w.setProps({cards:[]});expect(w.findAll('.heatmap-cells button')).toHaveLength(0)
 expect(w.text()).toContain('时间段数据等待接入');expect(w.find('.map-detail').text()).not.toContain('广东')
 w.unmount()
})
