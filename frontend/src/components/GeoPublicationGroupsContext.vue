<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { session } from '../store/session'
import { geoAdvisorProject } from '../store/geoAdvisorProject.js'
import { fetchGeoProjects } from '../api/geoProjects'
import { scopeId } from '../utils/articlePublicationGroups.js'
import ArticlePublicationGroups from './ArticlePublicationGroups.vue'

const props = defineProps({ tenantId: Number, taskId: Number, taskTitle: String })
const route = useRoute()
const projects = ref([]), selected = ref(null), error = ref(''), loading = ref(false)
let epoch = 0
watch([() => props.tenantId, () => session.token, () => JSON.stringify(session.permissions),
  () => route.query.project_id, () => route.query.tenant_id, () => geoAdvisorProject.projectId], async () => {
  const current = ++epoch
  selected.value = null; projects.value = []; error.value = ''; loading.value = false
  if (!scopeId(props.tenantId) || props.tenantId !== session.tenantId) return
  if (route.query.tenant_id != null && scopeId(route.query.tenant_id) !== props.tenantId) {
    error.value = '当前客户与入口客户不同，请重新选择项目。'; return
  }
  const hint = route.query.project_id != null ? scopeId(route.query.project_id)
    : (geoAdvisorProject.token === session.token && geoAdvisorProject.tenantId === props.tenantId ? scopeId(geoAdvisorProject.projectId) : null)
  if (route.query.project_id != null && !hint) { error.value = '项目参数无效，请重新选择项目。'; return }
  // Explicit project hints are reauthorized by the GET handler. No tenant-wide
  // receipt lookup or task-ID probing is used to guess a project.
  if (hint) { selected.value = hint; return }
  loading.value = true
  try {
    const data = await fetchGeoProjects(props.tenantId)
    if (current !== epoch) return
    projects.value = (data.projects || []).filter(p => p.status === 'active' && scopeId(p.id))
    if (projects.value.length === 1) selected.value = projects.value[0].id
  } catch (e) { if (current === epoch) error.value = e.message || '项目读取失败' }
  finally { if (current === epoch) loading.value = false }
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { epoch++ })
const project = computed(() => scopeId(selected.value))
</script>

<template>
  <section>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="loading" role="status">正在读取已授权项目…</p>
    <label v-if="projects.length > 1">所属项目 <select v-model="selected"><option :value="null">请选择项目</option><option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option></select></label>
    <ArticlePublicationGroups v-if="project" :tenant-id="tenantId" :project-id="project" :task-id="taskId" :task-title="taskTitle" :focus-article-id="scopeId(route.query.focus_article)" />
    <div v-else-if="!loading" class="project-empty"><h2>{{ taskId ? '本任务发布记录' : '发布记录' }}</h2><p>请先选择客户和已授权项目，再查看发布记录。</p><p>没选项目的回传不会出现在这里，请到多号通回传收件箱补选项目。</p></div>
  </section>
</template>
<style scoped>.project-empty{padding:24px;background:#f8fafc;border:1px dashed #cbd5e1;border-radius:12px;color:#64748b;margin:16px 0}select{padding:8px 12px;margin:12px;border:1px solid #cbd5e1;border-radius:6px;max-width:90%}[role=alert]{color:#9f1239}</style>
