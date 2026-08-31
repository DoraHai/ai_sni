<script setup>
/**
 * 优化单元：挂在业务下的关键词主题，意图词入库时关联到这里。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoUnit,
  listGeoBusinesses,
  listGeoUnits,
  patchGeoUnit,
} from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useClientPager } from '../../composables/useClientPager'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const businesses = ref([])
const units = ref([])
const status = ref('active')
const filterBusinessId = ref(null)
const qSearch = ref('')
const dialogOpen = ref(false)
const saving = ref(false)
const editing = ref(null)

function emptyForm() {
  return {
    business_id: filterBusinessId.value || null,
    name: '',
    keyword: '',
    description: '',
  }
}
const form = ref(emptyForm())

const filtered = computed(() => {
  let rows = units.value || []
  if (filterBusinessId.value) {
    rows = rows.filter((u) => u.business_id === filterBusinessId.value)
  }
  const q = qSearch.value.trim().toLowerCase()
  if (q) {
    rows = rows.filter((u) =>
      `${u.name || ''} ${u.keyword || ''} ${u.description || ''}`.toLowerCase().includes(q),
    )
  }
  return rows
})
const pager = useClientPager(filtered, { pageSize: 20 })

function bizName(id) {
  return businesses.value.find((b) => b.id === id)?.name || (id ? `#${id}` : '—')
}

function promptCount(row) {
  return row.prompt_count ?? 0
}

function statusMeta(row) {
  if (row.status === 'archived') return { zh: '已归档', tone: 'muted' }
  return { zh: '活跃', tone: 'ok' }
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [b, u] = await Promise.all([
      listGeoBusinesses(tenantId.value, { status: 'active' }),
      listGeoUnits(tenantId.value, { status: status.value }),
    ])
    businesses.value = b.items || []
    units.value = u.items || []
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  if (!businesses.value.length) {
    ElMessage.warning('请先到「品牌资料」建一条业务')
    return
  }
  editing.value = null
  form.value = emptyForm()
  if (!form.value.business_id) form.value.business_id = businesses.value[0].id
  dialogOpen.value = true
}

function openEdit(row) {
  editing.value = row
  form.value = {
    business_id: row.business_id,
    name: row.name || '',
    keyword: row.keyword || '',
    description: row.description || '',
  }
  dialogOpen.value = true
}

async function submitForm() {
  const name = String(form.value.name || '').trim()
  if (!form.value.business_id || !name) {
    ElMessage.warning('请选择业务并填写单元名称')
    return
  }
  saving.value = true
  try {
    const keyword = String(form.value.keyword || '').trim() || name
    const description = String(form.value.description || '').trim() || null
    if (editing.value) {
      await patchGeoUnit(tenantId.value, editing.value.id, {
        name,
        keyword,
        description,
        business_id: form.value.business_id,
      })
      ElMessage.success('已保存')
    } else {
      await createGeoUnit({
        tenant_id: tenantId.value,
        business_id: form.value.business_id,
        name,
        keyword,
        description,
      })
      ElMessage.success('已添加优化单元')
    }
    dialogOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

function goQuestions(row) {
  router.push({ path: '/geo/prompts', query: { unit_id: String(row.id) } })
}

async function archiveUnit(row) {
  try {
    await ElMessageBox.confirm(`归档「${row.keyword || row.name}」？挂在它下面的提问不会删。`, '归档', {
      type: 'warning',
      confirmButtonText: '归档',
    })
    await patchGeoUnit(tenantId.value, row.id, { status: 'archived' })
    ElMessage.success('已归档')
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '归档失败')
  }
}

async function restoreUnit(row) {
  try {
    await patchGeoUnit(tenantId.value, row.id, { status: 'active' })
    ElMessage.success('已恢复')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '恢复失败')
  }
}

watch([tenantId, status], load)
watch([filterBusinessId, qSearch], () => pager.resetPage())
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="优化单元"
    :show-period="false"
    sub="挂在业务下的关键词主题。生成意图词时选中它，提问才会进对应业务切片"
    :loading="loading"
  >
    <template #actions>
      <input v-model="qSearch" class="gd-search" placeholder="搜索单元 / 关键词…" />
      <button class="gd-btn" @click="load">刷新</button>
      <button class="gd-btn primary" @click="openCreate">+ 新增单元</button>
    </template>

    <div class="geo-dash">
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <div class="geo-filter-bar">
        <el-select v-model="status" style="width: 140px">
          <el-option label="活跃" value="active" />
          <el-option label="已归档" value="archived" />
          <el-option label="全部" value="" />
        </el-select>
        <el-select
          v-model="filterBusinessId"
          clearable
          filterable
          placeholder="全部业务"
          style="width: 220px"
        >
          <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
        </el-select>
        <router-link v-if="!businesses.length" class="gd-btn" to="/geo/brand">去品牌资料建业务</router-link>
      </div>

      <div class="geo-table-card">
        <el-table :data="pager.pagedItems" empty-text="还没有优化单元。先选业务再新增。">
          <el-table-column label="单元 / 关键词" min-width="220">
            <template #default="{ row }">
              <div class="name">{{ row.name }}</div>
              <div v-if="row.keyword && row.keyword !== row.name" class="note">{{ row.keyword }}</div>
              <div v-if="row.description" class="note">{{ row.description }}</div>
            </template>
          </el-table-column>
          <el-table-column label="所属业务" min-width="160">
            <template #default="{ row }">{{ bizName(row.business_id) }}</template>
          </el-table-column>
          <el-table-column label="意图词" width="100">
            <template #default="{ row }">{{ promptCount(row) }} 条</template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <span class="geo-status-cell">
                <i class="geo-status-dot" :class="statusMeta(row).tone" />
                {{ statusMeta(row).zh }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="操作" min-width="200">
            <template #default="{ row }">
              <div class="geo-act">
                <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
                <el-button link type="primary" @click="goQuestions(row)">查看提问</el-button>
                <el-button
                  v-if="row.status === 'archived'"
                  link
                  type="primary"
                  @click="restoreUnit(row)"
                >恢复</el-button>
                <el-button
                  v-else
                  link
                  type="danger"
                  @click="archiveUnit(row)"
                >归档</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
        <div class="geo-table-foot">
          <span>共 {{ pager.total }} 条</span>
          <el-pagination
            background
            layout="prev, pager, next"
            :total="pager.total"
            :page-size="pager.pageSize"
            :current-page="pager.page"
            @current-change="pager.onPageChange"
          />
        </div>
      </div>
    </div>

    <el-dialog
      v-model="dialogOpen"
      :title="editing ? '编辑优化单元' : '新增优化单元'"
      width="480px"
    >
      <el-form label-width="96px">
        <el-form-item label="所属业务" required>
          <el-select v-model="form.business_id" filterable placeholder="选择业务" style="width: 100%">
            <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="单元名称" required>
          <el-input v-model="form.name" placeholder="如：选型" />
        </el-form-item>
        <el-form-item label="关键词">
          <el-input v-model="form.keyword" placeholder="如：化工离心泵，默认同名称" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </GeoWorkbenchPage>
</template>

<style scoped>
.name { font-weight: 650; color: #1e2330; }
.note {
  margin-top: 3px;
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.4;
}
.geo-status-cell { white-space: nowrap; }
.mb { margin-bottom: 12px; }
</style>
