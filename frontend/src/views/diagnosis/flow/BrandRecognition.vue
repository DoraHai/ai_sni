<script setup>
defineProps({ website:String, failed:Boolean })
defineEmits(['retry','manual','back'])
</script>
<template><section class="fd-centered" aria-live="polite"><div v-if="!failed" class="fd-spinner" aria-hidden="true" /><p class="fd-eyebrow">企业识别</p><h1>{{ failed ? '暂时无法识别企业' : '正在了解你的企业' }}</h1><p class="fd-intro">正在读取：{{ website }}</p><p class="fd-note">仅使用官网公开信息，识别后由你确认。</p><div v-if="failed" class="fd-actions"><button class="fd-primary" @click="$emit('retry')">重新识别 →</button><button class="fd-secondary" @click="$emit('manual')">手动补充信息</button></div><button class="fd-link" @click="$emit('back')">← 修改网址</button></section></template>
