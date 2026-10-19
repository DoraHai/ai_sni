<script setup>
import { ref, watch } from 'vue'
import { fetchGeoProjects } from '../api/geoProjects'

const props = defineProps({ tenantId: Number, modelValue: Number })
const emit = defineEmits(['update:modelValue'])
const projects = ref([])
const error = ref('')
const loading = ref(false)
let generation = 0
watch(() => props.tenantId, async (tenantId) => {
  const current = ++generation
  projects.value = []
  error.value = ''
  loading.value = false
  emit('update:modelValue', null)
  if (!tenantId) return
  loading.value = true
  try {
    const data = await fetchGeoProjects(tenantId)
    if (current !== generation) return
    projects.value = (data.projects || []).filter((p) => p.status === 'active')
    if (projects.value.length === 1) emit('update:modelValue', projects.value[0].id)
  } catch (e) {
    if (current === generation) error.value = e.message || '项目加载失败'
  } finally {
    if (current === generation) loading.value = false
  }
}, { immediate: true })
</script>

<template>
  <label>
    所属项目
    <select :value="modelValue || ''" @change="emit('update:modelValue', Number($event.target.value) || null)">
      <option value="">请选择已分配给你的项目</option>
      <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
    </select>
  </label>
  <span v-if="error" role="alert">{{ error }}</span>
  <span v-else-if="loading" role="status">正在读取已分配项目…</span>
  <span v-else-if="tenantId && !projects.length" role="status">当前客户没有分配给你的有效 GEO 项目，请让超管在「GEO → 项目管理 → 计划与待办 → 项目顾问」核对分配和项目状态。</span>
</template>
