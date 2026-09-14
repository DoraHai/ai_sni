<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import {
  createGeoProject,
  fetchGeoProjects,
  updateGeoProject,
} from '../../api/geoProjects'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId, session } = useGeoTenant()
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const projects = ref([])
const dialogVisible = ref(false)
const editingId = ref(null)
const canEdit = computed(() => session.canEdit('geo.assets'))
const form = reactive({
  name: '',
  brand_name: '',
  domain: '',
  description: '',
  status: 'active',
})

function resetForm(row = null) {
  editingId.value = row?.id || null
  Object.assign(form, {
    name: row?.name || '',
    brand_name: row?.brand_name || '',
    domain: row?.domain || '',
    description: row?.description || '',
    status: row?.status || 'active',
  })
}

function openDialog(row = null) {
  if (!canEdit.value) return
  resetForm(row)
  dialogVisible.value = true
}

async function load() {
  const requestedTenantId = tenantId.value
  if (!requestedTenantId) {
    loading.value = false
    projects.value = []
    error.value = '请先选择客户'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await fetchGeoProjects(requestedTenantId)
    if (tenantId.value !== requestedTenantId) return
    projects.value = result.projects || []
  } catch (e) {
    if (tenantId.value !== requestedTenantId) return
    projects.value = []
    error.value = e.message || 'GEO 项目加载失败'
  } finally {
    if (tenantId.value === requestedTenantId) loading.value = false
  }
}

async function save() {
  const requestedTenantId = tenantId.value
  const name = form.name.trim()
  const domain = form.domain.trim()
  if (!requestedTenantId) {
    ElMessage.warning('请先选择客户')
    return
  }
  if (!name || !domain) {
    ElMessage.warning('请填写项目名称和网站域名')
    return
  }
  saving.value = true
  try {
    const body = {
      name,
      brand_name: form.brand_name.trim() || null,
      domain,
      description: form.description.trim() || null,
    }
    if (editingId.value) {
      await updateGeoProject(editingId.value, requestedTenantId, {
        ...body,
        status: form.status,
      })
    } else {
      await createGeoProject({ tenant_id: requestedTenantId, ...body })
    }
    if (tenantId.value !== requestedTenantId) return
    dialogVisible.value = false
    ElMessage.success(editingId.value ? 'GEO 项目已更新' : 'GEO 项目已创建')
    await load()
  } catch (e) {
    if (tenantId.value === requestedTenantId) {
      ElMessage.error(e.message || '保存失败')
    }
  } finally {
    saving.value = false
  }
}

watch(tenantId, () => {
  dialogVisible.value = false
  load()
})
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="项目管理"
    sub="维护当前客户的 GEO 项目、品牌与主网站；数据按客户隔离。"
    :show-period="false"
    :loading="loading"
  >
    <template #actions>
      <button class="gd-btn" :disabled="loading" @click="load">刷新</button>
      <button v-if="canEdit" class="gd-btn primary" @click="openDialog()">添加项目</button>
    </template>

    <el-alert v-if="error" type="error" :title="error" show-icon class="project-alert" />
    <section class="project-card">
      <el-table v-if="projects.length" :data="projects" stripe>
        <el-table-column prop="name" label="项目名称" min-width="180" />
        <el-table-column prop="brand_name" label="品牌" min-width="150">
          <template #default="{ row }">{{ row.brand_name || '—' }}</template>
        </el-table-column>
        <el-table-column prop="canonical_domain" label="主域名" min-width="220" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : row.status === 'paused' ? 'warning' : 'info'">
              {{ { active: '启用', paused: '暂停', archived: '归档' }[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="canEdit" label="操作" width="100" align="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDialog(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else-if="!loading && !error" description="当前客户尚未创建 GEO 项目">
        <el-button v-if="canEdit" type="primary" @click="openDialog()">添加项目</el-button>
      </el-empty>
    </section>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑 GEO 项目' : '添加 GEO 项目'"
      width="560px"
      destroy-on-close
    >
      <el-form label-width="90px">
        <el-form-item label="项目名称" required><el-input v-model="form.name" maxlength="120" /></el-form-item>
        <el-form-item label="品牌名称"><el-input v-model="form.brand_name" maxlength="160" /></el-form-item>
        <el-form-item label="网站域名" required><el-input v-model="form.domain" placeholder="www.example.com" maxlength="255" /></el-form-item>
        <el-form-item label="项目说明"><el-input v-model="form.description" type="textarea" :rows="4" maxlength="4000" show-word-limit /></el-form-item>
        <el-form-item v-if="editingId" label="状态">
          <el-select v-model="form.status">
            <el-option label="启用" value="active" />
            <el-option label="暂停" value="paused" />
            <el-option label="归档" value="archived" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </GeoWorkbenchPage>
</template>

<style scoped>
.project-alert { margin-bottom: 16px; }
.project-card { min-height: 260px; padding: 8px; border: 1px solid #e5e7eb; border-radius: 14px; background: #fff; }
</style>
