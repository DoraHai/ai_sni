<script setup>
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createGeoFact, listGeoFacts, patchGeoFact, verifyGeoFact } from '../../api/geoContent'
import NeedHintAlert from '../../components/NeedHintAlert.vue'
import { useClientPager } from '../../composables/useClientPager'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const items = ref([])
const trust = ref('')
const pager = useClientPager(items, { pageSize: 20 })
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

const FACT_TYPE_LABELS = {
  product: '产品',
  case: '案例',
  metric: '指标',
  policy: '政策',
  other: '其他',
}
const TRUST_LABELS = {
  verified: '已核验',
  needs_review: '待审',
  draft: '草稿',
}
const STATUS_LABELS = {
  active: '生效中',
  archived: '已归档',
}

function factTypeLabel(v) {
  return FACT_TYPE_LABELS[v] || v || '—'
}
function trustLabel(v) {
  return TRUST_LABELS[v] || v || '—'
}
function statusLabel(v) {
  return STATUS_LABELS[v] || v || '—'
}

watch([tenantId, trust], () => {
  pager.resetPage()
  load()
})
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

    <NeedHintAlert />
    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <div class="filters">
      <el-select v-model="trust" clearable placeholder="信任级别" style="width: 168px">
        <el-option label="已核验" value="verified" />
        <el-option label="待审" value="needs_review" />
        <el-option label="草稿" value="draft" />
      </el-select>
      <span class="toolbar-hint">生成母稿需 ≥3 条已核验事实</span>
    </div>

    <div class="geo-table-shell">
      <el-table :data="pager.pagedItems" stripe empty-text="暂无事实">
        <el-table-column prop="id" label="ID" width="72" />
        <el-table-column label="标题 / 陈述" min-width="260">
          <template #default="{ row }">
            <div class="title">{{ row.title }}</div>
            <div class="sub">{{ row.statement }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ factTypeLabel(row.fact_type) }}</template>
        </el-table-column>
        <el-table-column label="来源" min-width="120">
          <template #default="{ row }">
            <div>{{ row.source_name || '—' }}</div>
            <div v-if="row.source_url" class="sub">{{ row.source_url }}</div>
          </template>
        </el-table-column>
        <el-table-column label="信任" width="110">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.trust_level === 'verified' ? 'success' : row.trust_level === 'needs_review' ? 'warning' : 'info'"
              effect="light"
            >
              {{ trustLabel(row.trust_level) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">{{ statusLabel(row.status) }}</template>
        </el-table-column>
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
      <div class="geo-pager">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="pager.total"
          :page-size="pager.pageSize"
          :current-page="pager.page"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="pager.onPageChange"
          @size-change="pager.onSizeChange"
        />
      </div>
    </div>

    <el-dialog v-model="editOpen" title="编辑事实" width="560px" class="geo-form-dialog">
      <el-form label-width="88px" label-position="right" class="geo-dialog-form">
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

    <el-dialog v-model="createOpen" title="新建事实" width="560px" class="geo-form-dialog">
      <el-form label-width="88px" label-position="right" class="geo-dialog-form">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" placeholder="简短可检索的事实标题" />
        </el-form-item>
        <el-form-item label="陈述" required>
          <el-input v-model="form.statement" type="textarea" :rows="3" placeholder="可核验的陈述原文" />
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
.title { font-weight: 650; color: #0f172a; }
.sub {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 3px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.toolbar-hint {
  margin-left: auto;
  font-size: 12px;
  color: #94a3b8;
}
</style>
