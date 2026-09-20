<script setup>
import { computed } from 'vue'
import { historical, stateLabel } from './command-center.mjs'
const props=defineProps({card:{type:Object,required:true}})
const points=computed(()=>historical(props.card)?props.card.visualization.points:[])
const high=computed(()=>Math.max(1,...points.value.map(p=>p.value||0)))
const segments=computed(()=>{const out=[];let part=[];points.value.forEach((p,i)=>{if(p.value===null){if(part.length)out.push(part);part=[]}else part.push(`${2+i*116/Math.max(1,points.value.length-1)},${30-p.value/high.value*25}`)});if(part.length)out.push(part);return out})
const distribution=computed(()=>['available','partial'].includes(props.card.state)&&props.card.visualization?.state==='available'&&props.card.visualization?.type==='distribution'?props.card.visualization.items:[])
const total=computed(()=>distribution.value.reduce((sum,p)=>sum+p.value,0))
</script>
<template>
 <span class="micro-visual" aria-hidden="true">
  <svg v-if="points.length" viewBox="0 0 120 34" preserveAspectRatio="none"><template v-if="/内容|收录/.test(card.label)"><rect v-for="(p,i) in points" :key="p.key" :x="2+i*116/points.length" :y="p.value===null?32:30-p.value/high*25" :width="Math.max(1,100/points.length)" :height="p.value===null?0:p.value/high*25" fill="currentColor" opacity=".6"/></template><template v-else><polyline v-for="(part,i) in segments" :key="i" :points="part.join(' ')" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke"/></template></svg>
  <span v-else-if="distribution.length && total" class="micro-distribution"><i v-for="(item,i) in distribution" :key="item.key" :style="{width:`${item.value/total*100}%`,opacity:.3+i/distribution.length*.7}" /></span>
  <span v-else class="micro-state"><i :class="card.state"/>{{ stateLabel(card.state) }}<small>指标快照</small></span>
 </span>
</template>
<style scoped>.micro-visual{display:block;height:32px;margin-top:6px;color:var(--accent,#70bbef)}svg{width:100%;height:32px;display:block}.micro-distribution{display:flex;gap:2px;align-items:center;height:32px}.micro-distribution i{height:9px;background:currentColor;border-radius:1px}.micro-state{display:flex;align-items:center;gap:6px;font-size:9px;color:#95acbe;padding-top:12px}.micro-state i{width:5px;height:5px;border-radius:50%;background:#b0a088}.micro-state i.available{background:var(--accent)}.micro-state small{margin-left:auto;font-size:9px;color:#728da3}</style>
