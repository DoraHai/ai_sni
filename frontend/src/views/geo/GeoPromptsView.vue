<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createGeoContentTask, createGeoPrompt, listGeoPrompts, patchGeoPrompt } from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const { tenantId } = useGeoTenant()

const loading = ref(false)
const error = ref('')
const items = ref([])
const status = ref('active')
const createOpen = ref(false)
const creating = ref(false)
const form = ref({
  question: '',
  priority: 10,
  tags: '',
  question_group: '推荐',
  is_brand_probe: false,
})

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    items.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await listGeoPrompts(tenantId.value, {
      status: status.value || undefined,
    })
    items.value = data.items || []
  } catch (e) {
    error.value = e.message || '加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

async function submitCreate() {
  if (!form.value.question.trim() || form.value.question.trim().length < 4) {
    ElMessage.warning('问题至少 4 个字')
    return
  }
  creating.value = true
  try {
    await createGeoPrompt({
      tenant_id: tenantId.value,
      question: form.value.question.trim(),
      priority: Number(form.value.priority) || 0,
      tags: form.value.tags
        ? form.value.tags.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
        : [],
      question_group: form.value.question_group || null,
      is_brand_probe: !!form.value.is_brand_probe,
      source: 'manual',
    })
    ElMessage.success('已创建机会词')
    createOpen.value = false
    form.value = { question: '', priority: 10, tags: '', question_group: '推荐', is_brand_probe: false }
    await load()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    creating.value = false
  }
}

async function archive(row) {
  try {
    await patchGeoPrompt(tenantId.value, row.id, { status: 'archived' })
    ElMessage.success(`已归档 #${row.id}`)
    await load()
  } catch (e) {
    ElMessage.error(e.message || '归档失败')
  }
}

async function createTask(row) {
  try {
    const task = await createGeoContentTask({
      tenant_id: tenantId.value,
      prompt_id: row.id,
      title: row.question,
    })
    ElMessage.success(`已创建任务 #${task.id}`)
    router.push(`/geo/tasks/${task.id}`)
  } catch (e) {
    ElMessage.error(e.message || '创建任务失败')
  }
}

watch([tenantId, status], load)
onMounted(load)

const tagText = (tags) => (Array.isArray(tags) ? tags.join(', ') : '—')
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">机会词</div>
        <div class="page-desc">对应静态 prompts.html · 方案 B 已迁 Vue</div>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="createOpen = true">新建机会词</el-button>
        <el-button @click="load">刷新</el-button>
        <router-link class="el-button" to="/geo/workbench">工作台</router-link>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <div class="filters">
      <el-select v-model="status" style="width: 140px">
        <el-option label="活跃" value="active" />
        <el-option label="已归档" value="archived" />
        <el-option label="全部" value="" />
      </el-select>
    </div>

    <el-table :data="items" stripe empty-text="暂无机会词">
      <el-table-column prop="id" label="ID" width="72" />
      <el-table-column label="问题" min-width="240">
        <template #default="{ row }">
          <div class="title">{{ row.question }}</div>
          <div class="sub">{{ row.question_group || '—' }} · {{ row.market || 'cn' }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="priority" label="优先级" width="80" />
      <el-table-column label="标签" min-width="120">
        <template #default="{ row }">{{ tagText(row.tags) }}</template>
      </el-table-column>
      <el-table-column label="探测题" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.is_brand_probe" size="small" type="warning">是</el-tag>
          <span v-else class="muted">否</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link @click="createTask(row)">建任务</el-button>
          <el-button
            v-if="row.status === 'active'"
            type="danger"
            link
            @click="archive(row)"
          >归档</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createOpen" title="新建机会词" width="520px">
      <el-form label-width="100px">
        <el-form-item label="问题" required>
          <el-input v-model="form.question" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="form.priority" :min="0" :max="999" />
        </el-form-item>
        <el-form-item label="问题组">
          <el-input v-model="form.question_group" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="form.tags" placeholder="逗号分隔" />
        </el-form-item>
        <el-form-item label="品牌探测">
          <el-switch v-model="form.is_brand_probe" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.geo-page { padding: 4px 2px 24px; }
.page-header {
  display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.page-title { font-size: 20px; font-weight: 700; }
.page-desc { font-size: 13px; color: #6b7280; margin-top: 4px; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.filters { margin-bottom: 12px; }
.mb { margin-bottom: 12px; }
.title { font-weight: 600; }
.sub, .muted { font-size: 12px; color: #8b93a7; }
</style>
