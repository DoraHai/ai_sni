<script setup>
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  createGeoFact,
  importGeoFactsCsv,
  listGeoBusinesses,
  listGeoFacts,
  patchGeoFact,
  verifyGeoFact,
} from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useClientPager } from '../../composables/useClientPager'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { getGeoPrototypePageSurface } from '../../utils/geoEditorSurface'

const prototypeSurface = getGeoPrototypePageSurface()
const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const items = ref([])
const businesses = ref([])
const pager = useClientPager(items, { pageSize: 20 })
const creating = ref(false)
const importingCsv = ref(false)
const csvInput = ref(null)
const verifyingId = ref(null)

function emptyForm() {
  return {
    title: '',
    statement: '',
    fact_type: 'product',
    source_name: '',
    source_url: '',
    expires_at: '',
    author_name: '',
    trust_level: 'needs_review',
    business_id: null,
  }
}
const form = ref(emptyForm())

const editOpen = ref(false)
const saving = ref(false)
const editForm = ref({ ...emptyForm(), id: null })

const TRUST_LABELS = {
  verified: 'verified',
  needs_review: 'needs_review',
  draft: 'draft',
}

function fmtExpires(v) {
  if (!v) return '不过期'
  return String(v).slice(0, 10)
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
    const [data, b] = await Promise.all([
      listGeoFacts(tenantId.value),
      businesses.value.length
        ? Promise.resolve({ items: businesses.value })
        : listGeoBusinesses(tenantId.value, { status: 'active' }).catch(() => ({ items: [] })),
    ])
    businesses.value = b.items || businesses.value
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
      expires_at: form.value.expires_at || null,
      author_name: form.value.author_name.trim() || null,
      trust_level: form.value.trust_level || 'needs_review',
      business_id: form.value.business_id || null,
    })
    ElMessage.success('已创建事实卡')
    form.value = emptyForm()
    await load()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    creating.value = false
  }
}

async function verifyFact(row) {
  const statement = String(row.statement || '').trim()
  if (statement.length < 8 || !row.source_url) {
    ElMessage.warning('核验需要至少 8 字的陈述和来源 URL')
    return
  }
  verifyingId.value = row.id
  try {
    await verifyGeoFact(tenantId.value, row.id, {
      excerpt: statement.slice(0, 400),
      excerpt_locator: '事实库陈述',
      source_url: row.source_url,
    })
    ElMessage.success(`已核验 #${row.id}`)
    await load()
  } catch (e) {
    ElMessage.error(e.message || '核验失败')
  } finally {
    verifyingId.value = null
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
    expires_at: row.expires_at ? String(row.expires_at).slice(0, 10) : '',
    author_name: row.author_name || '',
    trust_level: row.trust_level || 'needs_review',
    business_id: row.business_id || null,
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
      expires_at: editForm.value.expires_at || null,
      author_name: editForm.value.author_name.trim() || null,
      trust_level: editForm.value.trust_level || null,
      business_id: editForm.value.business_id || null,
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

async function archive(row) {
  try {
    await patchGeoFact(tenantId.value, row.id, { status: 'archived' })
    ElMessage.success(`已归档 #${row.id}`)
    await load()
  } catch (e) {
    ElMessage.error(e.message || '归档失败')
  }
}

async function importFactCsv(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || !tenantId.value) return
  importingCsv.value = true
  try {
    const result = await importGeoFactsCsv(tenantId.value, file)
    const count = Number(result.ok_count ?? 0)
    const errors = result.errors || []
    ElMessage.success(`CSV 导入完成：${count} 条`)
    if (errors.length) ElMessage.warning(`另有 ${errors.length} 条未导入，请检查 CSV 格式`)
    await load()
  } catch (e) {
    ElMessage.error(e.message || 'CSV 导入失败')
  } finally {
    importingCsv.value = false
  }
}

watch(tenantId, () => {
  pager.resetPage()
  load()
})
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="知识库"
    :show-period="false"
    sub="存放可被 AI 直接引用的品牌事实，供 GEO 文章绑定，并用于纠偏事实偏差"
    :loading="loading"
  >
    <template #actions>
      <router-link class="gd-btn" to="/geo/brand">品牌信息</router-link>
      <button class="gd-btn" type="button" @click="load">刷新</button>
    </template>

    <div class="geo-dash facts-page">
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <div class="facts-grid">
        <section class="gd-card">
          <div class="gd-hd">
            <h3>事实卡</h3>
            <div class="hd-actions">
              <button
                class="gd-btn"
                type="button"
                :disabled="importingCsv"
                @click="csvInput?.click()"
              >
                {{ importingCsv ? '导入中…' : 'CSV 导入' }}
              </button>
              <input
                ref="csvInput"
                type="file"
                accept=".csv,text/csv"
                hidden
                @change="importFactCsv"
              />
              <button class="gd-btn" type="button" @click="load">刷新</button>
            </div>
          </div>
          <div class="gd-sub pad">
            表头：title,statement,fact_type,source_name,source_url,observed_at,trust_level,author_name
          </div>
          <div class="gd-bd" style="padding:0">
            <el-table
              :data="pager.pagedItems"
              empty-text="暂无事实卡 · 可手动新建或 CSV 导入"
              size="small"
            >
              <el-table-column label="标题" min-width="140">
                <template #default="{ row }">
                  <div class="title">{{ row.title || '—' }}</div>
                </template>
              </el-table-column>
              <el-table-column label="陈述" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">{{ row.statement || '—' }}</template>
              </el-table-column>
              <el-table-column label="来源" min-width="140">
                <template #default="{ row }">
                  <div>{{ row.source_name || '—' }}</div>
                  <div v-if="row.source_url" class="sub">{{ row.source_url }}</div>
                </template>
              </el-table-column>
              <el-table-column label="作者" width="100">
                <template #default="{ row }">{{ row.author_name || '—' }}</template>
              </el-table-column>
              <el-table-column label="可信度" width="110">
                <template #default="{ row }">
                  {{ TRUST_LABELS[row.trust_level] || row.trust_level || '—' }}
                </template>
              </el-table-column>
              <el-table-column label="过期日" width="110">
                <template #default="{ row }">{{ fmtExpires(row.expires_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="160" fixed="right">
                <template #default="{ row }">
                  <el-button
                    link
                    type="primary"
                    :loading="verifyingId === row.id"
                    @click="verifyFact(row)"
                  >核验</el-button>
                  <el-button link @click="openEdit(row)">编辑</el-button>
                  <el-button
                    v-if="prototypeSurface.showKnowledgeHealth && row.status === 'active'"
                    link
                    type="danger"
                    @click="archive(row)"
                  >归档</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div class="geo-pager">
              <el-pagination
                background
                layout="total, prev, pager, next"
                :total="pager.total"
                :page-size="pager.pageSize"
                :current-page="pager.page"
                @current-change="pager.onPageChange"
              />
            </div>
          </div>
        </section>

        <section class="gd-card create-card">
          <div class="gd-hd"><h3>新建事实卡</h3></div>
          <div class="gd-bd">
            <el-form label-position="top" size="small">
              <el-form-item label="标题" required>
                <el-input v-model="form.title" placeholder="如：私有化部署" />
              </el-form-item>
              <el-form-item label="事实陈述" required>
                <el-input
                  v-model="form.statement"
                  type="textarea"
                  :rows="4"
                  placeholder="可被引用的完整陈述"
                />
              </el-form-item>
              <el-form-item label="来源名称（必填）" required>
                <el-input v-model="form.source_name" placeholder="产品白皮书 2026" />
              </el-form-item>
              <el-form-item label="来源 URL">
                <el-input v-model="form.source_url" placeholder="https://" />
              </el-form-item>
              <el-form-item label="过期日（可选）">
                <el-input v-model="form.expires_at" type="date" />
              </el-form-item>
              <el-form-item label="类型">
                <el-select v-model="form.fact_type" style="width: 100%">
                  <el-option label="product" value="product" />
                  <el-option label="case" value="case" />
                  <el-option label="metric" value="metric" />
                  <el-option label="policy" value="policy" />
                  <el-option label="other" value="other" />
                </el-select>
              </el-form-item>
              <el-form-item v-if="prototypeSurface.showKnowledgeHealth" label="作者">
                <el-input v-model="form.author_name" placeholder="可选" />
              </el-form-item>
              <el-button
                type="primary"
                :loading="creating"
                style="width: 100%"
                @click="submitCreate"
              >
                创建
              </el-button>
            </el-form>
          </div>
        </section>
      </div>
    </div>

    <el-dialog v-model="editOpen" title="编辑事实卡" width="560px">
      <el-form label-width="96px">
        <el-form-item label="标题" required>
          <el-input v-model="editForm.title" />
        </el-form-item>
        <el-form-item label="陈述" required>
          <el-input v-model="editForm.statement" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="editForm.fact_type" style="width: 100%">
            <el-option label="product" value="product" />
            <el-option label="case" value="case" />
            <el-option label="metric" value="metric" />
            <el-option label="policy" value="policy" />
            <el-option label="other" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源名">
          <el-input v-model="editForm.source_name" />
        </el-form-item>
        <el-form-item label="来源 URL">
          <el-input v-model="editForm.source_url" />
        </el-form-item>
        <el-form-item label="作者">
          <el-input v-model="editForm.author_name" />
        </el-form-item>
        <el-form-item label="可信度">
          <el-select v-model="editForm.trust_level" style="width: 100%">
            <el-option label="verified" value="verified" />
            <el-option label="needs_review" value="needs_review" />
            <el-option label="draft" value="draft" />
          </el-select>
        </el-form-item>
        <el-form-item label="过期日">
          <el-input v-model="editForm.expires_at" type="date" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </GeoWorkbenchPage>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.pad { padding: 0 14px 8px; }
.facts-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(280px, 380px);
  gap: 14px;
  align-items: start;
}
.hd-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}
.title { font-weight: 650; color: #1e2330; }
.sub {
  margin-top: 3px;
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.4;
  word-break: break-all;
}
.gd-sub {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.45;
}
.geo-pager {
  display: flex;
  justify-content: flex-end;
  padding: 10px 14px;
}
@media (max-width: 1100px) {
  .facts-grid { grid-template-columns: 1fr; }
}
</style>
