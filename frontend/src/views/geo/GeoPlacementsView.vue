<script setup>
/**
 * 媒体阵地 CRUD（media-placements）
 */
import { onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoMediaPlacement,
  deleteGeoMediaPlacement,
  listGeoMediaPlacements,
  patchGeoMediaPlacement,
} from '../../api/geoContent'
import { useClientPager } from '../../composables/useClientPager'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const items = ref([])
const pager = useClientPager(items, { pageSize: 20 })
const createOpen = ref(false)
const form = ref({
  name: '',
  channel_type: 'website',
  channel_key: '',
  target_url: '',
  status: 'planned',
  priority: 0,
  authority_note: '',
})

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户'
    items.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await listGeoMediaPlacements(tenantId.value)
    items.value = data.items || []
  } catch (e) {
    error.value = e.message || '加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

async function submitCreate() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  try {
    await createGeoMediaPlacement({
      tenant_id: tenantId.value,
      name: form.value.name.trim(),
      channel_type: form.value.channel_type,
      channel_key: form.value.channel_key.trim() || null,
      target_url: form.value.target_url.trim() || null,
      status: form.value.status,
      priority: Number(form.value.priority) || 0,
      authority_note: form.value.authority_note.trim() || null,
    })
    ElMessage.success('已创建阵地')
    createOpen.value = false
    form.value = {
      name: '',
      channel_type: 'website',
      channel_key: '',
      target_url: '',
      status: 'planned',
      priority: 0,
      authority_note: '',
    }
    await load()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
}

async function setStatus(row, status) {
  try {
    await patchGeoMediaPlacement(tenantId.value, row.id, { status })
    ElMessage.success('已更新状态')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`删除阵地「${row.name}」？`, '删除', {
      type: 'warning',
      confirmButtonText: '删除',
    })
    await deleteGeoMediaPlacement(tenantId.value, row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '删除失败')
  }
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-pl">
    <div class="page-header">
      <div>
        <div class="page-title">媒体阵地</div>
        <div class="page-desc">
          权威信源 / 分发阵地布局（API：media-placements）。空库打开时可能自动种子 CN 蓝图。
        </div>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="createOpen = true">新建</el-button>
        <el-button @click="load">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <el-table :data="pager.pagedItems" stripe empty-text="暂无阵地" size="small">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="channel_type" label="类型" width="110" />
      <el-table-column prop="channel_key" label="蓝图 key" width="100" />
      <el-table-column prop="status" label="状态" width="100" />
      <el-table-column prop="priority" label="优先级" width="80" />
      <el-table-column prop="target_url" label="URL" min-width="160" show-overflow-tooltip />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.status !== 'published'"
            link
            type="success"
            @click="setStatus(row, 'published')"
          >标为已发布</el-button>
          <el-button
            v-if="row.status !== 'planned'"
            link
            @click="setStatus(row, 'planned')"
          >标为规划中</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
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

    <el-dialog v-model="createOpen" title="新建媒体阵地" width="480px">
      <el-form label-width="96px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="类型">
          <el-input v-model="form.channel_type" placeholder="website / zhihu / ranking …" />
        </el-form-item>
        <el-form-item label="蓝图 key">
          <el-input v-model="form.channel_key" />
        </el-form-item>
        <el-form-item label="目标 URL">
          <el-input v-model="form.target_url" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="planned" value="planned" />
            <el-option label="in_progress" value="in_progress" />
            <el-option label="published" value="published" />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="form.priority" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.authority_note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.geo-pl { padding: 4px 2px 24px; }
.page-header {
  display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.page-title { font-size: 20px; font-weight: 700; }
.page-desc { font-size: 13px; color: #6b7280; margin-top: 4px; }
.header-actions { display: flex; gap: 8px; }
.mb { margin-bottom: 12px; }
</style>
