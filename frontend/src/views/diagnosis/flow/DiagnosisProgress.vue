<script setup>
defineProps({ statuses:Object, errors:Object, saving:Boolean, compact:Boolean })
defineEmits(['retry-audit','retry-sample','retry-performance'])
const labels = {idle:'等待网站诊断完成',running:'正在处理…',success:'已完成',error:'检测失败',unavailable:'当前不可用'}
const steps = [{key:'brand',title:'企业信息'},{key:'audit',title:'网站诊断'},{key:'sample',title:'AI 品牌测试'},{key:'performance',title:'页面性能'}]
</script>
<template><section class="fd-progress" aria-live="polite"><template v-if="!compact"><p class="fd-eyebrow">真实请求状态</p><h1>{{ saving ? '正在保存确认信息' : '正在诊断你的网站' }}</h1><p class="fd-intro">检查官网公开内容，整理有依据的诊断结果。</p></template><ol class="fd-steps"><li v-for="(step,index) in steps" :key="step.key" :data-status="statuses[step.key]"><span class="fd-step-mark" :class="{'fd-spinning':statuses[step.key]==='running'}" aria-hidden="true">{{ statuses[step.key]==='success' ? '✓' : index+1 }}</span><div><strong>{{ step.title }}</strong><p>{{ step.key==='brand' && statuses.brand==='success' ? '已确认' : step.key==='audit' && statuses.audit==='idle' ? '等待企业信息保存' : labels[statuses[step.key]] }}</p><small v-if="errors?.[step.key]">{{ errors[step.key] }}</small></div><button v-if="statuses[step.key]==='error' && step.key!=='brand'" class="fd-link" @click="$emit(`retry-${step.key}`)">重新尝试</button></li></ol><p class="fd-note">状态随接口实际返回更新，不代表逐项检测的实时进度。</p></section></template>
