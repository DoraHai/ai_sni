<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import logo from '../../../assets/g-snipers-purple-logo.png'
import WebsiteEntry from './WebsiteEntry.vue'
import BrandRecognition from './BrandRecognition.vue'
import BrandConfirmation from './BrandConfirmation.vue'
import DiagnosisProgress from './DiagnosisProgress.vue'
import DiagnosisComplete from './DiagnosisComplete.vue'
import './free-diagnosis.css'
const props = defineProps({flow:Object,audit:Object})
const emit = defineEmits(['report'])
const body = ref(null)
const host = computed(()=>{try{return new URL(props.flow.website.value).hostname}catch{return props.flow.website.value}})
watch(()=>props.flow.stage.value, async()=>{await nextTick(); body.value?.focus(); window.scrollTo({top:0})})
</script>
<template><main class="free-diagnosis"><header class="fd-header"><a href="/growth-sniper" class="fd-brand"><img :src="logo" alt=""><span>获客狙击手<small>G-SNIPERS</small></span></a><span>免费网站诊断</span><button v-if="audit && !['recognizing','saving','progress'].includes(flow.stage.value)" class="fd-link" @click="emit('report')">返回已有报告 →</button></header><div ref="body" class="fd-body" tabindex="-1"><p v-if="flow.error.value" class="fd-error" role="alert">{{ flow.error.value }}</p><WebsiteEntry v-if="flow.stage.value==='entry'" :website="flow.website.value" @update:website="flow.website.value=$event" @start="flow.discover" /><BrandRecognition v-else-if="['recognizing','recognition-error'].includes(flow.stage.value)" :website="host" :failed="flow.stage.value==='recognition-error'" @retry="flow.discover" @manual="flow.manual" @back="flow.reset(flow.website.value)" /><BrandConfirmation v-else-if="flow.stage.value==='confirm'" :draft="flow.draft" :missing="flow.missing.value" :edit-all="flow.editAll.value" @edit="flow.editAll.value=!flow.editAll.value" @field="flow.setField" @confirm="flow.confirm" @back="flow.reset(flow.website.value)" /><DiagnosisProgress v-else-if="['saving','progress'].includes(flow.stage.value)" :saving="flow.stage.value==='saving'" :statuses="flow.statuses" :errors="flow.errors" @retry-audit="flow.runAudit" @retry-sample="flow.sample({automatic:true})" @retry-performance="flow.performance" /><DiagnosisComplete v-else-if="flow.stage.value==='complete' && audit" :audit="audit" :statuses="flow.statuses" :errors="flow.errors" @report="emit('report')" @retry-sample="flow.sample()" @retry-performance="flow.performance" /></div><footer class="fd-footer">公开信息 · 真实检测 · 由你确认</footer></main></template>
