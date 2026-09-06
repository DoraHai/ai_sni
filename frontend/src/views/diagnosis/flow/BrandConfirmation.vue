<script setup>
import { computed, ref, watch } from 'vue'
import BrandProfileEditor from './BrandProfileEditor.vue'
import { splitLines } from '../brandProfileFields'
const props = defineProps({ draft:Object, missing:Array, editAll:Boolean })
defineEmits(['confirm','edit','field','back'])
// Keep initially missing inputs mounted while the user completes them.
const missingInputs = ref([...props.missing])
watch(() => props.missing, values => { for (const f of values) if (!missingInputs.value.some(x=>x.key===f.key)) missingInputs.value.push(f) })
const products = computed(() => splitLines(props.draft.core_products))
const host = computed(() => { try { return new URL(props.draft.website).hostname } catch { return props.draft.website } })
</script>
<template><section class="fd-confirm"><p class="fd-eyebrow">识别完成 · 请确认官网信息</p><h1>我们识别到的企业信息</h1><p class="fd-intro">确认这些信息，让诊断更贴近你的业务。</p><div class="fd-brand-summary"><h2>{{ draft.name || '品牌名称待补充' }}</h2><p>{{ draft.industry || '所属行业待补充' }}</p><dl><div><dt>主要产品</dt><dd>{{ products.join(' · ') || '核心产品 / 服务待补充' }}</dd></div><div><dt>官网</dt><dd>{{ host }}</dd></div></dl></div><p v-if="missing.length" class="fd-warning">还需要补充 {{ missing.length }} 项信息才能开始诊断</p><BrandProfileEditor v-if="editAll" :draft="draft" @field="(...args)=>$emit('field',...args)" /><BrandProfileEditor v-else-if="missingInputs.length" :draft="draft" :fields="missingInputs" @field="(...args)=>$emit('field',...args)" /><div class="fd-actions"><button class="fd-primary" :disabled="missing.length > 0" @click="$emit('confirm')">信息正确，开始诊断 →</button><button class="fd-secondary" :aria-expanded="editAll" @click="$emit('edit')">{{ editAll ? '收起完整信息' : '修改信息' }}</button></div><button class="fd-link" @click="$emit('back')">← 修改官网，重新识别</button></section></template>
