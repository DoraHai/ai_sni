<script setup>
import { computed, ref, watch, useId } from 'vue'
import { vChartDraw, useChartDrawKey } from './chart-draw'
import CommandIcon from './CommandIcon.vue'
import { trendSelection, indexedTrends, costAnnotation } from './command-center.mjs'
const props=defineProps({cards:{type:Array,required:true},initialModule:{type:String,default:'all'}})
const emit=defineEmits(['focus','ask'])
const selected=ref(props.initialModule), cursor=ref(0), uid=useId()
const codes=computed(()=>[...new Set(props.cards.map(c=>c.moduleCode))])
const chosen=computed(()=>trendSelection(props.cards,selected.value))
const model=computed(()=>indexedTrends(chosen.value))
const annotation=computed(()=>costAnnotation(props.cards))
const maximum=computed(()=>Math.max(120,...model.value.series.flatMap(s=>s.points.map(p=>p.value || 0))))
const x=i=>48+i*694/Math.max(1,model.value.keys.length-1)
const y=value=>190-value/maximum.value*162
const colors={sem:'#72bbff',seo:'#69d5bf',geo:'#b5a2ea'}
const drawKey=useChartDrawKey(()=>`${selected.value}:${model.value.keys.join(',')}:${chosen.value.map(c=>c.id).join(',')}`)
const activeKey=computed(()=>model.value.keys[cursor.value])
function segments(series){
 const groups=[];let group=[]
 series.points.forEach((p,i)=>{if(p.value===null){if(group.length)groups.push(group);group=[]}else group.push({x:x(i),y:y(p.value)})})
 if(group.length)groups.push(group)
 return groups
}
const line=points=>points.map((p,i)=>`${i?'L':'M'}${p.x} ${p.y}`).join(' ')
function scrub(event){const r=event.currentTarget.getBoundingClientRect();cursor.value=Math.max(0,Math.min(model.value.keys.length-1,Math.round(((event.clientX-r.left)/r.width*780-48)/694*(model.value.keys.length-1))))}
function keydown(event){
 if(!model.value.keys.length)return
 if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();cursor.value=event.key==='Home'?0:event.key==='End'?model.value.keys.length-1:Math.max(0,Math.min(model.value.keys.length-1,cursor.value+(event.key==='ArrowLeft'?-1:1)))}
 if(event.key==='Enter' && chosen.value[0])emit('focus',chosen.value[0].id)
}
watch(()=>props.initialModule,value=>selected.value=value)
watch(()=>props.cards,()=>{if(selected.value!=='all'&&!codes.value.includes(selected.value))selected.value='all';cursor.value=0})
watch(selected,()=>cursor.value=0)
</script>
<template>
 <section v-chart-draw="drawKey" class="command-trend" aria-label="全域获客趋势">
  <header><div><small>ACQUISITION PULSE</small><h3><CommandIcon name="activity" />全域获客趋势</h3></div><div class="chart-tabs" aria-label="趋势渠道"><button type="button" :aria-pressed="selected==='all'" @click="selected='all'">全域</button><button v-for="code in codes" :key="code" type="button" :aria-pressed="selected===code" @click="selected=code">{{ code.toUpperCase() }}</button></div></header>
  <p class="axis-explainer">各指标首个有效观测 = 100 · 比较走势，不合并不同单位的业务量</p>
  <template v-if="model.series.some(s=>s.baseline!==null)">
   <div class="chart-surface" tabindex="0" role="group" aria-label="趋势图，左右方向键切换日期，回车查看首项证据" @keydown="keydown" @pointermove="scrub">
    <svg viewBox="0 0 780 220" preserveAspectRatio="none" role="img" aria-label="各渠道指标基准化趋势，缺失观测断开">
     <defs><linearGradient v-for="s in model.series" :id="`${uid}-${s.card.id}`" :key="s.card.id" x1="0" y1="0" x2="0" y2="1"><stop offset="0" :stop-color="colors[s.card.moduleCode]" stop-opacity=".13"/><stop offset="1" :stop-color="colors[s.card.moduleCode]" stop-opacity="0"/></linearGradient></defs>
     <g v-for="n in [0,1,2,3]" :key="n" class="chart-grid"><line x1="48" x2="742" :y1="28+n*54" :y2="28+n*54"/><text x="5" :y="32+n*54">{{ Math.round(maximum*(1-n/3)) }}</text></g>
     <g v-for="(s,si) in model.series" :key="s.card.id" :style="{color:colors[s.card.moduleCode]}">
      <template v-for="(points,i) in segments(s)" :key="i"><path data-draw="area" :d="`${line(points)} L${points.at(-1).x} 190 L${points[0].x} 190 Z`" :fill="`url(#${uid}-${s.card.id})`"/><path data-draw="line" class="series-line" :d="line(points)" :stroke-dasharray="['','6 3','2 3','8 3 2 3'][si]"/></template>
      <circle data-draw="reveal" v-for="(p,i) in s.points.filter(p=>p.value!==null)" :key="p.key" :cx="x(model.keys.indexOf(p.key))" :cy="y(p.value)" r="2.5" fill="currentColor" />
      <circle data-draw="reveal" v-if="s.points[cursor]?.value!==null && s.points[cursor]?.value!==undefined" :cx="x(cursor)" :cy="y(s.points[cursor].value)" r="4.5" fill="currentColor" stroke="#102a3d" stroke-width="2"/>
     </g>
     <line v-if="activeKey" class="cursor-line" :x1="x(cursor)" :x2="x(cursor)" y1="22" y2="190"/>
     <g v-if="annotation && model.keys.includes(annotation.key)" data-draw="reveal" class="annotation-pin"><circle :cx="x(model.keys.indexOf(annotation.key))" cy="17" r="5"/><path :d="`M${x(model.keys.indexOf(annotation.key))} 24 V190`"/></g>
     <text v-for="i in [...new Set([0,Math.floor((model.keys.length-1)/2),model.keys.length-1])]" :key="i" :x="x(i)" y="214" :text-anchor="i===0?'start':i===model.keys.length-1?'end':'middle'" class="date-tick">{{ model.keys[i]?.slice(5) || model.keys[i] }}</text>
    </svg>
   </div>
   <div data-draw="reveal" class="chart-tooltip" aria-live="polite"><time>{{ activeKey }}</time><button v-for="s in model.series" :key="s.card.id" type="button" @click="emit('focus',s.card.id)"><i :style="{background:colors[s.card.moduleCode]}"/><span>{{ s.card.moduleLabel }} · {{ s.card.label }}</span><b>{{ s.points[cursor]?.display || '未提供观测' }}</b></button></div>
   <p v-if="model.series.some(s=>s.baseline===null)" class="chart-note">部分指标首个观测为 0 或无有效值，无法基准化；原始观测仍可展开查看。</p>
  </template>
  <div v-else class="history-empty"><CommandIcon name="activity"/><strong>{{ chosen.length?'当前序列无法基准化':'历史序列等待接入' }}</strong><p>{{ chosen.length?'首个有效观测为 0 时不绘制基准化趋势，原始数值可展开证据查看。':'当前指标快照仍可查看；至少两次有效观测才能绘制走势。' }}</p><div><span v-for="code in codes" :key="code">{{ code.toUpperCase() }} <b>{{ trendSelection(cards,code).length ? '基准值不可计算' : '暂无可绘制序列' }}</b></span></div></div>
  <footer v-if="annotation && (selected==='all'||selected==='sem')" data-draw="reveal" class="chart-annotation"><CommandIcon name="spark"/><span><b>AI 观测标记 · {{ annotation.label }}</b>{{ annotation.text }}</span><button type="button" @click="emit('ask','分析 SEM 消耗与点击的趋势')">深入分析 ↗</button></footer>
  <footer v-else class="chart-note"><CommandIcon name="shield"/>{{ chosen.length }} 条可核验序列 · 缺报不连线；观测状态不等于业务效果。</footer>
 </section>
</template>
<style scoped>
.command-trend{min-width:0;color:#dfedfa;padding:16px 18px;background:radial-gradient(ellipse at 50% 75%,#15558223,transparent 65%)}header{display:flex;justify-content:space-between;gap:12px;align-items:center}small{font-size:9px;letter-spacing:.15em;color:#7eaccb}h3{font-size:17px;font-weight:500;margin:7px 0;display:flex;gap:9px;align-items:center}h3 svg{color:#82c8f0}.chart-tabs{display:flex;border:1px solid #79a6c32b;border-radius:6px;padding:3px;gap:2px}.chart-tabs button{font:inherit;font-size:10px;background:none;border:0;color:#8aa9bf;padding:6px 9px;border-radius:4px;cursor:pointer}.chart-tabs button[aria-pressed=true]{color:#d4e9f9;background:#274863}.axis-explainer,.chart-note{font-size:10px;line-height:1.7;color:#8aa5bc;margin:8px 0}.chart-surface{outline-offset:3px}.chart-surface svg{display:block;width:100%;height:165px;overflow:visible}.chart-grid line{stroke:#6999bd20;stroke-dasharray:3 5}.chart-grid text,.date-tick{font-size:11px;fill:#91adc1}.series-line{fill:none;stroke:currentColor;stroke-width:1.8;vector-effect:non-scaling-stroke;filter:drop-shadow(0 0 3px #5eafff20)}.cursor-line{stroke:#bdd7eb4a;stroke-dasharray:3 4}.annotation-pin circle{fill:#dcb17b}.annotation-pin path{stroke:#dcb17b40;stroke-dasharray:2 5}.chart-tooltip{display:flex;flex-wrap:wrap;gap:8px 14px;font-size:10px;padding:10px 0;min-height:36px}.chart-tooltip time{color:#c8ddf0}.chart-tooltip button{font:inherit;display:flex;gap:5px;align-items:center;border:0;background:none;padding:0;color:#9cb8ce;cursor:pointer}.chart-tooltip i{height:5px;width:5px;border-radius:50%}.chart-tooltip b{color:#dfedfa;font-weight:500}.chart-annotation{border-top:1px solid #739fc22b;display:flex;gap:10px;align-items:center;padding-top:12px;font-size:11px;color:#93b1c7;line-height:1.6}.chart-annotation>svg{color:#b8d7ef}.chart-annotation span{flex:1}.chart-annotation b{display:block;font-weight:500;color:#c6dded}.chart-annotation button{border:0;background:none;white-space:nowrap;color:#8bcafa;font:inherit;cursor:pointer}.chart-note{display:flex;gap:7px;align-items:center}.chart-note svg{width:14px;height:14px}.history-empty{min-height:215px;display:flex;align-items:center;justify-content:center;flex-direction:column;text-align:center;gap:12px;background:repeating-linear-gradient(0deg,transparent,transparent 49px,#7497b510 50px)}.history-empty>svg{width:35px;height:35px;color:#638cac}.history-empty strong{font-size:15px;font-weight:500}.history-empty p{font-size:11px;color:#819eb4;margin:0}.history-empty>div{display:flex;flex-wrap:wrap;justify-content:center;gap:18px;margin-top:12px;font-size:10px;color:#acd1e9}.history-empty b{display:block;font-weight:400;color:#7e9caf;margin-top:6px}button:focus-visible,.chart-surface:focus-visible{outline:2px solid #93d1ff;outline-offset:3px}@media(max-width:900px){header{flex-wrap:wrap}.chart-surface svg{height:170px}.chart-annotation{flex-wrap:wrap}}
</style>
