<script setup>
import { ref, watch } from 'vue'
import { fetchGeoProjects } from '../api/geoProjects'

const props = defineProps({ tenantId: Number, modelValue: Number })
const emit = defineEmits(['update:modelValue'])
const projects = ref([])
const error = ref('')
let generation = 0
watch(() => props.tenantId, async (tenantId) => {
  const current = ++generation
  projects.value = []
  error.value = ''
  emit('update:modelValue', null)
  if (!tenantId) return
  try {
    const data = await fetchGeoProjects(tenantId)
    if (current !== generation) return
    projects.value = (data.projects || []).filter((p) => p.status === 'active')
    if (projects.value.length === 1) emit('update:modelValue', projects.value[0].id)
  } catch (e) {
    if (current === generation) error.value = e.message || '项目加载失败'
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
</template>
