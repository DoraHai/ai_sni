<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { createGeoProject, fetchGeoProjects, updateGeoProject } from '../../api/geoProjects'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId, session } = useGeoTenant()
const loading = ref(false)
const saving = ref(false)
const dialogOpen = ref(false)
const editing = ref(null)
const projects = ref([])
const form = reactive({
  name: '',
  brand_name: '',
  domain: '',
  description: '',
  status: 'active',
})

async function load() {
  if (!tenantId.value) {
    projects.value = []
    return
  }
  loading.value = true
  try {
    const data = await fetchGeoProjects(tenantId.value)
    projects.value = data.projects || []
  } catch (error) {
    ElMessage.error(error.message || '项目加载失败')
  } finally {
    loading.value = false
  }
}

function openEditor(project = null) {
  editing.value = project
  Object.assign(form, {
    name: project?.name || '',
    brand_name: project?.brand_name || '',
    domain: project?.domain || '',
    description: project?.description || '',
    status: project?.status || 'active',
  })
  dialogOpen.value = true
}

async function save() {
  if (!form.name.trim() || !form.domain.trim()) {
    ElMessage.warning('请填写项目名称和网站域名')
    return
  }
  saving.value = true
  try {
    const body = {
      name: form.name,
      brand_name: form.brand_name,
      domain: form.domain,
      description: form.description,
      ...(editing.value ? { status: form.status } : { tenant_id: tenantId.value }),
    }
    if (editing.value) {
      await updateGeoProject(editing.value.id, tenantId.value, body)
    } else {
      await createGeoProject(body)
    }
    dialogOpen.value = false
    ElMessage.success('GEO 项目已保存')
    await load()
  } catch (error) {
    ElMessage.error(error.message || '项目保存失败')
  } finally {
    saving.value = false
  }
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="项目管理"
    sub="维护每个客户的品牌与网站项目，后续 GEO 数据按客户和项目归属。"
    :show-period="false"
    :loading="loading"
  >
    <template #actions>
      <button class="gd-btn" :disabled="loading" @click="load">刷新</button>
      <button
        v-if="session.canEdit('geo.assets')"
        class="gd-btn primary"
        :disabled="!tenantId"
        @click="openEditor()"
      >新建项目</button>
    </template>

    <div class="geo-projects">
      <el-empty v-if="!loading && !projects.length" description="尚未添加 GEO 项目" />
      <el-table v-else :data="projects" border>
        <el-table-column prop="name" label="项目名称" min-width="180" />
        <el-table-column prop="brand_name" label="品牌" min-width="140" />
        <el-table-column prop="canonical_domain" label="主域名" min-width="220" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column v-if="session.canEdit('geo.assets')" label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEditor(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogOpen" :title="editing ? '编辑项目' : '新建项目'" width="560px">
      <el-form label-width="90px">
        <el-form-item label="项目名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="品牌名称"><el-input v-model="form.brand_name" /></el-form-item>
        <el-form-item label="网站域名">
          <el-input v-model="form.domain" placeholder="www.example.com" />
        </el-form-item>
        <el-form-item label="项目说明">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item v-if="editing" label="状态">
          <el-select v-model="form.status">
            <el-option label="启用" value="active" />
            <el-option label="暂停" value="paused" />
            <el-option label="归档" value="archived" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </GeoWorkbenchPage>
</template>

<style scoped>
.geo-projects {
  padding: 20px;
  background: #fff;
  border: 1px solid #e8eaf0;
  border-radius: 14px;
}
</style>
