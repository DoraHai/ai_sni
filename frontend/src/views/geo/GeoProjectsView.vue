<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import GeoProjectExecution from '../../components/GeoProjectExecution.vue'
import { createGeoProject, fetchGeoProjects, updateGeoProject, updateGeoBusinessScope } from '../../api/geoProjects'
import { listGeoBusinesses } from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId, session } = useGeoTenant()
const loading = ref(false)
const saving = ref(false)
const dialogOpen = ref(false)
const editing = ref(null)
const projects = ref([])
const businesses = ref([])
const scopeOpen = ref(false)
const scopeProject = ref(null)
const scopeIds = ref([])
const executionProject = ref(null)
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
    const targetTenant = tenantId.value
    const [data, options] = await Promise.all([fetchGeoProjects(targetTenant), listGeoBusinesses(targetTenant)])
    if (targetTenant !== tenantId.value) return
    projects.value = data.projects || []
    businesses.value = options.items || []
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

function openScope(project) {
  scopeProject.value = project
  scopeIds.value = [...(project.business_scope?.business_ids || [])]
  scopeOpen.value = true
}

function otherOwner(businessId) {
  return projects.value.find(p => p.id !== scopeProject.value?.id && p.business_scope?.business_ids?.includes(businessId))
}

async function saveScope() {
  saving.value = true
  try {
    await updateGeoBusinessScope(scopeProject.value.id, tenantId.value, {
      business_ids: scopeIds.value, expected_revision: scopeProject.value.business_scope?.revision || 0,
    })
    scopeOpen.value = false
    ElMessage.success('项目业务归属已保存')
    await load()
  } catch (error) { ElMessage.error(error.message || '归属保存失败') }
  finally { saving.value = false }
}

watch(tenantId, () => { dialogOpen.value = false; scopeOpen.value = false; executionProject.value = null; projects.value = []; businesses.value = []; load() })
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="项目管理"
    sub="明确关联项目业务，报告和执行进度使用同一数据范围。"
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
        <el-table-column label="业务归属" min-width="160"><template #default="{ row }">{{ row.business_scope?.business_ids?.length ? `已关联 ${row.business_scope.business_ids.length} 个业务` : '待关联业务' }}</template></el-table-column>
        <el-table-column v-if="session.canView('geo.content')" label="执行进度" width="130"><template #default="{ row }"><el-button link type="primary" @click="executionProject = row">计划与待办</el-button></template></el-table-column>
        <el-table-column v-if="session.canEdit('geo.assets')" label="操作" width="180">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEditor(row)">编辑</el-button>
            <el-button link type="primary" @click="openScope(row)">关联业务</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer :model-value="!!executionProject" :title="`计划与执行 · ${executionProject?.name || ''}`" size="75%" destroy-on-close @close="executionProject = null">
      <GeoProjectExecution v-if="executionProject" :project-id="executionProject.id" :tenant-id="tenantId" />
    </el-drawer>

    <el-dialog v-model="scopeOpen" :title="`关联业务 · ${scopeProject?.name || ''}`" width="560px">
      <p>每个业务归属一个项目。未关联的历史数据保留待归属；解除关联不会删除数据。</p>
      <el-select v-model="scopeIds" multiple style="width:100%" placeholder="选择当前项目业务">
        <el-option v-for="b in businesses" :key="b.id" :value="b.id" :disabled="!!otherOwner(b.id)" :label="otherOwner(b.id) ? `${b.name}（归属 ${otherOwner(b.id).name}）` : b.name" />
      </el-select>
      <template #footer><el-button @click="scopeOpen = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveScope">保存归属</el-button></template>
    </el-dialog>

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
