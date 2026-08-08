<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createGeoContentTask,
  createGeoPrompt,
  listGeoPrompts,
  listGeoUnits,
  patchGeoPrompt,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const route = useRoute()
const { tenantId } = useGeoTenant()

const loading = ref(false)
const error = ref('')
const items = ref([])
const units = ref([])
const status = ref('active')
const filterUnitId = ref(null)
const createOpen = ref(false)
const editOpen = ref(false)
const creating = ref(false)
const saving = ref(false)
const form = ref({
  question: '',
  priority: 10,
  tags: '',
  question_group: '推荐',
  is_brand_probe: false,
  unit_id: null,
})
const editForm = ref({
  id: null,
  question: '',
  priority: 10,
  tags: '',
  question_group: '',
  is_brand_probe: false,
  unit_id: null,
})

const unitLabel = (id) => {
  if (!id) return '—'
  const u = units.value.find((x) => x.id === id)
  return u ? `${u.name}${u.keyword ? ` (${u.keyword})` : ''}` : `#${id}`
}

async function loadUnits() {
  if (!tenantId.value) {
    units.value = []
    return
  }
  try {
    const data = await listGeoUnits(tenantId.value, { status: 'active' })
    units.value = data.items || []
  } catch {
    units.value = []
  }
}

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
      unit_id: filterUnitId.value || undefined,
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
      unit_id: form.value.unit_id || null,
      source: 'manual',
    })
    ElMessage.success('已创建优化意图词')
    createOpen.value = false
    form.value = {
      question: '',
      priority: 10,
      tags: '',
      question_group: '推荐',
      is_brand_probe: false,
      unit_id: filterUnitId.value || null,
    }
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

function openEdit(row) {
  editForm.value = {
    id: row.id,
    question: row.question || '',
    priority: row.priority ?? 10,
    tags: Array.isArray(row.tags) ? row.tags.join(', ') : '',
    question_group: row.question_group || '',
    is_brand_probe: !!row.is_brand_probe,
    unit_id: row.unit_id || null,
  }
  editOpen.value = true
}

async function submitEdit() {
  if (!editForm.value.question.trim() || editForm.value.question.trim().length < 4) {
    ElMessage.warning('问题至少 4 个字')
    return
  }
  saving.value = true
  try {
    await patchGeoPrompt(tenantId.value, editForm.value.id, {
      question: editForm.value.question.trim(),
      priority: Number(editForm.value.priority) || 0,
      tags: editForm.value.tags
        ? editForm.value.tags.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
        : [],
      question_group: editForm.value.question_group || null,
      is_brand_probe: !!editForm.value.is_brand_probe,
      unit_id: editForm.value.unit_id || null,
    })
    ElMessage.success('已保存')
    editOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function createTask(row) {
  try {
    const task = await createGeoContentTask({
      tenant_id: tenantId.value,
      prompt_id: row.id,
      title: row.question,
    })
    ElMessage.success(`已创建优化文章 #${task.id}`)
    router.push(`/geo/tasks/${task.id}`)
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
}

function syncUnitFilterFromRoute() {
  const q = route.query.unit_id
  filterUnitId.value = q ? Number(q) : null
  if (filterUnitId.value) form.value.unit_id = filterUnitId.value
}

watch([tenantId, status, filterUnitId], load)
watch(
  () => route.query.unit_id,
  () => {
    syncUnitFilterFromRoute()
    load()
  },
)
onMounted(async () => {
  syncUnitFilterFromRoute()
  await loadUnits()
  await load()
})
watch(tenantId, loadUnits)

const tagText = (tags) => (Array.isArray(tags) ? tags.join(', ') : '—')
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">优化意图词</div>
        <div class="page-desc">业务 → 单元 → 意图词三级结构 · 探测题不计入品牌提及率</div>
      </div>
      <div class="header-actions">
        <router-link class="el-button" to="/geo/businesses">优化业务</router-link>
        <el-button type="primary" @click="createOpen = true">新建意图词</el-button>
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
      <el-select
        v-model="filterUnitId"
        clearable
        filterable
        placeholder="按优化单元筛选"
        style="width: 220px"
      >
        <el-option
          v-for="u in units"
          :key="u.id"
          :label="`${u.name}${u.keyword ? ' · ' + u.keyword : ''}`"
          :value="u.id"
        />
      </el-select>
    </div>

    <el-table :data="items" stripe empty-text="暂无优化意图词">
      <el-table-column prop="id" label="ID" width="72" />
      <el-table-column label="问题" min-width="240">
        <template #default="{ row }">
          <div class="title">{{ row.question }}</div>
          <div class="sub">{{ row.question_group || '—' }} · {{ row.market || 'cn' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="优化单元" min-width="120">
        <template #default="{ row }">{{ unitLabel(row.unit_id) }}</template>
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
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link @click="openEdit(row)">编辑</el-button>
          <el-button type="primary" link @click="createTask(row)">建文章</el-button>
          <el-button
            v-if="row.status === 'active'"
            type="danger"
            link
            @click="archive(row)"
          >归档</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="editOpen" title="编辑优化意图词" width="520px">
      <el-form label-width="100px">
        <el-form-item label="问题" required>
          <el-input v-model="editForm.question" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="优化单元">
          <el-select v-model="editForm.unit_id" clearable filterable style="width: 100%" placeholder="可选">
            <el-option
              v-for="u in units"
              :key="u.id"
              :label="`${u.name}${u.keyword ? ' · ' + u.keyword : ''}`"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="editForm.priority" :min="0" :max="999" />
        </el-form-item>
        <el-form-item label="问题组">
          <el-input v-model="editForm.question_group" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="editForm.tags" placeholder="逗号分隔" />
        </el-form-item>
        <el-form-item label="品牌探测">
          <el-switch v-model="editForm.is_brand_probe" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="createOpen" title="新建优化意图词" width="520px">
      <el-form label-width="100px">
        <el-form-item label="问题" required>
          <el-input v-model="form.question" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="优化单元">
          <el-select v-model="form.unit_id" clearable filterable style="width: 100%" placeholder="可选">
            <el-option
              v-for="u in units"
              :key="u.id"
              :label="`${u.name}${u.keyword ? ' · ' + u.keyword : ''}`"
              :value="u.id"
            />
          </el-select>
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
