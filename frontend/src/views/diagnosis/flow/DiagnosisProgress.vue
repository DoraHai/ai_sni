<script setup>
import { computed, ref } from 'vue'
import logo from '../../../assets/g-snipers-purple-logo.png'
const props = defineProps({ statuses:Object, errors:Object, saving:Boolean, compact:Boolean })
const paused = ref(false)
const running = computed(() => steps.filter(step => props.statuses?.[step.key] === 'running'))
const current = computed(() => props.saving ? '正在保存确认信息' : running.value.length ? running.value.map(step=>step.title).join(' · ')+'进行中' : steps.some(step=>props.statuses?.[step.key]==='error') ? '部分任务需要重试' : '正在等待任务结果')
defineEmits(['retry-audit','retry-sample','retry-performance'])
const labels = {idle:'等待网站诊断完成',running:'正在处理…',success:'已完成',error:'检测失败',unavailable:'当前不可用'}
const steps = [{key:'brand',title:'企业信息'},{key:'audit',title:'网站诊断'},{key:'sample',title:'AI 品牌测试'},{key:'performance',title:'页面性能'}]
</script>
<template>
  <section class="fd-progress" :class="{'dp-full':!compact,'dp-paused':paused,'dp-running':saving || running.length}">
    <header v-if="!compact" class="dp-heading"><p class="fd-eyebrow">从官网信息，到诊断依据</p><h1>{{ saving ? '正在保存确认信息' : '正在诊断你的网站' }}</h1><p class="fd-intro">检查官网公开内容，整理有依据的诊断结果。</p></header>
    <div class="dp-workspace">
      <div v-if="!compact" class="dp-visual">
        <div class="dp-orbit" aria-hidden="true"><span class="dp-ring dp-outer"/><span class="dp-ring dp-inner"/><div class="dp-logo"><img :src="logo" alt=""/></div></div>
        <p class="dp-current" role="status">{{ current }}</p><span class="dp-caption">公开信息 · 有据可循</span>
        <button type="button" class="dp-motion" :aria-pressed="paused" @click="paused=!paused">{{ paused ? '播放动效' : '暂停动效' }}</button>
      </div>
      <div class="dp-tasks">
        <div v-if="!compact" class="dp-task-heading"><h2>诊断任务</h2><span>状态随实际请求更新</span></div>
        <ol class="fd-steps" aria-live="polite"><li v-for="(step,index) in steps" :key="step.key" :data-status="statuses[step.key]"><span class="fd-step-mark" aria-hidden="true">{{ statuses[step.key]==='success' ? '✓' : statuses[step.key]==='error' ? '!' : index+1 }}</span><div><strong>{{ step.title }}</strong><p>{{ step.key==='brand' && statuses.brand==='success' ? '已确认' : step.key==='audit' && statuses.audit==='idle' ? '等待企业信息保存' : labels[statuses[step.key]] }}</p><small v-if="errors?.[step.key]">{{ errors[step.key] }}</small></div><span v-if="statuses[step.key]==='running'" class="dp-activity" aria-hidden="true"><i/><i/><i/></span><button v-if="statuses[step.key]==='error' && step.key!=='brand'" class="fd-link" @click="$emit(`retry-${step.key}`)">重新尝试</button></li></ol>
        <p class="fd-note">状态随接口实际返回更新，不代表逐项检测的实时进度。</p>
      </div>
    </div>
  </section>
</template>
<style>
.free-diagnosis:has(.dp-full) .fd-header{padding-block:16px}
.free-diagnosis:has(.dp-full) .fd-body{padding:28px 32px 12px}
.free-diagnosis .fd-progress.dp-full{max-width:1040px}
.free-diagnosis .dp-heading{text-align:center;margin-bottom:28px}
.free-diagnosis .dp-heading .fd-eyebrow{margin:0 0 12px;font-size:12px}
.free-diagnosis .dp-heading h1{font-size:clamp(28px,3vw,40px);line-height:1.25;margin:0}
.free-diagnosis .dp-heading .fd-intro{font-size:14px;margin:12px 0 0}
.free-diagnosis .dp-full .dp-workspace{display:grid;grid-template-columns:1fr 1.15fr;align-items:center;gap:40px}
.free-diagnosis .dp-visual{display:flex;flex-direction:column;align-items:center;min-width:0;padding:12px}
.free-diagnosis .dp-orbit{position:relative;width:240px;height:240px;display:grid;place-items:center;background:radial-gradient(circle,#ece3fc 0,transparent 65%)}
.free-diagnosis .dp-ring{position:absolute;border:1px solid #d8cbea;border-radius:50%;inset:12px}
.free-diagnosis .dp-inner{inset:38px;border-style:dashed;border-color:#c4b1de}
.free-diagnosis .dp-ring::after{content:"";position:absolute;width:8px;height:8px;border-radius:50%;background:var(--fd-purple);top:22px;left:28px;box-shadow:0 0 0 5px #793bd710}
.free-diagnosis .dp-inner::after{width:5px;height:5px;top:15px;left:24px;background:#3e9587}
.free-diagnosis .dp-logo{width:102px;height:102px;display:grid;place-items:center;border-radius:28px;background:#fff;border:1px solid #e2d7ef;box-shadow:0 14px 35px #462d6d12}
.free-diagnosis .dp-logo img{width:86px;height:86px;object-fit:contain}
.free-diagnosis .dp-current{font-size:16px;font-weight:600;margin:16px 0 8px;color:var(--fd-ink);text-align:center}
.free-diagnosis .dp-caption{font-size:12px;color:var(--fd-muted)}
.free-diagnosis .dp-motion{padding:6px 10px;margin-top:14px;border:0;background:transparent;color:#71617e;font:inherit;font-size:11px;cursor:pointer;border-radius:4px}
.free-diagnosis .dp-motion:focus-visible{outline:2px solid var(--fd-purple);outline-offset:3px}
.free-diagnosis .dp-motion:hover{background:#eee7f6}
.free-diagnosis .dp-task-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 12px}
.free-diagnosis .dp-task-heading h2{font-size:14px;margin:0}
.free-diagnosis .dp-task-heading>span{font-size:11px;color:var(--fd-muted)}
.free-diagnosis .dp-full .fd-steps{margin:12px 0;display:grid;gap:6px}
.free-diagnosis .dp-full .fd-steps li{padding:14px 16px;min-height:76px;border:1px solid transparent;border-radius:12px;gap:14px}
.free-diagnosis .dp-full .fd-steps li[data-status=running]{background:#fff;border-color:#d9c6ef;box-shadow:0 4px 16px #452e6610}
.free-diagnosis .dp-full .fd-steps li[data-status=error]{background:#fff5f3;border-color:#edcbc5}
.free-diagnosis .dp-full .fd-step-mark{flex:none}
.free-diagnosis .dp-full .fd-steps p{font-size:12px;margin-top:4px}
.free-diagnosis .dp-full .fd-note{font-size:11px;line-height:1.6;margin:12px;color:var(--fd-muted)}
.free-diagnosis .dp-activity{display:flex;gap:4px}
.free-diagnosis .dp-activity i{width:4px;height:4px;border-radius:50%;background:var(--fd-purple)}
@media(prefers-reduced-motion:no-preference){
 .free-diagnosis .dp-running .dp-outer{animation:dp-orbit-turn 14s linear infinite}
 .free-diagnosis .dp-running .dp-inner{animation:dp-orbit-turn 20s linear infinite reverse}
 .free-diagnosis .dp-activity i{animation:dp-breathe 1.5s ease-in-out infinite alternate}
 .free-diagnosis .dp-activity i:nth-child(2){animation-delay:.2s}
 .free-diagnosis .dp-activity i:nth-child(3){animation-delay:.4s}
 .free-diagnosis .dp-paused :is(.dp-ring,.dp-activity i){animation-play-state:paused}
}
@keyframes dp-orbit-turn{to{transform:rotate(360deg)}}
@keyframes dp-breathe{to{opacity:.3;transform:translateY(-3px)}}
@media(prefers-reduced-motion:reduce){.free-diagnosis .dp-motion{display:none}}
@media(max-width:700px){
 .free-diagnosis:has(.dp-full) .fd-body{padding:22px 20px 12px}
 .free-diagnosis .dp-full .dp-workspace{grid-template-columns:minmax(0,1fr);gap:22px}
 .free-diagnosis .dp-heading{margin-bottom:8px}
 .free-diagnosis .dp-orbit{width:160px;height:160px}
 .free-diagnosis .dp-inner{inset:25px}
 .free-diagnosis .dp-logo{width:76px;height:76px;border-radius:20px}
 .free-diagnosis .dp-logo img{width:65px;height:65px}
 .free-diagnosis .dp-current{font-size:14px;margin-top:8px}
 .free-diagnosis .dp-full .fd-steps li{padding:10px 12px;min-height:68px}
}
@media print{.free-diagnosis .dp-visual{display:none}.free-diagnosis .dp-full .dp-workspace{display:block}.free-diagnosis .dp-activity i{animation:none}}
</style>
