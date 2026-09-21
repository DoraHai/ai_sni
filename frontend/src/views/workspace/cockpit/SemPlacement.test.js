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
 expect(w.text()).toContain('所选日期暂无小时报告');expect(w.find('.map-detail').text()).not.toContain('广东')
 w.unmount()
})
test('real reports show independent totals, missing hours and coverage even without a daily KPI',()=>{
 const data={state:'available',demo:false,metric:'click',total:14,hourlyTotal:7,
 regions:[{code:'320000',clicks:14}],cells:Array.from({length:168},(_,i)=>({weekday:Math.floor(i/24),hour:i%24,clicks:i===9?7:null})),
 regionCoverage:{observed_days:1},hourlyCoverage:{observed_days:1},unmappedClicks:2,period:'2026-09-01 至 2026-09-03',source:'百度报表'}
 const w=mount(SemPlacement,{props:{cards:[{moduleCode:'sem',state:'unavailable',semPlacement:data}]}})
 expect(w.findAll('.heatmap-cells button')).toHaveLength(168)
 expect(w.find('.region-panel header strong').text()).toContain('14')
 expect(w.text()).toContain('未匹配省份 2 次点击')
 expect(w.text()).not.toContain('模拟分布');w.unmount()
})
