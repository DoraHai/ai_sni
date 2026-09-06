<script setup>
import { computed } from 'vue'
import DiagnosisProgress from './DiagnosisProgress.vue'
const props = defineProps({audit:Object,statuses:Object,errors:Object})
defineEmits(['report','retry-sample','retry-performance'])
const issues = computed(()=>Array.isArray(props.audit?.problems)?props.audit.problems:[])
const high = computed(()=>issues.value.filter(x=>['critical','high'].includes(x.severity)).length)
</script>
<template><section class="fd-complete"><p class="fd-eyebrow">你的基础诊断已准备好</p><h1>诊断完成</h1><p class="fd-intro">从发现问题，到找到下一步。</p><div class="fd-results"><section><span>综合评分</span><strong>{{ Number.isFinite(audit.score) ? audit.score : '未检测' }}<small v-if="Number.isFinite(audit.score)"> / 100</small></strong></section><section><span>发现问题</span><strong>{{ issues.length }}<small> 个</small></strong></section><section><span>高优先问题</span><strong>{{ high }}<small> 个</small></strong></section></div><button class="fd-primary" @click="$emit('report')">{{ ['running','idle'].includes(statuses.sample) || ['running','idle'].includes(statuses.performance) ? '查看已有诊断结果 →' : '查看诊断结果 →' }}</button><p class="fd-note">附加检测不会阻塞基础报告；完成后会自动更新结果。</p><DiagnosisProgress compact :statuses="statuses" :errors="errors" @retry-sample="$emit('retry-sample')" @retry-performance="$emit('retry-performance')" /></section></template>
