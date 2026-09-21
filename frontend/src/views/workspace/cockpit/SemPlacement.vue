<script setup>
import {computed,ref,watch} from 'vue'
import { vChartDraw, useChartDrawKey } from './chart-draw'
import provinces from './china-provinces.json'
import {validSemPlacement,clickColor} from './sem-placement.mjs'
const props=defineProps({cards:{type:Array,default:()=>[]}})
const source=computed(()=>props.cards.find(c=>c.moduleCode==='sem' && validSemPlacement(c.semPlacement)))
const data=computed(()=>source.value?.semPlacement)
const regionReady=computed(()=>data.value && (data.value.demo || data.value.regionCoverage?.observed_days>0))
const hourlyReady=computed(()=>data.value && (data.value.demo || data.value.hourlyCoverage?.observed_days>0))
const readError=computed(()=>props.cards.find(c=>c.moduleCode==='sem' && c.placementError)?.placementError)
const drawKey=useChartDrawKey(()=>data.value?.period || 'no-data')
const selected=ref(null),activeCell=ref(0)
const regions=computed(()=>new Map(data.value?.regions.map(r=>[r.code,r.clicks])||[]))
const maxRegion=computed(()=>Math.max(0,...regions.value.values()))
const maxHour=computed(()=>Math.max(0,...(data.value?.cells.map(c=>c.clicks??0)||[])))
const ranking=computed(()=>provinces.filter(p=>p.name && regions.value.has(p.code)).map(p=>({...p,clicks:regions.value.get(p.code)})).sort((a,b)=>b.clicks-a.clicks).slice(0,5))
const region=computed(()=>provinces.find(p=>p.code===selected.value))
const cell=computed(()=>data.value?.cells[activeCell.value])
const weekdays=['周一','周二','周三','周四','周五','周六','周日']
const fmt=n=>n===null||n===undefined?'暂无数据':new Intl.NumberFormat('zh-CN').format(n)
const share=computed(()=>data.value?.total>0 && regions.value.has(selected.value)?`${(regions.value.get(selected.value)/data.value.total*100).toFixed(1)}%`:'—')
watch(data,()=>{selected.value=ranking.value[0]?.code||null;activeCell.value=Math.max(0,data.value?.cells.findIndex(c=>c.clicks!==null)??0)},{immediate:true})
function moveCell(event,index){
 const offset={ArrowLeft:-1,ArrowRight:1,ArrowUp:-24,ArrowDown:24}[event.key]
 let next=event.key==='Home'?Math.floor(index/24)*24:event.key==='End'?Math.floor(index/24)*24+23:offset!==undefined?Math.max(0,Math.min(167,index+offset)):null
 if(next===null)return
 event.preventDefault();activeCell.value=next
 event.currentTarget.parentElement.querySelectorAll('button')[next]?.focus()
}
</script>
<template>
 <section class="sem-placement" aria-label="SEM 地域与时间段分析">
  <header class="placement-heading"><div><small>SEM · AUDIENCE & TIMING</small><h3>点击来自哪里，集中在何时</h3></div><span :class="{demo:data?.demo}">{{ data?.demo?'演示数据 · 模拟分布':data?'真实报表 · 已观测小计':'地域 / 小时报告未读取' }}</span></header>
  <div class="placement-grid">
   <section v-chart-draw="drawKey" class="region-panel" aria-label="中国地域点击分布">
    <header><div><h4>中国地域点击分布</h4><p>省级点击量 · 颜色越深，点击越多</p></div><strong data-draw="reveal">{{ regionReady?fmt(data.total):'—' }}<small>次点击</small></strong></header>
    <div class="map-body">
     <svg class="china-map" viewBox="0 0 570 520" role="group" aria-label="中国省级点击分布地图">
      <path data-draw="map" pathLength="1" v-for="p in provinces" :key="p.code" :d="p.path" :fill="p.name?clickColor(regions.get(p.code),maxRegion):'#49627a'" :class="{'map-region':p.name,selected:p.code===selected}" :tabindex="p.name?0:undefined" :role="p.name?'button':undefined" :aria-label="p.name?`${p.name}，${fmt(regions.get(p.code))}${regions.has(p.code)?'次点击':''}`:undefined" :aria-pressed="p.name?p.code===selected:undefined" @mouseenter="p.name && (selected=p.code)" @focus="p.name && (selected=p.code)" @click="p.name && (selected=p.code)" @keydown.enter.prevent="p.name && (selected=p.code)" @keydown.space.prevent="p.name && (selected=p.code)"><title>{{ p.name || '附属线条' }}{{ p.name?`：${fmt(regions.get(p.code))}`:'' }}</title></path>
     </svg>
     <aside data-draw="reveal" class="map-ranking"><small>点击 TOP 5</small><button v-for="(r,i) in ranking" :key="r.code" type="button" :class="{active:r.code===selected}" @click="selected=r.code"><em>0{{ i+1 }}</em><span>{{ r.name }}<b>{{ fmt(r.clicks) }}</b></span><i :style="{width:`${r.clicks/(maxRegion||1)*100}%`}"/></button><p v-if="!regionReady">所选日期暂无地域报告<br>不按全国总量推算地域分布</p></aside>
    </div>
    <div data-draw="reveal" class="map-detail" aria-live="polite"><b>{{ region?.name || '选择省份查看' }}</b><span>{{ region?fmt(regions.get(region.code)):'—' }}{{ region && regions.has(region.code)?' 次点击':'' }}</span><small v-if="data">占点击 {{ share }}</small></div>
    <footer class="scale"><span>少</span><i/><span>多</span><b/>暂无数据</footer>
   </section>
   <section v-chart-draw="drawKey" class="time-panel" aria-label="SEM 时间段点击分析">
    <header><div><h4>时间段点击分析</h4><p>星期 × 小时 · 中国标准时间（UTC+8）</p></div><span>点击次数</span></header>
    <template v-if="hourlyReady">
     <div class="heatmap-wrap"><div class="hour-axis"><span v-for="h in [0,6,12,18,23]" :key="h" :style="{gridColumn:h+2}">{{ String(h).padStart(2,'0') }}</span></div><div class="heatmap-body"><div class="weekday-axis"><span v-for="d in weekdays" :key="d">{{ d }}</span></div><div class="heatmap-cells" role="group" aria-label="星期小时点击热力图，方向键移动"><button data-draw="cell" v-for="(c,i) in data.cells" :key="i" type="button" :tabindex="activeCell===i?0:-1" :class="{active:activeCell===i,missing:c.clicks===null}" :style="{background:clickColor(c.clicks,maxHour),'--draw-step':c.hour}" :aria-label="`${weekdays[c.weekday]} ${c.hour}:00–${c.hour+1}:00，${fmt(c.clicks)}${c.clicks!==null?'次点击':''}`" @mouseenter="activeCell=i" @focus="activeCell=i" @click="activeCell=i" @keydown="moveCell($event,i)"/></div></div></div>
     <div data-draw="reveal" class="time-detail" aria-live="polite"><small>{{ weekdays[cell.weekday] }} · {{ String(cell.hour).padStart(2,'0') }}:00–{{ String(cell.hour+1).padStart(2,'0') }}:00</small><strong>{{ fmt(cell.clicks) }}<span v-if="cell.clicks!==null"> 次点击</span></strong><p>汇总所选日期中相同星期、相同小时的点击；无对应日期保持空缺。</p></div>
     <footer class="scale"><span>少</span><i/><span>多</span><b/>无对应数据</footer>
    </template>
    <div v-else class="placement-empty"><strong>所选日期暂无小时报告</strong><p>请在 SEM 同步所选日期的小时报表；缺报不等于零点击。</p></div>
   </section>
  </div>
  <footer class="placement-source">{{ data?`${data.period} · ${data.source}`:'地域与小时报告尚未读取，请刷新或检查 SEM 报表同步状态。' }}<span v-if="readError"> · {{ readError }}</span><span v-if="data && !data.demo"> · 地域已观测 {{ data.regionCoverage.observed_days }} 天，小时已观测 {{ data.hourlyCoverage.observed_days }} 天；两类报表分别汇总，缺报保留空缺。<template v-if="data.unmappedClicks">未匹配省份 {{ fmt(data.unmappedClicks) }} 次点击，未计入地图。</template></span><span v-if="data?.demo"> · 两张图均为模拟点击拆分，不代表真实投放表现。</span></footer>
 </section>
</template>
<style scoped>
.sem-placement{pointer-events:auto;margin:20px 0;color:#d3e8f8;border:1px solid #719db332;border-radius:16px;background:linear-gradient(125deg,#0d2533dd,#071a27ed);overflow:hidden}.placement-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:22px 24px;border-bottom:1px solid #648ba22b}.placement-heading small{font-size:10px;letter-spacing:.14em;color:#75bfe8}.placement-heading h3{font-size:19px;font-weight:500;margin:8px 0 0}.placement-heading>span{font-size:11px;color:#9bb9ca}.placement-heading .demo{color:#cfb78b;border:1px solid #a58c5d55;border-radius:20px;padding:6px 10px}.placement-grid{display:grid;grid-template-columns:1.1fr 1fr}.region-panel,.time-panel{min-width:0;padding:22px}.time-panel{border-left:1px solid #648ba22b}.placement-grid header{display:flex;justify-content:space-between;gap:12px}.placement-grid h4{font-size:15px;font-weight:500;margin:0}.placement-grid header p{font-size:11px;color:#83a3bb;line-height:1.6}.placement-grid header strong{font-size:23px;font-weight:500;white-space:nowrap}.placement-grid header strong small{display:block;font-size:10px;color:#83a3bb;text-align:right;margin-top:5px}.placement-grid header>span{font-size:10px;color:#9ab8d0;white-space:nowrap}.map-body{display:flex;align-items:center;gap:8px}.china-map{display:block;min-width:0;width:76%;height:290px}.map-region{stroke:#0b243b;stroke-width:.65;cursor:pointer;transition:fill .18s}.map-region:hover,.map-region.selected,.map-region:focus-visible{stroke:#f8da93;stroke-width:1.8;outline:none;filter:drop-shadow(0 0 3px #d8c89960)}.map-ranking{width:24%;min-width:85px}.map-ranking>small{font-size:9px;letter-spacing:.1em;color:#8eb5ce}.map-ranking button{display:flex;position:relative;gap:7px;width:100%;border:0;background:transparent;color:#a5c1d5;text-align:left;cursor:pointer;padding:10px 0;font:inherit}.map-ranking button.active{color:#eef6ff}.map-ranking em{font-size:9px;font-style:normal;color:#66869f}.map-ranking button span{font-size:10px;line-height:1.4}.map-ranking b{display:block;font-size:12px;font-weight:500}.map-ranking i{position:absolute;bottom:3px;height:2px;background:#397cb0;max-width:100%}.map-ranking p{font-size:11px;line-height:1.9;color:#8ba5b9}.map-detail{min-height:30px;display:flex;gap:12px;align-items:center;font-size:12px;flex-wrap:wrap}.map-detail b{font-weight:500}.map-detail small{font-size:10px;color:#83a3bb}.scale{display:flex;align-items:center;gap:8px;font-size:10px;color:#8ba9bf;margin-top:14px}.scale i{display:inline-block;width:95px;height:6px;border-radius:4px;background:linear-gradient(90deg,#bee6f7,#1656a1)}.scale>b{width:9px;height:9px;background:#163142;border:1px solid #426076;margin-left:9px}.heatmap-wrap{margin:25px 0 20px}.hour-axis{display:grid;grid-template-columns:32px repeat(24,minmax(0,1fr));font-size:9px;color:#82a4bf;margin-bottom:9px;gap:3px}.hour-axis span:last-child{justify-self:end}.heatmap-body{display:flex;gap:8px}.weekday-axis{display:grid;grid-template-rows:repeat(7,1fr);width:24px;flex-shrink:0;font-size:10px;color:#98b5ca;align-items:center}.heatmap-cells{display:grid;flex:1;min-width:0;grid-template-columns:repeat(24,minmax(0,1fr));gap:3px}.heatmap-cells button{padding:0;min-width:0;height:24px;border:1px solid transparent;border-radius:2px;cursor:pointer}.heatmap-cells button.active,.heatmap-cells button:focus-visible{outline:1px solid #ffe2a4;outline-offset:1px;z-index:1}.heatmap-cells button.missing{border-color:#314757}.time-detail{min-height:82px;border-top:1px solid #648ba22b;padding-top:14px}.time-detail>small{font-size:11px;color:#9dbed4}.time-detail strong{display:block;font-size:27px;font-weight:500;margin:8px 0}.time-detail strong span{font-size:11px;color:#9dbed4}.time-detail p,.placement-empty p{font-size:11px;line-height:1.8;color:#83a3bb;margin:0}.placement-empty{min-height:290px;display:flex;flex-direction:column;justify-content:center;gap:14px;max-width:320px;margin:auto}.placement-empty strong{font-size:17px;font-weight:500}.placement-source{padding:13px 24px;background:#06131b55;font-size:10px;line-height:1.8;color:#83a3bb;border-top:1px solid #648ba22b}.sem-placement button:focus-visible{outline:2px solid #b6dbf4;outline-offset:2px}@media(max-width:1200px){.placement-grid{grid-template-columns:1fr}.time-panel{border-left:0;border-top:1px solid #648ba22b}.china-map{height:320px}}@media(max-width:650px){.placement-heading{align-items:start;flex-direction:column}.region-panel,.time-panel{padding:16px}.heatmap-cells{gap:2px}.heatmap-cells button{height:21px}.china-map{height:240px}.map-ranking{min-width:72px}.placement-heading h3{font-size:17px}}@media(prefers-reduced-motion:reduce){.map-region{transition:none}}
</style>
