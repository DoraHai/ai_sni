<script setup>
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createGeoFact, listGeoFacts, patchGeoFact, verifyGeoFact } from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const items = ref([])
const trust = ref('')
const createOpen = ref(false)
const editOpen = ref(false)
const creating = ref(false)
const saving = ref(false)
const form = ref({
  title: '',
  statement: '',
  fact_type: 'product',
  source_name: '',
  source_url: '',
  trust_level: 'needs_review',
})
const editForm = ref({
  id: null,
  title: '',
  statement: '',
  fact_type: 'product',
  source_name: '',
  source_url: '',
  trust_level: 'needs_review',
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
    const params = {}
    if (trust.value) params.trust_level = trust.value
    const data = await listGeoFacts(tenantId.value, params)
    items.value = data.items || []
  } catch (e) {
    error.value = e.message || '加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

async function submitCreate() {
  if (!form.value.title.trim() || !form.value.statement.trim() || !form.value.source_name.trim()) {
    ElMessage.warning('标题、陈述与来源名必填')
    return
  }
  creating.value = true
  try {
    await createGeoFact({
      tenant_id: tenantId.value,
      title: form.value.title.trim(),
      statement: form.value.statement.trim(),
      fact_type: form.value.fact_type,
      source_name: form.value.source_name.trim(),
      source_url: form.value.source_url.trim() || null,
      trust_level: form.value.trust_level,
    })
    ElMessage.success('已创建事实')
    createOpen.value = false
    form.value = {
      title: '',
      statement: '',
      fact_type: 'product',
      source_name: '',
      source_url: '',
      trust_level: 'needs_review',
    }
    await load()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    creating.value = false
  }
}

async function onVerify(row) {
  try {
    await verifyGeoFact(tenantId.value, row.id)
    ElMessage.success(`已核验 #${row.id}`)
    await load()
  } catch (e) {
    ElMessage.error(e.message || '核验失败')
  }
}

async function archive(row) {
  try {
    await patchGeoFact(tenantId.value, row.id, { status: 'archived' })
    ElMessage.success(`已归档 #${row.id}`)
    await load()
  } catch (e) {
    ElMessage.error(e.message || '归档失败')
  }
}

function openEdit(row) {
  editForm.value = {
    id: row.id,
    title: row.title || '',
    statement: row.statement || '',
    fact_type: row.fact_type || 'product',
    source_name: row.source_name || '',
    source_url: row.source_url || '',
    trust_level: row.trust_level || 'needs_review',
  }
  editOpen.value = true
}

async function submitEdit() {
  if (!editForm.value.title.trim() || !editForm.value.statement.trim()) {
    ElMessage.warning('标题与陈述必填')
    return
  }
  saving.value = true
  try {
    await patchGeoFact(tenantId.value, editForm.value.id, {
      title: editForm.value.title.trim(),
      statement: editForm.value.statement.trim(),
      fact_type: editForm.value.fact_type,
      source_name: editForm.value.source_name.trim() || null,
      source_url: editForm.value.source_url.trim() || null,
      trust_level: editForm.value.trust_level,
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

watch([tenantId, trust], load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">事实库</div>
        <div class="page-desc">对应静态 sources.html · 方案 B 已迁 Vue</div>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="createOpen = true">新建事实</el-button>
        <el-button @click="load">刷新</el-button>
        <router-link class="el-button" to="/geo/workbench">工作台</router-link>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <div class="filters">
      <el-select v-model="trust" clearable placeholder="信任级别" style="width: 160px">
        <el-option label="已核验" value="verified" />
        <el-option label="待审" value="needs_review" />
        <el-option label="草稿" value="draft" />
      </el-select>
    </div>

    <el-table :data="items" stripe empty-text="暂无事实">
      <el-table-column prop="id" label="ID" width="72" />
      <el-table-column label="标题 / 陈述" min-width="260">
        <template #default="{ row }">
          <div class="title">{{ row.title }}</div>
          <div class="sub">{{ row.statement }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="fact_type" label="类型" width="90" />
      <el-table-column label="来源" min-width="120">
        <template #default="{ row }">
          <div>{{ row.source_name || '—' }}</div>
          <div v-if="row.source_url" class="sub">{{ row.source_url }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="trust_level" label="信任" width="110" />
      <el-table-column prop="status" label="状态" width="90" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link @click="openEdit(row)">编辑</el-button>
          <el-button
            v-if="row.trust_level !== 'verified' && row.status === 'active'"
            type="primary"
            link
            @click="onVerify(row)"
          >核验</el-button>
          <el-button
            v-if="row.status === 'active'"
            type="danger"
            link
            @click="archive(row)"
          >归档</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="editOpen" title="编辑事实" width="560px">
      <el-form label-width="88px">
        <el-form-item label="标题" required>
          <el-input v-model="editForm.title" />
        </el-form-item>
        <el-form-item label="陈述" required>
          <el-input v-model="editForm.statement" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="editForm.fact_type" style="width: 100%">
            <el-option label="产品" value="product" />
            <el-option label="案例" value="case" />
            <el-option label="指标" value="metric" />
            <el-option label="政策" value="policy" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源名">
          <el-input v-model="editForm.source_name" />
        </el-form-item>
        <el-form-item label="来源 URL">
          <el-input v-model="editForm.source_url" />
        </el-form-item>
        <el-form-item label="信任级">
          <el-select v-model="editForm.trust_level" style="width: 100%">
            <el-option label="待审" value="needs_review" />
            <el-option label="已核验" value="verified" />
            <el-option label="草稿" value="draft" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="createOpen" title="新建事实" width="560px">
      <el-form label-width="88px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" />
        </el-form-item>
        <el-form-item label="陈述" required>
          <el-input v-model="form.statement" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.fact_type" style="width: 100%">
            <el-option label="产品" value="product" />
            <el-option label="案例" value="case" />
            <el-option label="指标" value="metric" />
            <el-option label="政策" value="policy" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源名" required>
          <el-input v-model="form.source_name" />
        </el-form-item>
        <el-form-item label="来源 URL">
          <el-input v-model="form.source_url" />
        </el-form-item>
        <el-form-item label="信任级">
          <el-select v-model="form.trust_level" style="width: 100%">
            <el-option label="待审" value="needs_review" />
            <el-option label="已核验" value="verified" />
            <el-option label="草稿" value="draft" />
          </el-select>
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
.sub { font-size: 12px; color: #8b93a7; margin-top: 2px; }
</style>
